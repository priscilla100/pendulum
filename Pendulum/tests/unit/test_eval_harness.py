"""Eval harness: row identity, resume, header safety, selection (codex audit #2)."""

from __future__ import annotations

import csv

import pytest

from pendulum.eval.harness import CSV_FIELDS, load_done_keys, row_key, select_rows


def make_row(fid, tid, depth="3", translation="t"):
    return {"formula_id": fid, "translation_id": tid, "depth": depth,
            "translation": translation, "formula_canonical_form": "G p", "activity": "p = x"}


class TestRowIdentity:
    def test_duplicate_formula_ids_are_distinct_rows(self):
        a, b = make_row("27601", "1"), make_row("27601", "2")
        assert row_key(a) != row_key(b)

    def test_resume_respects_translation_id(self, tmp_path):
        out = tmp_path / "run.csv"
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerow({**{k: "" for k in CSV_FIELDS},
                             "formula_id": "27601", "translation_id": "1"})
        done = load_done_keys(out)
        assert ("27601", "1") in done and ("27601", "2") not in done


class TestHeaderSafety:
    def test_mismatched_header_refuses_append(self, tmp_path):
        out = tmp_path / "old.csv"
        out.write_text("formula_id,score\n1,exact\n")
        with pytest.raises(ValueError, match="different column schema"):
            load_done_keys(out)

    def test_missing_or_empty_file_is_fresh(self, tmp_path):
        assert load_done_keys(tmp_path / "nope.csv") == set()
        empty = tmp_path / "empty.csv"
        empty.touch()
        assert load_done_keys(empty) == set()


class TestSelection:
    ROWS = [make_row(str(i), "1", depth=str(i)) for i in range(1, 11)]

    def test_formula_ids_override_sampling(self):
        selected = select_rows(self.ROWS, sample_size=2, max_depth=None, seed=1,
                               formula_ids=["3", "7"])
        assert {r["formula_id"] for r in selected} == {"3", "7"}

    def test_unknown_formula_id_fails_loudly(self):
        with pytest.raises(ValueError, match="not found in dataset"):
            select_rows(self.ROWS, sample_size=2, max_depth=None, seed=1, formula_ids=["999"])

    def test_seeded_sampling_is_deterministic_and_depth_filtered(self):
        one = select_rows(self.ROWS, sample_size=3, max_depth=5, seed=42, formula_ids=None)
        two = select_rows(self.ROWS, sample_size=3, max_depth=5, seed=42, formula_ids=None)
        assert [r["formula_id"] for r in one] == [r["formula_id"] for r in two]
        assert all(int(r["depth"]) <= 5 for r in one)


class TestExternalDatasets:
    RAW = [{"id": 7, "nl": "the robot eventually reaches the goal",
            "formula": "F goal", "ap_map": {"goal": "the robot is at the goal"},
            "source": "warehouse"}]

    def test_adapt_rows_shape(self):
        from pendulum.eval.external import adapt_rows

        rows = adapt_rows(self.RAW, "vltl_bench")
        row = rows[0]
        assert row["formula_id"] == "7" and row["domain"] == "warehouse"
        assert row["formula_canonical_form"] == "F goal"
        assert row["_ap_map"] == {"goal": "the robot is at the goal"}

    def test_preset_aps_prefer_explicit_ap_map(self):
        from pendulum.eval.external import adapt_rows
        from pendulum.eval.harness import preset_aps_for_row

        aps = preset_aps_for_row(adapt_rows(self.RAW, "vltl_bench")[0])
        assert [(m.ap, m.nl_fragment) for m in aps] == [("goal", "the robot is at the goal")]

    def test_atoms_missing_from_ap_map_get_fallback(self):
        from pendulum.eval.external import adapt_rows
        from pendulum.eval.harness import preset_aps_for_row

        raw = [dict(self.RAW[0], formula="F (goal & done)")]
        aps = preset_aps_for_row(adapt_rows(raw, "vltl_bench")[0])
        by_name = {m.ap: m.nl_fragment for m in aps}
        assert by_name["goal"] == "the robot is at the goal"
        assert "done" in by_name and "`done`" in by_name["done"]

    def test_unknown_dataset_rejected_listing_valid_names(self, bare_config):
        import pytest
        from pendulum.eval.external import load_external_rows

        with pytest.raises(ValueError, match="unknown external dataset") as exc:
            load_external_rows("nope", bare_config)
        for name in ("vltl_bench", "synthtl", "unambiguous50"):
            assert name in str(exc.value)


class TestUnambiguous50:
    ENTRY = {
        "id": "u50_hard_03",
        "tier": "hard",
        "source": "vltl_bench",  # provenance — must NOT end up in domain
        "source_id": "vltl_x_1",
        "nl": "the arm eventually grips",
        "nl_original": "the arm eventually grips",
        "nl_edited": False,
        "formula": "F grip",
        "ap_map": {"grip": "the arm grips"},
        "metrics": {},
        "rationale": "r",
        "reviewers": {"codex": "keep", "claude": "keep"},
    }

    def _config_with(self, tmp_path, make_config, entries):
        import json

        path = tmp_path / "u50.json"
        path.write_text(json.dumps({"name": "unambiguous50", "version": 1,
                                    "criteria": [], "entries": entries}))
        return make_config(UNAMBIGUOUS50_JSON=path)

    def test_loader_row_shape_and_tier_in_domain(self, tmp_path, make_config):
        from pendulum.eval.external import load_external_rows

        config = self._config_with(tmp_path, make_config, [self.ENTRY])
        (row,) = load_external_rows("unambiguous50", config)
        assert row["formula_id"] == "u50_hard_03"
        assert row["translation"] == "the arm eventually grips"
        assert row["formula_canonical_form"] == "F grip"
        assert row["_ap_map"] == {"grip": "the arm grips"}
        assert row["domain"] == "hard"  # tier, not the provenance source
        # same shape as the other adapters (harness contract)
        assert set(row) == {"formula_id", "translation_id", "depth", "domain",
                            "formula_canonical_form", "translation", "activity", "_ap_map"}

    def test_loader_reads_committed_file_by_default(self, bare_config):
        from pendulum.eval.external import load_external_rows

        rows = load_external_rows("unambiguous50", bare_config)
        assert len(rows) == 50
        tiers = {r["domain"] for r in rows}
        assert tiers == {"very_easy", "easy", "medium", "hard", "impossible"}

    def test_preset_aps_come_from_ap_map(self, tmp_path, make_config):
        from pendulum.eval.external import load_external_rows
        from pendulum.eval.harness import preset_aps_for_row

        config = self._config_with(tmp_path, make_config, [self.ENTRY])
        aps = preset_aps_for_row(load_external_rows("unambiguous50", config)[0])
        assert [(m.ap, m.nl_fragment) for m in aps] == [("grip", "the arm grips")]

    def test_missing_file_fails_helpfully(self, tmp_path, make_config):
        import pytest
        from pendulum.eval.external import load_external_rows

        config = make_config(UNAMBIGUOUS50_JSON=tmp_path / "gone.json")
        with pytest.raises(ValueError, match="UNAMBIGUOUS50_JSON"):
            load_external_rows("unambiguous50", config)
