"""Recursive Dwyer decomposition (user-approved 2026-07-04, bounded depth 2).

Invoked by the Dwyer agent when the FLAT match reports "nothing fits":
1. one split completion chooses an OUTER catalogue entry and assigns each of
   its placeholders either a boolean atoms-expression or a SUB-REQUIREMENT
   text fragment (see prompts/dwyer_split_*.md);
2. each sub-fragment is flat-matched against the catalogue on its own
   retrieval (depth 2 — sub-fragments never decompose further);
3. composition is CODE-SIDE: instantiated sub-formulas are substituted into
   the outer template token-safely; the result passes the usual parser gate
   and confidence emission via make_candidate.

Every failure path returns [] — decomposition is a recall extension, never a
new failure mode; the other synthesis agents still cover the row.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pendulum.agents.emission import CandidateInvalid, make_candidate
from pendulum.agents.formatting import ap_block
from pendulum.agents.llm_json import json_completion_with_retry
from pendulum.agents.parsing import ExtractionError
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError
from pendulum.prompt_loader import render
from pendulum.schemas import APMapping, Candidate

_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_]*\b")
_ATOMS_VALUE_RE = re.compile(r"^[a-z0-9_!&|()<>\-\s]+$")


async def try_decompose(
    nl: str,
    aps: list[APMapping],
    deps: PendulumDeps,
    by_id: dict[str, dict[str, Any]],
    render_hits_text: str,
    *,
    round_: int,
) -> list[Candidate]:
    """One decomposition attempt. Returns [] on any failure (logged)."""
    cfg = deps.agent_cfg("DWYER")
    allowed = {m.ap for m in aps}

    def validate(parsed: dict[str, Any]) -> Optional[dict[str, Any]]:
        outer_id = parsed.get("outer_pattern_id")
        if outer_id is None:
            return None  # model says: not decomposable
        if outer_id not in by_id:
            raise ExtractionError(
                f'"outer_pattern_id" {outer_id!r} is not a retrieved entry: {", ".join(by_id)}'
            )
        entry = by_id[outer_id]
        assignments = parsed.get("assignments")
        if not isinstance(assignments, dict) or set(assignments) != set(entry["placeholders"]):
            raise ExtractionError(
                f'"assignments" keys must be exactly {sorted(entry["placeholders"])}'
            )
        subs = 0
        for ph, a in assignments.items():
            if not isinstance(a, dict) or a.get("type") not in ("atoms", "sub"):
                raise ExtractionError(f'assignment {ph!r} needs "type": "atoms" | "sub"')
            if a["type"] == "atoms":
                value = str(a.get("value", "")).strip()
                if not value or not _ATOMS_VALUE_RE.match(value):
                    raise ExtractionError(f"{ph!r}: atoms value may use only atoms and ! & | -> <-> ( )")
                for token in _TOKEN_RE.findall(value):
                    if token not in allowed and token not in ("true", "false"):
                        raise ExtractionError(f"{ph!r}: unknown atom {token!r}; allowed: {sorted(allowed)}")
            else:
                if not str(a.get("text", "")).strip():
                    raise ExtractionError(f'{ph!r}: "sub" assignment needs non-empty "text"')
                subs += 1
        if subs == 0:
            raise ExtractionError(
                "no sub-requirement assigned — a decomposition without any sub is just a flat "
                "match; use at least one \"sub\" or output outer_pattern_id null"
            )
        return parsed

    try:
        split, _, _ = await json_completion_with_retry(
            deps.router, cfg,
            render("dwyer_split_system"),
            render("dwyer_split_user", NATURAL_LANGUAGE=nl,
                   ATOMIC_PROPOSITIONS=ap_block(aps), RETRIEVED_PATTERNS=render_hits_text),
            validate=validate, logger=deps.logger, stage="dwyer_split", want_logprobs=False,
        )
    except (ExtractionError, LlmError) as exc:
        deps.logger.info("dwyer_split", "decomposition_failed", error=str(exc))
        return []
    if split is None:
        deps.logger.info("dwyer_split", "not_decomposable")
        return []

    entry = by_id[split["outer_pattern_id"]]
    values: dict[str, str] = {}
    sub_notes: list[str] = []
    for ph, a in split["assignments"].items():
        if a["type"] == "atoms":
            values[ph] = str(a["value"]).strip()
            continue
        fragment = str(a["text"]).strip()
        sub_formula = await _flat_match_fragment(fragment, aps, deps)
        if sub_formula is None:
            deps.logger.info("dwyer_split", "sub_match_failed", placeholder=ph, fragment=fragment)
            return []
        values[ph] = sub_formula
        sub_notes.append(f"{ph} := {sub_formula} (from: {fragment!r})")

    formula = _TOKEN_RE.sub(
        lambda m: f"({values[m.group()]})" if m.group() in values else m.group(),
        entry["ltl_template"],
    )
    try:
        candidate = await make_candidate(
            deps, source_agent="dwyer", formula=formula,
            rationale=(
                f"Dwyer RECURSIVE: outer {entry['pattern']} ({entry['scope']}); "
                f"{'; '.join(sub_notes)}; note={split.get('note', '')}"
            ),
            index=1, round_=round_,
        )
    except CandidateInvalid as exc:
        deps.logger.info("dwyer_split", "composed_formula_invalid", formula=formula, error=str(exc))
        return []
    deps.logger.info("dwyer_split", "recursive_candidate", formula=candidate.canonical)
    return [candidate]


async def _flat_match_fragment(
    fragment: str, aps: list[APMapping], deps: PendulumDeps
) -> Optional[str]:
    """Depth-2 leaf: flat pattern match for one sub-requirement fragment,
    returning the instantiated formula string (parser gate happens on the
    composed whole). No further decomposition."""
    from pendulum.agents.dwyer_to_ltl import _instantiate, _render_hits

    assert deps.rag is not None and deps.embedder is not None  # caller checked
    query_vec = await deps.embedder.embed_one(fragment)
    hits = deps.rag.dwyer.search(query_vec, deps.config.rag_top_k)
    if not hits:
        return None
    by_id = {h.chunk.metadata["id"]: h.chunk.metadata for h in hits}
    allowed = {m.ap for m in aps}

    def validate(parsed: dict[str, Any]) -> Optional[str]:
        selections = parsed.get("selections")
        if not isinstance(selections, list):
            raise ExtractionError('"selections" must be an array (possibly empty)')
        for sel in selections:
            if not isinstance(sel, dict) or sel.get("pattern_id") not in by_id:
                continue
            try:
                return _instantiate(by_id[sel["pattern_id"]], sel.get("substitution") or {}, allowed)
            except ValueError:
                continue
        return None  # nothing usable — treated as a failed sub-match, not a retry

    try:
        formula, _, _ = await json_completion_with_retry(
            deps.router, deps.agent_cfg("DWYER"),
            render("dwyer_system", MAX_CANDIDATES="1"),
            render("dwyer_user", NATURAL_LANGUAGE=fragment,
                   ATOMIC_PROPOSITIONS=ap_block(aps), RETRIEVED_PATTERNS=_render_hits(hits)),
            validate=validate, logger=deps.logger, stage="dwyer_sub", want_logprobs=False,
        )
        return formula
    except (ExtractionError, LlmError) as exc:
        deps.logger.info("dwyer_sub", "fragment_match_failed", fragment=fragment, error=str(exc))
        return None
