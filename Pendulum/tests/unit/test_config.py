"""config.py: typed getters, per-agent inheritance, path resolution, validation."""

from __future__ import annotations

import pytest

from pendulum.config import AGENT_PREFIXES, PENDULUM_ROOT, REPO_ROOT, PendulumConfig


class TestTypedGetters:
    def test_defaults_when_absent(self, bare_config):
        assert bare_config.get_str("NOPE", "x") == "x"
        assert bare_config.get_float("NOPE", 1.5) == 1.5
        assert bare_config.get_int("NOPE", 7) == 7
        assert bare_config.get_bool("NOPE", True) is True

    def test_empty_string_falls_back_to_default(self, make_config):
        cfg = make_config(PENDULUM_LOG_LEVEL="  ")
        assert cfg.log_level == "info"

    def test_bool_spellings(self, make_config):
        for raw, expected in [("1", True), ("true", True), ("YES", True), ("on", True),
                              ("0", False), ("false", False), ("No", False), ("off", False)]:
            assert make_config(K=raw).get_bool("K", not expected) is expected

    def test_bad_values_raise(self, make_config):
        with pytest.raises(ValueError, match="not a number"):
            make_config(K="abc").get_float("K", 0.0)
        with pytest.raises(ValueError, match="not an integer"):
            make_config(K="1.5").get_int("K", 0)
        with pytest.raises(ValueError, match="not a boolean"):
            make_config(K="maybe").get_bool("K", True)


class TestAgentInheritance:
    def test_code_defaults(self, bare_config):
        ap = bare_config.agent("AP")
        assert ap.model == "gemma4:31b-mlx"  # every seat defaults to gemma-31b now
        assert ap.base_url == "http://localhost:11434/v1"
        assert ap.temperature == 0.0
        assert ap.num_ctx == 16384
        assert ap.max_steps == 8
        assert ap.timeout_s == 480.0
        assert ap.thinking is False and ap.streaming is False

    def test_all_seats_default_to_gemma31b(self, bare_config):
        # gemma4:31b-mlx is the uniform default across every seat (2026-07 change).
        for seat in ("AP", "ORCH", "PYTHON", "DWYER", "SALT", "FUZZY", "DET", "ONESHOT"):
            assert bare_config.agent(seat).model == "gemma4:31b-mlx"

    def test_global_default_overrides_code_default(self, make_config):
        cfg = make_config(PENDULUM_DEFAULT_MODEL="gemma4:12b-it-qat")
        assert cfg.agent("SALT").model == "gemma4:12b-it-qat"
        # explicit per-agent code default still loses to the env global? No:
        # ORCH has a per-agent *code* default, but the resolution order is
        # ORCH_MODEL -> PENDULUM_DEFAULT_MODEL -> code default, so the env
        # global wins over the code-level ORCH default.
        assert cfg.agent("ORCH").model == "gemma4:12b-it-qat"

    def test_agent_prefix_beats_global(self, make_config):
        cfg = make_config(PENDULUM_DEFAULT_MODEL="a", SALT_MODEL="b", SALT_TIMEOUT_S="42")
        assert cfg.agent("SALT").model == "b"
        assert cfg.agent("SALT").timeout_s == 42.0
        assert cfg.agent("FUZZY").model == "a"

    def test_unknown_prefix_rejected(self, bare_config):
        with pytest.raises(ValueError, match="unknown agent prefix"):
            bare_config.agent("NOPE")

    def test_all_declared_prefixes_resolve(self, bare_config):
        for prefix in AGENT_PREFIXES:
            assert bare_config.agent(prefix).name == prefix.lower()


class TestPaths:
    def test_relative_paths_resolve_against_pendulum_root(self, make_config):
        cfg = make_config(PENDULUM_RAG_DIR="data/rag")
        assert cfg.rag_dir == (PENDULUM_ROOT / "data" / "rag").resolve()

    def test_default_repo_paths(self, bare_config):
        assert bare_config.mcp_server_bin == REPO_ROOT / "target" / "release" / "pltl-mcp"
        assert bare_config.grammar_file == REPO_ROOT / "grammars" / "pltl.gbnf"

    def test_absolute_path_kept(self, make_config):
        cfg = make_config(PLTL_PARSER_BIN="/abs/main.exe")
        assert str(cfg.pltl_parser_bin) == "/abs/main.exe"


class TestPipelineKnobs:
    def test_validated_enums(self, make_config):
        with pytest.raises(ValueError, match="PENDULUM_LOG_LEVEL"):
            _ = make_config(PENDULUM_LOG_LEVEL="loud").log_level
        with pytest.raises(ValueError, match="PENDULUM_LNLL_SCOPE"):
            _ = make_config(PENDULUM_LNLL_SCOPE="mid").lnll_scope
        with pytest.raises(ValueError, match="PYTHON_AGENT_MODE"):
            _ = make_config(PYTHON_AGENT_MODE="hybrid").python_agent_mode

    def test_defaults(self, bare_config):
        assert bare_config.feedback_loop is True
        assert bare_config.feedback_max_rounds == 1
        assert bare_config.ap_confidence_threshold == -1.5
        assert bare_config.tool_cache_enabled is True
        assert bare_config.max_output_formulas == 10  # raised for survivor+variant output
        assert bare_config.llamacpp_enabled is True

    def test_round3_toggle_defaults(self, bare_config):
        assert bare_config.dwyer_enabled is False
        assert bare_config.det_verify_enabled is False
        assert bare_config.orch_compare_filter is False
        assert bare_config.output_all_survivors is True
        assert bare_config.output_scope_variants is True

    def test_salt_rag_disabled_default_off(self, bare_config, make_config):
        assert bare_config.salt_rag_disabled is False
        assert make_config(PENDULUM_SALT_RAG_DISABLED="true").salt_rag_disabled is True

    def test_oneshot_toggle_and_seat(self, bare_config, make_config):
        assert bare_config.oneshot_enabled is False
        assert make_config(PENDULUM_ONESHOT_ENABLED="true").oneshot_enabled is True
        # the ONESHOT agent prefix resolves (added to AGENT_PREFIXES)
        assert bare_config.agent("ONESHOT").name == "oneshot"
        assert make_config(ONESHOT_MODEL="qwen3:14b").agent("ONESHOT").model == "qwen3:14b"
