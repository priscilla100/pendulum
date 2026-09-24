"""Ollama backend: chat completions + the embedding endpoint for RAG.

Two request paths, chosen per call:

- `want_logprobs=False` → native `/api/chat`. This is the only endpoint that
  honors `options.num_ctx` (context window) and `think` (reasoning mode), so
  it is the default.
- `want_logprobs=True` → OpenAI-compat `/v1/chat/completions` with
  `logprobs: true`. Ollama's support for logprobs is version-dependent; if the
  response has none, `lnll` is simply None (the pipeline's designed
  degradation). num_ctx cannot be set on this path — documented trade-off.

Grammar is NOT supported by Ollama (GBNF deliberately unexposed upstream);
passing one raises, so the router can never silently drop a constraint.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from pendulum.llm.base import CompletionResult, LlmError, Message
from pendulum.llm.lnll import compute_lnll
from pendulum.llm.llamacpp import _extract_logprobs


def _pendulum_trace_llm(body: dict, text: str) -> None:
    """PRINT-ONLY debug trace (no logic change). When PENDULUM_TRACE=<file> is set,
    append one JSON record per LLM call so the original can be diffed 3-way against
    the ports (same flag + format as the ports' support.trace())."""
    import json
    import os

    path = os.environ.get("PENDULUM_TRACE")
    if not path:
        return
    _pendulum_trace_llm.seq = getattr(_pendulum_trace_llm, "seq", 0) + 1
    msgs = body.get("messages", []) or []
    system = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")
    rest = [m for m in msgs if m.get("role") != "system"]
    rec = {
        "seq": _pendulum_trace_llm.seq,
        "kind": "llm",
        "options": {"think": body.get("think"), "options": body.get("options"), "model": body.get("model")},
        "system": system,
        "messages": rest,
        "raw": text,
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    except Exception:
        pass


class OllamaClient:
    def __init__(self, base_url: str, http_client: Optional[httpx.AsyncClient] = None,
                 seed: Optional[int] = None):
        # Accept ".../v1" or bare host root; normalize to the host root.
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self._http = http_client or httpx.AsyncClient()
        # Pin a decoding seed so temperature-0 completions are reproducible run-to-run.
        # (Without this the judge path drifted ~±2 rows — see FINDINGS #9 / exp16 correction.)
        # Overridable via PENDULUM_OLLAMA_SEED (e.g. to vary for a variance study).
        # NB (verified 2026-07-21): gguf/llama.cpp models (qwen*, gemma4:31b non-mlx) HONOR this seed
        # and become deterministic; **MLX models (gemma4:*-mlx) IGNORE it** — MLX has inherent temp-0
        # nondeterminism, so pinning the seed does NOT make -mlx runs reproducible. For a reproducible
        # -mlx measurement, run ×N or use the gguf variant.
        if seed is None:
            import os
            seed = int(os.environ.get("PENDULUM_OLLAMA_SEED", "7"))
        self.seed = seed

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
    ) -> CompletionResult:
        if grammar is not None:
            raise LlmError("Ollama does not support GBNF grammar-constrained decoding")
        if want_logprobs and response_schema is None:
            return await self._complete_openai(
                messages, model=model, temperature=temperature,
                max_tokens=max_tokens, timeout_s=timeout_s,
            )
        return await self._complete_native(
            messages, model=model, temperature=temperature, num_ctx=num_ctx,
            max_tokens=max_tokens, timeout_s=timeout_s, thinking=thinking,
            response_schema=response_schema,
        )

    async def _complete_native(
        self, messages: list[Message], *, model: str, temperature: float,
        num_ctx: int, max_tokens: int, timeout_s: float, thinking: bool,
        response_schema: Optional[dict] = None,
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": thinking,
            "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": max_tokens,
                        "seed": self.seed},
        }
        if response_schema is not None:
            # Ollama structured outputs: constrained decoding to this schema
            body["format"] = response_schema
        payload = await self._post("/api/chat", body, timeout_s)
        try:
            text = payload["message"]["content"] or ""
        except (KeyError, TypeError) as exc:
            raise LlmError(f"Ollama /api/chat response missing message: {payload!r:.500}") from exc
        _pendulum_trace_llm(body, text)  # print-only (no logic change)
        return CompletionResult(text=text, lnll=None, token_logprobs=None, backend="ollama", raw=payload)

    async def _complete_openai(
        self, messages: list[Message], *, model: str, temperature: float,
        max_tokens: int, timeout_s: float,
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "logprobs": True,
            "top_logprobs": 1,
            "seed": self.seed,
        }
        payload = await self._post("/v1/chat/completions", body, timeout_s)
        try:
            choice = payload["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"Ollama /v1 response missing choices: {payload!r:.500}") from exc
        token_logprobs = _extract_logprobs(choice)
        return CompletionResult(
            text=text, lnll=compute_lnll(token_logprobs),
            token_logprobs=token_logprobs, backend="ollama", raw=payload,
        )

    async def embed(self, texts: list[str], *, model: str, timeout_s: float = 120.0) -> list[list[float]]:
        """Batch embeddings via /api/embed (used by the RAG layer)."""
        payload = await self._post("/api/embed", {"model": model, "input": texts}, timeout_s)
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise LlmError(f"Ollama /api/embed returned {len(embeddings or [])} vectors for {len(texts)} inputs")
        return embeddings

    async def _post(self, path: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        try:
            resp = await self._http.post(f"{self.base_url}{path}", json=body, timeout=timeout_s)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise LlmError(f"Ollama request to {path} failed: {exc}") from exc
        except ValueError as exc:
            raise LlmError(f"Ollama returned non-JSON from {path}: {exc}") from exc

    async def aclose(self) -> None:
        await self._http.aclose()
