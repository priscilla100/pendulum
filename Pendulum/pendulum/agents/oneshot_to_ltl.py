"""ONESHOT_TO_LTL — plain one-shot NL->LTL synthesis (no code-completion trick).

A single LLM call emits one LTL formula directly; deterministic scaffolding
parses/validates it (parser gate via make_candidate) and retries on failure.
Purpose: a STRONG extra candidate source with model diversity vs the python
coder (exp-20). Optional path (PENDULUM_ONESHOT_ENABLED), model/backend via
ONESHOT_MODEL / ONESHOT_BACKEND.
"""

from __future__ import annotations

import time

from pendulum.agents.emission import CandidateInvalid, make_candidate
from pendulum.agents.envelope import AgentEnvelope, error_envelope, ok_envelope
from pendulum.agents.formatting import ap_block
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError, Message
from pendulum.mcp.client import McpError
from pendulum.prompt_loader import render
from pendulum.schemas import APMapping, Candidate


async def synthesize_oneshot(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str = "", round_: int = 0
) -> AgentEnvelope[list[Candidate]]:
    started = time.monotonic()
    try:
        envelope = await _run(nl, aps, deps, feedback, round_)
    except (LlmError, McpError) as exc:
        deps.logger.error("synth_oneshot", "failed", error=str(exc))
        envelope = error_envelope(str(exc))
    envelope.elapsed_s = round(time.monotonic() - started, 2)
    return envelope


def _extract_formula(text: str) -> str:
    """Strip ``` fences and leading labels; return the last non-empty line
    trimmed (models sometimes prefix a label or reasoning line)."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("```")]
    if not lines:
        return ""
    last = lines[-1]
    # drop a leading label like "Formula:" / "LTL:" if present
    for sep in (":",):
        if sep in last:
            head, _, tail = last.partition(sep)
            if head.lower().strip() in ("formula", "ltl", "answer", "output") and tail.strip():
                last = tail.strip()
    return last


async def _run(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str, round_: int
) -> AgentEnvelope[list[Candidate]]:
    cfg = deps.agent_cfg("ONESHOT")
    user = render("oneshot_to_ltl_user", NATURAL_LANGUAGE=nl, ATOMIC_PROPOSITIONS=ap_block(aps))
    if feedback:
        user = feedback + "\n" + user
    messages: list[Message] = [
        {"role": "system", "content": render("oneshot_to_ltl_system")},
        {"role": "user", "content": user},
    ]

    attempts = deps.config.synth_parse_max_retries + 1
    for attempt in range(1, attempts + 1):
        result = await deps.router.complete(cfg, messages, want_logprobs=False)
        deps.logger.debug("synth_oneshot", "completion", attempt=attempt, text=result.text)
        formula = _extract_formula(result.text)
        try:
            candidate = await make_candidate(
                deps, source_agent="oneshot", formula=formula,
                rationale=f"One-shot NL->LTL emission: {formula}",
                index=1, attempts=attempt, round_=round_,
            )
            deps.logger.info("synth_oneshot", "candidate", formula=candidate.canonical, attempt=attempt)
            return ok_envelope([candidate], attempts=attempt)
        except CandidateInvalid as exc:
            deps.logger.warning("synth_oneshot", "attempt_failed", attempt=attempt, error=str(exc))
            messages.append({"role": "assistant", "content": result.text})
            messages.append({
                "role": "user",
                "content": f"That was not a valid formula ({exc}). Output ONLY the corrected LTL formula, nothing else.",
            })

    return error_envelope(f"no valid formula after {attempts} attempts", attempts=attempts)
