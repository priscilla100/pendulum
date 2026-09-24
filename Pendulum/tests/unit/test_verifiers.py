"""Fuzzy + deterministic verification agents."""

from __future__ import annotations

import json

from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from pendulum.agents.deterministic_verifier import verify_deterministic
from pendulum.agents.fuzzy_verifier import JUDGE_SCHEMA, verify_fuzzy, verify_row_contrastive
from pendulum.config import PendulumConfig


def test_paraphrase_audit_is_default():
    # exp-16 made the per-paraphrase audit judge the production default (+4, 0 regressions).
    assert PendulumConfig({}).judge_paraphrase_audit is True
    assert PendulumConfig({"PENDULUM_JUDGE_PARAPHRASE_AUDIT": "false"}).judge_paraphrase_audit is False
from pendulum.llm.base import CompletionResult
from pendulum.mcp.client import McpError
from pendulum.schemas import APMapping, Candidate
from tests.conftest import FakeMCP, FakeRouter

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]
CAND = Candidate(id="python-1", formula="G (req -> F ack)", canonical="G (req -> F ack)",
                 source_agent="python", confidence=-0.4)

SUPPORTS = json.dumps({"verdict": "SUPPORTS", "evidence": "paraphrase 2 matches the requirement"})


class TestFuzzy:
    async def test_happy_path(self, make_deps):
        deps = make_deps(script=[SUPPORTS])
        result = await verify_fuzzy("every request is eventually acked", APS, CAND, deps)
        assert result.verdict == "SUPPORTS" and result.agent == "fuzzy"
        assert result.confidence == -0.5  # judge completion LNLL
        assert result.candidate_id == "python-1"
        # paraphrases reached the judge prompt
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "1. p one" in user and "G (req -> F ack)" in user

    async def test_invalid_verdict_retried(self, make_deps):
        bad = json.dumps({"verdict": "MAYBE", "evidence": "?"})
        deps = make_deps(script=[bad, SUPPORTS])
        result = await verify_fuzzy("x", APS, CAND, deps)
        assert result.verdict == "SUPPORTS" and len(deps.router.calls) == 2

    async def test_mcp_failure_becomes_error_verdict(self, make_deps):
        deps = make_deps(script=[])

        async def boom(formula):
            raise McpError("ltl_to_nl died")

        deps.mcp.ltl_to_nl = boom
        result = await verify_fuzzy("x", APS, CAND, deps)
        assert result.verdict == "ERROR" and "ltl_to_nl died" in result.evidence

    async def test_judge_exhaustion_becomes_error_verdict(self, make_deps):
        bad = json.dumps({"verdict": "MAYBE", "evidence": "?"})
        deps = make_deps(script=[bad] * 3)  # max_retries=2 → 3 attempts
        result = await verify_fuzzy("x", APS, CAND, deps)
        assert result.verdict == "ERROR"


class SchemaRouter(FakeRouter):
    """FakeRouter that additionally accepts and records `response_schema`
    (the conftest fake predates the structured-output router kwarg)."""

    def __init__(self, script, grammar_up: bool = False):
        super().__init__(script, grammar_up=grammar_up)
        self.schemas: list = []

    async def complete(self, agent_cfg, messages, *, need_grammar=False,
                       want_logprobs=False, max_tokens=2048,
                       response_schema=None) -> CompletionResult:
        self.schemas.append(response_schema)
        return await super().complete(
            agent_cfg, messages,
            need_grammar=need_grammar, want_logprobs=want_logprobs,
        )


class TraceMCP(FakeMCP):
    """FakeMCP whose generic call() serves gen_violating_trace per formula
    and compare_candidates from a fixed payload; entries may be exceptions."""

    def __init__(self, traces=None, compare=None, dist=None, **kw):
        super().__init__(**kw)
        self.traces = traces or {}
        self.compare = compare if compare is not None else {}
        self.dist = dist if dist is not None else {}

    async def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "gen_violating_trace":
            entry = self.traces.get(args["formula"], {"violatable": False})
            if isinstance(entry, Exception):
                raise entry
            return entry
        if tool == "compare_candidates":
            if isinstance(self.compare, Exception):
                raise self.compare
            return self.compare
        if tool == "distinguishing_trace":
            if isinstance(self.dist, Exception):
                raise self.dist
            return self.dist
        return {}


def contrastive_deps(make_deps, script, mcp=None):
    # These tests exercise the single-verdict contrastive judge. The paraphrase-audit
    # judge is now the PRODUCTION default (exp-16), so opt out explicitly here; the
    # TestParaphraseAudit tests re-enable it, and test_paraphrase_audit_is_default
    # asserts the production default separately.
    deps = make_deps(mcp=mcp or TraceMCP(), PENDULUM_JUDGE_PARAPHRASE_AUDIT="false")
    deps.router = SchemaRouter(script)
    return deps


