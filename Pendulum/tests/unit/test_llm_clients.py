"""llamacpp + ollama clients against httpx.MockTransport, plus LNLL math."""

from __future__ import annotations

import json

import httpx
import pytest

from pendulum.llm.base import LlmError
from pendulum.llm.llamacpp import LlamaCppClient
from pendulum.llm.lnll import compute_lnll
from pendulum.llm.ollama import OllamaClient

MSGS = [{"role": "user", "content": "hi"}]


def openai_response(text="G (p -> F q)", logprobs=None):
    choice = {"message": {"role": "assistant", "content": text}}
    if logprobs is not None:
        choice["logprobs"] = {"content": [{"token": "t", "logprob": lp} for lp in logprobs]}
    return {"choices": [choice]}


def make_client(cls, base_url, handler):
    return cls(base_url, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


class TestLnll:
    def test_mean(self):
        assert compute_lnll([-1.0, -2.0, -3.0]) == pytest.approx(-2.0)

    def test_empty_and_none(self):
        assert compute_lnll([]) is None
        assert compute_lnll(None) is None


class TestLlamaCpp:
    async def test_sends_grammar_and_logprobs_and_computes_lnll(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            seen["path"] = request.url.path
            return httpx.Response(200, json=openai_response(logprobs=[-0.5, -1.5]))

        client = make_client(LlamaCppClient, "http://x:8080", handler)
        result = await client.complete(MSGS, model="m", grammar="root ::= x", want_logprobs=True)
        assert seen["path"] == "/v1/chat/completions"
        assert seen["grammar"] == "root ::= x"
        assert seen["logprobs"] is True
        assert result.text == "G (p -> F q)"
        assert result.lnll == pytest.approx(-1.0)
        assert result.backend == "llamacpp"

    async def test_no_logprobs_requested_none_returned(self):
        client = make_client(
            LlamaCppClient, "http://x:8080",
            lambda r: httpx.Response(200, json=openai_response()),
        )
        result = await client.complete(MSGS, model="m")
        assert result.lnll is None and result.token_logprobs is None

    async def test_malformed_logprob_entries_treated_as_absent(self):
        payload = openai_response()
        payload["choices"][0]["logprobs"] = {"content": [{"token": "t", "logprob": "oops"}]}
        client = make_client(LlamaCppClient, "http://x:8080", lambda r: httpx.Response(200, json=payload))
        result = await client.complete(MSGS, model="m", want_logprobs=True)
        assert result.lnll is None

    async def test_http_error_raises_llm_error(self):
        client = make_client(LlamaCppClient, "http://x:8080", lambda r: httpx.Response(503))
        with pytest.raises(LlmError, match="llama-server request failed"):
            await client.complete(MSGS, model="m")

    async def test_health(self):
        healthy = make_client(LlamaCppClient, "http://x:8080", lambda r: httpx.Response(200, json={"status": "ok"}))
        assert await healthy.is_healthy() is True

        def refuse(request):
            raise httpx.ConnectError("refused")

        down = make_client(LlamaCppClient, "http://x:8080", refuse)
        assert await down.is_healthy() is False


class TestOllama:
    async def test_native_path_honors_num_ctx_and_thinking(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            seen["path"] = request.url.path
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

        client = make_client(OllamaClient, "http://x:11434/v1", handler)  # /v1 suffix normalized away
        result = await client.complete(MSGS, model="m", num_ctx=4096, thinking=True)
        assert seen["path"] == "/api/chat"
        assert seen["options"]["num_ctx"] == 4096
        assert seen["think"] is True
        assert result.lnll is None and result.backend == "ollama"

    async def test_logprobs_path_uses_openai_endpoint(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            return httpx.Response(200, json=openai_response(logprobs=[-2.0]))

        client = make_client(OllamaClient, "http://x:11434", handler)
        result = await client.complete(MSGS, model="m", want_logprobs=True)
        assert seen["path"] == "/v1/chat/completions"
        assert result.lnll == pytest.approx(-2.0)

    async def test_logprobs_absent_degrades_to_none(self):
        client = make_client(
            OllamaClient, "http://x:11434",
            lambda r: httpx.Response(200, json=openai_response()),
        )
        result = await client.complete(MSGS, model="m", want_logprobs=True)
        assert result.text and result.lnll is None

    async def test_grammar_rejected(self):
        client = make_client(OllamaClient, "http://x:11434", lambda r: httpx.Response(200, json={}))
        with pytest.raises(LlmError, match="does not support GBNF"):
            await client.complete(MSGS, model="m", grammar="root ::= x")

    async def test_embed(self):
        client = make_client(
            OllamaClient, "http://x:11434",
            lambda r: httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]}),
        )
        vecs = await client.embed(["a", "b"], model="all-minilm")
        assert vecs == [[0.1, 0.2], [0.3, 0.4]]

    async def test_embed_count_mismatch_raises(self):
        client = make_client(
            OllamaClient, "http://x:11434",
            lambda r: httpx.Response(200, json={"embeddings": [[0.1]]}),
        )
        with pytest.raises(LlmError, match="1 vectors for 2 inputs"):
            await client.embed(["a", "b"], model="all-minilm")
