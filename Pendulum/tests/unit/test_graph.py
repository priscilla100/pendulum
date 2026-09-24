"""Full-graph routing with fake deps: happy path, AP fallback, error
short-circuits, the feedback loop, and the candidate reducer."""

from __future__ import annotations

import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from tests.conftest import FakeMCP, FakeEmbedder, FakeStore, make_hit

from pendulum.config import PendulumConfig
from pendulum.deps import PendulumDeps
from pendulum.graph.build import build_graph
from pendulum.graph.state import merge_candidates
from pendulum.llm.base import CompletionResult
from pendulum.logging_setup import RunLogger
from pendulum.rag.init import RagStores
from pendulum.schemas import Candidate, SaltResult

# ---------------------------------------------------------------------------
# Fakes tailored to whole-graph runs
# ---------------------------------------------------------------------------


class AgentKeyedRouter:
    """Deterministic under parallel node execution: each agent has its own
    response queue, so scheduling order can't skew the script."""

    def __init__(self, queues: dict[str, list[str]], grammar_up: bool = False):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.grammar_up = grammar_up
        self.calls: dict[str, list[list[dict]]] = {}

    async def grammar_available(self) -> bool:
        return self.grammar_up

    async def complete(self, agent_cfg, messages, *, need_grammar=False,
                       want_logprobs=False, max_tokens=2048,
                       response_schema=None) -> CompletionResult:
        name = agent_cfg.name
        self.calls.setdefault(name, []).append(list(messages))
        queue = self.queues.get(name, [])
        if not queue:
            raise AssertionError(f"no scripted response left for agent {name!r}")
        return CompletionResult(text=queue.pop(0), lnll=-0.5, token_logprobs=[-0.5],
                                backend="fake", raw={})


def structured_model(verdict_args: dict, ranking_args: dict) -> FunctionModel:
    """One FunctionModel serving both PydanticAI agents: dispatches on the
    requested output schema (verdict vs formulas)."""

    def respond(messages, info):
        tool = info.output_tools[0]
        properties = tool.parameters_json_schema.get("properties", {})
        args = verdict_args if "verdict" in properties else ranking_args
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])

    return FunctionModel(respond)


AP_OK = json.dumps({"aps": [
    {"name": "req", "nl_fragment": "a request occurs", "polarity": "event"},
    {"name": "ack", "nl_fragment": "an acknowledgment occurs", "polarity": "event"},
], "open_questions": []})

PY_LINE = 'formulaToFind = Always(LImplies(AtomicProposition("req"), Eventually(AtomicProposition("ack"))))'
DWYER_HITS = [make_hit(
    "response_global", pattern="Response", scope="Global", id="response_global",
    intent="s responds to p", ltl_template="G (p -> F s)", placeholders=["p", "s"],
    example_nl=["every request is acked"],
)]
DWYER_PICK = json.dumps({"selections": [
    {"pattern_id": "response_global", "substitution": {"p": "req", "s": "ack"}},
]})
SALT_HITS = [make_hit("salthelp-00", text="[SALT] assert always ...", section="TOP")]
KEEP_ALL = json.dumps({"keep": ["python-r0-1", "dwyer-r0-1", "salt-r0-1"], "reasoning": "diverse readings"})
SUPPORTS = json.dumps({"verdict": "SUPPORTS", "evidence": "paraphrases match"})
REFUTES = json.dumps({"verdict": "REFUTES", "evidence": "paraphrases clash"})


