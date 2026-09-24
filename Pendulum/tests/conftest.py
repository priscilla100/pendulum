"""Shared fixtures: config factories + fake LLM/MCP layers for agent tests."""

from __future__ import annotations

import re

import pytest

from pendulum.config import PendulumConfig
from pendulum.deps import PendulumDeps
from pendulum.llm.base import CompletionResult
from pendulum.logging_setup import RunLogger
from pendulum.schemas import LtlToNlResult, ParseResult, SaltResult


@pytest.fixture
def bare_config() -> PendulumConfig:
    """A config backed by an empty mapping — pure code defaults."""
    return PendulumConfig({})


@pytest.fixture
def make_config():
    """Factory: make_config(KEY=value, ...) -> PendulumConfig over that dict."""

    def _make(**env: str) -> PendulumConfig:
        return PendulumConfig({k: str(v) for k, v in env.items()})

    return _make


class FakeRouter:
    """Scripted CompletionRouter stand-in.

    `script` is a list of str (text, lnll=-0.5) or CompletionResult; each
    complete() pops the next entry. Grammar availability is a flag."""

    def __init__(self, script, grammar_up: bool = False):
        self.script = list(script)
        self.grammar_up = grammar_up
        self.calls: list[dict] = []

    async def grammar_available(self) -> bool:
        return self.grammar_up

    async def complete(self, agent_cfg, messages, *, need_grammar=False,
                       want_logprobs=False, max_tokens=2048,
                       response_schema=None) -> CompletionResult:
        self.calls.append({
            "agent": agent_cfg.name, "messages": messages,
            "need_grammar": need_grammar, "want_logprobs": want_logprobs,
            "response_schema": response_schema,
        })
        if not self.script:
            raise AssertionError("FakeRouter script exhausted")
        entry = self.script.pop(0)
        if isinstance(entry, CompletionResult):
            return entry
        return CompletionResult(text=entry, lnll=-0.5, token_logprobs=[-0.5],
                                backend="fake", raw={})


class FakeMCP:
    """Typed-method fake of PendulumMCP.

    parse_and_canonicalize: valid iff the formula does not contain 'INVALID';
    canonical form = whitespace-normalized input (good enough for dedup and
    round-trip assertions). Other methods are scripted via constructor."""

    def __init__(self, salt_results=None, paraphrases=None):
        self.salt_results = list(salt_results or [])
        self.paraphrases = paraphrases or ["p one", "p two", "p three", "p four", "p five"]
        self.calls: list[tuple[str, dict]] = []

    async def parse_and_canonicalize(self, formula: str) -> ParseResult:
        self.calls.append(("parse_and_canonicalize", {"formula": formula}))
        if "INVALID" in formula or not formula.strip():
            return ParseResult(valid=False, error=f"Parse error in {formula!r}")
        canonical = re.sub(r"\s+", " ", formula.strip())
        return ParseResult(valid=True, canonical=canonical, aps=sorted(set(re.findall(r"\b[a-z][a-z0-9_]*\b", formula))))

    async def nl_to_ltl_via_salt(self, spec: str) -> SaltResult:
        self.calls.append(("nl_to_ltl_via_salt", {"spec": spec}))
        if not self.salt_results:
            raise AssertionError("FakeMCP salt script exhausted")
        return self.salt_results.pop(0)

    async def ltl_to_nl(self, formula: str) -> LtlToNlResult:
        self.calls.append(("ltl_to_nl", {"formula": formula}))
        return LtlToNlResult(paraphrases=self.paraphrases, tnl="gloss")

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return {}

    def black_toolset(self):
        return None


class FakeEmbedder:
    model = "fake-embed"

    async def embed_one(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeStore:
    """VectorStore stand-in returning pre-scripted hits regardless of query."""

    def __init__(self, hits):
        self.hits = hits

    def search(self, query_vec, k):
        return self.hits[:k]

    def chunks_by_source(self, source):
        return [h.chunk for h in self.hits if h.chunk.metadata.get("source") == source]


def make_hit(chunk_id: str, text: str = "", **metadata):
    from pendulum.rag.store import Chunk, Hit

    return Hit(chunk=Chunk(id=chunk_id, text=text or chunk_id, metadata=metadata), score=0.9)


@pytest.fixture
def make_deps(tmp_path):
    """Factory: make_deps(script=[...], grammar_up=False, mcp=FakeMCP(),
    dwyer_hits=[...], salt_hits=[...], **env)."""

    def _make(script=(), grammar_up=False, mcp=None, dwyer_hits=None, salt_hits=None, **env) -> PendulumDeps:
        from pendulum.rag.init import RagStores

        config = PendulumConfig({k: str(v) for k, v in env.items()})
        rag = None
        if dwyer_hits is not None or salt_hits is not None:
            rag = RagStores(dwyer=FakeStore(dwyer_hits or []), salt=FakeStore(salt_hits or []))
        return PendulumDeps(
            config=config,
            logger=RunLogger(tmp_path, level="debug", run_id="agent-test"),
            router=FakeRouter(script, grammar_up=grammar_up),
            mcp=mcp or FakeMCP(),
            embedder=FakeEmbedder() if rag is not None else None,
            rag=rag,
        )

    return _make
