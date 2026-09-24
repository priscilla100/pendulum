"""DWYERS_APPROACH_TO_LTL — synthesis via the property-pattern catalogue.

Deterministic scaffold: retrieve the top-k pattern×scope entries from the
Dwyer RAG index, let the LLM pick pattern(s) and a placeholder substitution
(JSON), then instantiate the LTL template LOCALLY (single-pass token
substitution — the model never writes LTL syntax). Failures feed back into a
bounded retry loop. An empty selection is a legitimate outcome ("nothing in
the catalogue fits"), not an error.
"""

from __future__ import annotations

import re
import time
from typing import Any

from pendulum.agents.emission import CandidateInvalid, make_candidate
from pendulum.agents.envelope import AgentEnvelope, error_envelope, ok_envelope
from pendulum.agents.formatting import ap_block
from pendulum.agents.parsing import ExtractionError, extract_json_object
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError, Message
from pendulum.mcp.client import McpError
from pendulum.prompt_loader import render
from pendulum.rag.store import Hit
from pendulum.schemas import APMapping, Candidate

_SUBST_VALUE_RE = re.compile(r"^[a-z0-9_!&|()<>\-\s]+$")
_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_]*\b")


async def synthesize_dwyer(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str = "", round_: int = 0
) -> AgentEnvelope[list[Candidate]]:
    started = time.monotonic()
    try:
        envelope = await _run(nl, aps, deps, feedback, round_)
    except (LlmError, McpError) as exc:
        deps.logger.error("synth_dwyer", "failed", error=str(exc))
        envelope = error_envelope(str(exc))
    envelope.elapsed_s = round(time.monotonic() - started, 2)
    return envelope


async def _run(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str, round_: int
) -> AgentEnvelope[list[Candidate]]:
    if deps.rag is None or deps.embedder is None:
        return error_envelope("Dwyer RAG index not initialized (run `python -m pendulum init-rag`)")

    query_vec = await deps.embedder.embed_one(nl)
    hits = deps.rag.dwyer.search(query_vec, deps.config.rag_top_k)
    if not hits:
        return error_envelope("Dwyer index returned no patterns")
    by_id = {h.chunk.metadata["id"]: h.chunk.metadata for h in hits}
    deps.logger.info("synth_dwyer", "patterns_retrieved", ids=list(by_id), scores=[round(h.score, 3) for h in hits])

    cfg = deps.agent_cfg("DWYER")
    allowed = {m.ap for m in aps}
    user = render(
        "dwyer_user",
        NATURAL_LANGUAGE=nl,
        ATOMIC_PROPOSITIONS=ap_block(aps),
        RETRIEVED_PATTERNS=_render_hits(hits),
    )
    if feedback:
        user = feedback + "\n" + user
    messages: list[Message] = [
        {"role": "system", "content": render("dwyer_system", MAX_CANDIDATES=str(deps.config.synth_max_candidates))},
        {"role": "user", "content": user},
    ]

    counter = 0
    attempts = deps.config.synth_parse_max_retries + 1
    for attempt in range(1, attempts + 1):
        result = await deps.router.complete(cfg, messages, want_logprobs=False)
        deps.logger.debug("synth_dwyer", "completion", attempt=attempt, text=result.text)

        candidates: list[Candidate] = []
        failures: list[str] = []
        try:
            selections = _validate_selections(extract_json_object(result.text), by_id)
            if not selections:  # nothing fits directly — try one decomposition
                deps.logger.info("synth_dwyer", "no_flat_fit_trying_decomposition", attempt=attempt)
                from pendulum.agents.dwyer_recurse import try_decompose

                recursive = await try_decompose(
                    nl, aps, deps, by_id, _render_hits(hits), round_=round_,
                )
                return ok_envelope(recursive, attempts=attempt)
            for selection in selections[: deps.config.synth_max_candidates]:
                entry = by_id[selection["pattern_id"]]
                try:
                    formula = _instantiate(entry, selection["substitution"], allowed)
                    counter += 1
                    candidates.append(await make_candidate(
                        deps, source_agent="dwyer", formula=formula,
                        rationale=(
                            f"Dwyer {entry['pattern']} ({entry['scope']}): {entry['intent']} "
                            f"substitution={selection['substitution']} "
                            f"note={selection.get('confidence_note', '')}"
                        ),
                        index=counter, attempts=attempt, round_=round_,
                    ))
                except (ValueError, CandidateInvalid) as exc:
                    failures.append(f"{selection['pattern_id']}: {exc}")
        except ExtractionError as exc:
            failures.append(str(exc))

        if candidates:
            if failures:
                deps.logger.warning("synth_dwyer", "partial_failures", failures=failures)
            deps.logger.info("synth_dwyer", "candidates", formulas=[c.canonical for c in candidates], attempt=attempt)
            return ok_envelope(candidates, attempts=attempt)

        deps.logger.warning("synth_dwyer", "attempt_failed", attempt=attempt, failures=failures)
        messages.append({"role": "assistant", "content": result.text})
        messages.append({
            "role": "user",
            "content": "Your selection was invalid: " + "; ".join(failures)
            + ". Fix it and output only the corrected JSON object.",
        })

    return error_envelope(f"no valid pattern instantiation after {attempts} attempts", attempts=attempts)


