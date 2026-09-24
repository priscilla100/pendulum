"""Google AI Studio / Gemini API completion backend — lets any agent seat run
against a hosted model instead of a local one.

Same protocol contract and degradation strategy as the CLI backends
(cli_backends.py): no token logprobs (lnll=None). Gemma models served over
this API return HTTP 500 on a strict `response_schema`, so schema enforcement
falls back to `response_mime_type="application/json"` (soft JSON mode) plus
the schema appended to the prompt as an instruction, exactly like the CLI
backends do. Shape errors are left to the caller's existing
validate-and-retry loop (_judge_completion_with_retry).

Auth: reads GOOGLE_API_KEY or GEMINI_API_KEY from the environment. Raises at
call time, not import time, if neither is set.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from pendulum.llm.base import CompletionResult, LlmError, Message
from pendulum.llm.cli_backends import _flatten  # reuse the exact same prompt-flattening + schema-instruction logic

# The free/shared Gemma-4-31B endpoint on Google AI Studio returns 503
# UNAVAILABLE ("high demand") on a large fraction of calls (~2/3 observed
# 2026-09-16) even though the request itself is fine -- this is capacity, not
# a bug. Pendulum's own judge-retry loop (_judge_completion_with_retry) only
# retries on malformed JSON, not transport errors, so without a retry here a
# single 503 fails the entire row. Retried transparently inside this client;
# callers never see the transient failures.
_TRANSIENT_MAX_RETRIES = 5
_TRANSIENT_BASE_DELAY_S = 2.0


class GeminiApiClient:
    """`{PREFIX}_BACKEND=gemini-api`. `{PREFIX}_MODEL` should be a model id
    from `client.models.list()`, e.g. "gemma-4-31b-it"."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key  # lazy: real default resolved in complete()
        self._client = None

    def _get_client(self, timeout_s: float = 300.0):
        if self._client is None:
            from google import genai
            from google.genai import types

            key = self._api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise LlmError(
                    "gemini-api backend: neither GOOGLE_API_KEY nor GEMINI_API_KEY is set"
                )
            # Explicit transport-level timeout (httpx, milliseconds). Without
            # this, a stuck OS-level DNS/socket operation is NOT actually
            # aborted by an outer asyncio.wait_for -- that only cancels the
            # awaiting coroutine, leaving the underlying blocking call (and
            # the httpx connection-pool slot it holds) stuck indefinitely.
            # Verified 2026-09-17: two prior stalls (both processes frozen at
            # 0% CPU for 30min-2h with zero progress, surviving the
            # coroutine-level timeout fix) only recovered via a manual
            # kill+restart -- consistent with pool exhaustion from a leaked
            # blocked connection, not just a slow response.
            self._client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            )
        return self._client

    def _invalidate_client(self):
        """Drop the cached client (and its httpx connection pool) so the next
        attempt builds a fresh one, rather than reusing a pool that may be
        holding a permanently-stuck connection from a prior failure."""
        self._client = None

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int = 16384,  # ignored -- not exposed by this API surface
        max_tokens: int = 2048,
        timeout_s: float = 300.0,
        grammar: Optional[str] = None,  # unsupported; ignored (router never sends one here)
        want_logprobs: bool = False,  # this API does not return logprobs; ignored
        thinking: bool = False,  # ignored
        response_schema: Optional[dict] = None,
    ) -> CompletionResult:
        if grammar is not None:
            raise LlmError("gemini-api backend does not support GBNF grammar-constrained decoding")

        prompt = _flatten(messages, response_schema)
        client = self._get_client(timeout_s)

        from google.genai import types

        # Gemma on this API doesn't support strict response_schema (see module
        # docstring), so it falls back to soft JSON mode -- which, unlike a
        # schema-constrained backend (e.g. Ollama's `format`), lets the model
        # ramble before/around the JSON payload. The caller's own default
        # (2048, matched to a stricter backend) was observed truncating real
        # judge responses mid-JSON (finish_reason=MAX_TOKENS, verified
        # 2026-09-16). An 8192 floor was tried next; empirical data from the
        # exp.25 run (2026-09-16) shows MAX_TOKENS failures are 100%
        # concentrated on multi-candidate rows (8/8 observed failures all had
        # 2 candidates, vs 0/loads with 1) -- more paraphrases + forbidden
        # traces + a comparison table in the prompt means more verbose
        # reasoning before the model settles on JSON. 8192 wasn't enough;
        # doubled to 16384 for schema requests, since there's no real
        # downside to a higher ceiling (the model still stops when done).
        effective_max_tokens = max(max_tokens, 16384) if response_schema is not None else max_tokens

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=effective_max_tokens,
            response_mime_type="application/json" if response_schema is not None else None,
            # We never pass `tools`, so automatic function calling has nothing to do --
            # but the SDK enables AFC introspection by default on generate_content
            # calls (it warns this isn't recommended outside AsyncChat), and that
            # introspection is implicated in an intermittent empty-`.text` response
            # observed on ~1 in 3-4 real calls (verified 2026-09-16). Disabling it
            # outright removes the interaction rather than working around symptoms.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        from google.genai import errors as genai_errors
        import httpx

        last_reason = None
        text = None
        for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model, contents=prompt, config=config,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError as exc:
                # The API can silently stall (connection established, no data,
                # no error raised) rather than returning a 5xx -- observed
                # 2026-09-17 during a concurrent exp.16/17 run: both processes
                # made zero progress for 12+ minutes with requests hanging
                # indefinitely. `timeout_s` was accepted as a parameter but
                # never actually applied to the call, so a stall could never
                # trigger the retry loop below. Treated as transient, same
                # backoff as a server error. Also invalidate the cached
                # client: an asyncio-level cancellation here does NOT abort
                # the underlying blocking network call, so the connection-pool
                # slot it holds can stay stuck -- reusing that same pool on
                # retry can perpetuate the stall (observed twice more
                # 2026-09-17 even after this timeout was added; see
                # _invalidate_client's docstring).
                last_reason = f"request timed out after {timeout_s}s"
                self._invalidate_client()
                if attempt == _TRANSIENT_MAX_RETRIES:
                    raise LlmError(
                        f"gemini-api request for model {model!r} timed out after "
                        f"{_TRANSIENT_MAX_RETRIES + 1} attempts (each capped at {timeout_s}s)"
                    ) from exc
                await asyncio.sleep(_TRANSIENT_BASE_DELAY_S * (2 ** attempt))
                client = self._get_client(timeout_s)
                continue
            except (httpx.TransportError, OSError) as exc:
                # DNS/socket-level failures (e.g. "[Errno 8] nodename nor
                # servname provided" during a real network outage, observed
                # 2026-09-17) previously fell through to the generic handler
                # below and failed immediately with NO retry -- correct for a
                # permanent DNS misconfiguration, but wrong for a transient
                # outage that resolves itself within seconds. Now retried
                # with the same backoff, AND the client is invalidated (a
                # broken connection is exactly the kind of state a cached
                # httpx pool can get stuck holding).
                last_reason = f"transport error: {exc}"
                self._invalidate_client()
                if attempt == _TRANSIENT_MAX_RETRIES:
                    raise LlmError(
                        f"gemini-api request for model {model!r} failed after "
                        f"{_TRANSIENT_MAX_RETRIES + 1} attempts (transport/DNS errors): {exc}"
                    ) from exc
                await asyncio.sleep(_TRANSIENT_BASE_DELAY_S * (2 ** attempt))
                client = self._get_client(timeout_s)
                continue
            except genai_errors.ServerError as exc:
                # 503 UNAVAILABLE ("high demand") and similar 5xx: transient
                # capacity issues on Google's side, not a request problem.
                last_reason = str(exc)
                self._invalidate_client()
                if attempt == _TRANSIENT_MAX_RETRIES:
                    raise LlmError(
                        f"gemini-api request for model {model!r} failed after "
                        f"{_TRANSIENT_MAX_RETRIES + 1} attempts (transient server errors): {exc}"
                    ) from exc
                await asyncio.sleep(_TRANSIENT_BASE_DELAY_S * (2 ** attempt))
                client = self._get_client(timeout_s)
                continue
            except genai_errors.ClientError as exc:
                # 429 RESOURCE_EXHAUSTED (rate limit): transient under
                # concurrent load from multiple rescore harnesses sharing one
                # API key -- verified empirically 2026-09-16 running exp.16/
                # 17/21 concurrently. Retried like a server error; any other
                # 4xx (e.g. 400 bad request) is not transient and should not
                # be retried, so only code 429 goes through the backoff path.
                if getattr(exc, "code", None) != 429:
                    raise LlmError(f"gemini-api request for model {model!r} failed: {exc}") from exc
                last_reason = str(exc)
                self._invalidate_client()
                if attempt == _TRANSIENT_MAX_RETRIES:
                    raise LlmError(
                        f"gemini-api request for model {model!r} failed after "
                        f"{_TRANSIENT_MAX_RETRIES + 1} attempts (rate limited): {exc}"
                    ) from exc
                await asyncio.sleep(_TRANSIENT_BASE_DELAY_S * (2 ** attempt))
                client = self._get_client(timeout_s)
                continue
            except Exception as exc:  # non-transient: normalize and give up immediately
                raise LlmError(f"gemini-api request for model {model!r} failed: {exc}") from exc

            text = getattr(resp, "text", None)
            if text is not None:
                break
            # Empty text with no exception: surface the actual reason (e.g. a
            # finish_reason other than STOP) and retry -- treated as transient
            # since disabling automatic_function_calling (above) should make
            # this rare but not necessarily impossible.
            try:
                last_reason = f"finish_reason={resp.candidates[0].finish_reason!r}"
            except Exception:
                last_reason = f"no candidates in response: {resp!r:.300}"
            if attempt == _TRANSIENT_MAX_RETRIES:
                raise LlmError(
                    f"gemini-api response for model {model!r} had no text after "
                    f"{_TRANSIENT_MAX_RETRIES + 1} attempts; last reason: {last_reason}"
                )
            await asyncio.sleep(_TRANSIENT_BASE_DELAY_S * (2 ** attempt))

        return CompletionResult(
            text=text, lnll=None, token_logprobs=None, backend="gemini-api",
            raw={"model": model},
        )
