"""PendulumMCP: deterministic-only caching, restart-once, payload normalization."""

from __future__ import annotations

import json

import pytest
from mcp.shared.exceptions import McpError as ProtocolError
from mcp.types import ErrorData

from pendulum.config import PendulumConfig
from pendulum.logging_setup import RunLogger
from pendulum.mcp.client import McpError, McpToolError, PendulumMCP, _normalize
from pendulum.mcp.toolsets import ALL_TOOLS, BLACK_TOOLS, CACHEABLE_TOOLS, FUZZY_TOOLS, is_cacheable


class FakeToolset:
    """Stands in for MCPToolset: scripted results, call counting, failure injection."""

    def __init__(self, results: dict[str, object], fail_first: int = 0):
        self.results = results
        self.fail_first = fail_first
        self.calls: list[tuple[str, dict]] = []
        self.entered = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        return None

    async def direct_call_tool(self, name, args, **kw):
        self.calls.append((name, args))
        if self.fail_first > 0:
            self.fail_first -= 1
            raise RuntimeError("transport died")
        return self.results[name]

    def filtered(self, fn):
        return ("filtered", fn)


def make_mcp(tmp_path, fake: FakeToolset, **env) -> PendulumMCP:
    config = PendulumConfig({k: str(v) for k, v in env.items()})
    mcp = PendulumMCP(config, RunLogger(tmp_path, level="debug", run_id="mcp-test"))
    mcp._build_toolset = lambda: fake  # type: ignore[method-assign]
    return mcp


class TestToolsets:
    def test_catalogue_shape(self):
        assert len(ALL_TOOLS) == 14
        assert len(BLACK_TOOLS) == 8
        assert not (BLACK_TOOLS & FUZZY_TOOLS)

    def test_fuzzy_never_cacheable(self):
        for tool in FUZZY_TOOLS:
            assert not is_cacheable(tool, {"text": "x"})

    def test_deterministic_cacheable(self):
        assert is_cacheable("parse_and_canonicalize", {"formula": "G p"})
        assert is_cacheable("check_equivalence", {"f1": "p", "f2": "p"})
        assert is_cacheable("nl_to_ltl_via_salt", {"spec": "assert always p"})

    def test_trace_satisfaction_boundary(self):
        args = {"formula": "G p", "trace": {"prefix": [], "loop": [["p"]]}}
        assert is_cacheable("check_trace_satisfaction", args)
        assert not is_cacheable("check_trace_satisfaction", {**args, "explain": True})
        assert is_cacheable("check_trace_satisfaction", {**args, "explain": False})

    def test_every_tool_classified(self):
        assert ALL_TOOLS == CACHEABLE_TOOLS | FUZZY_TOOLS


class TestCaching:
    async def test_deterministic_result_cached(self, tmp_path):
        fake = FakeToolset({"check_equivalence": {"equivalent": True}})
        async with make_mcp(tmp_path, fake) as mcp:
            for _ in range(3):
                assert (await mcp.call("check_equivalence", {"f1": "p", "f2": "p"}))["equivalent"]
        assert len(fake.calls) == 1

    async def test_different_args_not_conflated(self, tmp_path):
        fake = FakeToolset({"check_equivalence": {"equivalent": True}})
        async with make_mcp(tmp_path, fake) as mcp:
            await mcp.call("check_equivalence", {"f1": "p", "f2": "p"})
            await mcp.call("check_equivalence", {"f1": "p", "f2": "q"})
        assert len(fake.calls) == 2

    async def test_fuzzy_tool_never_cached(self, tmp_path):
        fake = FakeToolset({"ltl_to_nl": {"paraphrases": ["a"] * 5, "tnl": "t"}})
        async with make_mcp(tmp_path, fake) as mcp:
            await mcp.call("ltl_to_nl", {"formula": "G p"})
            await mcp.call("ltl_to_nl", {"formula": "G p"})
        assert len(fake.calls) == 2

    async def test_cache_disabled_by_env(self, tmp_path):
        fake = FakeToolset({"check_equivalence": {"equivalent": True}})
        async with make_mcp(tmp_path, fake, PENDULUM_TOOL_CACHE="false") as mcp:
            await mcp.call("check_equivalence", {"f1": "p", "f2": "p"})
            await mcp.call("check_equivalence", {"f1": "p", "f2": "p"})
        assert len(fake.calls) == 2

    async def test_lru_eviction(self, tmp_path):
        fake = FakeToolset({"parse_and_canonicalize": {"valid": True, "canonical": "p"}})
        async with make_mcp(tmp_path, fake, PENDULUM_TOOL_CACHE_SIZE="2") as mcp:
            for f in ("a", "b", "c"):  # 'a' evicted when 'c' arrives
                await mcp.call("parse_and_canonicalize", {"formula": f})
            await mcp.call("parse_and_canonicalize", {"formula": "a"})
        assert len(fake.calls) == 4