CAND2 = Candidate(id="salt-1", formula="F ack", canonical="F ack",
                  source_agent="salt", confidence=-1.2)

ROW_OK = json.dumps({
    "verdicts": [
        {"candidate_id": "python-1", "verdict": "SUPPORTS", "evidence": "no disagreement found"},
        {"candidate_id": "salt-1", "verdict": "REFUTES", "evidence": "drops the always scope"},
    ],
    "best_candidate_id": "python-1",
    "reasoning": "python-1 keeps the universal quantification",
})


class TestContrastive:
    async def test_happy_path_two_candidates(self, make_deps):
        mcp = TraceMCP(
            traces={
                "G (req -> F ack)": {"violatable": True,
                                     "trace": {"prefix": [["req"]], "loop": [[]]}},
                "F ack": {"violatable": True,
                          "trace": {"prefix": [], "loop": [["req"]]}},
            },
            compare={"equivalent_pairs": [], "stronger_than": [[0, 1]]},
        )
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)
        results = await verify_row_contrastive(
            "every request is eventually acked", APS, [CAND, CAND2], deps)

        # ids round-trip in candidate order, agent + mixed verdicts as scripted
        assert [r.candidate_id for r in results] == ["python-1", "salt-1"]
        assert [r.verdict for r in results] == ["SUPPORTS", "REFUTES"]
        assert all(r.agent == "fuzzy" for r in results)
        # the ONE completion's LNLL is shared by every verdict
        assert [r.confidence for r in results] == [-0.5, -0.5]
        assert results[1].evidence == "drops the always scope"
        # single judge call, schema-constrained, logprobs requested
        assert len(deps.router.calls) == 1
        assert deps.router.calls[0]["want_logprobs"] is True
        assert deps.router.schemas == [JUDGE_SCHEMA]
        verdict_schema = JUDGE_SCHEMA["properties"]["verdicts"]["items"]
        assert verdict_schema["properties"]["verdict"]["enum"] == [
            "SUPPORTS", "REFUTES", "INCONCLUSIVE"]
        assert JUDGE_SCHEMA["additionalProperties"] is False

        user = deps.router.calls[0]["messages"][1]["content"]
        # evidence assembly: paraphrases, readable traces, id-based lattice
        assert "candidate python-1: G (req -> F ack)" in user
        assert "1. p one" in user
        assert "forbidden example: step1 {req}; then forever {}" in user
        assert "forbidden example: then forever {req}" in user
        assert "python-1 ⇒ salt-1 (strictly stronger)" in user

    async def test_trace_tautology_and_error_branches(self, make_deps):
        mcp = TraceMCP(
            traces={
                "G (req -> F ack)": {"violatable": False},
                "F ack": McpError("black exploded"),
            },
            compare={"equivalent_pairs": [[0, 1]], "stronger_than": []},
        )
        ok = json.dumps({
            "verdicts": [
                {"candidate_id": "python-1", "verdict": "SUPPORTS", "evidence": "e"},
                {"candidate_id": "salt-1", "verdict": "SUPPORTS", "evidence": "e"},
            ],
            "best_candidate_id": None, "reasoning": "",
        })
        deps = contrastive_deps(make_deps, [ok], mcp=mcp)
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        assert [r.verdict for r in results] == ["SUPPORTS", "SUPPORTS"]
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "(no violating trace — formula is a tautology!)" in user
        assert "(trace unavailable)" in user
        assert "python-1 ≡ salt-1 (merged)" in user

    async def test_paraphrase_failure_degrades_in_prompt(self, make_deps):
        mcp = TraceMCP()

        async def boom(formula):
            raise McpError("ltl_to_nl died")

        mcp.ltl_to_nl = boom
        ok = json.dumps({
            "verdicts": [{"candidate_id": "python-1", "verdict": "INCONCLUSIVE",
                          "evidence": "no paraphrases to judge from"}],
            "best_candidate_id": None, "reasoning": "",
        })
        deps = contrastive_deps(make_deps, [ok], mcp=mcp)
        results = await verify_row_contrastive("x", APS, [CAND], deps)
        assert results[0].verdict == "INCONCLUSIVE"  # degraded, not ERROR
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "(paraphrases unavailable)" in user

    async def test_lattice_skipped_for_single_candidate(self, make_deps):
        ok = json.dumps({
            "verdicts": [{"candidate_id": "python-1", "verdict": "SUPPORTS", "evidence": "e"}],
            "best_candidate_id": "python-1", "reasoning": "",
        })
        deps = contrastive_deps(make_deps, [ok])
        await verify_row_contrastive("x", APS, [CAND], deps)
        assert not any(name == "compare_candidates" for name, _ in deps.mcp.calls)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "(single candidate — no relations to compare)" in user

    async def test_lattice_error_degrades(self, make_deps):
        mcp = TraceMCP(compare=McpError("compare_candidates died"))
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        assert [r.verdict for r in results] == ["SUPPORTS", "REFUTES"]
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "(relations unavailable)" in user

    async def test_tnl_hidden_by_default(self, make_deps):
        deps = contrastive_deps(make_deps, [ROW_OK])  # PENDULUM_JUDGE_SHOW_TNL defaults off
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "gloss" not in user and "literal reading" not in user

    async def test_tnl_shown_when_flag_on(self, make_deps):
        deps = contrastive_deps(make_deps, [ROW_OK])
        deps.config = deps.config.__class__({**deps.config._env, "PENDULUM_JUDGE_SHOW_TNL": "true"})
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        # the deterministic TNL ("gloss" from the fake) appears, framed as authoritative
        assert user.count("gloss") == 2  # one per candidate
        assert "literal reading (deterministic, AUTHORITATIVE" in user

    async def test_tnl_only_replaces_paraphrases(self, make_deps):
        deps = contrastive_deps(make_deps, [ROW_OK])
        deps.config = deps.config.__class__({**deps.config._env, "PENDULUM_JUDGE_TNL_ONLY": "true"})
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "deterministic literal reading" in user and user.count("gloss") == 2
        assert "mechanical paraphrases" not in user and "p one" not in user

    async def test_dist_trace_added_with_explanation(self, make_deps):
        mcp = TraceMCP(dist={"direction": "f1_only", "trace": {"prefix": [["req"]], "loop": [[]]}})
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)
        deps.config = deps.config.__class__({**deps.config._env, "PENDULUM_JUDGE_DIST_TRACE": "true"})
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "DISTINGUISHING TRACES" in user
        # f1_only: the trace satisfies f1 (python-1) and violates f2 (salt-1)
        assert "python-1 ACCEPTS but salt-1 REJECTS" in user

    async def test_explain_traces_annotates_forbidden_example(self, make_deps):
        mcp = TraceMCP(traces={
            "G (req -> F ack)": {"violatable": True, "trace": {"prefix": [["req"]], "loop": [[]]},
                                 "explanation": "req holds at step 0 but ack never occurs afterward"},
            "F ack": {"violatable": True, "trace": {"prefix": [[]], "loop": [[]]},
                      "explanation": "ack never occurs"},
        })
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)
        deps.config = deps.config.__class__(
            {**deps.config._env, "PENDULUM_JUDGE_EXPLAIN_TRACES": "true"})
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "why the formula forbids this run: req holds at step 0 but ack never occurs" in user
        gv = [args for tool, args in mcp.calls if tool == "gen_violating_trace"]
        assert gv and all(a.get("explain") is True for a in gv)  # explain=true passed

    async def test_explain_traces_off_no_annotation(self, make_deps):
        mcp = TraceMCP(traces={
            "G (req -> F ack)": {"violatable": True, "trace": {"prefix": [["req"]], "loop": [[]]},
                                 "explanation": "should not appear"},
            "F ack": {"violatable": True, "trace": {"prefix": [[]], "loop": [[]]}, "explanation": "nope"},
        })
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)  # flag defaults off
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "why the formula forbids" not in user and "should not appear" not in user
        gv = [args for tool, args in mcp.calls if tool == "gen_violating_trace"]
        assert gv and all("explain" not in a for a in gv)  # flag off -> no explain arg

    async def test_explain_traces_annotates_distinguishing(self, make_deps):
        mcp = TraceMCP(
            traces={"G (req -> F ack)": {"violatable": False}, "F ack": {"violatable": False}},
            dist={"direction": "f1_only", "trace": {"prefix": [["req"]], "loop": [[]]},
                  "explanation": "Accepted by f1 because req->F ack holds; Rejected by f2 because ack absent"})
        deps = contrastive_deps(make_deps, [ROW_OK], mcp=mcp)
        deps.config = deps.config.__class__(
            {**deps.config._env, "PENDULUM_JUDGE_DIST_TRACE": "true", "PENDULUM_JUDGE_EXPLAIN_TRACES": "true"})
        await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "DISTINGUISHING TRACES" in user and "why: Accepted by f1 because" in user
        dt = [args for tool, args in mcp.calls if tool == "distinguishing_trace"]
        assert dt and all(a.get("explain") is True for a in dt)