def _render_hits(hits: list[Hit]) -> str:
    blocks = []
    for h in hits:
        m = h.chunk.metadata
        blocks.append(
            f"- pattern_id: {m['id']}\n"
            f"  pattern: {m['pattern']}   scope: {m['scope']}\n"
            f"  intent: {m['intent']}\n"
            f"  ltl_template: {m['ltl_template']}\n"
            f"  placeholders: {', '.join(m['placeholders'])}"
            + (f"\n  notes: {m['notes']}" if m.get("notes") else "")
        )
    return "\n".join(blocks)


def _validate_selections(parsed: dict[str, Any], by_id: dict[str, Any]) -> list[dict[str, Any]]:
    selections = parsed.get("selections")
    if not isinstance(selections, list):
        raise ExtractionError('"selections" must be an array (possibly empty)')
    for i, sel in enumerate(selections):
        if not isinstance(sel, dict):
            raise ExtractionError(f'"selections"[{i}] must be an object')
        if sel.get("pattern_id") not in by_id:
            raise ExtractionError(
                f'"selections"[{i}].pattern_id {sel.get("pattern_id")!r} is not one of the '
                f"retrieved entries: {', '.join(by_id)}"
            )
        if not isinstance(sel.get("substitution"), dict) or not sel["substitution"]:
            raise ExtractionError(f'"selections"[{i}].substitution must be a non-empty object')
    return selections


def _instantiate(entry: dict[str, Any], substitution: dict[str, Any], allowed: set[str]) -> str:
    placeholders = set(entry["placeholders"])
    if set(substitution) != placeholders:
        raise ValueError(
            f"substitution keys {sorted(substitution)} must be exactly the placeholders {sorted(placeholders)}"
        )
    values: dict[str, str] = {}
    for ph, value in substitution.items():
        value = str(value).strip()
        if not value or not _SUBST_VALUE_RE.match(value):
            raise ValueError(f"substitution for {ph!r} may use only atoms and ! & | -> <-> ( )")
        for token in _TOKEN_RE.findall(value):
            # true/false are formula constants, not atoms — e.g. r := false
            # correctly degenerates an "until R" scope into "forever".
            if token not in allowed and token not in ("true", "false"):
                raise ValueError(f"substitution for {ph!r} uses unknown atom {token!r}; allowed: {sorted(allowed)}")
        values[ph] = value

    # Single-pass token substitution: a value containing 'p' can never be
    # re-substituted by placeholder p.
    return _TOKEN_RE.sub(lambda m: f"({values[m.group()]})" if m.group() in values else m.group(),
                         entry["ltl_template"])
