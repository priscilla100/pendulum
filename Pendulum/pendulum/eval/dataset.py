"""Dataset loading + syntactic scoring, ported from ../scripts/eval_dataset.py.

Ported (not imported) because that script lives outside any package; the
logic is kept identical so scores are comparable with the previous agentic
system's eval runs. Pure stdlib.
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from pendulum.config import REPO_ROOT

DEFAULT_DATASET = REPO_ROOT / "test_inputs_ground_truth.txt"
# Honor the same override the rest of the system uses — a misconfigured
# parser path must not silently degrade every verdict to *_parses.
PARSER_BIN = Path(os.environ.get("PLTL_PARSER_BIN") or REPO_ROOT / "ocaml" / "_build" / "default" / "main.exe")


def parse_dataset(path: Path = DEFAULT_DATASET) -> list[dict]:
    """Parse the ground-truth TSV. Returns one dict per row."""
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def extract_atoms_from_formula(formula: str) -> set[str]:
    """Atom names in a formula: lowercase identifiers minus the constants."""
    tokens = re.findall(r"\b[a-z][a-z0-9_]*\b", formula)
    return {t for t in tokens if t not in ("true", "false")}


def parse_activity_ap_map(activity: str) -> dict[str, str]:
    """Best-effort parse of the activity prose (`letter = meaning, ...`)."""
    out: dict[str, str] = {}
    for m in re.finditer(r"\b([a-z])\s*=\s*([^,;\n]+?)(?=[,;\n]|\s+[A-Z]|$)", activity):
        letter, meaning = m.group(1), m.group(2).strip().rstrip(".")
        if letter not in out:  # first match wins
            out[letter] = meaning
    return out


def ocaml_canonicalize(formula: str, timeout: float = 5.0) -> Optional[str]:
    """Canonical pretty-printed form via the OCaml parser; None on failure."""
    if not formula or not PARSER_BIN.exists():
        return None
    try:
        r = subprocess.run([str(PARSER_BIN), formula], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()
    try:
        ast_idx = lines.index("AST:")
    except ValueError:
        return None
    collected = []
    for line in lines[ast_idx + 1 :]:
        if not line.strip() or line.startswith("Success"):
            break
        collected.append(line)
    return " ".join(collected).strip() or None


def score(predicted: Optional[str], ground_truth: str) -> str:
    """Syntactic verdict, identical semantics to the previous harness:
    exact | mismatch | parse_only_gt | parse_only_pred | neither_parses."""
    gt_canonical = ocaml_canonicalize(ground_truth)
    pred_canonical = ocaml_canonicalize(predicted) if predicted else None
    if gt_canonical and pred_canonical:
        return "exact" if gt_canonical == pred_canonical else "mismatch"
    if gt_canonical:
        return "parse_only_gt"
    if pred_canonical:
        return "parse_only_pred"
    return "neither_parses"
