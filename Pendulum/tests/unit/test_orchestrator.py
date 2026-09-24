"""Orchestrator: filter stage + finalize stage with fallbacks, plus the
round-3 output shaping (all-survivors, scope variants, compare lattice)."""

from __future__ import annotations

import json

from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from pendulum.agents.orchestrator import (
    _heuristic_keep,
    compare_lattice,
    expand_scope_variants,
    filter_candidates,
    finalize,
)
from pendulum.mcp.client import McpToolError
from pendulum.schemas import APMapping, Candidate, RankedFormula, VerificationResult
from tests.conftest import FakeMCP

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]


def cand(id_, source, canonical="G (req -> F ack)", confidence=None):
    return Candidate(id=id_, formula=canonical, canonical=canonical,
                     source_agent=source, confidence=confidence)


def rf(canonical, rank=1, **kw):
    return RankedFormula(formula=canonical, canonical=canonical, rank=rank, **kw)


def read_events(deps):
    return [json.loads(line) for line in deps.logger.path.read_text().splitlines()]


def find_event(deps, name):
    matches = [e for e in read_events(deps) if e["event"] == name]
    assert matches, f"no {name!r} event logged"
    return matches[-1]


class LatticeMCP(FakeMCP):
    """FakeMCP whose generic call() returns a scripted dict or raises."""

    def __init__(self, result=None, exc=None):
        super().__init__()
        self.result = result or {}
        self.exc = exc

    async def call(self, tool, args):
        self.calls.append((tool, args))
        if self.exc is not None:
            raise self.exc
        return self.result


class TestFilter:
    async def test_llm_keep_list_respected(self, make_deps):
        cands = [cand("python-1", "python"), cand("dwyer-1", "dwyer", "G (! req)"), cand("salt-1", "salt", "F ack")]
        deps = make_deps(script=[json.dumps({"keep": ["python-1", "salt-1"], "reasoning": "dwyer reading wrong"})])
        kept, reasoning = await filter_candidates("x", APS, cands, deps)
        assert [c.id for c in kept] == ["python-1", "salt-1"]
        assert "dwyer" in reasoning

    async def test_single_candidate_short_circuits(self, make_deps):
        deps = make_deps(script=[])
        kept, _ = await filter_candidates("x", APS, [cand("python-1", "python")], deps)
        assert len(kept) == 1 and not deps.router.calls

    async def test_unknown_id_retried_then_heuristic_fallback(self, make_deps):
        cands = [cand("python-1", "python", confidence=-0.2), cand("salt-1", "salt", "F ack", confidence=-0.9)]
        bad = json.dumps({"keep": ["ghost-1"]})
        deps = make_deps(script=[bad, bad, bad])  # exhausts retries
        kept, reasoning = await filter_candidates("x", APS, cands, deps)
        assert len(kept) == 2  # heuristic keeps best per source
        assert "heuristic" in reasoning

    async def test_cap_enforced_on_llm_output(self, make_deps):
        cands = [cand(f"python-{i}", "python", f"G (req -> F ack)") for i in range(1, 8)]
        deps = make_deps(
            script=[json.dumps({"keep": [c.id for c in cands], "reasoning": "all"})],
            PENDULUM_MAX_CANDIDATES_TO_VERIFY="3",
        )
        kept, _ = await filter_candidates("x", APS, cands, deps)
        assert len(kept) == 3

    def test_heuristic_prefers_source_diversity(self):
        cands = [
            cand("python-1", "python", confidence=-0.1),
            cand("python-2", "python", confidence=-0.2),
            cand("salt-1", "salt", confidence=None),
        ]
        kept = _heuristic_keep(cands, cap=2)
        assert {c.source_agent for c in kept} == {"python", "salt"}


def verif(cid, agent, verdict):
    return VerificationResult(candidate_id=cid, agent=agent, verdict=verdict, evidence="e")


