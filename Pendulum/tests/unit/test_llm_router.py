"""CompletionRouter: grammar routing, health caching, graceful fallback."""

from __future__ import annotations

import httpx
import pytest

from pendulum.config import PendulumConfig
from pendulum.llm.llamacpp import LlamaCppClient
from pendulum.llm.ollama import OllamaClient
from pendulum.llm.router import CompletionRouter
from pendulum.logging_setup import RunLogger

MSGS = [{"role": "user", "content": "emit"}]


class Recorder:
    """Programmable fake HTTP surface for both backends."""

    def __init__(self, llamacpp_healthy=True, llamacpp_fails=False):
        self.llamacpp_healthy = llamacpp_healthy
        self.llamacpp_fails = llamacpp_fails
        self.calls: list[str] = []
        self.health_probes = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            self.health_probes += 1
            return httpx.Response(200 if self.llamacpp_healthy else 503)
        if path == "/v1/chat/completions":  # llama-server (only grammar calls go here)
            self.calls.append("llamacpp")
            if self.llamacpp_fails:
                return httpx.Response(500)
            return httpx.Response(200, json={
                "choices": [{
                    "message": {"role": "assistant", "content": "G p"},
                    "logprobs": {"content": [{"token": "G", "logprob": -0.25}]},
                }]
            })
        if path == "/api/chat":  # ollama native
            self.calls.append("ollama")
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "F q"}})
        raise AssertionError(f"unexpected path {path}")


@pytest.fixture
def make_router(tmp_path):
    def _make(recorder: Recorder, grammar_text="root ::= x", **env) -> CompletionRouter:
        grammar_path = tmp_path / "g.gbnf"
        grammar_path.write_text(grammar_text)
        config = PendulumConfig({
            "PENDULUM_GRAMMAR_FILE": str(grammar_path),
            "LLAMACPP_HEALTH_TTL_S": "1000",
            **{k: str(v) for k, v in env.items()},
        })
        transport = httpx.MockTransport(recorder.handler)
        ollama = OllamaClient("http://o:11434", http_client=httpx.AsyncClient(transport=transport))
        return CompletionRouter(
            config,
            ollama,
            LlamaCppClient("http://l:8080", http_client=httpx.AsyncClient(transport=transport)),
            RunLogger(tmp_path, level="debug", run_id="router-test"),
            ollama_factory=lambda url: ollama,  # all base_urls resolve to the mocked client
        )

    return _make


async def test_grammar_call_routes_to_llamacpp_with_lnll(bare_config, make_router):
    rec = Recorder()
    router = make_router(rec)
    result = await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.calls == ["llamacpp"]
    assert result.backend == "llamacpp" and result.lnll == pytest.approx(-0.25)


async def test_unhealthy_llamacpp_falls_back_to_ollama(bare_config, make_router):
    rec = Recorder(llamacpp_healthy=False)
    router = make_router(rec)
    result = await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.calls == ["ollama"]
    assert result.backend == "ollama" and result.lnll is None


async def test_llamacpp_disabled_never_probed(bare_config, make_router):
    rec = Recorder()
    router = make_router(rec, LLAMACPP_ENABLED="false")
    result = await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.health_probes == 0 and result.backend == "ollama"


async def test_health_probe_cached_within_ttl(bare_config, make_router):
    rec = Recorder()
    router = make_router(rec)
    for _ in range(3):
        await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.health_probes == 1  # TTL=1000s → one probe for all three calls


async def test_midrun_llamacpp_failure_falls_back_and_invalidates_health(bare_config, make_router):
    rec = Recorder(llamacpp_fails=True)
    router = make_router(rec)
    result = await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.calls == ["llamacpp", "ollama"]  # tried, failed, degraded
    assert result.backend == "ollama"
    # next call re-probes health rather than trusting the stale OK
    probes_before = rec.health_probes
    await router.complete(bare_config.agent("PYTHON"), MSGS, need_grammar=True)
    assert rec.health_probes == probes_before + 1


async def test_plain_call_goes_straight_to_ollama(bare_config, make_router):
    rec = Recorder()
    router = make_router(rec)
    result = await router.complete(bare_config.agent("AP"), MSGS)
    assert rec.calls == ["ollama"] and rec.health_probes == 0
    assert result.text == "F q"
