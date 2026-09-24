"""Invariant tests over the COMMITTED curated dataset data/unambiguous50.json.

These guard the dataset file itself (not the loader — see the external-adapter
tests in test_eval_harness.py): if a hand-edit breaks an invariant the matrix
experiment relies on (50 rows, tier balance, id scheme, ap_map/formula
consistency, review status), these fail before any eval burns compute.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from pendulum.eval.dataset import extract_atoms_from_formula

DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "unambiguous50.json"
TIERS = ("very_easy", "easy", "medium", "hard", "impossible")
ID_PATTERN = re.compile(r"^u50_(very_easy|easy|medium|hard|impossible)_\d\d$")


@pytest.fixture(scope="module")
def dataset() -> dict:
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def entries(dataset) -> list[dict]:
    return dataset["entries"]


def test_exactly_50_entries(entries):
    assert len(entries) == 50


def test_tier_counts_balanced(entries):
    counts = Counter(e["tier"] for e in entries)
    assert set(counts) == set(TIERS), f"unexpected tiers: {sorted(counts)}"
    for tier in TIERS:
        assert 8 <= counts[tier] <= 12, f"tier {tier}: {counts[tier]} entries (want 8-12)"
    assert sum(counts.values()) == 50


def test_ids_unique_and_well_formed(entries):
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), "duplicate ids"
    for e in entries:
        assert ID_PATTERN.match(e["id"]), f"malformed id: {e['id']!r}"
        # the tier embedded in the id must be the entry's own tier
        assert e["id"].startswith(f"u50_{e['tier']}_"), (
            f"id/tier mismatch: {e['id']!r} vs tier {e['tier']!r}")


def test_no_duplicate_formulas(entries):
    formulas = [e["formula"] for e in entries]
    dupes = [f for f, c in Counter(formulas).items() if c > 1]
    assert not dupes, f"duplicate formula strings: {dupes}"


def test_ap_map_matches_formula_atoms_exactly(entries):
    for e in entries:
        atoms = extract_atoms_from_formula(e["formula"])
        ap_keys = set(e["ap_map"])
        assert ap_keys == atoms, (
            f"{e['id']}: ap_map keys {sorted(ap_keys)} != formula atoms "
            f"{sorted(atoms)} in {e['formula']!r}")


def test_nl_non_empty(entries):
    for e in entries:
        assert isinstance(e["nl"], str) and e["nl"].strip(), f"{e['id']}: empty nl"


def test_nl_edited_flag_consistent(entries):
    for e in entries:
        assert e["nl_edited"] == (e["nl"] != e["nl_original"]), (
            f"{e['id']}: nl_edited={e['nl_edited']} but "
            f"nl {'differs from' if e['nl'] != e['nl_original'] else 'equals'} nl_original")


def test_both_reviewers_keep(entries):
    for e in entries:
        assert e["reviewers"] == {"codex": "keep", "claude": "keep"}, (
            f"{e['id']}: reviewers {e['reviewers']}")