def graph_deps(tmp_path, queues, *, salt_results=(), verdict="SUPPORTS",
               ranking_formulas=({"formula": "G (req -> F ack)", "canonical": "", "rank": 1,
                                  "justification": "verified"},), **env) -> PendulumDeps:
    # These scenarios were written for the full 3-agent/2-verifier pipeline;
    # dwyer + det verification are now opt-in, so enable them explicitly.
    env.setdefault("PENDULUM_DWYER_ENABLED", "true")
    env.setdefault("PENDULUM_DET_VERIFY_ENABLED", "true")
    # legacy per-candidate judging: these scenarios script per-candidate
    # fuzzy responses; the contrastive row-judge has its own tests below
    env.setdefault("PENDULUM_CONTRASTIVE_JUDGE", "false")
    deps = PendulumDeps(
        config=PendulumConfig({k: str(v) for k, v in env.items()}),
        logger=RunLogger(tmp_path, level="debug", run_id="graph-test"),
        router=AgentKeyedRouter(queues),
        mcp=FakeMCP(salt_results=list(salt_results)),
        embedder=FakeEmbedder(),
        rag=RagStores(dwyer=FakeStore(DWYER_HITS), salt=FakeStore(SALT_HITS)),
        test_model=structured_model(
            {"verdict": verdict, "evidence": "solver checks"},
            {"formulas": list(ranking_formulas), "reasoning": "done"},
        ),
    )
    return deps


async def run_graph(deps, nl="every request is eventually acknowledged"):
    graph = build_graph(deps)
    return await graph.ainvoke({"nl_input": nl, "run_id": "graph-test", "feedback_round": 0})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_all_stages(tmp_path):
    deps = graph_deps(
        tmp_path,
        queues={
            "ap": [AP_OK],
            "python": [PY_LINE],
            "dwyer": [DWYER_PICK],
            "salt": ["declare req, ack\nassert eventually ack"],
            "orch": [KEEP_ALL],
            "fuzzy": [SUPPORTS, SUPPORTS, SUPPORTS],
        },
        salt_results=[SaltResult(ok=True, ltl="F ack")],
    )
    state = await run_graph(deps)
    final = state["final"]
    assert final.status == "OK"
    assert final.formulas[0].canonical == "G (req -> F ack)"
    assert [m.ap for m in final.ap_mapping] == ["req", "ack"]
    # three distinct candidates → 3 Sends × 2 verifiers = 6 verifications
    assert len(state["candidates"]) == 3
    assert len(state["verifications"]) == 6
    assert state["ap_source"] == "extractor"
    assert not state.get("errors")


async def test_low_confidence_triggers_ap_fallback(tmp_path):
    low_conf = CompletionResult(text=AP_OK, lnll=-3.0, token_logprobs=[-3.0], backend="fake", raw={})
    deps = graph_deps(
        tmp_path,
        queues={"ap": [], "orch": [AP_OK, KEEP_ALL], "python": [PY_LINE],
                "dwyer": [json.dumps({"selections": []})], "salt": ["s"],
                "fuzzy": [SUPPORTS]},
        salt_results=[SaltResult(ok=False, error="nope")] * 4,
    )
    deps.router.queues["ap"] = [low_conf]

    # AgentKeyedRouter returns strings; patch to allow a CompletionResult entry
    orig = deps.router.queues["ap"]

    async def complete(agent_cfg, messages, *, need_grammar=False, want_logprobs=False, max_tokens=2048):
        deps.router.calls.setdefault(agent_cfg.name, []).append(list(messages))
        if agent_cfg.name == "ap":
            return orig[0]
        queue = deps.router.queues[agent_cfg.name]
        return CompletionResult(text=queue.pop(0), lnll=-0.5, token_logprobs=[-0.5], backend="fake", raw={})

    deps.router.complete = complete
    state = await run_graph(deps)
    assert state["ap_source"] == "orchestrator_fallback"
    assert state["final"].status == "OK"
    # fallback prompt carried the low-confidence reason
    fallback_system = deps.router.calls["orch"][0][0]["content"]
    assert "ESCALATION CONTEXT" in fallback_system and "-3.0" in fallback_system


