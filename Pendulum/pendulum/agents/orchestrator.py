"""The main orchestrator's two decision points.

- filter_candidates: one JSON completion choosing which candidates go to
  (expensive) verification. Falls back to a deterministic heuristic keep-list
  rather than ever failing the run. Optionally (PENDULUM_ORCH_COMPARE_FILTER)
  a compare_candidates lattice merges equivalent candidates first and is
  rendered into the prompt.
- finalize: a PydanticAI agent (the pipeline's "powerful" model) with the
  BLACK toolset, making the final ranking. Its formulas are re-validated
  through the parser; an agent crash degrades to a deterministic ranking from
  the verification verdicts, so the pipeline always returns an honest result.
  Every OK output then flows through _finish: optional all-survivors append
  (agent path), optional scope-variant expansion, cap + sequential re-rank.

Per task.md the orchestrator itself reports NO confidence score; it consumes
the other agents' confidences (rendered into its prompts, marked tie-break).
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from pendulum.agents.formatting import ap_block, candidate_table, lattice_block, verification_table
from pendulum.agents.llm_json import json_completion_with_retry
from pendulum.agents.parsing import ExtractionError
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError
from pendulum.llm.pydantic_models import build_chat_model
from pendulum.mcp.client import McpError
from pendulum.prompt_loader import render
from pendulum.schemas import (
    APMapping,
    Candidate,
    FinalOutput,
    OrchestratorRanking,
    RankedFormula,
    VerificationResult,
)

# ---------------------------------------------------------------------------
# compare_candidates lattice (PENDULUM_ORCH_COMPARE_FILTER)
# ---------------------------------------------------------------------------


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


async def compare_lattice(
    candidates: list[Candidate], deps: PendulumDeps
) -> tuple[list[Candidate], str]:
    """compare_candidates over all candidates: merge equivalents, render text.

    Returns (possibly-merged candidates, lattice text for the prompts).
    No-op — (candidates, "") — when the option is off, there are fewer than
    two candidates, or the tool call fails (logged, degraded)."""
    if not deps.config.orch_compare_filter or len(candidates) < 2:
        return candidates, ""

    try:
        raw = await deps.mcp.call(
            "compare_candidates", {"formulas": [c.canonical for c in candidates]}
        )
    except McpError as exc:  # McpToolError subclasses McpError
        deps.logger.warning("orch_filter", "compare_lattice_failed", error=str(exc))
        return candidates, ""

    n = len(candidates)
    equiv = _index_pairs(raw.get("equivalent_pairs"), n)
    stronger = _index_pairs(raw.get("stronger_than"), n)

    # Union-find over the equivalence pairs.
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

    def conf_key(i: int):
        c = candidates[i]
        return (c.confidence is None, -(c.confidence or 0.0), i)  # tie → first

    rep = list(range(n))
    drop: set[int] = set()
    equiv_group_ids: list[list[str]] = []
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        keep = min(idxs, key=conf_key)
        for i in idxs:
            rep[i] = keep
            if i != keep:
                drop.add(i)
        equiv_group_ids.append([candidates[i].id for i in idxs])
        deps.logger.info(
            "orch_filter", "compare_merge",
            kept=candidates[keep].id,
            merged=[candidates[i].id for i in idxs if i != keep],
        )

    stronger_ids: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for i, j in stronger:
        ri, rj = rep[i], rep[j]
        if ri == rj:
            continue
        pair = (candidates[ri].id, candidates[rj].id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            stronger_ids.append(pair)

    merged = [c for i, c in enumerate(candidates) if i not in drop]
    return merged, lattice_block(equiv_group_ids, stronger_ids)


# ---------------------------------------------------------------------------
# Stage 1: candidate filtering
# ---------------------------------------------------------------------------


async def filter_candidates(
    nl: str,
    aps: list[APMapping],
    candidates: list[Candidate],
    deps: PendulumDeps,
    verifications: list[VerificationResult] | None = None,
) -> tuple[list[Candidate], str]:
    """Returns (kept candidates, reasoning). Never raises. `verifications`
    carries prior-round verdicts into the table on feedback rounds."""
    cap = deps.config.max_candidates_to_verify
    if len(candidates) <= 1:
        deps.logger.info("orch_filter", "filter_single_candidate_skip",
                         ids=[c.id for c in candidates])
        return candidates, "single candidate — nothing to filter"

    candidates, lattice_text = await compare_lattice(candidates, deps)
    if len(candidates) == 1:
        deps.logger.info("orch_filter", "filter_single_candidate_skip",
                         ids=[c.id for c in candidates], after="compare_merge")
        return candidates, "single candidate after equivalence merge — nothing to filter"

    by_id = {c.id: c for c in candidates}

    def validate(parsed: dict[str, Any]) -> tuple[list[str], str]:
        keep = parsed.get("keep")
        if not isinstance(keep, list) or not keep:
            raise ExtractionError('"keep" must be a non-empty array of candidate ids')
        unknown = [k for k in keep if k not in by_id]
        if unknown:
            raise ExtractionError(f"unknown candidate ids {unknown}; valid ids: {', '.join(by_id)}")
        return keep, str(parsed.get("reasoning", ""))

    try:
        (keep_ids, reasoning), _, _ = await json_completion_with_retry(
            deps.router, deps.agent_cfg("ORCH"),
            render("orchestrator_filter_system", MAX_KEEP=str(cap)),
            render(
                "orchestrator_filter_user",
                NATURAL_LANGUAGE=nl,
                ATOMIC_PROPOSITIONS=ap_block(aps),
                CANDIDATE_TABLE=candidate_table(candidates, verifications or []),
                COMPARE_TABLE=lattice_text or "(not computed)",
            ),
            validate=validate, logger=deps.logger, stage="orch_filter",
            want_logprobs=False,
        )
        kept = [by_id[k] for k in dict.fromkeys(keep_ids)][:cap]  # dedupe, keep order, cap
    except (ExtractionError, LlmError) as exc:
        kept = _heuristic_keep(candidates, cap)
        reasoning = f"orchestrator filter failed ({exc}); heuristic keep-list used"
        deps.logger.warning("orch_filter", "fallback_heuristic", error=str(exc), kept=[c.id for c in kept])

    deps.logger.info("orch_filter", "kept", ids=[c.id for c in kept], reasoning=reasoning)
    return kept, reasoning


def _heuristic_keep(candidates: list[Candidate], cap: int) -> list[Candidate]:
    """Diversity first (best per source agent), then confidence."""

    def sort_key(c: Candidate):
        return (c.confidence is None, -(c.confidence or 0.0))

    best_per_source: dict[str, Candidate] = {}
    for c in sorted(candidates, key=sort_key):
        best_per_source.setdefault(c.source_agent, c)
    kept = list(best_per_source.values())
    for c in sorted(candidates, key=sort_key):
        if c not in kept and len(kept) < cap:
            kept.append(c)
    return kept[:cap]


async def _rank_via_completion(cfg, system: str, user: str, deps) -> OrchestratorRanking:
    """Orchestrator finalization for a non-tool-calling (CLI) backend: one
    schema-constrained completion that ranks over the precomputed solver
    evidence already rendered into `user` (verification verdicts + the
    compare_candidates lattice). Returns an OrchestratorRanking; raises on
    exhausted retries so the caller degrades to the deterministic ranking.
    """
    def validate(parsed: dict[str, Any]) -> OrchestratorRanking:
        formulas = parsed.get("formulas")
        if not isinstance(formulas, list):
            raise ExtractionError('"formulas" must be an array (possibly empty)')
        items: list[RankedFormula] = []
        for i, f in enumerate(formulas, start=1):
            if not isinstance(f, dict) or not isinstance(f.get("formula"), str) or not f["formula"].strip():
                raise ExtractionError('each formula needs a non-empty string "formula"')
            items.append(RankedFormula(
                formula=f["formula"].strip(), canonical="", rank=i,
                score=f.get("score") if isinstance(f.get("score"), (int, float)) else None,
                justification=str(f.get("justification", "")),
            ))
        return OrchestratorRanking(formulas=items, reasoning=str(parsed.get("reasoning", "")))

    # Two overrides on top of the shared system prompt:
    # 1. NO LIVE TOOLS. The base prompt says "use the BLACK tools yourself";
    #    on this path there are none. Say so explicitly, or the model will
    #    claim tool checks it never ran (the exact confabulation this design
    #    avoids). It must reason ONLY over the rendered evidence.
    # 2. JSON shape: the PydanticAI path enforces it via output_type; here it
    #    is not enforced, so spell it out.
    system_json = system + (
        '\n\nIMPORTANT: you have NO tools on this path. Do NOT claim to run '
        'check_equivalence, compare_candidates, or any solver check. Rely '
        'ONLY on the verification verdicts and the compare_candidates lattice '
        'already provided below as text.\n\n'
        'Return ONLY a JSON object (no prose, no code fences):\n'
        '{"formulas": [{"formula": "<canonical LTL>", "score": <number or null>, '
        '"justification": "<one line>"}], "reasoning": "<why this ranking>"}\n'
        'formulas is best-first and may be empty if nothing survives.'
    )
    ranking, _lnll, _attempts = await json_completion_with_retry(
        deps.router, cfg, system_json, user,
        validate=validate, logger=deps.logger, stage="orch_final",
        want_logprobs=False,
    )
    return ranking


def _latest_verifications(verifications: list[VerificationResult]) -> list[VerificationResult]:
    """Collapse the append-only channel to the LAST verdict per
    (candidate_id, agent): contrastive feedback rounds re-judge the whole row,
    and fallback logic must not count stale round-1 votes (codex audit)."""
    latest: dict[tuple[str, str], VerificationResult] = {}
    for v in verifications:
        latest[(v.candidate_id, v.agent)] = v
    return list(latest.values())


# ---------------------------------------------------------------------------
# Stage 2: final determination
# ---------------------------------------------------------------------------


async def finalize(
    nl: str,
    aps: list[APMapping],
    candidates: list[Candidate],
    verifications: list[VerificationResult],
    deps: PendulumDeps,
    *,
    lattice_text: str = "",
) -> FinalOutput:
    if not candidates:
        return FinalOutput(
            status="ERROR",
            message="no candidate formulas survived synthesis",
            ap_mapping=aps,
        )

    # Latest verdict per (candidate, agent): contrastive feedback rounds
    # re-judge the row and stale round-1 votes must not steer fallbacks.
    verifications = _latest_verifications(verifications)

    cfg = deps.agent_cfg("ORCH")
    max_out = deps.config.max_output_formulas
    started = time.monotonic()

    # Deterministic-orchestrator mode (PENDULUM_ORCH_DETERMINISTIC): skip the
    # LLM finalize agent entirely and rank purely from the verification
    # verdicts (SUPPORTS - REFUTES, confidence tie-break). The LLM finalize is
    # ~106s/row on a small local model and, in the judgment-phase experiment,
    # was no more accurate than this deterministic ranking; this toggle lets
    # the pipeline run the fast, faithful selection when the LLM step is not
    # earning its cost. Off by default (the LLM orchestrator is the default).
    if deps.config.orch_deterministic:
        final = _deterministic_ranking(
            candidates, verifications, aps, max_out,
            note="orchestrator: deterministic verdict-ranking (PENDULUM_ORCH_DETERMINISTIC)",
        )
        deps.logger.info("orch_final", "deterministic_ranking_selected",
                         formulas=[f.canonical for f in final.formulas],
                         elapsed_s=round(time.monotonic() - started, 2))
        return await _finish(final, deps)

    system = render("orchestrator_final_system", MAX_FORMULAS=str(max_out))
    user = render(
        "orchestrator_final_user",
        NATURAL_LANGUAGE=nl,
        ATOMIC_PROPOSITIONS=ap_block(aps),
        VERIFICATION_TABLE=verification_table(candidates, verifications),
        COMPARE_TABLE=lattice_text or "(not computed)",
    )

    try:
        if cfg.backend != "ollama" and deps.test_model is None:
            # CLI-backed orchestrator (e.g. Opus via claude-cli): a subprocess
            # model cannot drive PydanticAI's live tool loop against our MCP
            # BLACK tools, so it ranks over the PRECOMPUTED solver evidence
            # already in the prompt (VERIFICATION_TABLE + COMPARE_TABLE) via a
            # single schema-constrained completion. No live tool calls.
            ranking = await _rank_via_completion(cfg, system, user, deps)
        else:
            model = deps.test_model or build_chat_model(cfg)
            toolset = deps.mcp.black_toolset()
            agent: Agent = Agent(
                model,
                instructions=system,
                toolsets=[toolset] if toolset is not None else [],
                output_type=OrchestratorRanking,
                retries=cfg.max_retries,
            )
            run = await agent.run(user, usage_limits=UsageLimits(request_limit=cfg.max_steps))
            ranking = run.output
    except Exception as exc:  # noqa: BLE001 — degrade to deterministic ranking
        deps.logger.error("orch_final", "agent_failed_deterministic_fallback", error=str(exc))
        fallback = _deterministic_ranking(candidates, verifications, aps, max_out,
                                          note=f"orchestrator agent failed: {exc}")
        return await _finish(fallback, deps)

    if not ranking.formulas:
        # The orchestrator explicitly judged that nothing survives.
        if deps.config.emit_best_guess:
            final = _deterministic_ranking(
                candidates, verifications, aps, max_out,
                note="low_confidence: orchestrator judged all candidates refuted; "
                     "emitting best guess (PENDULUM_EMIT_BEST_GUESS)",
            )
            final.message = f"{final.message} | orchestrator reasoning: {ranking.reasoning}"
            deps.logger.info(
                "orch_final", "best_guess_emitted",
                candidates=[c.id for c in candidates], reasoning=ranking.reasoning,
            )
            return await _finish(final, deps)
        return FinalOutput(
            status="ERROR",
            message=ranking.reasoning or "orchestrator: no candidate survived verification",
            ap_mapping=aps,
        )

    validated: list[RankedFormula] = []
    try:
        for item in ranking.formulas[:max_out]:
            parsed = await deps.mcp.parse_and_canonicalize(item.formula)
            if not parsed.valid or not parsed.canonical:
                deps.logger.warning("orch_final", "output_formula_invalid", formula=item.formula, error=parsed.error)
                continue
            validated.append(RankedFormula(
                formula=item.formula, canonical=parsed.canonical,
                rank=len(validated) + 1, score=item.score, justification=item.justification,
            ))
    except Exception as exc:  # noqa: BLE001 — e.g. MCP transport death mid-validation
        deps.logger.error("orch_final", "validation_failed_deterministic_fallback", error=str(exc))
        fallback = _deterministic_ranking(candidates, verifications, aps, max_out,
                                          note=f"ranking validation failed: {exc}")
        return await _finish(fallback, deps)

    if not validated:
        fallback = _deterministic_ranking(candidates, verifications, aps, max_out,
                                          note="all orchestrator-ranked formulas failed the parser")
        return await _finish(fallback, deps)

    if deps.config.output_all_survivors:
        validated = _append_survivors(validated, candidates, verifications, deps)

    final = await _finish(
        FinalOutput(status="OK", message=ranking.reasoning, formulas=validated, ap_mapping=aps),
        deps,
    )
    deps.logger.info(
        "orch_final", "final_ranking",
        formulas=[f.canonical for f in final.formulas],
        reasoning=ranking.reasoning,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return final


def _append_survivors(
    validated: list[RankedFormula],
    candidates: list[Candidate],
    verifications: list[VerificationResult],
    deps: PendulumDeps,
) -> list[RankedFormula]:
    """All-survivors emission (PENDULUM_OUTPUT_ALL_SURVIVORS): append every
    candidate without a fuzzy REFUTES verdict (zero verifications counts as
    surviving), deduped by canonical against the agent's validated ranking.
    Order: SUPPORTS count desc, then confidence (non-null first, higher first)."""
    seen = {f.canonical for f in validated}
    fuzzy_refuted = {v.candidate_id for v in verifications
                     if v.agent == "fuzzy" and v.verdict == "REFUTES"}
    supports = Counter(v.candidate_id for v in verifications if v.verdict == "SUPPORTS")
    fuzzy_verdict: dict[str, str] = {}
    for v in verifications:
        if v.agent == "fuzzy":
            fuzzy_verdict[v.candidate_id] = v.verdict

    survivors = [c for c in candidates if c.id not in fuzzy_refuted]
    survivors.sort(key=lambda c: (-supports[c.id], c.confidence is None, -(c.confidence or 0.0)))

    out = list(validated)
    appended: list[str] = []
    for c in survivors:
        if c.canonical in seen:
            continue
        seen.add(c.canonical)
        out.append(RankedFormula(
            formula=c.formula, canonical=c.canonical, rank=len(out) + 1,
            justification=f"survivor (fuzzy: {fuzzy_verdict.get(c.id, 'unverified')})",
        ))
        appended.append(c.id)
    if appended:
        deps.logger.info("orch_final", "survivors_appended", ids=appended)
    return out


# ---------------------------------------------------------------------------
# Scope-variant expansion (PENDULUM_OUTPUT_SCOPE_VARIANTS)
# ---------------------------------------------------------------------------

_G_WRAPPED = re.compile(r"G \((.*)\)")
_G_ATOM = re.compile(r"G ([a-z][a-z0-9_]*)")


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _scope_counterpart(canonical: str) -> str:
    """Unwrapped body for a G-rooted canonical, else the G-wrapped form.

    Any `G <rest>` canonical unwraps to `<rest>` — including unary chains
    like `G !hsel` or `G X p` that the earlier paren/atom regexes missed
    (round-4 forensic: the miss emitted junk `G G !hsel` and cost a winning
    row). The balanced guard still protects `G (a) U (b)`-style strings
    where the G does not scope the whole formula; expand_scope_variants
    additionally parser-validates every counterpart."""
    m = _G_WRAPPED.fullmatch(canonical)
    if m and _balanced(m.group(1)):
        return m.group(1)
    m = _G_ATOM.fullmatch(canonical)
    if m:
        return m.group(1)
    if (canonical.startswith("G ") and _balanced(canonical[2:])
            and _no_toplevel_binary(canonical[2:])):
        return canonical[2:]
    return f"G ({canonical})"


_BINARY_TOKENS = ("U", "S", "W", "R", "T", "&", "|", "->", "<->")


def _no_toplevel_binary(s: str) -> bool:
    """True when no binary operator token sits at paren depth 0 — i.e. the
    string is a unary chain over one operand and a leading G scopes all of
    it. Keeps `(p) U (q)` remainders from being torn off their G."""
    depth = 0
    for token in s.split():
        depth_change = token.count("(") - token.count(")")
        stripped = token.strip("()!")
        if depth == 0 and stripped in _BINARY_TOKENS:
            return False
        depth += depth_change
    return True


async def expand_scope_variants(
    formulas: list[RankedFormula], deps: PendulumDeps
) -> list[RankedFormula]:
    """For each formula in rank order emit it, then its G-wrap/unwrap
    counterpart (parser-round-tripped, deduped by canonical). Re-ranked
    sequentially and capped at max_output_formulas."""
    max_out = deps.config.max_output_formulas
    seen: set[str] = set()
    out: list[RankedFormula] = []
    for item in formulas:
        if item.canonical in seen:
            continue
        seen.add(item.canonical)
        out.append(item)
        source_rank = len(out)
        counterpart = _scope_counterpart(item.canonical)
        if counterpart in seen:
            continue
        try:
            parsed = await deps.mcp.parse_and_canonicalize(counterpart)
        except Exception as exc:  # noqa: BLE001 — a variant must never abort finalize
            deps.logger.warning("orch_final", "scope_variant_parse_crashed",
                                source=item.canonical, counterpart=counterpart, error=str(exc))
            continue
        if not parsed.valid or not parsed.canonical:
            deps.logger.warning("orch_final", "scope_variant_invalid",
                                source=item.canonical, counterpart=counterpart,
                                error=parsed.error)
            continue
        if parsed.canonical in seen:
            continue
        seen.add(parsed.canonical)
        out.append(RankedFormula(
            formula=counterpart, canonical=parsed.canonical, rank=len(out),
            justification=f"scope variant of rank {source_rank}",
        ))
    out = out[:max_out]
    for i, f in enumerate(out):
        f.rank = i + 1
    return out


async def _finish(output: FinalOutput, deps: PendulumDeps) -> FinalOutput:
    """Shared last step of every OK-producing finalize path: optional
    scope-variant expansion, then cap + sequential re-rank."""
    if output.status != "OK":
        return output
    formulas = output.formulas
    if deps.config.output_scope_variants and formulas:
        formulas = await expand_scope_variants(formulas, deps)
    formulas = formulas[:deps.config.max_output_formulas]
    for i, f in enumerate(formulas):
        f.rank = i + 1
    output.formulas = formulas
    return output


def _deterministic_ranking(
    candidates: list[Candidate],
    verifications: list[VerificationResult],
    aps: list[APMapping],
    max_out: int,
    *,
    note: str,
) -> FinalOutput:
    """Verdict-count ranking (SUPPORTS − REFUTES), confidence as tie-break —
    the code-side embodiment of the prompt's priority order."""
    score: dict[str, int] = {c.id: 0 for c in candidates}
    # Fuzzy-verifier confidence per candidate: for the contrastive judge this is
    # the single shared completion LNLL (identical across candidates -> a no-op
    # tie-break); for the paraphrase-audit judge it is the FRACTION of paraphrases
    # that captured the requirement, so this ranks 5/5 above 3/5 (the exp-16 win).
    vconf: dict[str, float] = {}
    for v in verifications:
        if v.candidate_id in score:
            score[v.candidate_id] += {"SUPPORTS": 1, "REFUTES": -1}.get(v.verdict, 0)
            if v.agent == "fuzzy" and v.confidence is not None:
                vconf[v.candidate_id] = max(vconf.get(v.candidate_id, v.confidence), v.confidence)

    ranked = sorted(
        candidates,
        key=lambda c: (-score[c.id], c.id not in vconf, -vconf.get(c.id, 0.0),
                       c.confidence is None, -(c.confidence or 0.0)),
    )
    formulas = [
        RankedFormula(
            formula=c.formula, canonical=c.canonical, rank=i + 1, score=float(score[c.id]),
            justification=f"deterministic fallback ranking (verdict score {score[c.id]}, source {c.source_agent})",
        )
        for i, c in enumerate(ranked[:max_out])
    ]
    return FinalOutput(
        status="OK",
        message=f"deterministic fallback ranking used — {note}",
        formulas=formulas,
        ap_mapping=aps,
    )