AUDIT_OK = json.dumps({
    "audits": [
        {"candidate_id": "python-1", "paraphrase_checks": [
            {"index": i, "captures_requirement": True, "reason": ""} for i in range(1, 6)]},
        {"candidate_id": "salt-1", "paraphrase_checks": [
            {"index": 1, "captures_requirement": True, "reason": ""},
            {"index": 2, "captures_requirement": False, "reason": "drops the always scope"},
            {"index": 3, "captures_requirement": False, "reason": "wrong tense"},
            {"index": 4, "captures_requirement": False, "reason": "too weak"},
            {"index": 5, "captures_requirement": False, "reason": "adds an escape clause"}]},
    ],
    "reasoning": "python-1 matches on every reading; salt-1 mostly does not",
})


class TestParaphraseAudit:
    async def test_verdict_derived_from_capture_majority(self, make_deps):
        deps = contrastive_deps(make_deps, [AUDIT_OK])
        deps.config = deps.config.__class__(
            {**deps.config._env, "PENDULUM_JUDGE_PARAPHRASE_AUDIT": "true"})
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        by = {r.candidate_id: r for r in results}
        # 5/5 capture -> SUPPORTS, confidence 1.0 ; 1/5 -> REFUTES, confidence 0.2
        assert by["python-1"].verdict == "SUPPORTS" and by["python-1"].confidence == 1.0
        assert by["salt-1"].verdict == "REFUTES" and by["salt-1"].confidence == 0.2
        assert "1/5 paraphrases capture" in by["salt-1"].evidence
        assert "drops the always scope" in by["salt-1"].evidence
        # prompt showed the authoritative TNL and the numbered paraphrases to audit
        user = deps.router.calls[0]["messages"][1]["content"]
        assert "literal reading (TNL" in user and "p one" in user

    async def test_audit_mcp_failure_errors_all(self, make_deps):
        mcp = TraceMCP()
        async def boom(formula):
            raise McpError("ltl_to_nl down")
        mcp.ltl_to_nl = boom
        deps = contrastive_deps(make_deps, [AUDIT_OK], mcp=mcp)
        deps.config = deps.config.__class__(
            {**deps.config._env, "PENDULUM_JUDGE_PARAPHRASE_AUDIT": "true"})
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        assert [r.verdict for r in results] == ["ERROR", "ERROR"]

    async def test_missing_candidate_id_retried(self, make_deps):
        incomplete = json.dumps({
            "verdicts": [{"candidate_id": "python-1", "verdict": "SUPPORTS", "evidence": "e"}],
            "best_candidate_id": "python-1", "reasoning": "",
        })
        deps = contrastive_deps(make_deps, [incomplete, ROW_OK])
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        assert [r.verdict for r in results] == ["SUPPORTS", "REFUTES"]
        assert len(deps.router.calls) == 2
        # the retry told the model which id it forgot
        retry_msg = deps.router.calls[1]["messages"][-1]["content"]
        assert "salt-1" in retry_msg

    async def test_malformed_exhaustion_errors_all(self, make_deps):
        bad = json.dumps({"verdicts": "nope"})
        deps = contrastive_deps(make_deps, [bad] * 3)  # max_retries=2 → 3 attempts
        results = await verify_row_contrastive("x", APS, [CAND, CAND2], deps)
        assert [r.candidate_id for r in results] == ["python-1", "salt-1"]
        assert all(r.verdict == "ERROR" for r in results)
        assert all("contrastive verification failed" in r.evidence for r in results)
        assert len(deps.router.calls) == 3

    async def test_empty_row_returns_empty(self, make_deps):
        deps = contrastive_deps(make_deps, [])
        assert await verify_row_contrastive("x", APS, [], deps) == []


