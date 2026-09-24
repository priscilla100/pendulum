"""SALT_TO_LTL: author → compile → fix loop → parser gate."""

from __future__ import annotations

from tests.conftest import FakeMCP, make_hit

from pendulum.agents.salt_to_ltl import synthesize_salt
from pendulum.mcp.client import McpToolError
from pendulum.schemas import APMapping, SaltResult

APS = [APMapping(ap="req", nl_fragment="a request occurs"),
       APMapping(ap="ack", nl_fragment="an acknowledgment occurs")]

SPEC = "declare req, ack\nassert always (req implies eventually ack)"
SALT_HITS = [make_hit("salthelp-00", text="[SALT reference] assert always ...", section="TOP-LEVEL")]


class TestSaltAgent:
    async def test_happy_path_first_compile(self, make_deps):
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G (req -> F ack)")])
        deps = make_deps(script=[SPEC], mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("every request is eventually acked", APS, deps)
        assert env.ok and env.payload[0].canonical == "G (req -> F ack)"
        assert env.payload[0].source_agent == "salt"
        # spec reached the compiler verbatim (parse gate runs after compile)
        assert ("nl_to_ltl_via_salt", {"spec": SPEC}) in mcp.calls

    async def test_reference_excerpts_in_prompt(self, make_deps):
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G p")])
        deps = make_deps(script=["assert always p"], mcp=mcp, salt_hits=SALT_HITS)
        await synthesize_salt("x", APS, deps)
        assert "[SALT reference]" in deps.router.calls[0]["messages"][1]["content"]

    async def test_compile_error_feeds_back_then_succeeds(self, make_deps):
        mcp = FakeMCP(salt_results=[
            SaltResult(ok=False, error="syntax error: unexpected 'alway'"),
            SaltResult(ok=True, ltl="G (req -> F ack)"),
        ])
        deps = make_deps(script=["assert alway req", SPEC], mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("x", APS, deps)
        assert env.ok and env.attempts == 2
        fix_msg = deps.router.calls[1]["messages"][-1]["content"]
        assert "unexpected 'alway'" in fix_msg and "assert alway req" in fix_msg

    async def test_mcp_tool_error_treated_as_compile_feedback(self, make_deps):
        class RejectingMCP(FakeMCP):
            async def nl_to_ltl_via_salt(self, spec):
                if "bad" in spec:
                    raise McpToolError("nl_to_ltl_via_salt", "spec rejected: no assert line")
                return SaltResult(ok=True, ltl="G p")

        deps = make_deps(script=["bad spec", "assert always p"], mcp=RejectingMCP(), salt_hits=SALT_HITS)
        env = await synthesize_salt("x", APS, deps)
        assert env.ok and env.attempts == 2
        assert "no assert line" in deps.router.calls[1]["messages"][-1]["content"]

    async def test_unparseable_compiler_output_retries(self, make_deps):
        mcp = FakeMCP(salt_results=[
            SaltResult(ok=True, ltl="G (req -> INVALID"),
            SaltResult(ok=True, ltl="G (req -> F ack)"),
        ])
        deps = make_deps(script=[SPEC, SPEC], mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("x", APS, deps)
        assert env.ok and env.attempts == 2
        assert "rejected by the LTL parser" in deps.router.calls[1]["messages"][-1]["content"]

    async def test_exhaustion_after_max_attempts(self, make_deps):
        mcp = FakeMCP(salt_results=[SaltResult(ok=False, error="boom")] * 2)
        deps = make_deps(script=["s1", "s2"], mcp=mcp, salt_hits=SALT_HITS, SALT_FIX_MAX_ATTEMPTS="2")
        env = await synthesize_salt("x", APS, deps)
        assert not env.ok and "after 2 attempts" in env.message

    async def test_code_fences_stripped_from_spec(self, make_deps):
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G p")])
        deps = make_deps(script=[f"```salt\n{SPEC}\n```"], mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("x", APS, deps)
        assert env.ok
        salt_calls = [args for name, args in mcp.calls if name == "nl_to_ltl_via_salt"]
        assert salt_calls == [{"spec": SPEC}]

    async def test_missing_rag_is_clean_error(self, make_deps):
        deps = make_deps(script=[])
        env = await synthesize_salt("x", APS, deps)
        assert not env.ok and "init-rag" in env.message

    async def test_rag_disabled_skips_index_and_empty_reference(self, make_deps):
        # RAG off (exp-19): no index at all, empty reference block, static prompt
        # only — must NOT return the "init-rag" error.
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G (req -> F ack)")])
        deps = make_deps(script=[SPEC], mcp=mcp, PENDULUM_SALT_RAG_DISABLED="true")
        env = await synthesize_salt("every request is eventually acked", APS, deps)
        assert env.ok and env.payload[0].canonical == "G (req -> F ack)"
        # no reference excerpts leaked into the prompt (empty reference)
        user_msg = deps.router.calls[0]["messages"][1]["content"]
        assert "[SALT reference]" not in user_msg


class TestReservedMangling:
    def test_mangle_and_unmangle(self):
        from pendulum.agents.salt_to_ltl import _mangle_reserved, _unmangle

        aps = [APMapping(ap="req", nl_fragment="a request occurs"),
               APMapping(ap="ack", nl_fragment="an ack occurs"),
               APMapping(ap="before", nl_fragment="the earlier phase is active")]
        renamed, inverse = _mangle_reserved(aps)
        assert [m.ap for m in renamed] == ["req_ap", "ack", "before_ap"]
        assert inverse == {"req_ap": "req", "before_ap": "before"}
        # unmangle is token-safe: req_ap -> req, but reqx/ack untouched
        assert _unmangle("G (req_ap -> (F ack))", inverse) == "G (req -> (F ack))"
        assert _unmangle("G before_ap", inverse) == "G before"

    def test_mangle_collision_avoidance(self):
        from pendulum.agents.salt_to_ltl import _mangle_reserved

        aps = [APMapping(ap="req", nl_fragment="a"), APMapping(ap="req_ap", nl_fragment="b")]
        renamed, inverse = _mangle_reserved(aps)
        names = [m.ap for m in renamed]
        assert len(set(names)) == 2 and "req_ap" in names  # original req_ap kept
        assert inverse and list(inverse.values()) == ["req"]

    async def test_reserved_atom_round_trips_through_compiler(self, make_deps):
        """Atom 'req' (SALT-reserved) is mangled in the prompt/spec and the
        compiled LTL is renamed back before the parser gate."""
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G (req_ap -> (F ack))")])
        deps = make_deps(script=["declare req_ap, ack\nassert always (req_ap implies eventually ack)"],
                         mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("every request is eventually acked", APS, deps)
        assert env.ok
        assert env.payload[0].canonical == "G (req -> (F ack))"  # original name restored
        prompt = deps.router.calls[0]["messages"][1]["content"]
        assert "req_ap" in prompt and "\n  req =" not in prompt  # model saw only the mangled name


class TestMultiAssertConjoin:
    def test_multiple_ltlspec_lines_conjoined(self):
        from pendulum.agents.salt_to_ltl import _conjoin_ltlspecs

        two = "G (p -> F q)\nLTLSPEC G (r -> F s)"
        assert _conjoin_ltlspecs(two) == "(G (p -> F q)) & (G (r -> F s))"
        assert _conjoin_ltlspecs("G p") == "G p"  # single formula untouched
        assert _conjoin_ltlspecs("LTLSPEC G p\n\nLTLSPEC F q") == "(G p) & (F q)"

    async def test_two_assert_spec_round_trips(self, make_deps):
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="G (req -> F ack)\nLTLSPEC G ack")])
        deps = make_deps(script=[SPEC], mcp=mcp, salt_hits=SALT_HITS)
        env = await synthesize_salt("x", APS, deps)
        assert env.ok
        assert env.payload[0].canonical == "(G (req -> F ack)) & (G ack)"


class TestPinnedCondensedReference:
    """RAG-retrieval fix: all salt_help cards pinned regardless of top-k rank."""

    async def test_pin_on_includes_all_salt_help_even_if_not_top_k(self, make_deps):
        from tests.conftest import make_hit
        # only ONE salt_help card would rank via top-k, but there are two in corpus
        ranked = [make_hit("saltmanual-01", text="[verbose PDF noise]", source="salt_manual_pdf", section="noise")]
        corpus_cards = [
            make_hit("salthelp-04", text="[BOOLEAN OPERATORS] iff -> <->", source="salt_help", section="BOOLEAN"),
            make_hit("salthelp-06", text="[EXTENDED until] weak until = W", source="salt_help", section="UNTIL"),
        ]
        mcp = FakeMCP(salt_results=[__import__("pendulum.schemas", fromlist=["SaltResult"]).SaltResult(ok=True, ltl="p")])
        deps = make_deps(script=["assert p"], mcp=mcp,
                         salt_hits=ranked + corpus_cards,
                         PENDULUM_SALT_PIN_CONDENSED_REFERENCE="true")
        await synthesize_salt("x", APS, deps)
        prompt = deps.router.calls[0]["messages"][1]["content"]
        # BOTH condensed cards present even though only the noise chunk was "top-k"
        assert "BOOLEAN OPERATORS" in prompt and "EXTENDED until" in prompt

    async def test_pin_off_is_legacy_top_k_only(self, make_deps):
        from tests.conftest import make_hit
        from pendulum.schemas import SaltResult
        cards = [make_hit("salthelp-04", text="[BOOLEAN OPERATORS] iff -> <->", source="salt_help", section="BOOLEAN")]
        mcp = FakeMCP(salt_results=[SaltResult(ok=True, ltl="p")])
        deps = make_deps(script=["assert p"], mcp=mcp, salt_hits=cards,
                         PENDULUM_SALT_PIN_CONDENSED_REFERENCE="false")
        await synthesize_salt("x", APS, deps)
        prompt = deps.router.calls[0]["messages"][1]["content"]
        assert "BOOLEAN OPERATORS" in prompt  # it was top-k, so present either way
