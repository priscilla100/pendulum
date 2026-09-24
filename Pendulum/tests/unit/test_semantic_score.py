"""Semantic scoring: any-rank BLACK equivalence (`pendulum score`)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pendulum.eval.semantic_score import (
    NEW_COLUMNS,
    candidates_for_row,
    default_out_path,
    score_file,
)
from pendulum.mcp.client import McpError, McpToolError
from tests.conftest import FakeMCP

BASE_FIELDS = [
    "formula_id", "translation", "ground_truth_formula", "predicted_formula", "all_formulas",
]


class ScoringMCP(FakeMCP):
    """FakeMCP whose check_equivalence verdict is scripted per (f1, f2).

    `equivalences` maps (gt, candidate) -> True; anything else is not
    equivalent. `errors` maps (gt, candidate) -> an exception to raise.
    Inherits the conftest parse gate: formulas containing 'INVALID' fail
    parse_and_canonicalize."""

    def __init__(self, equivalences=None, errors=None):
        super().__init__()
        self.equivalences = dict(equivalences or {})
        self.errors = dict(errors or {})

    async def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "check_equivalence":
            key = (args["f1"], args["f2"])
            if key in self.errors:
                raise self.errors[key]
            return {"equivalent": self.equivalences.get(key, False)}
        return {}

    def equivalence_calls(self):
        return [args for tool, args in self.calls if tool == "check_equivalence"]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] = BASE_FIELDS) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def make_row(gt="F q", all_formulas="G p | F q", **extra) -> dict:
    row = {
        "formula_id": "1", "translation": "eventually q",
        "ground_truth_formula": gt,
        "predicted_formula": all_formulas.split(" | ")[0] if all_formulas else "",
        "all_formulas": all_formulas,
    }
    row.update(extra)
    return row


async def run_score(tmp_path, rows, mcp, fieldnames=BASE_FIELDS):
    in_path = write_csv(tmp_path / "run.csv", rows, fieldnames)
    out_path = tmp_path / "run_scored.csv"
    rc = await score_file(in_path, out_path, None, mcp=mcp)
    assert rc == 0
    return read_csv(out_path)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_default_out_path_inserts_scored_before_suffix(self):
        assert default_out_path(Path("/x/run.csv")) == Path("/x/run_scored.csv")

    def test_candidates_split_and_strip(self):
        assert candidates_for_row({"all_formulas": "G p | F q |  "}) == ["G p", "F q"]

    def test_candidates_empty_column(self):
        assert candidates_for_row({"all_formulas": ""}) == []

    def test_candidates_missing_column_falls_back_to_top1(self):
        assert candidates_for_row({"predicted_formula": "F q"}) == ["F q"]
        assert candidates_for_row({"predicted_formula": ""}) == []


# ---------------------------------------------------------------------------
# scoring semantics
# ---------------------------------------------------------------------------


class TestScoring:
    async def test_success_at_rank_2(self, tmp_path, capsys):
        mcp = ScoringMCP(equivalences={("F q", "F q"): True})
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="G p | F q")], mcp)
        row = rows[0]
        assert row["any_equivalent"] == "true"
        assert row["equivalent_rank"] == "2"
        assert row["n_checked"] == "2"
        assert row["gt_parses"] == "true"
        out = capsys.readouterr().out
        assert "any-rank equivalent (SUCCESS): 1/1" in out
        assert "top-1 equivalent (comparison): 0/1" in out  # rank-1 candidate was a miss

    async def test_stops_at_first_equivalent(self, tmp_path):
        mcp = ScoringMCP(equivalences={("F q", "F q"): True, ("F q", "O q"): True})
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="F q | O q")], mcp)
        assert rows[0]["equivalent_rank"] == "1"
        assert rows[0]["n_checked"] == "1"
        assert mcp.equivalence_calls() == [{"f1": "F q", "f2": "F q"}]

    async def test_no_equivalent_candidate(self, tmp_path, capsys):
        mcp = ScoringMCP()
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="G p | H p")], mcp)
        row = rows[0]
        assert row["any_equivalent"] == "false"
        assert row["equivalent_rank"] == ""
        assert row["n_checked"] == "2"
        assert "any-rank equivalent (SUCCESS): 0/1" in capsys.readouterr().out

    async def test_unparseable_candidate_skipped_later_rank_checked(self, tmp_path):
        mcp = ScoringMCP(equivalences={("F q", "F q"): True})
        rows = await run_score(
            tmp_path, [make_row(gt="F q", all_formulas="INVALID x | F q")], mcp
        )
        row = rows[0]
        assert row["any_equivalent"] == "true"
        assert row["equivalent_rank"] == "2"
        # the unparseable rank-1 candidate never reached the solver
        assert mcp.equivalence_calls() == [{"f1": "F q", "f2": "F q"}]

    async def test_unparseable_ground_truth(self, tmp_path):
        mcp = ScoringMCP()
        rows = await run_score(
            tmp_path, [make_row(gt="INVALID gt", all_formulas="G p | F q")], mcp
        )
        row = rows[0]
        assert row["gt_parses"] == "false"
        assert row["any_equivalent"] == "false"
        assert row["equivalent_rank"] == ""
        assert row["n_checked"] == "0"
        assert mcp.equivalence_calls() == []

    async def test_tool_error_on_equivalence_means_gt_did_not_parse(self, tmp_path):
        # Defensive path: parse gate said OK but the server rejects the pair
        # (GT-side parse failure) -> whole-row parse_gt verdict.
        mcp = ScoringMCP(errors={("F q", "G p"): McpToolError("check_equivalence", "invalid_params")})
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="G p | F q")], mcp)
        row = rows[0]
        assert row["gt_parses"] == "false"
        assert row["any_equivalent"] == "false"

    async def test_black_error_on_one_check_continues(self, tmp_path):
        mcp = ScoringMCP(
            equivalences={("F q", "F q"): True},
            errors={("F q", "G p"): McpError("BLACK timed out")},
        )
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="G p | F q")], mcp)
        row = rows[0]
        assert row["any_equivalent"] == "true"
        assert row["equivalent_rank"] == "2"
        assert row["gt_parses"] == "true"

    async def test_missing_all_formulas_column_falls_back_to_predicted(self, tmp_path):
        fields = ["formula_id", "translation", "ground_truth_formula", "predicted_formula"]
        mcp = ScoringMCP(equivalences={("F q", "F q"): True})
        rows = await run_score(
            tmp_path,
            [{"formula_id": "1", "translation": "t",
              "ground_truth_formula": "F q", "predicted_formula": "F q"}],
            mcp, fieldnames=fields,
        )
        row = rows[0]
        assert row["any_equivalent"] == "true"
        assert row["equivalent_rank"] == "1"
        assert row["n_checked"] == "1"

    async def test_empty_candidate_list(self, tmp_path):
        mcp = ScoringMCP()
        rows = await run_score(tmp_path, [make_row(gt="F q", all_formulas="")], mcp)
        row = rows[0]
        assert row["any_equivalent"] == "false"
        assert row["n_checked"] == "0"
        assert row["gt_parses"] == "true"
        assert mcp.equivalence_calls() == []

    async def test_original_columns_preserved_verbatim(self, tmp_path):
        mcp = ScoringMCP()
        original = make_row(gt="F q", all_formulas="G p",
                            formula_id="27601", translation="the, weird | text")
        rows = await run_score(tmp_path, [original], mcp)
        row = rows[0]
        for col in BASE_FIELDS:
            assert row[col] == original[col]
        assert set(NEW_COLUMNS) <= set(row)


# ---------------------------------------------------------------------------
# fatal I/O handling
# ---------------------------------------------------------------------------


class TestIO:
    async def test_refuses_out_equal_to_in(self, tmp_path):
        in_path = write_csv(tmp_path / "run.csv", [make_row()])
        with pytest.raises(ValueError, match="refusing to overwrite"):
            await score_file(in_path, in_path, None, mcp=ScoringMCP())

    async def test_missing_input_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await score_file(tmp_path / "nope.csv", tmp_path / "out.csv", None, mcp=ScoringMCP())

    async def test_malformed_header_rejected(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("foo,bar\n1,2\n")
        with pytest.raises(ValueError, match="not a harness CSV"):
            await score_file(bad, tmp_path / "out.csv", None, mcp=ScoringMCP())

    def test_cli_score_exits_1_on_missing_input(self, tmp_path, capsys):
        from pendulum.cli import main

        rc = main(["score", "--in", str(tmp_path / "nope.csv")])
        assert rc == 1
        assert "score failed" in capsys.readouterr().err

    def test_cli_score_refuses_same_out(self, tmp_path):
        from pendulum.cli import main

        in_path = write_csv(tmp_path / "run.csv", [make_row()])
        rc = main(["score", "--in", str(in_path), "--out", str(in_path)])
        assert rc == 1


class TestDisjunctionCollision:
    """Codex audit (high): 'p | q' inside a formula must not be split as two
    candidates. Current harness writes JSON; legacy delimiter still parses."""

    def test_json_all_formulas_with_disjunction(self):
        from pendulum.eval.semantic_score import candidates_for_row
        import json as _json

        row = {"all_formulas": _json.dumps(["G (p | q)", "F r"])}
        assert candidates_for_row(row) == ["G (p | q)", "F r"]

    def test_legacy_delimiter_still_supported(self):
        from pendulum.eval.semantic_score import candidates_for_row

        row = {"all_formulas": "G (req -> F ack) | F ack"}
        # legacy files without disjunction inside formulas still split
        assert candidates_for_row(row) == ["G (req -> F ack)", "F ack"]

    def test_harness_encoding_round_trips_through_scorer(self):
        from pendulum.eval.harness import encode_all_formulas
        from pendulum.eval.semantic_score import candidates_for_row

        # the ACTUAL harness encoder must survive the ACTUAL scorer decoder,
        # including the disjunction operator that broke the old delimiter
        formulas = ["(p | q)", "G (p | q)", "F r"]
        row = {"all_formulas": encode_all_formulas(formulas)}
        assert candidates_for_row(row) == formulas
