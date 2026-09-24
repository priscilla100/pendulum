"""PYTHON_TO_LTL — synthesis via the code-completion trick.

A coding model completes `formulaToFind = <constructor expression>` lines
against a dataclass AST (prompt adapted from the parent repo's
nl_to_ltl_via_python tool). Deterministic scaffolding around it:

    completion → extract assignment lines → safe AST eval → parser gate
    → grammar-constrained confidence emission → Candidate

Any failure in that chain becomes model-facing feedback for the bounded retry
loop (SYNTH_PARSE_MAX_RETRIES). PYTHON_AGENT_MODE=mcp delegates the middle to
the parent repo's MCP tool instead (helper-LLM based, no retry conversation).
"""

from __future__ import annotations

import time

from pendulum.agents.emission import CandidateInvalid, make_candidate
from pendulum.agents.envelope import AgentEnvelope, error_envelope, ok_envelope
from pendulum.agents.formatting import ap_json
from pendulum.agents.parsing import ExtractionError, extract_assignment_lines
from pendulum.agents.python_ast_eval import PythonAstError, eval_formula_expr
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError, Message
from pendulum.mcp.client import McpError
from pendulum.prompt_loader import load, render
from pendulum.schemas import APMapping, Candidate


async def synthesize_python(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str = "", round_: int = 0
) -> AgentEnvelope[list[Candidate]]:
    started = time.monotonic()
    try:
        if deps.config.python_agent_mode == "mcp":
            envelope = await _via_mcp_tool(nl, aps, deps, round_)
        else:
            envelope = await _direct(nl, aps, deps, feedback, round_)
    except (LlmError, McpError) as exc:
        deps.logger.error("synth_python", "failed", error=str(exc))
        envelope = error_envelope(str(exc))
    envelope.elapsed_s = round(time.monotonic() - started, 2)
    return envelope


async def _direct(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str, round_: int
) -> AgentEnvelope[list[Candidate]]:
    cfg = deps.agent_cfg("PYTHON")
    max_candidates = deps.config.synth_max_candidates
    allowed = {m.ap for m in aps}
    user = render("python_to_ltl_user", NATURAL_LANGUAGE=nl, ATOMIC_PROPOSITIONS=ap_json(aps))
    if feedback:
        user = feedback + "\n" + user
    system_prompt = ("python_to_ltl_system_semantics"
                     if deps.config.python_semantics_prompt else "python_to_ltl_system")
    messages: list[Message] = [
        {"role": "system", "content": render(system_prompt, MAX_CANDIDATES=str(max_candidates))},
        {"role": "user", "content": user},
    ]

    counter = 0
    attempts = deps.config.synth_parse_max_retries + 1
    for attempt in range(1, attempts + 1):
        result = await deps.router.complete(cfg, messages, want_logprobs=False)
        deps.logger.debug("synth_python", "completion", attempt=attempt, text=result.text)

        candidates: list[Candidate] = []
        failures: list[str] = []
        try:
            lines = extract_assignment_lines(result.text)[:max_candidates]
        except ExtractionError as exc:
            lines, failures = [], [str(exc)]

        for line in lines:
            try:
                formula = eval_formula_expr(line, allowed)
                counter += 1
                candidates.append(await make_candidate(
                    deps, source_agent="python", formula=formula,
                    rationale=f"Python AST completion: formulaToFind = {line}",
                    index=counter, attempts=attempt, round_=round_,
                ))
            except (PythonAstError, CandidateInvalid) as exc:
                failures.append(f"`{line}`: {exc}")

        if candidates:
            if failures:
                deps.logger.warning("synth_python", "partial_failures", failures=failures)
            deps.logger.info(
                "synth_python", "candidates",
                formulas=[c.canonical for c in candidates], attempt=attempt,
            )
            return ok_envelope(candidates, attempts=attempt)

        deps.logger.warning("synth_python", "all_lines_failed_retrying", attempt=attempt, failures=failures)
        messages.append({"role": "assistant", "content": result.text})
        messages.append({
            "role": "user",
            "content": render("python_to_ltl_retry", FAILURE="\n".join(failures)),
        })

    return error_envelope(f"no valid candidate after {attempts} attempts", attempts=attempts)


async def _via_mcp_tool(
    nl: str, aps: list[APMapping], deps: PendulumDeps, round_: int
) -> AgentEnvelope[list[Candidate]]:
    payload = await deps.mcp.call(
        "nl_to_ltl_via_python", {"text": nl, "aps": {m.ap: m.nl_fragment for m in aps}}
    )
    if not isinstance(payload, dict) or not payload.get("ok") or not payload.get("formula"):
        return error_envelope(f"nl_to_ltl_via_python tool failed: {payload.get('error') if isinstance(payload, dict) else payload!r}")
    try:
        candidate = await make_candidate(
            deps, source_agent="python", formula=str(payload["formula"]),
            rationale=f"nl_to_ltl_via_python tool (raw: {payload.get('raw_python', '')})",
            index=1, round_=round_,
        )
    except CandidateInvalid as exc:
        return error_envelope(f"tool returned unparseable formula: {exc}")
    return ok_envelope([candidate])
