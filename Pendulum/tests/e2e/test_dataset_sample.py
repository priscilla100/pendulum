"""Live dataset sample through the harness (small N; the real experiment
runs via `python -m pendulum eval`)."""

from __future__ import annotations

import csv
import os

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("PENDULUM_E2E") != "1", reason="PENDULUM_E2E != 1"),
]


async def test_two_shallow_rows_produce_parseable_output(tmp_path):
    from pendulum.eval.harness import run_eval

    out = tmp_path / "sample.csv"
    rc = await run_eval(
        input_path=None, sample_size=2, max_depth=3, seed=7,
        formula_ids=None, out_path=str(out),
    )
    assert rc == 0
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 2
    for row in rows:
        assert row["condition"] == "pendulum"
        assert row["score"] in ("exact", "mismatch", "parse_only_gt")  # parse gate: never parse_only_pred
