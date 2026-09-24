"""End-to-end evaluation: run the pipeline over ground-truth rows, score, CSV.

CSV columns are a superset of the previous harness's
(`row_idx, formula_id, depth, domain, model, condition, translation,
ground_truth_formula, predicted_formula, score, iterations, failure_reason,
elapsed_sec, session_id`) so existing tooling — including
../scripts/score_semantic.py for BLACK-based semantic verdicts — works on the
output unchanged. Pendulum extras: `all_formulas` (every ranked output,
|-joined) and `top_k_exact` (rank of the first exact match, if any).

Resumable: rows whose formula_id already appears in the output CSV are
skipped, mirroring the previous harness's convention.
"""

from __future__ import annotations

import csv
import json
import random
import time
from pathlib import Path
from typing import Optional

from pendulum.config import REPO_ROOT, PendulumConfig
from pendulum.eval.dataset import (
    DEFAULT_DATASET,
    extract_atoms_from_formula,
    ocaml_canonicalize,
    parse_activity_ap_map,
    parse_dataset,
    score,
)
from pendulum.schemas import APMapping

CSV_FIELDS = [
    "row_idx", "formula_id", "translation_id", "depth", "domain", "model", "condition",
    "translation", "ground_truth_formula", "predicted_formula", "score",
    "iterations", "failure_reason", "elapsed_sec", "session_id",
    "all_formulas", "n_formulas", "top_k_exact",
]


def encode_all_formulas(formulas: list[str]) -> str:
    """JSON array encoding for the all_formulas CSV cell — a ' | ' join would
    collide with the disjunction operator inside canonicals like 'p | q'."""
    return json.dumps(formulas, ensure_ascii=False)


def row_key(row: dict) -> tuple[str, str]:
    """Stable row identity: formula_id alone is NOT unique in the dataset
    (e.g. 27601 appears twice with different translations)."""
    return (row.get("formula_id", ""), row.get("translation_id", ""))


def select_rows(
    rows: list[dict],
    *,
    sample_size: int,
    max_depth: Optional[int],
    seed: int,
    formula_ids: Optional[list[str]],
) -> list[dict]:
    if formula_ids:
        wanted = set(formula_ids)
        selected = [r for r in rows if r.get("formula_id") in wanted]
        missing = wanted - {r.get("formula_id") for r in selected}
        if missing:
            raise ValueError(f"formula_ids not found in dataset: {sorted(missing)}")
        return selected
    if max_depth is not None:
        rows = [r for r in rows if r.get("depth") and int(r["depth"]) <= max_depth]
    rng = random.Random(seed)
    return rng.sample(rows, min(sample_size, len(rows)))


def preset_aps_for_row(row: dict) -> list[APMapping]:
    """The datasets pre-define the atoms; mirror the previous harness by
    handing the pipeline exactly those (extraction skipped). External rows
    carry an explicit `_ap_map`; the internal TSV encodes it as activity
    prose."""
    atoms = sorted(extract_atoms_from_formula(row["formula_canonical_form"]))
    ap_map = row.get("_ap_map") or parse_activity_ap_map(row.get("activity", ""))
    return [
        APMapping(ap=a, nl_fragment=ap_map.get(a, f"the proposition `{a}`"))
        for a in atoms
    ]


