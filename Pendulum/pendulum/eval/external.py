"""External datasets for the eval harness: VLTL-Bench, synthTL, unambiguous50.

VLTL-Bench and synthTL reuse the parent repo's adapters (scripts/datasets/*),
which normalize both datasets to {id, nl, formula, ap_map, source} with
formulas rewritten into this project's parser syntax. Those checkouts live
OUTSIDE the repo (they were lost to a /tmp wipe once): default
<repo-parent>/datasets/, overridable via VLTL_BENCH_ROOT / SYNTHTL_JSON.

unambiguous50 is the curated 50-entry dataset committed at
Pendulum/data/unambiguous50.json (overridable via UNAMBIGUOUS50_JSON). Its
rows carry the entry's complexity TIER in the harness `domain` field, so every
results CSV records the tier per row.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pendulum.config import PENDULUM_ROOT, REPO_ROOT, PendulumConfig

EXTERNAL_DATASETS = ("vltl_bench", "synthtl", "unambiguous50")
_DATASETS_DIR = REPO_ROOT.parent / "datasets"
UNAMBIGUOUS50_JSON = PENDULUM_ROOT / "data" / "unambiguous50.json"


def _import_adapters():
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from datasets import synthtl, vltl_bench  # the repo's adapter package

    return vltl_bench, synthtl


def adapt_rows(raw: list[dict[str, Any]], dataset: str) -> list[dict[str, Any]]:
    """Adapter row shape → the harness's internal row shape. The ap_map rides
    along under `_ap_map` so preset atoms come from the dataset directly
    instead of activity-prose parsing."""
    rows = []
    for r in raw:
        rows.append({
            "formula_id": str(r["id"]),
            "translation_id": "",
            "depth": "",
            "domain": str(r.get("source", dataset)),
            "formula_canonical_form": r["formula"],
            "translation": r["nl"],
            "activity": "",
            "_ap_map": dict(r.get("ap_map") or {}),
        })
    return rows


def unambiguous50_raw(config: PendulumConfig) -> list[dict[str, Any]]:
    """unambiguous50 entries → the adapter row shape adapt_rows expects.

    Deliberate mapping: `source` is set to the entry's TIER (not its
    provenance `source` field), because adapt_rows writes `source` into the
    harness `domain` column and the scored CSVs must carry the complexity
    tier per row for the per-tier summary breakdown."""
    path = config.get_path("UNAMBIGUOUS50_JSON", UNAMBIGUOUS50_JSON)
    if not path.exists():
        raise ValueError(f"unambiguous50 dataset file missing: {path} (set UNAMBIGUOUS50_JSON?)")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [
        {
            "id": e["id"],
            "nl": e["nl"],
            "formula": e["formula"],
            "ap_map": e.get("ap_map"),
            "source": e["tier"],  # tier → domain column (see docstring)
        }
        for e in data["entries"]
    ]


def load_external_rows(dataset: str, config: PendulumConfig) -> list[dict[str, Any]]:
    if dataset not in EXTERNAL_DATASETS:
        raise ValueError(f"unknown external dataset {dataset!r}; expected one of {EXTERNAL_DATASETS}")
    if dataset == "unambiguous50":
        raw = unambiguous50_raw(config)
    elif dataset == "vltl_bench":
        vltl_bench, _ = _import_adapters()
        root = config.get_path("VLTL_BENCH_ROOT", _DATASETS_DIR / "VLTL-Bench")
        raw = vltl_bench.all_benchmark(root)
    else:
        _, synthtl = _import_adapters()
        json_path = config.get_path(
            "SYNTHTL_JSON",
            _DATASETS_DIR / "synthTL" / "metadata" / "ambaworker_llm-3_translations.json",
        )
        raw = synthtl.pairs(json_path)
    if not raw:
        raise ValueError(f"{dataset}: adapter returned no rows — is the checkout present?")
    return adapt_rows(raw, dataset)
