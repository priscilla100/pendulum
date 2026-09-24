"""node_guard: the graph's exception firewall.

Every node runs under an asyncio timeout (the relevant agent's TIMEOUT_S —
task.md's "expiration time") and a catch-all. A timed-out or crashed node
contributes an AgentError to the error channel and a timing entry; it never
takes the run down. Stage timing is recorded on success too.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Awaitable, Callable

from pendulum.schemas import AgentError, StageTiming

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def node_guard(stage: str, timeout_s: float, logger) -> Callable[[NodeFn], NodeFn]:
    def decorate(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def guarded(state: dict[str, Any]) -> dict[str, Any]:
            started = time.monotonic()
            try:
                update = await asyncio.wait_for(fn(state), timeout=timeout_s)
            except asyncio.TimeoutError:
                elapsed = round(time.monotonic() - started, 2)
                logger.error(stage, "node_timeout", timeout_s=timeout_s)
                return {
                    "errors": [AgentError(stage=stage, agent=stage,
                                          message=f"timed out after {timeout_s}s")],
                    "timings": [StageTiming(stage=stage, seconds=elapsed)],
                }
            except Exception as exc:  # noqa: BLE001 — the graph must keep going
                elapsed = round(time.monotonic() - started, 2)
                logger.error(stage, "node_crashed", error=str(exc))
                return {
                    "errors": [AgentError(stage=stage, agent=stage, message=str(exc))],
                    "timings": [StageTiming(stage=stage, seconds=elapsed)],
                }
            elapsed = round(time.monotonic() - started, 2)
            update.setdefault("timings", []).append(StageTiming(stage=stage, seconds=elapsed))
            return update

        return guarded

    return decorate