async def test_double_ap_failure_short_circuits_to_error(tmp_path):
    garbage = "not json at all"
    deps = graph_deps(tmp_path, queues={
        "ap": [garbage, garbage, garbage],
        "orch": [garbage, garbage, garbage],
    })
    state = await run_graph(deps)
    assert state["final"].status == "ERROR"
    assert "atomic-proposition extraction failed" in state["final"].message
    assert "verifications" not in state or not state["verifications"]


async def test_all_synthesis_failed_is_honest_error(tmp_path):
    deps = graph_deps(tmp_path, queues={
        "ap": [AP_OK],
        "python": ["no assignment"] * 4,
        "dwyer": [json.dumps({"selections": []})],
        "salt": ["s"] * 4,
    }, salt_results=[SaltResult(ok=False, error="boom")] * 4)
    state = await run_graph(deps)
    assert state["final"].status == "ERROR"
    assert "no candidate" in state["final"].message
    # the python agent's exhaustion landed on the error channel
    assert any("synth_python" == e.stage for e in state["errors"])


async def test_feedback_loop_resynthesizes_once(tmp_path):
    deps = graph_deps(
        tmp_path,
        queues={
            "ap": [AP_OK],
            # round 1 produces G req; round 2 a different formula
            "python": ['formulaToFind = Always(AtomicProposition("req"))', PY_LINE],
            "dwyer": [json.dumps({"selections": []})] * 2,
            "salt": ["s"] * 2,
            # round-2 filter sees 2 candidates → orchestrator filter call
            "orch": [json.dumps({"keep": ["python-r1-1"], "reasoning": "first reading refuted"})],
            "fuzzy": [REFUTES, SUPPORTS],
        },
        salt_results=[SaltResult(ok=False, error="boom")] * 2,
        verdict="INCONCLUSIVE",
        ranking_formulas=[{"formula": "G (req -> F ack)", "canonical": "", "rank": 1,
                           "justification": "second round"}],
        SALT_FIX_MAX_ATTEMPTS="1",
        PENDULUM_FEEDBACK_MAX_ROUNDS="1",
    )
    state = await run_graph(deps)
    assert state["feedback_round"] == 1
    assert state["final"].status == "OK"
    # round 2 python prompt carried the failure evidence addendum
    second_user = deps.router.calls["python"][1][-1]["content"]
    assert "RETRY CONTEXT" in second_user and "REFUTES" in second_user
    # old candidate was not re-verified: 2 (round 1) + 2 (round 2) verifications
    assert len(state["verifications"]) == 4


async def test_feedback_loop_disabled_goes_straight_to_finalize(tmp_path):
    deps = graph_deps(
        tmp_path,
        queues={
            "ap": [AP_OK],
            "python": ['formulaToFind = Always(AtomicProposition("req"))'],
            "dwyer": [json.dumps({"selections": []})],
            "salt": ["s"],
            "fuzzy": [REFUTES],
        },
        salt_results=[SaltResult(ok=False, error="boom")] * 4,
        verdict="REFUTES",
        PENDULUM_FEEDBACK_LOOP="false",
    )
    state = await run_graph(deps)
    assert state.get("feedback_round", 0) == 0
    assert len(deps.router.calls["python"]) == 1  # no second round
    assert state["final"].status in ("OK", "ERROR")  # orchestrator's call, but no loop


class TestMergeReducer:
    def c(self, id_, canonical, conf=None):
        return Candidate(id=id_, formula=canonical, canonical=canonical,
                         source_agent="python", confidence=conf)

    def test_dedupes_keeping_incumbent_identity_and_best_confidence(self):
        merged = merge_candidates(
            [self.c("a", "G p", conf=-1.0)],
            [self.c("b", "G p", conf=-0.2), self.c("c", "F q")],
        )
        assert len(merged) == 2
        kept = next(m for m in merged if m.canonical == "G p")
        # identity survives (verification results are keyed by id);
        # only the confidence upgrades
        assert kept.id == "a" and kept.confidence == -0.2

    def test_null_confidence_never_displaces(self):
        merged = merge_candidates([self.c("a", "G p", conf=-1.0)], [self.c("b", "G p")])
        assert next(m for m in merged if m.canonical == "G p").id == "a"

    def test_handles_empty_sides(self):
        assert merge_candidates([], []) == []
        one = [self.c("a", "G p")]
        assert merge_candidates(one, []) == one
        assert merge_candidates([], one) == one


