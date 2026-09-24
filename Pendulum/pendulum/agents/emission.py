"""Turning a raw formula string into a validated `Candidate`.

Two responsibilities shared by all three synthesis agents:

1. WELL-FORMEDNESS GATE: every candidate goes through parse_and_canonicalize;
   an invalid formula raises CandidateInvalid whose message is the parser's —
   the agents' retry loops feed it back to their LLM verbatim (task.md
   requirement).

2. CONFIDENCE: when llama-server is up, the formula is re-emitted through a
   grammar-constrained completion whose LNLL becomes the candidate's
   confidence. The emission must round-trip to the SAME canonical form —
   if the constrained model deviates, we keep the original formula and a null
   confidence rather than silently swapping in a different formula.
"""

from __future__ import annotations

from pendulum.deps import PendulumDeps
from pendulum.prompt_loader import load, render
from pendulum.schemas import Candidate, SourceAgent


class CandidateInvalid(Exception):
    """Formula failed the parser; str() is the parser's error message."""


async def make_candidate(
    deps: PendulumDeps,
    *,
    source_agent: SourceAgent,
    formula: str,
    rationale: str,
    index: int,
    attempts: int = 1,
    round_: int = 0,
) -> Candidate:
    parsed = await deps.mcp.parse_and_canonicalize(formula)
    if not parsed.valid or not parsed.canonical:
        raise CandidateInvalid(parsed.error or "parser rejected the formula")

    confidence = await _emission_confidence(deps, source_agent, parsed.canonical, rationale)
    return Candidate(
        # round-scoped ids: a feedback round restarts each agent's counter,
        # and ids must stay unique across rounds (verified-skip + filter maps)
        id=f"{source_agent}-r{round_}-{index}",
        formula=formula,
        canonical=parsed.canonical,
        source_agent=source_agent,
        confidence=confidence,
        rationale=rationale,
        attempts=attempts,
    )


async def _emission_confidence(
    deps: PendulumDeps, source_agent: SourceAgent, canonical: str, rationale: str
) -> float | None:
    """Best-effort by contract: ANY failure here degrades to a null
    confidence — it must never invalidate an already-parsed candidate."""
    try:
        if not await deps.router.grammar_available():
            return None
        agent_prefix = {"python": "PYTHON", "dwyer": "DWYER", "salt": "SALT",
                        "orchestrator": "ORCH", "oneshot": "ONESHOT"}
        cfg = deps.agent_cfg(agent_prefix[source_agent])
        derivation = f"{rationale}\nFormula derived above: {canonical}"
        result = await deps.router.complete(
            cfg,
            [
                {"role": "system", "content": load("formula_emit_system")},
                {"role": "user", "content": render("formula_emit_user", DERIVATION=derivation)},
            ],
            need_grammar=True,
            max_tokens=256,
        )
        emitted = await deps.mcp.parse_and_canonicalize(result.text.strip())
        if emitted.valid and emitted.canonical == canonical:
            return result.lnll  # fast path: string-identical canonicals
        if emitted.valid and emitted.canonical:
            # Semantic round-trip (user-approved proposal 6): associativity or
            # parenthesization differences are logically identical — check with
            # BLACK (deterministic, cached) before declaring a deviation.
            verdict = await deps.mcp.call(
                "check_equivalence", {"f1": canonical, "f2": emitted.canonical}
            )
            if isinstance(verdict, dict) and verdict.get("equivalent"):
                return result.lnll
    except Exception as exc:  # noqa: BLE001 — confidence is optional, candidates are not
        deps.logger.warning("emission", "confidence_emission_failed", agent=source_agent, error=str(exc))
        return None
    deps.logger.warning(
        "emission", "constrained_emission_deviated",
        agent=source_agent, expected=canonical, emitted=result.text.strip()[:120],
    )
    return None