def load_done_keys(out_path: Path) -> set[tuple[str, str]]:
    """Resume keys from an existing CSV; fails fast on a header mismatch so
    we never append rows misaligned with an older schema."""
    if not out_path.exists() or out_path.stat().st_size == 0:
        return set()
    with open(out_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(
                f"{out_path} has a different column schema than this harness "
                f"writes — refusing to append. Move it aside or pass a new --out.\n"
                f"  file:     {reader.fieldnames}\n  expected: {CSV_FIELDS}"
            )
        return {row_key(r) for r in reader}


def _session_limited(final, config) -> bool:
    """True when this row's run tripped a CLI session/usage limit: the token
    appears in the final message or anywhere in the run's JSONL log (agent
    envelopes and judge evidence both stringify SessionLimitError)."""
    from pendulum.llm.cli_backends import SESSION_LIMIT_TOKEN

    if SESSION_LIMIT_TOKEN in (final.message or ""):
        return True
    try:
        log_path = config.log_dir / f"{final.run_id}.jsonl"
        return SESSION_LIMIT_TOKEN in log_path.read_text(encoding="utf-8")
    except OSError:
        return False


async def run_eval(
    *,
    input_path: Optional[str],
    sample_size: int,
    max_depth: Optional[int],
    seed: int,
    formula_ids: Optional[list[str]],
    out_path: Optional[str],
    dataset: str = "gt",
) -> int:
    from pendulum.pipeline import translate  # late import: heavy deps

    config = PendulumConfig.from_env()
    if dataset == "gt":
        dataset_path = Path(input_path) if input_path else DEFAULT_DATASET
        rows = parse_dataset(dataset_path)
    else:
        from pendulum.eval.external import load_external_rows

        dataset_path = Path(dataset)  # display only
        rows = load_external_rows(dataset, config)
    out = Path(out_path) if out_path else REPO_ROOT / "eval_results" / f"pendulum_{dataset}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    for idx, row in enumerate(rows):  # preserve the original dataset position
        row["_dataset_idx"] = idx
    selected = select_rows(rows, sample_size=sample_size, max_depth=max_depth,
                           seed=seed, formula_ids=formula_ids)
    done = load_done_keys(out)
    todo = [r for r in selected if row_key(r) not in done]
    print(f"dataset={dataset_path.name} selected={len(selected)} "
          f"already_done={len(selected) - len(todo)} to_run={len(todo)} -> {out}")

    needs_header = not out.exists() or out.stat().st_size == 0
    exact_top1 = exact_topk = 0
    completed = 0

    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if needs_header:
            writer.writeheader()
        for i, row in enumerate(todo):
            fid = row["formula_id"]
            gt = row["formula_canonical_form"]
            nl = row["translation"]
            print(f"[{i + 1}/{len(todo)}] formula_id={fid} depth={row.get('depth')}")
            started = time.monotonic()
            final = await translate(nl, config=config, preset_aps=preset_aps_for_row(row))
            elapsed = round(time.monotonic() - started, 1)

            if _session_limited(final, config):
                print(f"SESSION LIMIT during {fid}: row NOT recorded; aborting "
                      f"eval (exit 4) so a resume can re-run it cleanly.")
                return 4

            formulas = [rf.canonical for rf in final.formulas]
            predicted = formulas[0] if formulas else None
            verdict = score(predicted, gt)
            gt_canonical = ocaml_canonicalize(gt)
            top_k_exact = ""
            for rank, formula in enumerate(formulas, start=1):
                if ocaml_canonicalize(formula) == gt_canonical and gt_canonical:
                    top_k_exact = str(rank)
                    break

            writer.writerow({
                "row_idx": row["_dataset_idx"],
                "formula_id": fid,
                "translation_id": row.get("translation_id", ""),
                "depth": row.get("depth", ""),
                "domain": row.get("domain", ""),
                "model": "pendulum",
                "condition": "pendulum",
                "translation": nl,
                "ground_truth_formula": gt,
                "predicted_formula": predicted or "",
                "score": verdict,
                # deliberately blank: this pipeline has no single loop count;
                # ranked-output size lives in n_formulas instead
                "iterations": "",
                "failure_reason": final.message if final.status == "ERROR" else "",
                "elapsed_sec": elapsed,
                "session_id": final.run_id,
                "all_formulas": encode_all_formulas(formulas),
                "n_formulas": len(final.formulas),
                "top_k_exact": top_k_exact,
            })
            f.flush()
            completed += 1
            exact_top1 += verdict == "exact"
            exact_topk += bool(top_k_exact)
            print(f"    -> {verdict} (top_k_exact={top_k_exact or '-'}) in {elapsed}s "
                  f"status={final.status}")

    if completed:
        print(f"\ncompleted {completed} rows: top-1 exact {exact_top1}/{completed}, "
              f"any-rank exact {exact_topk}/{completed}")
        print("semantic scoring: ../scripts/score_semantic.py --in", out)
    return 0