class TestRound3Toggles:
    """Default config: dwyer OFF, det verification OFF."""

    async def test_default_graph_runs_two_synth_agents_fuzzy_only(self, tmp_path):
        deps = graph_deps(
            tmp_path,
            queues={
                "ap": [AP_OK],
                "python": [PY_LINE],
                "salt": ["declare req, ack\nassert eventually ack"],
                "orch": [json.dumps({"keep": ["python-r0-1", "salt-r0-1"], "reasoning": "both"})],
                "fuzzy": [SUPPORTS, SUPPORTS],
            },
            salt_results=[SaltResult(ok=True, ltl="F ack")],
            PENDULUM_DWYER_ENABLED="false",
            PENDULUM_DET_VERIFY_ENABLED="false",
        )
        state = await run_graph(deps)
        assert state["final"].status == "OK"
        assert len(state["candidates"]) == 2  # no dwyer candidate
        assert "dwyer" not in deps.router.calls  # dwyer LLM never invoked
        # fuzzy-only: one verification per candidate
        assert len(state["verifications"]) == 2
        assert {v.agent for v in state["verifications"]} == {"fuzzy"}

    async def test_dwyer_toggle_restores_three_way_fanout(self, tmp_path):
        deps = graph_deps(
            tmp_path,
            queues={
                "ap": [AP_OK],
                "python": [PY_LINE],
                "dwyer": [DWYER_PICK],
                "salt": ["s"],
                "orch": [KEEP_ALL],
                "fuzzy": [SUPPORTS, SUPPORTS, SUPPORTS],
            },
            salt_results=[SaltResult(ok=True, ltl="F ack")],
            PENDULUM_DET_VERIFY_ENABLED="false",
        )  # dwyer enabled via graph_deps default
        state = await run_graph(deps)
        assert len(state["candidates"]) == 3
        assert {v.agent for v in state["verifications"]} == {"fuzzy"}


class TestContrastiveGraphPath:
    """Default config routes filter -> verify_all (one row-level judge call)."""

    async def test_contrastive_single_judge_call_for_row(self, tmp_path):
        row_verdicts = json.dumps({
            "verdicts": [
                {"candidate_id": "python-r0-1", "verdict": "SUPPORTS", "evidence": "matches"},
                {"candidate_id": "salt-r0-1", "verdict": "REFUTES", "evidence": "wrong scope"},
            ],
            "best_candidate_id": "python-r0-1",
            "reasoning": "python reading is faithful",
        })
        deps = graph_deps(
            tmp_path,
            queues={
                "ap": [AP_OK],
                "python": [PY_LINE],
                "salt": ["declare req, ack\nassert eventually ack"],
                "orch": [json.dumps({"keep": ["python-r0-1", "salt-r0-1"], "reasoning": "both"})],
                "fuzzy": [row_verdicts],  # ONE call for the whole row
            },
            salt_results=[SaltResult(ok=True, ltl="F ack")],
            PENDULUM_DWYER_ENABLED="false",
            PENDULUM_DET_VERIFY_ENABLED="false",
            PENDULUM_CONTRASTIVE_JUDGE="true",
            PENDULUM_JUDGE_PARAPHRASE_AUDIT="false",  # this test exercises the single-verdict judge
        )
        state = await run_graph(deps)
        assert state["final"].status == "OK"
        assert len(deps.router.calls["fuzzy"]) == 1  # single row-level judge call
        verdicts = {v.candidate_id: v.verdict for v in state["verifications"]}
        assert verdicts == {"python-r0-1": "SUPPORTS", "salt-r0-1": "REFUTES"}
