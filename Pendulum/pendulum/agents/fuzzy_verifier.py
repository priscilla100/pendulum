"""FUZZY_FORMULA_VERIFICATION_AGENT.

Two modes, both fixed scaffolds (deliberately NOT free tool-loop agents):

Legacy per-candidate (`verify_fuzzy`):
  1. ltl_to_nl on the candidate → 5 mechanical paraphrases of what the
     formula actually says;
  2. one judge completion comparing the paraphrases to the original NL,
     with LNLL confidence.

Contrastive per-row (`verify_row_contrastive`, PENDULUM_CONTRASTIVE_JUDGE):
  1. code-side evidence assembly for the WHOLE filtered row — per-candidate
     paraphrases, per-candidate violating trace ("forbidden example"), and
     a BLACK compare_candidates lattice rendered with candidate ids;
  2. ONE falsification-framed judge completion over all candidates, JSON
     schema-constrained (Ollama structured output), returning one verdict
     per candidate plus a best pick.

Neither mode raises — failures become verdict=ERROR results the
orchestrator sees; evidence-gathering failures degrade to placeholder
lines inside the prompt.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pendulum.agents.formatting import ap_block, lattice_block, numbered
from pendulum.agents.llm_json import json_completion_with_retry
from pendulum.agents.parsing import ExtractionError, extract_json_object
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError, Message
from pendulum.mcp.client import McpError
from pendulum.prompt_loader import load, render
from pendulum.schemas import APMapping, Candidate, VerificationResult

_VERDICTS = ("SUPPORTS", "REFUTES", "INCONCLUSIVE")

# JSON schema handed to the router as `response_schema`: on local Ollama
# models this triggers structured-output constrained decoding; CLI backends
# receive it best-effort. The validator below re-checks everything anyway.
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(_VERDICTS)},
                    "evidence": {"type": "string"},
                },
                "required": ["candidate_id", "verdict", "evidence"],
                "additionalProperties": False,
            },
        },
        "best_candidate_id": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["verdicts", "best_candidate_id", "reasoning"],
    "additionalProperties": False,
}


def _validate_verdict(parsed: dict[str, Any]) -> tuple[str, str]:
    verdict = parsed.get("verdict")
    if verdict not in _VERDICTS:
        raise ExtractionError(f'"verdict" must be one of {", ".join(_VERDICTS)}')
    evidence = parsed.get("evidence", "")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ExtractionError('"evidence" must be a non-empty string')
    return verdict, evidence.strip()


async def verify_fuzzy(
    nl: str, aps: list[APMapping], candidate: Candidate, deps: PendulumDeps
) -> VerificationResult:
    started = time.monotonic()
    try:
        paraphrased = await deps.mcp.ltl_to_nl(candidate.canonical)
        if not paraphrased.paraphrases:
            raise McpError("ltl_to_nl returned no paraphrases")
        user = render(
            "fuzzy_judge_user",
            NATURAL_LANGUAGE=nl,
            FORMULA=candidate.canonical,
            ATOMIC_PROPOSITIONS=ap_block(aps),
            PARAPHRASES=numbered(paraphrased.paraphrases),
        )
        (verdict, evidence), lnll, _ = await json_completion_with_retry(
            deps.router, deps.agent_cfg("FUZZY"), load("fuzzy_judge_system"), user,
            validate=_validate_verdict, logger=deps.logger, stage="verify_fuzzy",
        )
    except (McpError, LlmError, ExtractionError) as exc:
        deps.logger.error("verify_fuzzy", "failed", candidate=candidate.id, error=str(exc))
        return VerificationResult(
            candidate_id=candidate.id, agent="fuzzy", verdict="ERROR",
            evidence=f"fuzzy verification failed: {exc}",
        )

    deps.logger.info(
        "verify_fuzzy", "verdict",
        candidate=candidate.id, verdict=verdict, confidence=lnll,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return VerificationResult(
        candidate_id=candidate.id, agent="fuzzy", verdict=verdict,
        confidence=lnll, evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Contrastive row judge (PENDULUM_CONTRASTIVE_JUDGE)
# ---------------------------------------------------------------------------


def _render_state(step: Any) -> str:
    if not isinstance(step, (list, tuple, set)):  # a str would render as chars
        raise ValueError(f"trace step must be a list of atoms, got {type(step).__name__}")
    return "{" + ", ".join(str(atom) for atom in step) + "}"


def _render_trace(trace: dict[str, Any]) -> str:
    """Compact, readable ω-trace: 'step1 {req}; step2 {}; then forever {ack}'."""
    prefix = trace.get("prefix") or []
    loop = trace.get("loop") or []
    parts = [f"step{i} {_render_state(step)}" for i, step in enumerate(prefix, start=1)]
    if len(loop) == 1:
        parts.append(f"then forever {_render_state(loop[0])}")
    elif loop:
        parts.append(
            "then repeating forever " + " -> ".join(_render_state(step) for step in loop)
        )
    if not parts:
        raise ValueError("empty trace")
    return "; ".join(parts)


async def _paraphrase_lines(candidate: Candidate, deps: PendulumDeps) -> tuple[str, str]:
    """Return (numbered paraphrases, literal TNL). The TNL is the deterministic
    AST-walk already computed inside ltl_to_nl; the caller surfaces it only when
    PENDULUM_JUDGE_SHOW_TNL is on."""
    try:
        result = await deps.mcp.ltl_to_nl(candidate.canonical)
        if not result.paraphrases:
            raise McpError("ltl_to_nl returned no paraphrases")
        return numbered(result.paraphrases), (result.tnl or "")
    except McpError as exc:
        deps.logger.warning("verify_fuzzy", "paraphrases_unavailable",
                            candidate=candidate.id, error=str(exc))
        return "(paraphrases unavailable)", ""


async def _forbidden_example(candidate: Candidate, deps: PendulumDeps) -> str:
    explain = deps.config.judge_explain_traces
    try:
        args: dict[str, Any] = {"formula": candidate.canonical}
        if explain:
            args["explain"] = True
        raw = await deps.mcp.call("gen_violating_trace", args)
        if not raw.get("violatable", False):
            return "(no violating trace — formula is a tautology!)"
        line = "forbidden example: " + _render_trace(raw.get("trace") or {})
        why = raw.get("explanation") if explain else None
        if why:
            line += f"\n  why the formula forbids this run: {why}"
        return line
    except Exception as exc:  # noqa: BLE001 — evidence must degrade, never raise
        deps.logger.warning("verify_fuzzy", "trace_unavailable",
                            candidate=candidate.id, error=str(exc))
        return "(trace unavailable)"


def _index_pairs(raw: Any, n: int) -> list[tuple[int, int]]:
    """Defensive extraction of [i, j] index pairs from a tool-result field."""
    pairs: list[tuple[int, int]] = []
    if not isinstance(raw, list):
        return pairs
    for item in raw:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in item)
            and all(0 <= x < n for x in item)
        ):
            pairs.append((item[0], item[1]))
    return pairs


async def _relations_block(candidates: list[Candidate], deps: PendulumDeps) -> str:
    """compare_candidates lattice rendered with candidate ids. Unlike the
    orchestrator's compare_lattice this never merges — the judge needs to see
    every candidate, with its relations, under its own id."""
    if len(candidates) < 2:
        return "(single candidate — no relations to compare)"
    try:
        raw = await deps.mcp.call(
            "compare_candidates", {"formulas": [c.canonical for c in candidates]}
        )
    except Exception as exc:  # noqa: BLE001 — evidence must degrade, never raise
        deps.logger.warning("verify_fuzzy", "relations_unavailable", error=str(exc))
        return "(relations unavailable)"
    if not isinstance(raw, dict):  # malformed payload must degrade too (codex audit)
        deps.logger.warning("verify_fuzzy", "relations_unavailable", error=f"non-dict payload: {type(raw).__name__}")
        return "(relations unavailable)"

    n = len(candidates)
    equiv = _index_pairs(raw.get("equivalent_pairs"), n)
    stronger = _index_pairs(raw.get("stronger_than"), n)

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in equiv:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    equiv_ids = [[candidates[i].id for i in idxs]
                 for idxs in groups.values() if len(idxs) >= 2]

    stronger_ids: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i, j in stronger:
        if find(i) == find(j):
            continue  # equivalent — already in a group line
        pair = (candidates[i].id, candidates[j].id)
        if pair not in seen:
            seen.add(pair)
            stronger_ids.append(pair)
    return lattice_block(equiv_ids, stronger_ids)


async def _distinguishing_block(candidates: list[Candidate], deps: PendulumDeps) -> str:
    """Per-pair distinguishing traces (a concrete run one candidate accepts and the
    other rejects), each explained so the judge can check it against the requirement.
    The sharpest discriminator for look-alike candidates. Bounded to a few pairs;
    degrades to '' if unavailable. (PENDULUM_JUDGE_DIST_TRACE)"""
    if len(candidates) < 2:
        return ""
    explain = deps.config.judge_explain_traces
    pairs = [(i, j) for i in range(len(candidates)) for j in range(i + 1, len(candidates))][:3]
    lines: list[str] = []
    for i, j in pairs:
        ci, cj = candidates[i], candidates[j]
        try:
            args: dict[str, Any] = {"f1": ci.canonical, "f2": cj.canonical}
            if explain:
                args["explain"] = True
            dt = await deps.mcp.call("distinguishing_trace", args)
        except Exception as exc:  # noqa: BLE001 — evidence must degrade, never raise
            deps.logger.warning("verify_fuzzy", "dist_trace_unavailable",
                                pair=(ci.id, cj.id), error=str(exc))
            continue
        direction, trace = (dt.get("direction") if isinstance(dt, dict) else None), \
                           (dt.get("trace") if isinstance(dt, dict) else None)
        if direction not in ("f1_only", "f2_only") or not trace:
            continue  # equivalent or no separating run
        acc, rej = (ci.id, cj.id) if direction == "f1_only" else (cj.id, ci.id)
        try:
            rendered = _render_trace(trace)
        except Exception:
            continue
        line = f"  {acc} ACCEPTS but {rej} REJECTS this run: {rendered}"
        why = dt.get("explanation") if explain else None
        if why:
            line += f"\n    why: {why}"
        lines.append(line)
    if not lines:
        return ""
    return (
        "DISTINGUISHING TRACES (concrete runs where two candidates disagree — the sharpest\n"
        "test). For each run, ask whether the REQUIREMENT permits it: if the requirement\n"
        "ALLOWS the run, the candidate that ACCEPTS it is more faithful; if the requirement\n"
        "FORBIDS the run, the candidate that REJECTS it is more faithful.\n" + "\n".join(lines)
    )


def _make_row_validator(
    ids: list[str],
) -> Callable[[dict[str, Any]], tuple[dict[str, tuple[str, str]], str | None, str]]:
    expected = set(ids)

    def validate(parsed: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], str | None, str]:
        raw_verdicts = parsed.get("verdicts")
        if not isinstance(raw_verdicts, list):
            raise ExtractionError('"verdicts" must be an array of verdict objects')
        verdicts: dict[str, tuple[str, str]] = {}
        for entry in raw_verdicts:
            if not isinstance(entry, dict):
                raise ExtractionError('each entry in "verdicts" must be a JSON object')
            cid = entry.get("candidate_id")
            if cid not in expected:
                raise ExtractionError(
                    f'unknown "candidate_id" {cid!r}; valid ids: {", ".join(ids)}'
                )
            if cid in verdicts:
                raise ExtractionError(
                    f"duplicate verdict for candidate id {cid!r} — each id exactly once"
                )
            verdict = entry.get("verdict")
            if verdict not in _VERDICTS:
                raise ExtractionError(f'"verdict" must be one of {", ".join(_VERDICTS)}')
            evidence = entry.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                raise ExtractionError('"evidence" must be a non-empty string')
            verdicts[cid] = (verdict, evidence.strip())
        missing = [cid for cid in ids if cid not in verdicts]
        if missing:
            raise ExtractionError(
                f"missing verdicts for candidate ids: {', '.join(missing)} — "
                f"every candidate must appear exactly once"
            )
        best = parsed.get("best_candidate_id")
        if not (best is None or best in expected):
            best = None  # informational field — don't burn a retry on it
        return verdicts, best, str(parsed.get("reasoning", ""))

    return validate


async def _judge_completion_with_retry(
    deps: PendulumDeps,
    system: str,
    user: str,
    validate: Callable[[dict[str, Any]], Any],
    schema: dict[str, Any] = JUDGE_SCHEMA,
) -> tuple[Any, float | None]:
    """Local clone of json_completion_with_retry: same feed-the-model-its-own-
    mistake loop, but forwarding `response_schema` to the router (which
    json_completion_with_retry does not accept) so local models decode under
    the JSON schema constraint."""
    cfg = deps.agent_cfg("FUZZY")
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    attempts = cfg.max_retries + 1
    last_error: ExtractionError | None = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        result = await deps.router.complete(
            cfg, messages, want_logprobs=True, response_schema=schema,
        )
        deps.logger.debug(
            "verify_fuzzy", "contrastive_completion",
            attempt=attempt, lnll=result.lnll,
            elapsed_s=round(time.monotonic() - started, 2), text=result.text,
        )
        try:
            return validate(extract_json_object(result.text)), result.lnll
        except ExtractionError as exc:
            last_error = exc
            deps.logger.warning("verify_fuzzy", "invalid_json_retrying",
                                attempt=attempt, error=str(exc))
            messages.append({"role": "assistant", "content": result.text})
            messages.append({
                "role": "user",
                "content": f"Your reply was invalid: {exc}. Output only the corrected JSON object.",
            })
    raise ExtractionError(f"no valid JSON after {attempts} attempts: {last_error}")


async def verify_row_contrastive(
    nl: str, aps: list[APMapping], candidates: list[Candidate], deps: PendulumDeps
) -> list[VerificationResult]:
    """ONE falsification-framed judge call over the whole filtered row.

    Confidence: the single completion's LNLL is applied to every verdict —
    the judge emits all verdicts in one sequence, so no per-candidate
    logprob decomposition exists; the shared LNLL measures the judge's
    certainty about the joint verdict object.
    """
    started = time.monotonic()
    if not candidates:
        return []
    if deps.config.judge_paraphrase_audit:
        return await verify_row_paraphrase_audit(nl, aps, candidates, deps)
    ids = [c.id for c in candidates]

    show_tnl = deps.config.judge_show_tnl
    tnl_only = deps.config.judge_tnl_only
    blocks: list[str] = []
    for c in candidates:
        paraphrases, tnl = await _paraphrase_lines(c, deps)
        forbidden = await _forbidden_example(c, deps)
        if tnl_only and tnl:
            # literal reading REPLACES the paraphrases (test paraphrases as net noise)
            reading = ("what the formula actually says (deterministic literal reading):\n"
                       f"{tnl}\n")
        else:
            tnl_line = ""
            if show_tnl and tnl:
                tnl_line = (
                    "literal reading (deterministic, AUTHORITATIVE — this is exactly what the "
                    "formula says; trust it over the paraphrases if they disagree):\n"
                    f"{tnl}\n"
                )
            reading = (f"{tnl_line}"
                       "what the formula actually says (mechanical paraphrases):\n"
                       f"{paraphrases}\n")
        blocks.append(f"candidate {c.id}: {c.canonical}\n{reading}{forbidden}")
    compare_table = await _relations_block(candidates, deps)
    if deps.config.judge_dist_trace:
        dist = await _distinguishing_block(candidates, deps)
        if dist:
            compare_table = f"{compare_table}\n\n{dist}"

    user = render(
        "judge_contrastive_user",
        NATURAL_LANGUAGE=nl,
        ATOMIC_PROPOSITIONS=ap_block(aps),
        CANDIDATE_BLOCKS="\n\n".join(blocks),
        COMPARE_TABLE=compare_table,
    )

    try:
        (verdicts, best, reasoning), lnll = await _judge_completion_with_retry(
            deps, load("judge_contrastive_system"), user, _make_row_validator(ids),
        )
    except (McpError, LlmError, ExtractionError) as exc:
        deps.logger.error("verify_fuzzy", "contrastive_failed",
                          candidates=ids, error=str(exc))
        return [
            VerificationResult(
                candidate_id=cid, agent="fuzzy", verdict="ERROR",
                evidence=f"contrastive verification failed: {exc}",
            )
            for cid in ids
        ]

    deps.logger.info(
        "verify_fuzzy", "contrastive_verdicts",
        verdicts={cid: verdict for cid, (verdict, _) in verdicts.items()},
        best_candidate_id=best, reasoning=reasoning, confidence=lnll,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return [
        VerificationResult(
            candidate_id=cid, agent="fuzzy", verdict=verdicts[cid][0],
            confidence=lnll, evidence=verdicts[cid][1],
        )
        for cid in ids
    ]


# --- paraphrase-audit judge mode (PENDULUM_JUDGE_PARAPHRASE_AUDIT) ------------

PARAPHRASE_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "audits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "paraphrase_checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "captures_requirement": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["index", "captures_requirement", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["candidate_id", "paraphrase_checks"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["audits", "reasoning"],
    "additionalProperties": False,
}


def _make_audit_validator(counts: dict[str, int]):
    """counts: candidate_id -> number of paraphrases shown. Returns a validator
    yielding {cid: [(index, captures, reason)]} plus the trailing reasoning."""
    ids = list(counts)

    def validate(parsed: dict[str, Any]):
        raw = parsed.get("audits")
        if not isinstance(raw, list):
            raise ExtractionError('"audits" must be an array of per-candidate audit objects')
        out: dict[str, list[tuple[int, bool, str]]] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ExtractionError('each entry in "audits" must be a JSON object')
            cid = entry.get("candidate_id")
            if cid not in counts:
                raise ExtractionError(f'unknown "candidate_id" {cid!r}; valid ids: {", ".join(ids)}')
            if cid in out:
                raise ExtractionError(f"duplicate audit for candidate id {cid!r}")
            checks = entry.get("paraphrase_checks")
            if not isinstance(checks, list) or len(checks) != counts[cid]:
                raise ExtractionError(
                    f'candidate {cid!r} must have exactly {counts[cid]} paraphrase_checks'
                )
            parsed_checks: list[tuple[int, bool, str]] = []
            for ch in checks:
                cap = ch.get("captures_requirement")
                if not isinstance(cap, bool):
                    raise ExtractionError('"captures_requirement" must be a boolean')
                reason = ch.get("reason", "")
                if not isinstance(reason, str):
                    raise ExtractionError('"reason" must be a string')
                parsed_checks.append((int(ch.get("index", 0)), cap, reason.strip()))
            out[cid] = parsed_checks
        missing = [cid for cid in ids if cid not in out]
        if missing:
            raise ExtractionError(f"missing audits for candidate ids: {', '.join(missing)}")
        return out, str(parsed.get("reasoning", ""))

    return validate


async def verify_row_paraphrase_audit(
    nl: str, aps: list[APMapping], candidates: list[Candidate], deps: PendulumDeps
) -> list[VerificationResult]:
    """Per-paraphrase audit judge. For each candidate the model is shown the
    deterministic literal reading (TNL) and its N paraphrases, and decides for
    EACH paraphrase whether it captures the requirement (with a reason if not).
    The candidate verdict is DERIVED: SUPPORTS iff a majority of paraphrases
    capture it; confidence = fraction captured; evidence lists the misses."""
    started = time.monotonic()
    if not candidates:
        return []
    ids = [c.id for c in candidates]
    counts: dict[str, int] = {}
    blocks: list[str] = []
    try:
        for c in candidates:
            result = await deps.mcp.ltl_to_nl(c.canonical)
            if not result.paraphrases:
                raise McpError("ltl_to_nl returned no paraphrases")
            counts[c.id] = len(result.paraphrases)
            tnl = (result.tnl or "(literal reading unavailable)")
            blocks.append(
                f"candidate {c.id}: {c.canonical}\n"
                f"literal reading (TNL — authoritative, exactly what the formula says):\n"
                f"{tnl}\n"
                f"paraphrases to audit against the requirement:\n"
                f"{numbered(result.paraphrases)}"
            )
        user = render(
            "judge_paraphrase_audit_user",
            NATURAL_LANGUAGE=nl,
            ATOMIC_PROPOSITIONS=ap_block(aps),
            CANDIDATE_BLOCKS="\n\n".join(blocks),
        )
        (audits, reasoning), lnll = await _judge_completion_with_retry(
            deps, load("judge_paraphrase_audit_system"), user,
            _make_audit_validator(counts), schema=PARAPHRASE_AUDIT_SCHEMA,
        )
    except (McpError, LlmError, ExtractionError) as exc:
        deps.logger.error("verify_fuzzy", "paraphrase_audit_failed", candidates=ids, error=str(exc))
        return [
            VerificationResult(candidate_id=cid, agent="fuzzy", verdict="ERROR",
                               evidence=f"paraphrase audit failed: {exc}")
            for cid in ids
        ]

    results: list[VerificationResult] = []
    summary: dict[str, str] = {}
    for c in candidates:
        checks = audits[c.id]
        n_total = len(checks)
        n_cap = sum(1 for _, cap, _ in checks if cap)
        # majority rule (ties -> SUPPORTS, since paraphrases are meaning-preserving);
        # confidence is the graded fraction so the ranker can separate 5/5 from 3/5.
        verdict = "SUPPORTS" if 2 * n_cap >= n_total else "REFUTES"
        misses = [f"#{i}: {r}" for i, cap, r in checks if not cap and r]
        evidence = (f"{n_cap}/{n_total} paraphrases capture the requirement"
                    + ("; misses — " + " | ".join(misses) if misses else ""))
        summary[c.id] = f"{verdict}({n_cap}/{n_total})"
        results.append(VerificationResult(
            candidate_id=c.id, agent="fuzzy", verdict=verdict,
            confidence=(n_cap / n_total if n_total else None), evidence=evidence,
        ))
    deps.logger.info(
        "verify_fuzzy", "paraphrase_audit_verdicts",
        verdicts=summary, reasoning=reasoning, confidence=lnll,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return results
