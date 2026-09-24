"""Configuration: one .env file, typed accessors, per-agent inheritance.

Resolution order for every agent knob (e.g. the SALT agent's model):
    SALT_MODEL  →  PENDULUM_DEFAULT_MODEL  →  code default

`PendulumConfig.from_env()` reads os.environ after loading `Pendulum/.env`
(real environment variables win over the file, so tests and one-off runs can
override without editing it). Tests construct `PendulumConfig({...})` directly
from a plain dict — no module-level global state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

PENDULUM_ROOT = Path(__file__).resolve().parent.parent  # Pendulum/
REPO_ROOT = PENDULUM_ROOT.parent  # PLTL-MCP/

#: Prefixes for the eight configurable agents.
AGENT_PREFIXES = ("AP", "ORCH", "PYTHON", "DWYER", "SALT", "FUZZY", "DET", "ONESHOT")

# Per-seat model defaults. Empty -> every seat falls back to gemma4:31b-mlx
# (see the `.get(..., "gemma4:31b-mlx")` below). gemma-31b is the default because
# the session experiments ran on it end-to-end and it matched or beat the frontier
# in every seat measured — incl. python synthesis, where it beat qwen2.5-coder
# 169 vs 120 (exp-15). Override any seat via {SEAT}_MODEL (e.g. a coder model for
# PYTHON, a stronger orchestrator for ORCH) in .env.
_AGENT_MODEL_DEFAULTS: dict[str, str] = {}


VALID_BACKENDS = ("ollama", "claude-cli", "codex-cli", "gemini-api")


@dataclass(frozen=True)
class AgentConfig:
    """Everything one agent needs to talk to its LLM (task.md requirement)."""

    name: str
    backend: str  # ollama | claude-cli | codex-cli (router-path agents only)
    base_url: str
    api_key: str
    model: str
    temperature: float
    num_ctx: int  # context window size
    max_steps: int  # max tool-call iterations
    timeout_s: float  # expiration time per invocation
    max_retries: int
    thinking: bool  # request thinking/reasoning mode when the model supports it
    streaming: bool


class PendulumConfig:
    """Typed view over an environment mapping. Immutable after construction."""

    def __init__(self, env: Mapping[str, str]):
        self._env = dict(env)

    @classmethod
    def from_env(cls, dotenv_path: Optional[Path] = None) -> "PendulumConfig":
        load_dotenv(dotenv_path or PENDULUM_ROOT / ".env", override=False)
        return cls(os.environ)

    # -- low-level typed getters ------------------------------------------

    def _get(self, key: str, default: str) -> str:
        value = self._env.get(key, "").strip()
        return value if value else default

    def get_str(self, key: str, default: str) -> str:
        return self._get(key, default)

    def get_float(self, key: str, default: float) -> float:
        raw = self._get(key, str(default))
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{key}={raw!r} is not a number") from exc

    def get_int(self, key: str, default: int) -> int:
        raw = self._get(key, str(default))
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{key}={raw!r} is not an integer") from exc

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self._get(key, str(default)).lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key}={raw!r} is not a boolean (use true/false)")

    def get_path(self, key: str, default: Path) -> Path:
        """Relative paths resolve against Pendulum/ (where .env lives)."""
        raw = self._env.get(key, "").strip()
        path = Path(raw).expanduser() if raw else default
        return path if path.is_absolute() else (PENDULUM_ROOT / path).resolve()

    # -- per-agent config with PENDULUM_DEFAULT_* inheritance -------------

    def _agent_str(self, prefix: str, field: str, default: str) -> str:
        return self._get(f"{prefix}_{field}", self._get(f"PENDULUM_DEFAULT_{field}", default))

    def agent(self, prefix: str) -> AgentConfig:
        if prefix not in AGENT_PREFIXES:
            raise ValueError(f"unknown agent prefix {prefix!r}; expected one of {AGENT_PREFIXES}")

        def s(field: str, default: str) -> str:
            return self._agent_str(prefix, field, default)

        backend = s("BACKEND", "ollama")
        if backend not in VALID_BACKENDS:
            raise ValueError(f"{prefix}_BACKEND={backend!r}: use one of {VALID_BACKENDS}")
        return AgentConfig(
            name=prefix.lower(),
            backend=backend,
            base_url=s("BASE_URL", "http://localhost:11434/v1"),
            api_key=s("API_KEY", "ollama"),
            model=s("MODEL", _AGENT_MODEL_DEFAULTS.get(prefix, "gemma4:31b-mlx")),
            temperature=float(s("TEMPERATURE", "0.0")),
            num_ctx=int(s("NUM_CTX", "16384")),
            max_steps=int(s("MAX_STEPS", "8")),
            timeout_s=float(s("TIMEOUT_S", "480")),  # raised from 300 (user-approved, 2026-07-04)
            max_retries=int(s("MAX_RETRIES", "2")),
            thinking=s("THINKING", "false").lower() in ("1", "true", "yes", "on"),
            streaming=s("STREAMING", "false").lower() in ("1", "true", "yes", "on"),
        )

    # -- pipeline-level knobs ----------------------------------------------

    @property
    def log_level(self) -> str:
        level = self.get_str("PENDULUM_LOG_LEVEL", "info").lower()
        if level not in ("debug", "info", "warning", "error"):
            raise ValueError(f"PENDULUM_LOG_LEVEL={level!r}: use debug|info|warning|error")
        return level

    @property
    def log_dir(self) -> Path:
        return self.get_path("PENDULUM_LOG_DIR", PENDULUM_ROOT / "logs")

    @property
    def ap_confidence_threshold(self) -> float:
        return self.get_float("PENDULUM_AP_CONFIDENCE_THRESHOLD", -1.5)

    @property
    def feedback_loop(self) -> bool:
        return self.get_bool("PENDULUM_FEEDBACK_LOOP", True)

    @property
    def feedback_max_rounds(self) -> int:
        return self.get_int("PENDULUM_FEEDBACK_MAX_ROUNDS", 1)

    @property
    def lnll_scope(self) -> str:
        scope = self.get_str("PENDULUM_LNLL_SCOPE", "formula")
        if scope not in ("formula", "full"):
            raise ValueError(f"PENDULUM_LNLL_SCOPE={scope!r}: use formula|full")
        return scope

    @property
    def max_output_formulas(self) -> int:
        # default raised 5 -> 10 (user-approved round-3 plan): all-survivors +
        # scope-variant expansion would truncate under the original cap
        return self.get_int("PENDULUM_MAX_OUTPUT_FORMULAS", 10)

    # -- round-3 feature toggles (user-approved plan, 2026-07-04) ----------

    @property
    def dwyer_enabled(self) -> bool:
        """Include the Dwyer agent in the synthesis fan-out (default off:
        forensic run showed ~0 usable yield on realistic corpora)."""
        return self.get_bool("PENDULUM_DWYER_ENABLED", False)

    @property
    def oneshot_enabled(self) -> bool:
        """Include the one-shot synthesizer (a plain NL->LTL emit by a possibly
        different model) in the synthesis fan-out. Default off; A/B'd in exp-20
        as an extra candidate source."""
        return self.get_bool("PENDULUM_ONESHOT_ENABLED", False)

    @property
    def det_verify_enabled(self) -> bool:
        """Run the deterministic (BLACK-tool) verifier alongside fuzzy
        (default off: 60% of wall clock, refuted exact-GT candidates)."""
        return self.get_bool("PENDULUM_DET_VERIFY_ENABLED", False)

    @property
    def orch_compare_filter(self) -> bool:
        """Give the orchestrator a code-side compare_candidates lattice for
        filtering/tie-breaks. Off: it filters on fuzzy verdicts only."""
        return self.get_bool("PENDULUM_ORCH_COMPARE_FILTER", False)

    @property
    def output_all_survivors(self) -> bool:
        """Emit every kept, not-fuzzy-refuted candidate in the final ranking
        (forensic: top-1-only emission cost 4 any-rank exacts)."""
        return self.get_bool("PENDULUM_OUTPUT_ALL_SURVIVORS", True)

    @property
    def output_scope_variants(self) -> bool:
        """For each output formula also emit its G-wrapped / unwrapped
        counterpart (scope-ambiguous NL: 4 predicted_stronger rows)."""
        return self.get_bool("PENDULUM_OUTPUT_SCOPE_VARIANTS", True)

    @property
    def contrastive_judge(self) -> bool:
        """One lattice-informed, falsification-framed judge call per row over
        ALL candidates (user-approved judge fixes 1-5) instead of the legacy
        per-candidate paraphrase match."""
        return self.get_bool("PENDULUM_CONTRASTIVE_JUDGE", True)

    @property
    def judge_show_tnl(self) -> bool:
        """Also show the contrastive judge the deterministic literal reading (TNL)
        of each candidate, not just the LLM paraphrases. The TNL is a faithful
        AST-walk (already computed inside ltl_to_nl) and is the authoritative
        witness of what the formula says; the paraphrases are fluent but fallible.
        Off by default (experimental — A/B on the exp-11 harness)."""
        return self.get_bool("PENDULUM_JUDGE_SHOW_TNL", False)

    @property
    def judge_tnl_only(self) -> bool:
        """Contrastive judge sees ONLY the deterministic literal reading (TNL) per
        candidate — the LLM paraphrases are omitted entirely. Tests whether the
        fluent-but-fallible paraphrases are net signal or net noise. Off by default."""
        return self.get_bool("PENDULUM_JUDGE_TNL_ONLY", False)

    @property
    def judge_explain_traces(self) -> bool:
        """Attach the deterministic trace explanation (from the Rust trace_explain
        analysis, via the MCP tools' explain=true) to the judge's trace evidence:
        the forbidden-example trace gets 'why the formula forbids this run', and each
        distinguishing trace gets 'why one candidate accepts and the other rejects'.
        Turns a raw lasso into a grounded reason. Off by default (experimental)."""
        return self.get_bool("PENDULUM_JUDGE_EXPLAIN_TRACES", False)

    @property
    def judge_dist_trace(self) -> bool:
        """Add per-pair DISTINGUISHING TRACES (a concrete run one candidate accepts
        and another rejects) to the contrastive judge, with an explanation of how to
        use them against the requirement — the sharpest discriminator for look-alike
        candidates, currently unused by the judge. Off by default."""
        return self.get_bool("PENDULUM_JUDGE_DIST_TRACE", False)

    @property
    def judge_paraphrase_audit(self) -> bool:
        """Contrastive-judge mode. Instead of one holistic verdict per candidate,
        the judge is shown each candidate's literal TNL + its 5 paraphrases and,
        FOR EACH paraphrase, decides whether it captures the user's requirement
        (with a reason if not). The candidate's verdict is DERIVED from how many
        paraphrases capture it (majority -> SUPPORTS; confidence = fraction
        captured, used as the ranking tie-break). **On by default** as a ~neutral,
        lower-variance selector. NOTE (2026-07-21): exp-16's original "+4 (181->185)"
        did NOT reproduce — the MLX judge path is nondeterministic (MLX ignores the
        decoding seed; gguf models honor it), and four gemma-31b-mlx re-runs
        give base {181,185,185,185} (181 an outlier), audit-base averaging ~+0.8, and
        +0/+0 cross-model. Kept because it doesn't hurt and is more stable, NOT for a
        +4 gain. Set to "false" to restore the single-verdict contrastive judge."""
        return self.get_bool("PENDULUM_JUDGE_PARAPHRASE_AUDIT", True)

    @property
    def claude_cli_bin(self) -> str:
        return self.get_str("CLAUDE_CLI_BIN", "claude")

    @property
    def codex_cli_bin(self) -> str:
        return self.get_str("CODEX_CLI_BIN", "codex")

    @property
    def emit_best_guess(self) -> bool:
        """When the orchestrator judges ALL candidates refuted: emit the
        deterministic-fallback ranking flagged low_confidence (True, the
        user-approved default) instead of an empty honest refusal (False)."""
        return self.get_bool("PENDULUM_EMIT_BEST_GUESS", True)

    @property
    def max_candidates_to_verify(self) -> int:
        return self.get_int("PENDULUM_MAX_CANDIDATES_TO_VERIFY", 5)

    @property
    def synth_parse_max_retries(self) -> int:
        return self.get_int("SYNTH_PARSE_MAX_RETRIES", 3)

    @property
    def synth_max_candidates(self) -> int:
        """Max candidate formulas each synthesis agent may emit per round."""
        return self.get_int("SYNTH_MAX_CANDIDATES", 3)

    @property
    def salt_fix_max_attempts(self) -> int:
        return self.get_int("SALT_FIX_MAX_ATTEMPTS", 4)

    @property
    def python_agent_mode(self) -> str:
        mode = self.get_str("PYTHON_AGENT_MODE", "direct")
        if mode not in ("direct", "mcp"):
            raise ValueError(f"PYTHON_AGENT_MODE={mode!r}: use direct|mcp")
        return mode

    # llama-server (grammar-constrained decoding + logprobs)

    @property
    def llamacpp_enabled(self) -> bool:
        return self.get_bool("LLAMACPP_ENABLED", True)

    @property
    def llamacpp_base_url(self) -> str:
        return self.get_str("LLAMACPP_BASE_URL", "http://localhost:8080")

    @property
    def llamacpp_health_ttl_s(self) -> float:
        return self.get_float("LLAMACPP_HEALTH_TTL_S", 30.0)

    @property
    def grammar_file(self) -> Path:
        return self.get_path("PENDULUM_GRAMMAR_FILE", REPO_ROOT / "grammars" / "pltl.gbnf")

    # pltl-mcp server

    @property
    def mcp_server_bin(self) -> Path:
        return self.get_path("PENDULUM_MCP_BIN", REPO_ROOT / "target" / "release" / "pltl-mcp")

    @property
    def pltl_parser_bin(self) -> Path:
        return self.get_path(
            "PLTL_PARSER_BIN", REPO_ROOT / "ocaml" / "_build" / "default" / "main.exe"
        )

    @property
    def tool_llm_base_url(self) -> str:
        return self.get_str("PLTL_TOOL_LLM_BASE_URL", "http://localhost:11434")

    @property
    def tool_llm_model(self) -> str:
        return self.get_str("PLTL_TOOL_LLM_MODEL", "gemma4:31b-mlx")

    @property
    def black_bin(self) -> str:
        return self.get_str("BLACK_BIN", "")  # empty = rely on PATH

    @property
    def tool_cache_enabled(self) -> bool:
        return self.get_bool("PENDULUM_TOOL_CACHE", True)

    @property
    def tool_cache_size(self) -> int:
        return self.get_int("PENDULUM_TOOL_CACHE_SIZE", 1024)

    # RAG

    @property
    def rag_dir(self) -> Path:
        return self.get_path("PENDULUM_RAG_DIR", PENDULUM_ROOT / "data" / "rag")

    @property
    def rag_autobuild(self) -> bool:
        return self.get_bool("PENDULUM_RAG_AUTOBUILD", True)

    @property
    def rag_embed_model(self) -> str:
        return self.get_str("RAG_EMBED_MODEL", "all-minilm")

    @property
    def rag_embed_base_url(self) -> str:
        return self.get_str("RAG_EMBED_BASE_URL", "http://localhost:11434")

    @property
    def salt_pin_condensed_reference(self) -> bool:
        """Always include the full condensed SALT reference (all salt_help
        cards) instead of relying on top-k retrieval. The RAG-retrieval test
        (2026-07-06) showed verbose PDF chunks crowd out the concise operator
        cards >50% of the time — but the A/B (2026-07-07) found pinning is a
        WASH once the pitfalls prompt is in place (+1/50, 4 gained/3 lost):
        the pitfalls prompt already captured the gain, and flooding all 18
        cards induces spurious-`always` regressions on trivial rows. Hence
        DEFAULT OFF. Kept as a toggle for a future refined pin (operator-table
        cards only)."""
        return self.get_bool("PENDULUM_SALT_PIN_CONDENSED_REFERENCE", False)

    @property
    def salt_hybrid_retrieval(self) -> bool:
        """SALT reference retrieval: hybrid (dense + BM25, reciprocal-rank
        fusion) over the CONDENSED cards only, with an LLM-reformulated
        SALT-vocabulary query, instead of dense-only top-k over the raw NL.

        This FIXED retrieval quality (probe: the biconditional/past cards that
        dense search missed now rank #1) — but the A/B (2026-07-07) found it
        does NOT move the SALT output score (18->17/50, 3 gained/4 lost). The
        pitfalls prompt already hard-codes the same guidance, so improving
        retrieval is redundant. Conclusion: retrieval quality is not the
        bottleneck once the prompt is fixed — and by extension a tool-based
        (agentic) RAG rebuild is not worth building either. DEFAULT OFF; kept
        as documented, working infrastructure."""
        return self.get_bool("PENDULUM_SALT_HYBRID_RETRIEVAL", False)

    @property
    def salt_rag_disabled(self) -> bool:
        """Run the SALT author with NO retrieved reference at all (empty
        reference block) — the static system prompt only. Default OFF. Added to
        A/B whether retrieval adds anything over the pitfalls prompt (exp-19)."""
        return self.get_bool("PENDULUM_SALT_RAG_DISABLED", False)

    @property
    def orch_deterministic(self) -> bool:
        """Skip the LLM finalize agent and rank the final candidates purely
        from the verification verdicts (deterministic, ~17s/row vs ~106s/row
        for the LLM orchestrator on a small local model). **On by default**:
        the end-to-end experiment (exp-08, 2026-07-11) found deterministic
        ranking scores 171/303 top-1 vs 140/303 for the LLM orchestrator
        (+31 rows, and far faster / no extra model). Set to "false" to restore
        the LLM finalize agent."""
        return self.get_bool("PENDULUM_ORCH_DETERMINISTIC", True)

    @property
    def python_semantics_prompt(self) -> bool:
        """Use the python_to_ltl system prompt that includes the executable
        evalFormula operational semantics (Danso et al.) instead of the
        prose-only variant. A/B-gated (Task #18); default off."""
        return self.get_bool("PENDULUM_PYTHON_SEMANTICS_PROMPT", False)

    @property
    def rag_top_k(self) -> int:
        return self.get_int("RAG_TOP_K", 4)

    # Eval

    @property
    def eval_use_black(self) -> bool:
        return self.get_bool("EVAL_USE_BLACK", True)
