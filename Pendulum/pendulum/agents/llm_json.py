"""One shared shape for 'LLM call that must return validated JSON'.

Used by the AP extractor, the Dwyer selector, the fuzzy judge and the
orchestrator filter. The retry loop feeds the model its own mistake
(ExtractionError text is written for the model, not the user) and re-asks
up to the agent's configured max_retries.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from pendulum.agents.parsing import ExtractionError, extract_json_object
from pendulum.config import AgentConfig
from pendulum.llm.base import Message
from pendulum.llm.router import CompletionRouter
from pendulum.logging_setup import RunLogger

T = TypeVar("T")


async def json_completion_with_retry(
    router: CompletionRouter,
    agent_cfg: AgentConfig,
    system: str,
    user: str,
    *,
    validate: Callable[[dict[str, Any]], T],
    logger: RunLogger,
    stage: str,
    want_logprobs: bool = True,
) -> tuple[T, float | None, int]:
    """Returns (validated value, lnll, attempts). Raises ExtractionError when
    the model never produces valid JSON within the retry budget; transport
    errors (LlmError) propagate to the caller's envelope handling."""
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    attempts = agent_cfg.max_retries + 1
    last_error: ExtractionError | None = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        result = await router.complete(agent_cfg, messages, want_logprobs=want_logprobs)
        logger.debug(
            stage, "json_completion",
            attempt=attempt, lnll=result.lnll,
            elapsed_s=round(time.monotonic() - started, 2), text=result.text,
        )
        try:
            return validate(extract_json_object(result.text)), result.lnll, attempt
        except ExtractionError as exc:
            last_error = exc
            logger.warning(stage, "invalid_json_retrying", attempt=attempt, error=str(exc))
            messages.append({"role": "assistant", "content": result.text})
            messages.append({
                "role": "user",
                "content": f"Your reply was invalid: {exc}. Output only the corrected JSON object.",
            })
    raise ExtractionError(f"no valid JSON after {attempts} attempts: {last_error}")
