"""ATOMIC_PROPOSITION_EXTRACTOR — and its orchestrator-model fallback.

One structured LLM completion (no tools): NL in, {aps, open_questions} out,
LNLL confidence from the completion's logprobs. Returns the task.md envelope
`APExtractionResult` directly; never raises. The fallback variant is the SAME
prompt (task.md requirement) run on the orchestrator's model, with a preamble
explaining the escalation.
"""

from __future__ import annotations

import time
from typing import Any

from pendulum.agents.llm_json import json_completion_with_retry
from pendulum.agents.parsing import ATOM_NAME_RE, ExtractionError
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError
from pendulum.prompt_loader import load, render
from pendulum.schemas import APExtractionResult, APMapping


def _validate_payload(parsed: dict[str, Any]) -> tuple[list[APMapping], list[str]]:
    aps = parsed.get("aps")
    if not isinstance(aps, list) or not aps:
        raise ExtractionError('"aps" must be a non-empty array of atom objects')
    mappings: list[APMapping] = []
    seen: set[str] = set()
    for i, entry in enumerate(aps):
        if not isinstance(entry, dict):
            raise ExtractionError(f'"aps"[{i}] must be an object')
        name = entry.get("name", "")
        fragment = entry.get("nl_fragment", "")
        if not isinstance(name, str) or not ATOM_NAME_RE.match(name):
            raise ExtractionError(
                f'"aps"[{i}].name {name!r} must match [a-z][a-z0-9_]* (lowercase, no dashes)'
            )
        if name in seen:
            raise ExtractionError(f"duplicate atom name {name!r} — merge or rename")
        seen.add(name)
        if not isinstance(fragment, str) or not fragment.strip():
            raise ExtractionError(f'"aps"[{i}].nl_fragment must be a non-empty string')
        polarity = entry.get("polarity")
        mappings.append(APMapping(
            ap=name,
            nl_fragment=fragment.strip(),
            polarity=polarity if polarity in ("event", "state") else None,
        ))
    questions = parsed.get("open_questions", [])
    if not isinstance(questions, list):
        raise ExtractionError('"open_questions" must be an array of strings')
    return mappings, [str(q) for q in questions]


async def extract_aps(
    nl: str,
    deps: PendulumDeps,
    *,
    fallback: bool = False,
    failure_reason: str = "",
) -> APExtractionResult:
    agent_name = "ap_fallback" if fallback else "ap_extractor"
    cfg = deps.agent_cfg("ORCH" if fallback else "AP")
    system = load("ap_extractor_system")
    if fallback:
        system = render("ap_fallback_preamble", FAILURE_REASON=failure_reason or "unspecified") + system
    user = render("ap_extractor_user", NATURAL_LANGUAGE=nl)

    started = time.monotonic()
    try:
        (mappings, questions), lnll, attempts = await json_completion_with_retry(
            deps.router, cfg, system, user,
            validate=_validate_payload, logger=deps.logger, stage=agent_name,
        )
    except (ExtractionError, LlmError) as exc:
        deps.logger.error(agent_name, "extraction_failed", error=str(exc))
        return APExtractionResult(status="ERROR", message=str(exc))

    deps.logger.info(
        agent_name, "aps_extracted",
        atoms=[m.ap for m in mappings], confidence=lnll, attempts=attempts,
        open_questions=questions, elapsed_s=round(time.monotonic() - started, 2),
    )
    message = ""
    if questions:
        message = "open questions: " + " | ".join(questions)
    return APExtractionResult(
        status="OK", message=message, ap_nl_mapping_list=mappings, confidence=lnll
    )
