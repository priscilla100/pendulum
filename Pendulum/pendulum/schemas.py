"""Shared pydantic models — the single vocabulary every Pendulum module speaks.

Nothing here performs I/O. Data flowing between graph nodes, agents, the MCP
wrapper and the eval harness is always one of these types, so a change in shape
is a change in exactly one file.
"""

from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Errors and timing (graph state channels)
# ---------------------------------------------------------------------------


class AgentError(BaseModel):
    """One recoverable failure, appended to the graph's error channel."""

    stage: str
    agent: str
    message: str
    recoverable: bool = True
    ts: float = Field(default_factory=time.time)


class StageTiming(BaseModel):
    stage: str
    seconds: float


# ---------------------------------------------------------------------------
# Atomic-proposition extraction (task.md envelope, verbatim field semantics)
# ---------------------------------------------------------------------------


class APMapping(BaseModel):
    """One atom: a tense-neutral predicate name and the NL fragment it grounds."""

    ap: str
    nl_fragment: str
    polarity: Optional[str] = None  # "event" | "state" per the extraction prompt


class APExtractionResult(BaseModel):
    """{STATUS, MESSAGE, AP_NL_MAPPING_LIST, CONFIDENCE} from task.md."""

    status: Literal["OK", "ERROR"]
    message: str = ""
    ap_nl_mapping_list: list[APMapping] = Field(default_factory=list)
    confidence: Optional[float] = None  # LNLL; None when logprobs unavailable


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

SourceAgent = Literal["python", "dwyer", "salt", "orchestrator", "oneshot"]


class Candidate(BaseModel):
    """One well-formed candidate formula (already parse_and_canonicalize-validated)."""

    id: str  # "<source_agent>-<n>", unique within a run
    formula: str  # as emitted by the agent
    canonical: str  # parser's canonical form; dedup key
    source_agent: SourceAgent
    confidence: Optional[float] = None  # LNLL of the formula emission
    rationale: str = ""
    attempts: int = 1  # how many generation attempts it took


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

Verdict = Literal["SUPPORTS", "REFUTES", "INCONCLUSIVE", "ERROR"]


class VerificationResult(BaseModel):
    candidate_id: str
    agent: Literal["fuzzy", "deterministic"]
    verdict: Verdict
    confidence: Optional[float] = None  # LNLL of the judge; None for deterministic
    evidence: str = ""  # judge reasoning / trace summaries for the orchestrator


class DeterministicVerdict(BaseModel):
    """Structured output type for the deterministic-verifier PydanticAI agent."""

    verdict: Verdict
    evidence: str = Field(
        description="What was checked (traces, entailments, consistency) and what it showed."
    )


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------


class RankedFormula(BaseModel):
    formula: str
    canonical: str
    rank: int  # 1 = best
    score: Optional[float] = None
    justification: str = ""


class FinalOutput(BaseModel):
    """What `pipeline.translate` returns: 1-5 ranked formulas, or an error."""

    status: Literal["OK", "ERROR"]
    message: str = ""
    formulas: list[RankedFormula] = Field(default_factory=list)
    ap_mapping: list[APMapping] = Field(default_factory=list)
    run_id: str = ""


class OrchestratorRanking(BaseModel):
    """Structured output type for the finalize PydanticAI agent."""

    # no schema-level max: the runtime cap is config.max_output_formulas
    # (default 10); a hard max_length=5 made valid 6-10-formula rankings
    # fail structured-output validation (codex audit, medium)
    formulas: list[RankedFormula] = Field(min_length=0)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Typed views of pltl-mcp tool results (populated by pendulum.mcp.client)
# ---------------------------------------------------------------------------


class ParseResult(BaseModel):
    valid: bool
    canonical: Optional[str] = None
    error: Optional[str] = None
    aps: list[str] = Field(default_factory=list)
    temporal_class: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class SaltResult(BaseModel):
    ok: bool
    ltl: Optional[str] = None
    error: Optional[str] = None


class LtlToNlResult(BaseModel):
    paraphrases: list[str] = Field(default_factory=list)
    tnl: str = ""
