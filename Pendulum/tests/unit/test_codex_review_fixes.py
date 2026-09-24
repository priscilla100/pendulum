"""Regression tests for codex review checkpoint #1 findings."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.conftest import FakeMCP, FakeRouter

from pendulum.agents.emission import make_candidate
from pendulum.config import PendulumConfig
from pendulum.llm.base import LlmError
from pendulum.llm.router import CompletionRouter
from pendulum.logging_setup import RunLogger
from pendulum.mcp.client import McpError
from pendulum.schemas import APMapping, Candidate


class TestEmissionDegradation:
    """Finding: confidence emission failures must never invalidate a candidate."""

    async def test_router_failure_during_emission_yields_null_confidence(self, make_deps):
        deps = make_deps(script=[], grammar_up=True)  # empty script → complete() raises

        async def failing_complete(*a, **k):
            raise LlmError("llama-server died mid-run")

        deps.router.complete = failing_complete
        candidate = await make_candidate(
            deps, source_agent="python", formula="G (req -> F ack)",
            rationale="test", index=1,
        )
        assert candidate.confidence is None
        assert candidate.canonical == "G (req -> F ack)"

    async def test_parse_failure_during_emission_yields_null_confidence(self, make_deps):
        deps = make_deps(script=["G (req -> F ack)"], grammar_up=True)
        parse_calls = {"n": 0}
        real_parse = deps.mcp.parse_and_canonicalize

        async def flaky_parse(formula):
            parse_calls["n"] += 1
            if parse_calls["n"] > 1:  # first call = candidate gate, second = emission check
                raise McpError("server gone")
            return await real_parse(formula)

        deps.mcp.parse_and_canonicalize = flaky_parse
        candidate = await make_candidate(
            deps, source_agent="python", formula="G (req -> F ack)",
            rationale="test", index=1,
        )
        assert candidate.confidence is None


class TestVerifyNodeIsolation:
    """Finding: one verifier crashing must not cancel/lose the other."""

    async def test_crashing_verifier_becomes_error_result(self, make_deps, monkeypatch):
        from pendulum.graph import nodes as nodes_mod

        deps = make_deps(script=[json.dumps({"verdict": "SUPPORTS", "evidence": "ok"})],
                         PENDULUM_DET_VERIFY_ENABLED="true")  # det is opt-in now

        async def crash(*a, **k):
            raise RuntimeError("det verifier exploded")

        monkeypatch.setattr(nodes_mod, "verify_deterministic", crash)
        node = nodes_mod.make_nodes(deps)["verify_candidate"]
        candidate = Candidate(id="python-r0-1", formula="G p", canonical="G p", source_agent="python")
        update = await node({
            "candidate": candidate, "others": [], "nl_input": "x",
            "ap_result": None,
        })
        verdicts = {v.agent: v.verdict for v in update["verifications"]}
        assert verdicts["fuzzy"] == "SUPPORTS"  # survived
        assert verdicts["deterministic"] == "ERROR"
        assert "exploded" in next(v for v in update["verifications"] if v.agent == "deterministic").evidence


class TestMcpRestartCoordination:
    """Finding: restart must drain in-flight calls; concurrent failures must
    not double-restart."""

    async def test_concurrent_calls_during_failure_all_complete(self, tmp_path):
        from tests.unit.test_mcp_client import FakeToolset, make_mcp

        class SlowFlakyToolset(FakeToolset):
            async def direct_call_tool(self, name, args, **kw):
                self.calls.append((name, args))
                await asyncio.sleep(0.01)
                if self.fail_first > 0:
                    self.fail_first -= 1
                    raise RuntimeError("transport died")
                return {"consistent": True}

        fake = SlowFlakyToolset({"check_consistency": {"consistent": True}}, fail_first=2)
        async with make_mcp(tmp_path, fake, PENDULUM_TOOL_CACHE="false") as mcp:
            results = await asyncio.gather(
                *(mcp.call("check_consistency", {"formulas": [f"p{i}"]}) for i in range(4)),
                return_exceptions=True,
            )
        assert all(isinstance(r, dict) and r.get("consistent") for r in results), results
        # both failures were retried after restart(s); nothing deadlocked

    async def test_router_aclose_closes_created_clients(self, tmp_path):
        closed = []

        class TrackingClient:
            def __init__(self, url):
                self.base_url = url

            async def aclose(self):
                closed.append(self.base_url)

        router = CompletionRouter(
            PendulumConfig({"LLAMACPP_ENABLED": "false"}),
            TrackingClient("http://a:11434"),
            None,
            RunLogger(tmp_path, level="error", run_id="t"),
            ollama_factory=TrackingClient,
        )
        router._ollama_for("http://b:11434/v1")
        await router.aclose()
        assert sorted(closed) == ["http://a:11434", "http://b:11434"]


class TestMalformedPayloadIsMcpError:
    """Finding: pydantic shape errors must surface as McpError."""

    async def test_wrong_type_field(self, make_deps):
        deps = make_deps()

        async def bad_call(tool, args):
            return {"paraphrases": "not a list", "tnl": 1}

        deps.mcp.call = bad_call
        from pendulum.mcp.client import PendulumMCP

        mcp = PendulumMCP.__new__(PendulumMCP)
        mcp.call = bad_call  # bypass lifecycle; typed wrapper only
        with pytest.raises(McpError, match="malformed payload"):
            await PendulumMCP.ltl_to_nl(mcp, "G p")


class TestFinalizeTimeoutFallback:
    """Production bug: finalize node timeout left the run with no final."""

    def test_missing_final_ranks_survivors_deterministically(self, tmp_path):
        from pendulum.logging_setup import RunLogger
        from pendulum.pipeline import _final_from_state
        from pendulum.schemas import Candidate, VerificationResult

        state = {
            "filtered": [
                Candidate(id="a", formula="G p", canonical="G p", source_agent="python"),
                Candidate(id="b", formula="F q", canonical="F q", source_agent="salt"),
            ],
            "verifications": [
                VerificationResult(candidate_id="a", agent="fuzzy", verdict="SUPPORTS", evidence="e"),
                VerificationResult(candidate_id="b", agent="fuzzy", verdict="REFUTES", evidence="e"),
            ],
        }
        final = _final_from_state(state, RunLogger(tmp_path, level="error", run_id="t"))
        assert final.status == "OK"
        assert final.formulas[0].canonical == "G p"  # SUPPORTS beats REFUTES
        assert "timed out or crashed" in final.message

    def test_no_candidates_is_error(self, tmp_path):
        from pendulum.logging_setup import RunLogger
        from pendulum.pipeline import _final_from_state

        final = _final_from_state({}, RunLogger(tmp_path, level="error", run_id="t"))
        assert final.status == "ERROR" and "no candidates" in final.message


class TestEmissionSemanticDeviation:
    """Approved proposal 6: associativity-only differences are not deviations."""

    async def test_semantically_equal_emission_keeps_confidence(self, make_deps):
        deps = make_deps(script=["G (a & (b & c))"], grammar_up=True)
        # syntactic mismatch vs original, but BLACK says equivalent
        equivalence_calls = []

        async def fake_call(tool, args):
            equivalence_calls.append((tool, args))
            return {"equivalent": True}

        deps.mcp.call = fake_call
        candidate = await make_candidate(
            deps, source_agent="python", formula="G ((a & b) & c)",
            rationale="t", index=1,
        )
        assert candidate.confidence == -0.5  # kept via semantic equivalence
        assert equivalence_calls and equivalence_calls[0][0] == "check_equivalence"

    async def test_semantically_different_emission_nulls_confidence(self, make_deps):
        deps = make_deps(script=["G (a | b)"], grammar_up=True)

        async def fake_call(tool, args):
            return {"equivalent": False}

        deps.mcp.call = fake_call
        candidate = await make_candidate(
            deps, source_agent="python", formula="G (a & b)",
            rationale="t", index=1,
        )
        assert candidate.confidence is None
