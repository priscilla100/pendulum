"""DETERMINISTIC_VERIFICATION_AGENT — a genuine PydanticAI agent.

This is one of the two places (with the orchestrator's finalize) where an LLM
gets free tool choice, restricted to the 8 BLACK solver tools. The structured
output type forces a DeterministicVerdict; UsageLimits bounds the probing to
the agent's MAX_STEPS. Confidence is None by design: PydanticAI exposes no
token logprobs, and this agent's value is its solver-backed evidence.
"""

from __future__ import annotations

import time

from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from pendulum.agents.formatting import ap_block
from pendulum.deps import PendulumDeps
from pendulum.llm.pydantic_models import build_chat_model
from pendulum.prompt_loader import load, render
from pendulum.schemas import APMapping, Candidate, DeterministicVerdict, VerificationResult


async def verify_deterministic(
    nl: str,
    aps: list[APMapping],
    candidate: Candidate,
    others: list[Candidate],
    deps: PendulumDeps,
) -> VerificationResult:
    cfg = deps.agent_cfg("DET")
    started = time.monotonic()

    try:
        # Setup inside the try: a failure here (dead MCP toolset, missing
        # prompt) must also degrade to an ERROR verdict, not propagate.
        model = deps.test_model or build_chat_model(cfg)
        toolset = deps.mcp.black_toolset()
        agent: Agent = Agent(
            model,
            instructions=load("det_verifier_system"),
            toolsets=[toolset] if toolset is not None else [],
            output_type=DeterministicVerdict,
            retries=cfg.max_retries,
        )
        user = render(
            "det_verifier_user",
            NATURAL_LANGUAGE=nl,
            ATOMIC_PROPOSITIONS=ap_block(aps),
            FORMULA=candidate.canonical,
            OTHER_CANDIDATES="\n".join(f"- {c.id}: {c.canonical}" for c in others) or "(none)",
        )
        run = await agent.run(user, usage_limits=UsageLimits(request_limit=cfg.max_steps))
        verdict: DeterministicVerdict = run.output
    except UsageLimitExceeded:
        deps.logger.warning("verify_det", "budget_exhausted", candidate=candidate.id, max_steps=cfg.max_steps)
        return VerificationResult(
            candidate_id=candidate.id, agent="deterministic", verdict="INCONCLUSIVE",
            evidence=f"tool budget ({cfg.max_steps} requests) exhausted without a decisive check",
        )
    except Exception as exc:  # noqa: BLE001 — agent failure must not kill the run
        deps.logger.error("verify_det", "failed", candidate=candidate.id, error=str(exc))
        return VerificationResult(
            candidate_id=candidate.id, agent="deterministic", verdict="ERROR",
            evidence=f"deterministic verification failed: {exc}",
        )

    deps.logger.info(
        "verify_det", "verdict",
        candidate=candidate.id, verdict=verdict.verdict,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return VerificationResult(
        candidate_id=candidate.id, agent="deterministic",
        verdict=verdict.verdict, confidence=None, evidence=verdict.evidence,
    )
