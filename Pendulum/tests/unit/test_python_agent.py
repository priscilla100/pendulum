"""python_ast_eval whitelist + PYTHON_TO_LTL agent paths."""

from __future__ import annotations

import pytest

from pendulum.agents.python_ast_eval import PythonAstError, eval_formula_expr
from pendulum.agents.python_to_ltl import synthesize_python
from pendulum.schemas import APMapping

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]


class TestAstEval:
    def test_response_pattern(self):
        expr = 'Always(LImplies(AtomicProposition("req"), Eventually(AtomicProposition("ack"))))'
        assert eval_formula_expr(expr, {"req", "ack"}) == "G (req -> F ack)"

    def test_past_operators_and_literals(self):
        assert eval_formula_expr('Once(AtomicProposition("p"))', {"p"}) == "O p"
        assert eval_formula_expr('Since(AtomicProposition("p"), Literal("True"))', {"p"}) == "(p S true)"
        assert eval_formula_expr('Yesterday(LNot(AtomicProposition("p")))', {"p"}) == "Y ! p"

    def test_weak_until(self):
        expr = 'WeakUntil(AtomicProposition("req"), AtomicProposition("ack"))'
        assert eval_formula_expr(expr, {"req", "ack"}) == "(req W ack)"

    @pytest.mark.parametrize("expr,match", [
        ('__import__("os").system("rm -rf /")', "unknown constructor|only constructor calls|no attributes"),
        ('AtomicProposition("p").name', "only constructor calls"),
        ('Always(AtomicProposition("p")) and True', "only constructor calls"),
        ('exec("x")', "unknown constructor"),
        ('Always(lambda: 1)', "only constructor calls"),
        ('AtomicProposition(open("f"))', "one string literal"),
        ('Always(AtomicProposition("p"), AtomicProposition("q"))', "exactly 1 argument"),
        ('Until(AtomicProposition("p"))', "exactly 2 arguments"),
        ('AtomicProposition("BadName")', r"\[a-z\]"),
        ('AtomicProposition("other")', "not in the provided mapping"),
        ('Literal("Maybe")', "True.*False"),
        ('LAnd(left=AtomicProposition("p"), right=AtomicProposition("q"))', "keyword arguments"),
        ('Always(AtomicProposition("p")', "not valid Python syntax"),  # unbalanced paren
        ('this is not python', "only constructor calls"),  # parses as `is not` comparison
    ])
    def test_rejections(self, expr, match):
        with pytest.raises(PythonAstError, match=match):
            eval_formula_expr(expr, {"p", "q"})


GOOD_LINE = 'formulaToFind = Always(LImplies(AtomicProposition("req"), Eventually(AtomicProposition("ack"))))'


class TestPythonAgent:
    async def test_happy_path_multiple_candidates(self, make_deps):
        completion = (
            GOOD_LINE + "\n"
            + 'formulaToFind = WeakUntil(LNot(AtomicProposition("ack")), AtomicProposition("req"))'
        )
        deps = make_deps(script=[completion])
        env = await synthesize_python("every request is eventually acked", APS, deps)
        assert env.ok and len(env.payload) == 2
        assert env.payload[0].canonical == "G (req -> F ack)"
        assert env.payload[0].source_agent == "python"
        assert env.payload[0].id != env.payload[1].id
        assert env.payload[0].confidence is None  # grammar down in this test

    async def test_bad_line_feeds_error_back_and_retries(self, make_deps):
        deps = make_deps(script=['formulaToFind = Nope("req")', GOOD_LINE])
        env = await synthesize_python("x", APS, deps)
        assert env.ok and env.attempts == 2
        retry_msg = deps.router.calls[1]["messages"][-1]["content"]
        assert "Nope" in retry_msg and "unknown constructor" in retry_msg

    async def test_partial_success_keeps_good_candidates(self, make_deps):
        completion = GOOD_LINE + "\n" + 'formulaToFind = Bad("x")'
        deps = make_deps(script=[completion])
        env = await synthesize_python("x", APS, deps)
        assert env.ok and len(env.payload) == 1  # no retry needed: one line worked
        assert len(deps.router.calls) == 1

    async def test_exhaustion(self, make_deps):
        bad = "no assignment here at all"
        deps = make_deps(script=[bad] * 4, SYNTH_PARSE_MAX_RETRIES="3")
        env = await synthesize_python("x", APS, deps)
        assert not env.ok and "after 4 attempts" in env.message

    async def test_grammar_up_attaches_confidence(self, make_deps):
        # completion, then the constrained emission returning the same canonical
        deps = make_deps(script=[GOOD_LINE, "G (req -> F ack)"], grammar_up=True)
        env = await synthesize_python("x", APS, deps)
        assert env.ok and env.payload[0].confidence == -0.5
        assert deps.router.calls[1]["need_grammar"] is True

    async def test_emission_deviation_nulls_confidence(self, make_deps):
        deps = make_deps(script=[GOOD_LINE, "G (req -> F wrong_atom)"], grammar_up=True)
        env = await synthesize_python("x", APS, deps)
        assert env.ok and env.payload[0].confidence is None
        assert env.payload[0].canonical == "G (req -> F ack)"  # original kept

    async def test_mcp_mode(self, make_deps):
        deps = make_deps(PYTHON_AGENT_MODE="mcp")

        async def fake_call(tool, args):
            assert tool == "nl_to_ltl_via_python" and args["text"] == "x"
            return {"ok": True, "formula": "G (req -> F ack)", "raw_python": "..."}

        deps.mcp.call = fake_call
        env = await synthesize_python("x", APS, deps)
        assert env.ok and env.payload[0].canonical == "G (req -> F ack)"
