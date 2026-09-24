"""The uniform result wrapper every agent function returns.

Agents never raise into the graph: success and failure travel in the same
`AgentEnvelope` shape, so node code can route on `.status` without try/except
at every call site. Mirrors the {STATUS, MESSAGE, ...} convention of task.md.
"""

from __future__ import annotations

from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class AgentEnvelope(BaseModel, Generic[T]):
    status: Literal["OK", "ERROR"]
    message: str = ""
    payload: Optional[T] = None
    confidence: Optional[float] = None  # LNLL where applicable
    attempts: int = 1
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def ok_envelope(
    payload: T,
    *,
    confidence: Optional[float] = None,
    attempts: int = 1,
    elapsed_s: float = 0.0,
) -> AgentEnvelope[T]:
    return AgentEnvelope[T](
        status="OK", payload=payload, confidence=confidence, attempts=attempts, elapsed_s=elapsed_s
    )


def error_envelope(
    message: str, *, attempts: int = 1, elapsed_s: float = 0.0
) -> AgentEnvelope[T]:
    return AgentEnvelope[T](status="ERROR", message=message, attempts=attempts, elapsed_s=elapsed_s)
