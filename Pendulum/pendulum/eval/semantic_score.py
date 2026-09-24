"""Semantic scoring: any-rank BLACK equivalence over harness CSVs.

Implements the success criterion for `python -m pendulum score`: a row is a
SUCCESS when the ground truth is logically equivalent (per the BLACK-backed
`check_equivalence` tool) to ANY of the ranked output formulas — not just the
top-1 `predicted_formula`.

Reads a CSV produced by pendulum.eval.harness, appends four columns to every
row (all original columns are preserved verbatim):

- ``any_equivalent``   "true"/"false" — some candidate is equivalent to GT
- ``equivalent_rank``  1-based rank of the first equivalent candidate ("" if none)
- ``n_checked``        candidates examined (parse gate + equivalence) before stopping
- ``gt_parses``        "true"/"false" — the ground-truth formula itself parses

One PendulumMCP session is shared across all rows; the deterministic tool
cache makes repeated parses/equivalence checks cheap.
"""

from __future__ import annotations

import csv
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pendulum.config import PendulumConfig
from pendulum.mcp.client import McpError, McpToolError

CANDIDATE_SEP = " | "
NEW_COLUMNS = ["any_equivalent", "equivalent_rank", "n_checked", "gt_parses"]


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def default_out_path(in_path: Path) -> Path:
    """`foo.csv` -> `foo_scored.csv` (suffix-agnostic for non-.csv inputs)."""
    if in_path.suffix:
        return in_path.with_name(in_path.stem + "_scored" + in_path.suffix)
    return in_path.with_name(in_path.name + "_scored")


def candidates_for_row(row: dict) -> list[str]:
    """Ranked candidate formulas for one row.

    `all_formulas` is authoritative. Current harnesses write it as a JSON
    array (a " | " join collides with the disjunction operator in canonicals
    like "p | q" — codex audit finding). Legacy CSVs fall back to the old
    delimiter split; rows lacking the column entirely fall back to the
    top-1 `predicted_formula`.
    """
    if "all_formulas" in row:
        raw = row.get("all_formulas") or ""
        if not raw.strip():
            return []
        if raw.lstrip().startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(c).strip() for c in parsed if str(c).strip()]
            except ValueError:
                pass  # not JSON after all — fall through to legacy split
        return [c.strip() for c in raw.split(CANDIDATE_SEP) if c.strip()]
    predicted = (row.get("predicted_formula") or "").strip()
    return [predicted] if predicted else []


@dataclass
class RowScore:
    any_equivalent: bool = False
    equivalent_rank: Optional[int] = None
    n_checked: int = 0
    gt_parses: bool = True

    def as_columns(self) -> dict[str, str]:
        return {
            "any_equivalent": "true" if self.any_equivalent else "false",
            "equivalent_rank": str(self.equivalent_rank) if self.equivalent_rank else "",
            "n_checked": str(self.n_checked),
            "gt_parses": "true" if self.gt_parses else "false",
        }


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


async def score_row(mcp: Any, gt: str, candidates: list[str]) -> RowScore:
    """Check candidates in rank order against `gt`, stopping at the first
    equivalent one. Unparseable candidates are skipped (but counted in
    n_checked); an unparseable ground truth fails the whole row."""
    score = RowScore()

    try:
        gt_parse = await mcp.parse_and_canonicalize(gt)
        gt_valid = gt_parse.valid
    except (McpToolError, McpError) as exc:
        _warn(f"ground truth parse check failed ({exc}); treating GT as unparseable")
        gt_valid = False
    if not gt_valid:
        score.gt_parses = False
        return score

    for rank, candidate in enumerate(candidates, start=1):
        score.n_checked = rank
        try:
            parsed = await mcp.parse_and_canonicalize(candidate)
        except (McpToolError, McpError) as exc:
            _warn(f"parse check failed for candidate rank {rank} ({exc}); skipping")
            continue
        if not parsed.valid:
            continue  # candidate verdict: parse_error — later ranks still checked

        try:
            payload = await mcp.call("check_equivalence", {"f1": gt, "f2": candidate})
        except McpToolError as exc:
            # The candidate already passed the parse gate, so a server-side
            # rejection means the GT side did not parse: whole-row parse_gt.
            _warn(f"check_equivalence rejected the ground truth ({exc})")
            score.gt_parses = False
            score.any_equivalent = False
            score.equivalent_rank = None
            return score
        except McpError as exc:  # BLACK / transport failure on this one check
            _warn(f"check_equivalence failed at rank {rank} ({exc}); treating as not equivalent")
            continue

        if isinstance(payload, dict) and payload.get("equivalent"):
            score.any_equivalent = True
            score.equivalent_rank = rank
            return score

    return score


async def score_file(
    in_path: Path,
    out_path: Path,
    config: Optional[PendulumConfig] = None,
    *,
    mcp: Any = None,
) -> int:
    """Score every row of `in_path` and write `out_path` with the four extra
    columns. Raises FileNotFoundError / ValueError on fatal I/O problems
    (missing input, malformed header, out == in). `mcp` may be a pre-built
    client (tests); when absent a real PendulumMCP session is opened once for
    the whole file."""
    in_path, out_path = Path(in_path), Path(out_path)
    if not in_path.exists():
        raise FileNotFoundError(f"input CSV not found: {in_path}")
    if out_path.resolve() == in_path.resolve():
        raise ValueError(f"refusing to overwrite the input CSV: pass a different --out ({in_path})")

    with open(in_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames or "ground_truth_formula" not in fieldnames or not (
            "all_formulas" in fieldnames or "predicted_formula" in fieldnames
        ):
            raise ValueError(
                f"{in_path} is not a harness CSV: header must contain "
                f"'ground_truth_formula' and 'all_formulas' (or 'predicted_formula'); "
                f"got {fieldnames}"
            )
        rows = list(reader)

    out_fields = [c for c in fieldnames if c not in NEW_COLUMNS] + NEW_COLUMNS

    async with AsyncExitStack() as stack:
        if mcp is None:
            from pendulum.logging_setup import RunLogger
            from pendulum.mcp.client import PendulumMCP

            config = config or PendulumConfig.from_env()
            logger = RunLogger(config.log_dir, level=config.log_level)
            mcp = await stack.enter_async_context(PendulumMCP(config, logger))

        successes = top1 = 0
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                gt = (row.get("ground_truth_formula") or "").strip()
                score = await score_row(mcp, gt, candidates_for_row(row))
                successes += score.any_equivalent
                top1 += score.equivalent_rank == 1
                writer.writerow({**row, **score.as_columns()})
                f.flush()

    total = len(rows)
    rate = f"{successes / total:.1%}" if total else "n/a"
    print(f"scored {total} rows -> {out_path}")
    print(f"any-rank equivalent (SUCCESS): {successes}/{total} ({rate})")
    print(f"top-1 equivalent (comparison): {top1}/{total}")
    return 0
