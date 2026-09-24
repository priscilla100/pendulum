"""DWYERS_APPROACH_TO_LTL: retrieval → selection JSON → local instantiation."""

from __future__ import annotations

import json

from tests.conftest import make_hit

from pendulum.agents.dwyer_to_ltl import _instantiate, synthesize_dwyer
from pendulum.schemas import APMapping

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]

RESPONSE_GLOBAL = dict(
    id="response_global", pattern="Response", scope="Global",
    intent="s responds to p globally", ltl_template="G (p -> F s)",
    placeholders=["p", "s"], example_nl=["every request is eventually acked"],
)
ABSENCE_GLOBAL = dict(
    id="absence_global", pattern="Absence", scope="Global",
    intent="p never holds", ltl_template="G (! p)",
    placeholders=["p"], example_nl=["the alarm never rings"],
)


def hits():
    return [make_hit("response_global", **RESPONSE_GLOBAL), make_hit("absence_global", **ABSENCE_GLOBAL)]


def selection(pattern_id="response_global", substitution=None, **extra):
    return json.dumps({"selections": [
        {"pattern_id": pattern_id, "substitution": substitution or {"p": "req", "s": "ack"},
         "confidence_note": "direct response phrasing", **extra},
    ]})


class TestInstantiate:
    def test_simple(self):
        formula = _instantiate(RESPONSE_GLOBAL, {"p": "req", "s": "ack"}, {"req", "ack"})
        assert formula == "G ((req) -> F (ack))"

    def test_boolean_combination_value(self):
        formula = _instantiate(ABSENCE_GLOBAL, {"p": "req & !ack"}, {"req", "ack"})
        assert formula == "G (! (req & !ack))"

    def test_constants_allowed_as_scope_degeneration(self):
        # r := false degenerates an "until R" scope into "forever" — the
        # canonical trick; constants are not atoms and must not be rejected
        formula = _instantiate(RESPONSE_GLOBAL, {"p": "req", "s": "false"}, {"req"})
        assert formula == "G ((req) -> F (false))"

    def test_no_reentrant_substitution(self):
        # value 'p' for placeholder 's' must NOT be re-substituted by placeholder p
        entry = dict(RESPONSE_GLOBAL, placeholders=["p", "s"])
        formula = _instantiate(entry, {"p": "ack", "s": "p"}, {"req", "ack", "p"})
        assert formula == "G ((ack) -> F (p))"

    def test_rejections(self):
        import pytest

        with pytest.raises(ValueError, match="exactly the placeholders"):
            _instantiate(RESPONSE_GLOBAL, {"p": "req"}, {"req"})
        with pytest.raises(ValueError, match="unknown atom"):
            _instantiate(RESPONSE_GLOBAL, {"p": "req", "s": "ghost"}, {"req"})
        with pytest.raises(ValueError, match="only atoms and"):
            _instantiate(RESPONSE_GLOBAL, {"p": "req; drop", "s": "ack"}, {"req", "ack"})


class TestDwyerAgent:
    async def test_happy_path(self, make_deps):
        deps = make_deps(script=[selection()], dwyer_hits=hits())
        env = await synthesize_dwyer("every request is eventually acked", APS, deps)
        assert env.ok and len(env.payload) == 1
        c = env.payload[0]
        assert c.canonical == "G ((req) -> F (ack))" and c.source_agent == "dwyer"
        assert "Dwyer Response (Global)" in c.rationale

    async def test_prompt_carries_retrieved_templates(self, make_deps):
        deps = make_deps(script=[selection()], dwyer_hits=hits())
        await synthesize_dwyer("x", APS, deps)
        user_msg = deps.router.calls[0]["messages"][1]["content"]
        assert "G (p -> F s)" in user_msg and "absence_global" in user_msg

    async def test_empty_selection_is_ok_not_error(self, make_deps):
        # flat no-fit now attempts ONE decomposition before giving up
        deps = make_deps(
            script=[json.dumps({"selections": []}), json.dumps({"outer_pattern_id": None})],
            dwyer_hits=hits(),
        )
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.payload == []
        assert len(deps.router.calls) == 2  # flat attempt + declined decomposition

    async def test_unknown_pattern_id_feeds_back_and_retries(self, make_deps):
        deps = make_deps(script=[selection(pattern_id="nope_global"), selection()], dwyer_hits=hits())
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.attempts == 2
        assert "nope_global" in deps.router.calls[1]["messages"][-1]["content"]

    async def test_bad_substitution_feeds_back(self, make_deps):
        deps = make_deps(
            script=[selection(substitution={"p": "ghost", "s": "ack"}), selection()],
            dwyer_hits=hits(),
        )
        env = await synthesize_dwyer("x", APS, deps)
        assert env.ok and env.attempts == 2
        assert "ghost" in deps.router.calls[1]["messages"][-1]["content"]

    async def test_exhaustion(self, make_deps):
        bad = selection(pattern_id="nope")
        deps = make_deps(script=[bad] * 4, dwyer_hits=hits(), SYNTH_PARSE_MAX_RETRIES="3")
        env = await synthesize_dwyer("x", APS, deps)
        assert not env.ok and "after 4 attempts" in env.message

    async def test_missing_rag_is_clean_error(self, make_deps):
        deps = make_deps(script=[])
        env = await synthesize_dwyer("x", APS, deps)
        assert not env.ok and "init-rag" in env.message
