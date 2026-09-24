"""Recursive Dwyer decomposition: split → sub-match → code-side composition."""

from __future__ import annotations

import json

from tests.unit.test_dwyer_agent import ABSENCE_GLOBAL, APS, RESPONSE_GLOBAL, hits

from pendulum.agents.dwyer_to_ltl import synthesize_dwyer

FLAT_EMPTY = json.dumps({"selections": []})

SPLIT = json.dumps({
    "outer_pattern_id": "response_global",
    "assignments": {
        "p": {"type": "atoms", "value": "req"},
        "s": {"type": "sub", "text": "the acknowledgment never occurs"},
    },
    "note": "response whose response is itself a temporal property",
})
SUB_PICK = json.dumps({"selections": [
    {"pattern_id": "absence_global", "substitution": {"p": "ack"}},
]})


class TestRecursiveDecomposition:
    async def test_flat_no_fit_decomposes_and_composes(self, make_deps):
        deps = make_deps(script=[FLAT_EMPTY, SPLIT, SUB_PICK], dwyer_hits=hits())
        env = await synthesize_dwyer("whenever a request occurs, the acknowledgment never occurs", APS, deps)
        assert env.ok and len(env.payload) == 1
        c = env.payload[0]
        # outer G (p -> F s) with p := (req), s := (G (! (ack)))
        assert c.canonical == "G ((req) -> F (G (! (ack))))"
        assert "RECURSIVE" in c.rationale and "absence" in c.rationale.lower() or "G (! (ack))" in c.rationale
        assert c.source_agent == "dwyer"

    async def test_model_declines_decomposition(self, make_deps):
        deps = make_deps(script=[FLAT_EMPTY, json.dumps({"outer_pattern_id": None})], dwyer_hits=hits())
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []

    async def test_failed_sub_match_degrades_to_empty(self, make_deps):
        deps = make_deps(script=[FLAT_EMPTY, SPLIT, FLAT_EMPTY], dwyer_hits=hits())
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []  # graceful: other agents cover the row

    async def test_all_atoms_split_rejected_then_declined(self, make_deps):
        no_sub = json.dumps({
            "outer_pattern_id": "response_global",
            "assignments": {"p": {"type": "atoms", "value": "req"},
                            "s": {"type": "atoms", "value": "ack"}},
        })
        deps = make_deps(
            script=[FLAT_EMPTY, no_sub, json.dumps({"outer_pattern_id": None})],
            dwyer_hits=hits(),
        )
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []
        # the rejection was fed back to the model before it declined
        retry_msg = deps.router.calls[2]["messages"][-1]["content"]
        assert "no sub-requirement" in retry_msg

    async def test_unknown_atom_in_assignment_rejected(self, make_deps):
        bad = json.dumps({
            "outer_pattern_id": "response_global",
            "assignments": {"p": {"type": "atoms", "value": "ghost"},
                            "s": {"type": "sub", "text": "y"}},
        })
        deps = make_deps(
            script=[FLAT_EMPTY, bad, json.dumps({"outer_pattern_id": None})],
            dwyer_hits=hits(),
        )
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []
        assert "ghost" in deps.router.calls[2]["messages"][-1]["content"]

    async def test_composed_formula_failing_parser_degrades(self, make_deps):
        split_bad = json.dumps({
            "outer_pattern_id": "response_global",
            "assignments": {"p": {"type": "atoms", "value": "req"},
                            "s": {"type": "sub", "text": "z"}},
        })
        sub_bad = json.dumps({"selections": [
            {"pattern_id": "absence_global", "substitution": {"p": "ack"}},
        ]})

        deps = make_deps(script=[FLAT_EMPTY, split_bad, sub_bad], dwyer_hits=hits())
        # make the parse gate reject the composed formula
        real_parse = deps.mcp.parse_and_canonicalize

        async def reject_composed(formula):
            if "F (" in formula:  # the composed outer formula
                from pendulum.schemas import ParseResult
                return ParseResult(valid=False, error="synthetic parse failure")
            return await real_parse(formula)

        deps.mcp.parse_and_canonicalize = reject_composed
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []
