"""PendulumState: the single state object flowing through the LangGraph graph.

Channels written by parallel branches carry reducers:
- `candidates` merges the three synthesis agents' outputs (dedupe on the
  canonical form, keeping the better-attested copy);
- `verifications`, `errors`, `timings` are append-only.

The feedback loop keeps failed candidates in the pool (append-only channels
cannot shrink); instead `feedback_round`/`feedback_evidence` inform the second
synthesis round, and the second filter pass sees prior verdicts.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from pendulum.schemas import (
    AgentError,
    APExtractionResult,
    Candidate,
    FinalOutput,
    StageTiming,
    VerificationResult,
)


def merge_candidates(existing: list[Candidate], new: list[Candidate]) -> list[Candidate]:
    """Concatenate, dedupe by canonical form.

    The INCUMBENT'S IDENTITY always survives a duplicate: verification
    results are keyed by candidate id, so a feedback round regenerating an
    already-refuted formula must not resurface it under a fresh id (it would
    be re-verified and its verdicts orphaned — observed in eval round 2).
    Only the confidence value is upgraded when the newcomer's is better."""
    by_canonical: dict[str, Candidate] = {}
    for candidate in list(existing or []) + list(new or []):
        incumbent = by_canonical.get(candidate.canonical)
        if incumbent is None:
            by_canonical[candidate.canonical] = candidate
            continue
        if _better_confidence(candidate.confidence, incumbent.confidence):
            by_canonical[candidate.canonical] = incumbent.model_copy(
                update={"confidence": candidate.confidence}
            )
    return list(by_canonical.values())


def _better_confidence(challenger: Optional[float], incumbent: Optional[float]) -> bool:
    if challenger is None:
        return False
    if incumbent is None:
        return True
    return challenger > incumbent


class PendulumState(TypedDict, total=False):
    nl_input: str
    run_id: str

    ap_result: Optional[APExtractionResult]
    ap_source: str  # "extractor" | "orchestrator_fallback"

    candidates: Annotated[list[Candidate], merge_candidates]
    filtered: list[Candidate]
    filter_reasoning: str

    verifications: Annotated[list[VerificationResult], operator.add]

    feedback_round: int
    feedback_evidence: str
    assess_decision: str  # "loop" | "finalize", written by the assess node only

    final: Optional[FinalOutput]

    errors: Annotated[list[AgentError], operator.add]
    timings: Annotated[list[StageTiming], operator.add]
