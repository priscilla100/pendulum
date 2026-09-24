"""Render pipeline data as prompt-ready text blocks (tables, lists)."""

from __future__ import annotations

import json
from typing import Iterable, Optional, Sequence

from pendulum.schemas import APMapping, Candidate, VerificationResult


def ap_block(aps: Sequence[APMapping]) -> str:
    """`name = meaning` lines, mirroring the dataset's activity format."""
    if not aps:
        return "(none)"
    return "\n".join(f"  {m.ap} = {m.nl_fragment}" for m in aps)


def ap_json(aps: Sequence[APMapping]) -> str:
    """{name: fragment} JSON for prompts that consume a mapping object."""
    return json.dumps({m.ap: m.nl_fragment for m in aps}, ensure_ascii=False)


def _fmt_conf(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def candidate_table(
    candidates: Sequence[Candidate],
    verifications: Iterable[VerificationResult] = (),
) -> str:
    """Prior verdicts (feedback round 2) appear as an extra column so the
    filter model knows which candidates already failed verification."""
    if not candidates:
        return "(none)"
    verdicts: dict[str, list[str]] = {}
    for v in verifications:
        verdicts.setdefault(v.candidate_id, []).append(f"{v.agent}={v.verdict}")
    lines = ["id | formula | source | confidence | prior verdicts | rationale"]
    for c in candidates:
        rationale = c.rationale.replace("\n", " ")[:160]
        prior = ", ".join(verdicts.get(c.id, [])) or "-"
        lines.append(
            f"{c.id} | {c.canonical} | {c.source_agent} | {_fmt_conf(c.confidence)} | {prior} | {rationale}"
        )
    return "\n".join(lines)


def verification_table(
    candidates: Sequence[Candidate], verifications: Iterable[VerificationResult]
) -> str:
    by_candidate: dict[str, list[VerificationResult]] = {}
    for v in verifications:
        by_candidate.setdefault(v.candidate_id, []).append(v)
    blocks = []
    for c in candidates:
        blocks.append(
            f"candidate {c.id}: {c.canonical}\n"
            f"  source={c.source_agent} confidence={_fmt_conf(c.confidence)}"
        )
        for v in sorted(by_candidate.get(c.id, []), key=lambda v: v.agent):
            evidence = v.evidence.replace("\n", " ")[:400]
            blocks.append(f"  [{v.agent}] {v.verdict} (conf={_fmt_conf(v.confidence)}): {evidence}")
        if c.id not in by_candidate:
            blocks.append("  (no verification results)")
    return "\n".join(blocks) if blocks else "(none)"


def lattice_block(
    equiv_groups: Sequence[Sequence[str]], stronger: Sequence[tuple[str, str]]
) -> str:
    """compare_candidates relations as compact prompt lines:
    'a ≡ b (merged)' per equivalence class, 'c ⇒ d (strictly stronger)'."""
    lines = [" ≡ ".join(group) + " (merged)" for group in equiv_groups]
    lines += [f"{a} ⇒ {b} (strictly stronger)" for a, b in stronger]
    return "\n".join(lines) if lines else "no equivalences or strict orderings found"


def numbered(items: Sequence[str]) -> str:
    return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items)) or "(none)"