class TestDeterministic:
    async def test_happy_path_with_test_model(self, make_deps):
        deps = make_deps()
        deps.test_model = TestModel(
            custom_output_args={"verdict": "REFUTES", "evidence": "gen_violating_trace: requirement-allowed trace violates it"},
        )
        result = await verify_deterministic("x", APS, CAND, [], deps)
        assert result.verdict == "REFUTES" and result.agent == "deterministic"
        assert result.confidence is None  # by design
        assert "gen_violating_trace" in result.evidence

    async def test_agent_exception_becomes_error_verdict(self, make_deps):
        def explode(messages, info):
            raise RuntimeError("model server on fire")

        deps = make_deps()
        deps.test_model = FunctionModel(explode)
        result = await verify_deterministic("x", APS, CAND, [], deps)
        assert result.verdict == "ERROR" and "model server on fire" in result.evidence

    async def test_other_candidates_rendered(self, make_deps):
        deps = make_deps()
        seen = {}

        def capture(messages, info):
            from pydantic_ai.messages import ModelResponse, ToolCallPart

            seen["prompt"] = str(messages)
            return ModelResponse(parts=[ToolCallPart(
                tool_name="final_result",
                args={"verdict": "INCONCLUSIVE", "evidence": "n/a"},
            )])

        deps.test_model = FunctionModel(capture)
        other = Candidate(id="salt-1", formula="G p", canonical="G p", source_agent="salt")
        result = await verify_deterministic("x", APS, CAND, [other], deps)
        assert result.verdict == "INCONCLUSIVE"
        assert "salt-1" in seen["prompt"]
