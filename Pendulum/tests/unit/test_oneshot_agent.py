"""ONESHOT_TO_LTL: plain one-shot NL->LTL emit + parser gate + retry loop."""

from __future__ import annotations

from pendulum.agents.oneshot_to_ltl import _extract_formula, synthesize_oneshot
from pendulum.schemas import APMapping

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]

GOOD = "G (req -> F ack)"


class TestExtractFormula:
    def test_plain_last_line(self):
        assert _extract_formula("G (req -> F ack)") == "G (req -> F ack)"

    def test_strips_fences(self):
        assert _extract_formula("```\nG (req -> F ack)\n```") == "G (req -> F ack)"

    def test_strips_leading_label(self):
        assert _extract_formula("Formula: G (req -> F ack)") == "G (req -> F ack)"

    def test_takes_last_nonempty_line(self):
        assert _extract_formula("here is the answer\n\nG (req -> F ack)\n") == "G (req -> F ack)"

    def test_empty(self):
        assert _extract_formula("```\n```") == ""


class TestOneshotAgent:
    async def test_happy_path(self, make_deps):
        deps = make_deps(script=[GOOD])
        env = await synthesize_oneshot("every request is eventually acked", APS, deps)
        assert env.ok and len(env.payload) == 1
        c = env.payload[0]
        assert c.canonical == GOOD and c.source_agent == "oneshot"
        assert c.confidence is None  # grammar down in this test

    async def test_prompt_carries_nl_and_aps(self, make_deps):
        deps = make_deps(script=[GOOD])
        await synthesize_oneshot("every request is eventually acked", APS, deps)
        user_msg = deps.router.calls[0]["messages"][1]["content"]
        assert "every request is eventually acked" in user_msg and "req = a request occurs" in user_msg

    async def test_garbage_feeds_back_then_succeeds(self, make_deps):
        deps = make_deps(script=["G (req -> F INVALID", GOOD])
        env = await synthesize_oneshot("x", APS, deps)
        assert env.ok and env.attempts == 2
        retry_msg = deps.router.calls[1]["messages"][-1]["content"]
        assert "not a valid formula" in retry_msg

    async def test_exhaustion(self, make_deps):
        deps = make_deps(script=["INVALID"] * 4, SYNTH_PARSE_MAX_RETRIES="3")
        env = await synthesize_oneshot("x", APS, deps)
        assert not env.ok and "after 4 attempts" in env.message
