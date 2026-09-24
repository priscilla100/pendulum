"""llama-server backend: grammar-constrained decoding + token logprobs.

Speaks the OpenAI-compatible `/v1/chat/completions` endpoint. Two llama.cpp
specifics (both verified in the parent repo, docs/GRAMMAR_DECODING.md):

- GBNF grammar is passed per-request as a top-level `"grammar"` field (raw
  grammar text), so one server hosts constrained and free-form calls alike.
- `"logprobs": true` composes with `"grammar"` — constrained emission still
  reports per-token logprobs, which is exactly what makes formula-scope LNLL
  possible.

llama-server serves a single model; the `model` field is sent but ignored.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from pendulum.llm.base import CompletionResult, LlmError, Message
from pendulum.llm.lnll import compute_lnll


class LlamaCppClient:
    def __init__(self, base_url: str, http_client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url.rstrip("/")
        self._http = http_client or httpx.AsyncClient()

    async def is_healthy(self, timeout_s: float = 2.0) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/health", timeout=timeout_s)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int = 16384,  # accepted for protocol parity; server context is fixed at launch
        max_tokens: int = 2048,
        timeout_s: float = 300.0,
        grammar: Optional[str] = None,
        want_logprobs: bool = False,
        thinking: bool = False,  # not supported by llama-server; ignored
        response_schema: Optional[dict] = None,  # use `grammar` instead here
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if grammar is not None:
            body["grammar"] = grammar
        if want_logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = 1

        try:
            resp = await self._http.post(
                f"{self.base_url}/v1/chat/completions", json=body, timeout=timeout_s
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise LlmError(f"llama-server request failed: {exc}") from exc
        except ValueError as exc:
            raise LlmError(f"llama-server returned non-JSON: {exc}") from exc

        try:
            choice = payload["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"llama-server response missing choices/message: {payload!r:.500}") from exc

        token_logprobs = _extract_logprobs(choice)
        return CompletionResult(
            text=text,
            lnll=compute_lnll(token_logprobs),
            token_logprobs=token_logprobs,
            backend="llamacpp",
            raw=payload,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _extract_logprobs(choice: dict[str, Any]) -> Optional[list[float]]:
    """OpenAI shape: choice.logprobs.content = [{token, logprob, ...}, ...]."""
    content = (choice.get("logprobs") or {}).get("content")
    if not isinstance(content, list) or not content:
        return None
    out: list[float] = []
    for entry in content:
        lp = entry.get("logprob") if isinstance(entry, dict) else None
        if not isinstance(lp, (int, float)):
            return None  # malformed → treat the whole thing as absent
        out.append(float(lp))
    return out