class TestRestart:
    async def test_one_failure_triggers_restart_and_retry(self, tmp_path):
        fake = FakeToolset({"check_consistency": {"consistent": True}}, fail_first=1)
        async with make_mcp(tmp_path, fake) as mcp:
            result = await mcp.call("check_consistency", {"formulas": ["p"]})
        assert result == {"consistent": True}
        assert fake.entered == 2  # initial enter + restart
        assert len(fake.calls) == 2

    async def test_double_failure_raises_mcp_error(self, tmp_path):
        fake = FakeToolset({"check_consistency": {}}, fail_first=2)
        async with make_mcp(tmp_path, fake) as mcp:
            with pytest.raises(McpError, match="after restart"):
                await mcp.call("check_consistency", {"formulas": ["p"]})

    async def test_use_outside_context_rejected(self, tmp_path):
        mcp = make_mcp(tmp_path, FakeToolset({}))
        with pytest.raises(McpError, match="outside 'async with'"):
            await mcp.call("salt_help", {})

    async def test_tool_level_error_does_not_restart(self, tmp_path):
        """invalid_params (e.g. unparseable formula) is the server working
        correctly — must surface as McpToolError without a restart."""

        class RejectingToolset(FakeToolset):
            async def direct_call_tool(self, name, args, **kw):
                self.calls.append((name, args))
                raise ProtocolError(ErrorData(code=-32602, message="f1 rejected by parser"))

        fake = RejectingToolset({})
        async with make_mcp(tmp_path, fake) as mcp:
            with pytest.raises(McpToolError, match="rejected by parser") as info:
                await mcp.call("check_equivalence", {"f1": "G (p ->", "f2": "p"})
        assert info.value.server_message == "f1 rejected by parser"
        assert fake.entered == 1  # no restart
        assert len(fake.calls) == 1  # no retry


class TestNormalizeAndTypedWrappers:
    def test_normalize_shapes(self):
        assert _normalize({"a": 1}) == {"a": 1}
        assert _normalize('{"a": 1}') == {"a": 1}
        assert _normalize([{"type": "text", "text": '{"a": 1}'}]) == {"a": 1}
        assert _normalize("not json") == "not json"

    async def test_parse_and_canonicalize_typed(self, tmp_path):
        payload = json.dumps({"valid": True, "canonical": "G (p -> F q)", "aps": ["p", "q"],
                              "temporal_class": "FUTURE_ONLY", "warnings": []})
        fake = FakeToolset({"parse_and_canonicalize": payload})
        async with make_mcp(tmp_path, fake) as mcp:
            result = await mcp.parse_and_canonicalize("G(p->Fq)")
        assert result.valid and result.canonical == "G (p -> F q)" and result.aps == ["p", "q"]

    async def test_salt_and_ltl_to_nl_typed(self, tmp_path):
        fake = FakeToolset({
            "nl_to_ltl_via_salt": {"ok": False, "error": "syntax error near 'assert'"},
            "ltl_to_nl": {"paraphrases": ["one", "two", "three", "four", "five"], "tnl": "gloss"},
        })
        async with make_mcp(tmp_path, fake) as mcp:
            salt = await mcp.nl_to_ltl_via_salt("bad spec")
            nl = await mcp.ltl_to_nl("G p")
        assert not salt.ok and "syntax" in salt.error
        assert len(nl.paraphrases) == 5 and nl.tnl == "gloss"

    async def test_scalar_payload_rejected_by_typed_wrapper(self, tmp_path):
        fake = FakeToolset({"parse_and_canonicalize": "just a string"})
        async with make_mcp(tmp_path, fake) as mcp:
            with pytest.raises(McpError, match="expected a JSON object"):
                await mcp.parse_and_canonicalize("p")

    async def test_black_toolset_filter(self, tmp_path):
        fake = FakeToolset({})
        async with make_mcp(tmp_path, fake) as mcp:
            tag, fn = mcp.black_toolset()
        assert tag == "filtered"

        class TD:
            def __init__(self, name):
                self.name = name

        assert fn(None, TD("check_equivalence")) is True
        assert fn(None, TD("ltl_to_nl")) is False