class TestFinalize:
    async def test_no_candidates_is_error(self, make_deps):
        deps = make_deps()
        out = await finalize("x", APS, [], [], deps)
        assert out.status == "ERROR" and "no candidate" in out.message

    async def test_happy_path_validates_and_ranks(self, make_deps):
        deps = make_deps()
        deps.test_model = TestModel(custom_output_args={
            "formulas": [
                {"formula": "G (req -> F ack)", "canonical": "", "rank": 1, "score": 0.9,
                 "justification": "both verifiers support"},
            ],
            "reasoning": "clear winner",
        })
        cands = [cand("python-1", "python")]
        out = await finalize("x", APS, cands, [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert out.status == "OK"
        assert out.formulas[0].canonical == "G (req -> F ack)" and out.formulas[0].rank == 1
        # defaults ON: the G-unwrapped scope variant follows the winner
        assert out.formulas[1].canonical == "req -> F ack" and out.formulas[1].rank == 2
        assert out.ap_mapping == APS

    async def test_empty_ranking_emits_best_guess_by_default(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false")
        deps.test_model = TestModel(custom_output_args={"formulas": [], "reasoning": "all refuted"})
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "OK"
        assert "low_confidence" in out.message and "all refuted" in out.message
        assert out.formulas  # best guess emitted

    async def test_empty_ranking_is_honest_error_when_switch_off(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false", PENDULUM_EMIT_BEST_GUESS="false")
        deps.test_model = TestModel(custom_output_args={"formulas": [], "reasoning": "all refuted"})
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "ERROR" and "all refuted" in out.message

    async def test_agent_crash_degrades_to_deterministic_ranking(self, make_deps):
        def explode(messages, info):
            raise RuntimeError("boom")

        deps = make_deps()
        deps.test_model = FunctionModel(explode)
        cands = [cand("python-1", "python", confidence=-0.3),
                 cand("salt-1", "salt", "F ack", confidence=-0.1)]
        verifs = [verif("python-1", "fuzzy", "SUPPORTS"), verif("python-1", "deterministic", "SUPPORTS"),
                  verif("salt-1", "fuzzy", "REFUTES")]
        out = await finalize("x", APS, cands, verifs, deps)
        assert out.status == "OK" and "fallback" in out.message
        # verdict score dominates confidence: python-1 (+2) beats salt-1 (-1)
        assert out.formulas[0].canonical == "G (req -> F ack)"
        assert out.formulas[0].score == 2.0

    async def test_invalid_output_formula_dropped_then_fallback(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false")
        deps.test_model = TestModel(custom_output_args={
            "formulas": [{"formula": "G (req -> INVALID", "canonical": "", "rank": 1,
                          "justification": "oops"}],
            "reasoning": "",
        })
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "OK" and "failed the parser" in out.message  # deterministic fallback


def ranking_model(*formulas, reasoning="r"):
    return TestModel(custom_output_args={
        "formulas": [{"formula": f, "canonical": "", "rank": i + 1, "justification": "j"}
                     for i, f in enumerate(formulas)],
        "reasoning": reasoning,
    })


class TestAllSurvivors:
    async def test_appends_non_refuted_and_skips_fuzzy_refuted(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false", PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = ranking_model("G (req -> F ack)")
        cands = [cand("python-1", "python"),
                 cand("dwyer-1", "dwyer", "G (! req)"),
                 cand("salt-1", "salt", "F ack")]
        verifs = [verif("python-1", "fuzzy", "SUPPORTS"), verif("dwyer-1", "fuzzy", "REFUTES")]
        out = await finalize("x", APS, cands, verifs, deps)
        assert [f.canonical for f in out.formulas] == ["G (req -> F ack)", "F ack"]
        assert out.formulas[1].justification == "survivor (fuzzy: unverified)"
        assert [f.rank for f in out.formulas] == [1, 2]
        assert find_event(deps, "survivors_appended")["ids"] == ["salt-1"]

    async def test_dedupes_against_agent_ranking_by_canonical(self, make_deps):
        deps = make_deps(PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = ranking_model("G  (req -> F ack)")  # canonicalizes to the same
        cands = [cand("python-1", "python", "G (req -> F ack)")]
        out = await finalize("x", APS, cands, [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert [f.canonical for f in out.formulas] == ["G (req -> F ack)"]

    async def test_survivor_order_supports_then_confidence(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false", PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = ranking_model("G ack")
        cands = [cand("salt-1", "salt", "O req", confidence=-0.1),      # unverified, good conf
                 cand("dwyer-1", "dwyer", "X req", confidence=None),    # unverified, null conf
                 cand("python-1", "python", "F ack", confidence=-0.9)]  # SUPPORTS
        out = await finalize("x", APS, cands, [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert [f.canonical for f in out.formulas] == ["G ack", "F ack", "O req", "X req"]
        assert out.formulas[1].justification == "survivor (fuzzy: SUPPORTS)"
        assert [f.rank for f in out.formulas] == [1, 2, 3, 4]

    async def test_switch_off_preserves_old_single_formula_behavior(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false", PENDULUM_OUTPUT_ALL_SURVIVORS="false",
                         PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = ranking_model("G (req -> F ack)")
        cands = [cand("python-1", "python"), cand("salt-1", "salt", "F ack")]
        out = await finalize("x", APS, cands, [], deps)
        assert [f.canonical for f in out.formulas] == ["G (req -> F ack)"]


class TestScopeVariants:
    async def test_g_rooted_unwrapped(self, make_deps):
        deps = make_deps()
        out = await expand_scope_variants([rf("G (req -> F ack)")], deps)
        assert [f.canonical for f in out] == ["G (req -> F ack)", "req -> F ack"]
        assert out[1].justification == "scope variant of rank 1"
        assert [f.rank for f in out] == [1, 2]

    async def test_non_g_rooted_wrapped(self, make_deps):
        deps = make_deps()
        out = await expand_scope_variants([rf("F ack")], deps)
        assert [f.canonical for f in out] == ["F ack", "G (F ack)"]

    async def test_g_atom_unwrapped(self, make_deps):
        deps = make_deps()
        out = await expand_scope_variants([rf("G req")], deps)
        assert [f.canonical for f in out] == ["G req", "req"]

    async def test_balanced_paren_guard_blocks_naive_unwrap(self, make_deps):
        deps = make_deps()
        # outer parens do NOT enclose one body — must wrap, never unwrap
        out = await expand_scope_variants([rf("G (p) U (q)")], deps)
        assert [f.canonical for f in out] == ["G (p) U (q)", "G (G (p) U (q))"]
        out = await expand_scope_variants([rf("(G (p) U q)")], deps)
        assert out[1].canonical == "G ((G (p) U q))"

    async def test_invalid_counterpart_dropped_and_logged(self, make_deps):
        deps = make_deps()  # FakeMCP rejects formulas containing INVALID
        out = await expand_scope_variants([rf("G (oops INVALID)")], deps)
        assert [f.canonical for f in out] == ["G (oops INVALID)"]
        assert find_event(deps, "scope_variant_invalid")["counterpart"] == "oops INVALID"

    async def test_dedupe_across_originals_and_variants(self, make_deps):
        deps = make_deps()
        out = await expand_scope_variants([rf("G (p)"), rf("p", rank=2)], deps)
        assert [f.canonical for f in out] == ["G (p)", "p"]  # later original deduped

    async def test_cap_and_sequential_rerank(self, make_deps):
        deps = make_deps(PENDULUM_MAX_OUTPUT_FORMULAS="3")
        out = await expand_scope_variants([rf("G (p)"), rf("G (q)", rank=2)], deps)
        assert [f.canonical for f in out] == ["G (p)", "p", "G (q)"]
        assert [f.rank for f in out] == [1, 2, 3]

    async def test_fallback_paths_flow_through_expansion(self, make_deps):
        def explode(messages, info):
            raise RuntimeError("boom")

        deps = make_deps()
        deps.test_model = FunctionModel(explode)
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "OK" and "fallback" in out.message
        assert [f.canonical for f in out.formulas] == ["G (req -> F ack)", "req -> F ack"]

    async def test_best_guess_path_flows_through_expansion(self, make_deps):
        deps = make_deps()
        deps.test_model = ranking_model(reasoning="all refuted")  # empty ranking
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "OK"
        assert [f.canonical for f in out.formulas] == ["G (req -> F ack)", "req -> F ack"]


class TestCompareLattice:
    CANDS = staticmethod(lambda: [
        cand("python-1", "python", "G (req -> F ack)", confidence=None),
        cand("dwyer-1", "dwyer", "G ((req) -> (F ack))", confidence=-0.2),
        cand("salt-1", "salt", "G (req -> X ack)", confidence=-0.5),
    ])

    async def test_noop_when_option_off(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": [[0, 1]]})
        deps = make_deps(mcp=mcp)  # PENDULUM_ORCH_COMPARE_FILTER defaults off
        cands = self.CANDS()
        merged, text = await compare_lattice(cands, deps)
        assert merged == cands and text == "" and not mcp.calls

    async def test_noop_below_two_candidates(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": []})
        deps = make_deps(mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true")
        merged, text = await compare_lattice([cand("python-1", "python")], deps)
        assert len(merged) == 1 and text == "" and not mcp.calls

    async def test_merges_equivalents_keeping_better_confidence(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": [[0, 1]], "stronger_than": [[2, 0]],
                          "incomparable": []})
        deps = make_deps(mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true")
        merged, text = await compare_lattice(self.CANDS(), deps)
        # dwyer-1 (conf -0.2) beats python-1 (conf None) as representative
        assert [c.id for c in merged] == ["dwyer-1", "salt-1"]
        assert "python-1 ≡ dwyer-1 (merged)" in text
        assert "salt-1 ⇒ dwyer-1 (strictly stronger)" in text  # remapped to representative
        event = find_event(deps, "compare_merge")
        assert event["kept"] == "dwyer-1" and event["merged"] == ["python-1"]

    async def test_confidence_tie_keeps_first(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": [[0, 1]]})
        deps = make_deps(mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true")
        cands = [cand("python-1", "python", "G p"), cand("salt-1", "salt", "G (p)")]
        merged, _ = await compare_lattice(cands, deps)
        assert [c.id for c in merged] == ["python-1"]

    async def test_degrades_cleanly_on_tool_failure(self, make_deps):
        mcp = LatticeMCP(exc=McpToolError("compare_candidates", "black exploded"))
        deps = make_deps(mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true")
        cands = self.CANDS()
        merged, text = await compare_lattice(cands, deps)
        assert merged == cands and text == ""
        assert "black exploded" in find_event(deps, "compare_lattice_failed")["error"]

    async def test_filter_injects_lattice_and_uses_merged_candidates(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": [[0, 1]]})
        deps = make_deps(
            script=[json.dumps({"keep": ["dwyer-1"], "reasoning": "merged rep wins"})],
            mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true",
        )
        kept, _ = await filter_candidates("x", APS, self.CANDS(), deps)
        assert [c.id for c in kept] == ["dwyer-1"]
        assert "≡" in str(deps.router.calls[0]["messages"])

    async def test_filter_skips_llm_when_merge_leaves_one(self, make_deps):
        mcp = LatticeMCP({"equivalent_pairs": [[0, 1]]})
        deps = make_deps(script=[], mcp=mcp, PENDULUM_ORCH_COMPARE_FILTER="true")
        cands = [cand("python-1", "python", "G p", confidence=-0.1),
                 cand("salt-1", "salt", "G (p)")]
        kept, reasoning = await filter_candidates("x", APS, cands, deps)
        assert [c.id for c in kept] == ["python-1"] and "merge" in reasoning
        assert not deps.router.calls

    async def test_finalize_accepts_lattice_text(self, make_deps):
        deps = make_deps(PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = ranking_model("G (req -> F ack)")
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps,
                             lattice_text="python-1 ⇒ salt-1 (strictly stronger)")
        assert out.status == "OK"


class TestNewLogEvents:
    async def test_best_guess_emitted_logged(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false")
        deps.test_model = ranking_model(reasoning="all refuted")
        await finalize("x", APS, [cand("python-1", "python")], [], deps)
        event = find_event(deps, "best_guess_emitted")
        assert event["candidates"] == ["python-1"] and event["reasoning"] == "all refuted"

    async def test_filter_single_candidate_skip_logged(self, make_deps):
        deps = make_deps(script=[])
        await filter_candidates("x", APS, [cand("python-1", "python")], deps)
        assert find_event(deps, "filter_single_candidate_skip")["ids"] == ["python-1"]

    async def test_final_ranking_logs_reasoning(self, make_deps):
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false")
        deps.test_model = ranking_model("G (req -> F ack)", reasoning="clear winner")
        await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert find_event(deps, "final_ranking")["reasoning"] == "clear winner"


class TestCodexVerificationGaps:
    """Second-opinion codex review: malformed lattice payloads, transitive
    merge, survivors+variants interaction, variant parse crash."""

    async def test_lattice_malformed_payload_ignored(self, make_deps):
        from pendulum.agents.orchestrator import compare_lattice

        cands = [cand("a", "python", "G p", confidence=-0.2),
                 cand("b", "salt", "F q"), cand("c", "dwyer", "G r")]
        deps = make_deps(PENDULUM_ORCH_COMPARE_FILTER="true")

        async def bad_payload(tool, args):
            return {"equivalent_pairs": [[0, True], [0, 99], "junk", [1]],
                    "stronger_than": {"not": "a list"}}

        deps.mcp.call = bad_payload
        merged, text = await compare_lattice(cands, deps)
        assert len(merged) == 3  # nothing merged from garbage
        assert "no equivalences" in text

    async def test_lattice_transitive_equivalence_single_group(self, make_deps):
        from pendulum.agents.orchestrator import compare_lattice

        cands = [cand("a", "python", "G p", confidence=None),
                 cand("b", "salt", "G (p)", confidence=-0.1),
                 cand("c", "dwyer", "G ((p))", confidence=-0.5)]
        deps = make_deps(PENDULUM_ORCH_COMPARE_FILTER="true")

        async def payload(tool, args):
            return {"equivalent_pairs": [[0, 1], [1, 2]], "stronger_than": []}

        deps.mcp.call = payload
        merged, text = await compare_lattice(cands, deps)
        assert len(merged) == 1 and merged[0].id == "b"  # best confidence wins transitively
        assert "a" in text and "c" in text

    async def test_survivors_then_variants_respect_cap(self, make_deps):
        from pydantic_ai.models.test import TestModel

        deps = make_deps(PENDULUM_MAX_OUTPUT_FORMULAS="4")
        deps.test_model = TestModel(custom_output_args={
            "formulas": [{"formula": "G (req -> F ack)", "canonical": "", "rank": 1,
                          "justification": "winner"}],
            "reasoning": "",
        })
        cands = [cand("python-1", "python"),
                 cand("salt-1", "salt", "F ack", confidence=-0.1),
                 cand("dwyer-1", "dwyer", "G req", confidence=-0.4)]
        out = await finalize("x", APS, cands, [], deps)
        assert out.status == "OK"
        assert len(out.formulas) == 4  # capped after survivor + variant expansion
        assert [f.rank for f in out.formulas] == [1, 2, 3, 4]  # sequential
        canonicals = [f.canonical for f in out.formulas]
        assert len(set(canonicals)) == 4  # deduped

    async def test_variant_parse_crash_degrades_not_aborts(self, make_deps):
        from pydantic_ai.models.test import TestModel
        from pendulum.mcp.client import McpError

        deps = make_deps()
        deps.test_model = TestModel(custom_output_args={
            "formulas": [{"formula": "G (req -> F ack)", "canonical": "", "rank": 1,
                          "justification": "w"}],
            "reasoning": "",
        })
        real_parse = deps.mcp.parse_and_canonicalize
        calls = {"n": 0}

        async def crash_on_variant(formula):
            calls["n"] += 1
            if formula.startswith("(req"):  # the unwrap counterpart
                raise McpError("transport died mid-variant")
            return await real_parse(formula)

        deps.mcp.parse_and_canonicalize = crash_on_variant
        out = await finalize("x", APS, [cand("python-1", "python")], [], deps)
        assert out.status == "OK"  # finalize survived the variant crash
        assert out.formulas[0].canonical == "G (req -> F ack)"


class TestLatestVerifications:
    """Codex audit: re-judged rows must not be haunted by stale round-1 votes."""

    def test_last_verdict_per_candidate_agent_wins(self):
        from pendulum.agents.orchestrator import _latest_verifications

        history = [verif("a", "fuzzy", "REFUTES"),   # round 1
                   verif("b", "fuzzy", "SUPPORTS"),  # round 1
                   verif("a", "fuzzy", "SUPPORTS"),  # round 2 re-judge
                   verif("b", "fuzzy", "REFUTES")]   # round 2 re-judge
        latest = {(v.candidate_id, v.agent): v.verdict for v in _latest_verifications(history)}
        assert latest == {("a", "fuzzy"): "SUPPORTS", ("b", "fuzzy"): "REFUTES"}

    async def test_survivor_append_uses_fresh_votes(self, make_deps):
        from pydantic_ai.models.test import TestModel

        deps = make_deps(PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        deps.test_model = TestModel(custom_output_args={
            "formulas": [{"formula": "G (req -> F ack)", "canonical": "", "rank": 1,
                          "justification": "w"}], "reasoning": ""})
        stale_then_fresh = [verif("salt-1", "fuzzy", "REFUTES"),   # round 1: refuted
                            verif("salt-1", "fuzzy", "SUPPORTS")]  # round 2: vindicated
        cands = [cand("python-1", "python"), cand("salt-1", "salt", "F ack")]
        out = await finalize("x", APS, cands, stale_then_fresh, deps)
        # salt-1's fresh SUPPORTS means it survives despite the stale REFUTES
        assert any(f.canonical == "F ack" for f in out.formulas)


class TestScopeUnwrapUnaryChains:
    """Round-4 forensic bug: `G !hsel` must unwrap to `!hsel`, not wrap again."""

    def test_unary_chains_unwrap(self):
        from pendulum.agents.orchestrator import _scope_counterpart

        assert _scope_counterpart("G !hsel") == "!hsel"
        assert _scope_counterpart("G X htransidle") == "X htransidle"
        assert _scope_counterpart("G ! F hsel") == "! F hsel"

    def test_toplevel_binary_remainder_still_wraps(self):
        from pendulum.agents.orchestrator import _scope_counterpart

        # G scoping only the left operand: must NOT tear the G off
        assert _scope_counterpart("G (p) U (q)") == "G (G (p) U (q))"


class TestOrchestratorCliBackend:
    """CLI-backed orchestrator (e.g. Opus): finalize ranks over precomputed
    solver evidence via a schema-constrained completion, no PydanticAI tool
    loop, no live tool calls."""

    async def test_cli_backend_ranks_via_completion(self, make_deps):
        import json as _json
        ranking = _json.dumps({
            "formulas": [{"formula": "G (req -> F ack)", "score": 0.8,
                          "justification": "keeps the always-scope"}],
            "reasoning": "precomputed lattice shows this is strictly the intended reading",
        })
        # ORCH on a CLI backend; FakeRouter serves the ranking completion
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false", script=[ranking], ORCH_BACKEND="claude-cli",
                         ORCH_MODEL="claude-opus-4-8",
                         PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        cands = [cand("python-1", "python")]
        out = await finalize("every request is acked", APS, cands,
                             [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert out.status == "OK"
        assert out.formulas[0].canonical == "G (req -> F ack)"
        # it went through the router (completion), NOT a PydanticAI agent:
        assert len(deps.router.calls) == 1
        assert deps.router.calls[0]["agent"] == "orch"
        # the JSON-format instruction was appended to the system prompt
        sysmsg = deps.router.calls[0]["messages"][0]["content"]
        assert "JSON object" in sysmsg
        # and the no-tools override is present (Opus must not confabulate tool use)
        assert "NO tools" in sysmsg and "check_equivalence" in sysmsg

    async def test_cli_backend_bad_json_degrades_to_deterministic(self, make_deps):
        # never valid JSON -> exhausts retries -> deterministic ranking, still OK
        deps = make_deps(script=["not json"] * 3, ORCH_BACKEND="claude-cli",
                         ORCH_MODEL="claude-opus-4-8")
        cands = [cand("python-1", "python", "F ack")]
        out = await finalize("x", APS, cands, [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert out.status == "OK"  # deterministic fallback never fails the run
        assert out.formulas


class TestOrchDeterministicToggle:
    async def test_deterministic_mode_skips_llm_finalize(self, make_deps):
        # FakeRouter with NO scripted completions -> if finalize called the LLM
        # it would raise "script exhausted"; deterministic mode must not.
        deps = make_deps(script=[], PENDULUM_ORCH_DETERMINISTIC="true",
                         PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        cands = [cand("python-1", "python", "F ack"), cand("salt-1", "salt", "G ack")]
        verifs = [verif("python-1", "fuzzy", "SUPPORTS"), verif("salt-1", "fuzzy", "REFUTES")]
        out = await finalize("x", APS, cands, verifs, deps)
        assert out.status == "OK"
        # SUPPORTS-ranked python candidate wins; zero LLM calls were made
        assert out.formulas[0].canonical == "F ack"
        assert len(deps.router.calls) == 0

    async def test_default_is_deterministic(self, make_deps):
        # PENDULUM_ORCH_DETERMINISTIC now defaults TRUE (exp-08: +31 rows). With no
        # scripted completions, the LLM finalize would raise "script exhausted"; the
        # default deterministic path must not call the LLM.
        deps = make_deps(script=[], PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        out = await finalize("x", APS, [cand("python-1", "python", "F ack")],
                             [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert out.status == "OK" and out.formulas[0].canonical == "F ack"
        assert len(deps.router.calls) == 0

    async def test_deterministic_ranking_breaks_ties_by_fuzzy_confidence(self, make_deps):
        # The audit judge gives both candidates SUPPORTS but different capture-fractions
        # (as the fuzzy verification confidence); the higher fraction must win the tie.
        deps = make_deps(script=[], PENDULUM_OUTPUT_SCOPE_VARIANTS="false")
        cands = [cand("python-1", "python", "F a"), cand("salt-1", "salt", "G b")]
        verifs = [
            VerificationResult(candidate_id="python-1", agent="fuzzy", verdict="SUPPORTS",
                               evidence="3/5 capture", confidence=0.6),
            VerificationResult(candidate_id="salt-1", agent="fuzzy", verdict="SUPPORTS",
                               evidence="5/5 capture", confidence=1.0),
        ]
        out = await finalize("x", APS, cands, verifs, deps)
        assert out.formulas[0].canonical == "G b"  # 5/5 outranks 3/5 despite same verdict

    async def test_llm_finalize_when_disabled(self, make_deps):
        from pydantic_ai.models.test import TestModel
        deps = make_deps(PENDULUM_ORCH_DETERMINISTIC="false")  # explicitly opt into LLM finalize
        deps.test_model = TestModel(custom_output_args={
            "formulas": [{"formula": "F ack", "canonical": "", "rank": 1, "justification": "w"}],
            "reasoning": "llm ranked"})
        out = await finalize("x", APS, [cand("python-1", "python", "F ack")],
                             [verif("python-1", "fuzzy", "SUPPORTS")], deps)
        assert out.status == "OK" and out.formulas[0].canonical == "F ack"
