"""Completion-client protocol shared by every LLM backend.

A "completion" here is one stateless chat call: messages in, text out, plus
whatever token logprobs the backend could supply (the raw material for the
Length-Normalized Log-Likelihood confidence exposed to the orchestrator).
Agents never import a concrete backend — they receive a `CompletionRouter`
(see router.py) which speaks this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

#: One chat message: {"role": "system"|"user"|"assistant", "content": str}
Message = dict[str, str]


class LlmError(Exception):
    """Any transport/protocol failure talking to an LLM backend."""


@dataclass
class CompletionResult:
    text: str
    lnll: Optional[float]  # mean token logprob; None if backend gave no logprobs
    token_logprobs: Optional[list[float]]
    backend: str  # "ollama" | "llamacpp"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class CompletionClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int = 16384,
        max_tokens: int = 2048,
        timeout_s: float = 300.0,
        grammar: Optional[str] = None,
        want_logprobs: bool = False,
        thinking: bool = False,
        response_schema: Optional[dict] = None,
    ) -> CompletionResult: ...
