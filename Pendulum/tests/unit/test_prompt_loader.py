"""Prompt loader + integrity of the committed prompt files."""

from __future__ import annotations

import re

import pytest

from pendulum.prompt_loader import PROMPTS_DIR, PromptError, load, render

EXPECTED_PROMPTS = {
    "ap_extractor_system", "ap_extractor_user", "ap_fallback_preamble",
    "python_to_ltl_system", "python_to_ltl_system_semantics", "python_to_ltl_user", "python_to_ltl_retry",
    "dwyer_system", "dwyer_user", "dwyer_split_system", "dwyer_split_user",
    "salt_author_system", "salt_author_user", "salt_fix_user",
    "formula_emit_system", "formula_emit_user",
    "fuzzy_judge_system", "fuzzy_judge_user",
    "judge_contrastive_system", "judge_contrastive_user",
    "det_verifier_system", "det_verifier_user",
    "orchestrator_filter_system", "orchestrator_filter_user",
    "orchestrator_final_system", "orchestrator_final_user",
    "feedback_round_addendum",
}


class TestLoader:
    def test_render_substitutes_and_validates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pendulum.prompt_loader.PROMPTS_DIR", tmp_path)
        load.cache_clear()
        (tmp_path / "t.md").write_text('Say {THING} about {"json": "braces are fine"}')
        assert render("t", THING="hello") == 'Say hello about {"json": "braces are fine"}'

    def test_unresolved_placeholder_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pendulum.prompt_loader.PROMPTS_DIR", tmp_path)
        load.cache_clear()
        (tmp_path / "t.md").write_text("Needs {NATURAL_LANGUAGE} and {FORMULA}")
        with pytest.raises(PromptError, match="unresolved placeholders.*FORMULA"):
            render("t", NATURAL_LANGUAGE="x")

    def test_unknown_substitution_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pendulum.prompt_loader.PROMPTS_DIR", tmp_path)
        load.cache_clear()
        (tmp_path / "t.md").write_text("no placeholders")
        with pytest.raises(PromptError, match="no placeholder"):
            render("t", NOPE="x")

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pendulum.prompt_loader.PROMPTS_DIR", tmp_path)
        load.cache_clear()
        with pytest.raises(PromptError, match="missing"):
            load("does_not_exist")


class TestCommittedPrompts:
    """Guard the real prompt files: presence + placeholder inventory."""

    def setup_method(self):
        load.cache_clear()

    def test_all_expected_prompts_exist(self):
        actual = {p.stem for p in PROMPTS_DIR.glob("*.md")}
        missing = EXPECTED_PROMPTS - actual
        assert not missing, f"missing prompt files: {missing}"

    @pytest.mark.parametrize("name,placeholders", [
        ("ap_extractor_user", {"NATURAL_LANGUAGE"}),
        ("ap_fallback_preamble", {"FAILURE_REASON"}),
        ("python_to_ltl_system", {"MAX_CANDIDATES"}),
        ("python_to_ltl_system_semantics", {"MAX_CANDIDATES"}),
        ("python_to_ltl_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS"}),
        ("python_to_ltl_retry", {"FAILURE"}),
        ("dwyer_system", {"MAX_CANDIDATES"}),
        ("dwyer_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "RETRIEVED_PATTERNS"}),
        ("dwyer_split_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "RETRIEVED_PATTERNS"}),
        ("salt_author_user", {"SALT_REFERENCE", "NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS"}),
        ("salt_fix_user", {"SPEC", "COMPILE_ERROR"}),
        ("formula_emit_user", {"DERIVATION"}),
        ("fuzzy_judge_user", {"NATURAL_LANGUAGE", "FORMULA", "ATOMIC_PROPOSITIONS", "PARAPHRASES"}),
        ("judge_contrastive_system", set()),
        ("judge_contrastive_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "CANDIDATE_BLOCKS", "COMPARE_TABLE"}),
        ("det_verifier_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "FORMULA", "OTHER_CANDIDATES"}),
        ("orchestrator_filter_system", {"MAX_KEEP"}),
        ("orchestrator_filter_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "CANDIDATE_TABLE", "COMPARE_TABLE"}),
        ("orchestrator_final_system", {"MAX_FORMULAS"}),
        ("orchestrator_final_user", {"NATURAL_LANGUAGE", "ATOMIC_PROPOSITIONS", "VERIFICATION_TABLE", "COMPARE_TABLE"}),
        ("feedback_round_addendum", {"FAILURE_EVIDENCE"}),
    ])
    def test_placeholder_inventory(self, name, placeholders):
        text = load(name)
        found = set(re.findall(r"\{([A-Z][A-Z0-9_]*)\}", text))
        assert found == placeholders, f"{name}: expected {placeholders}, found {found}"

    def test_tense_neutrality_requirement_present(self):
        """The user-mandated tense rule with the Robin example must stay in
        the AP-extractor prompt, with examples covering past, future, and
        perfect tense (per important_details_to_remember_for_later.txt)."""
        text = load("ap_extractor_system")
        assert "TENSE NEUTRALITY" in text
        assert "robin_plays_soccer" in text
        assert "O robin_plays_soccer" in text
        assert "F backup_runs" in text  # future tense example
        assert "H interlock_engaged" in text  # perfect/historically example

    def test_lnll_demoted_in_orchestrator_prompts(self):
        for name in ("orchestrator_filter_system", "orchestrator_final_system"):
            text = load(name)
            assert "TIE-BREAK" in text, f"{name} must demote LNLL to tie-break"
