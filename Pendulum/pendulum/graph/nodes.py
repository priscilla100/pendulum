"""Graph nodes and routing functions.

Each node is a thin async wrapper: pull inputs out of state, call one agent,
return a minimal state update (only keys this node owns — parallel branches
writing a shared key must go through a reducer channel). Nodes are created as
closures over `PendulumDeps` by `make_nodes(deps)`; `graph/build.py` wires
them. All nodes are wrapped in node_guard by the builder.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pendulum.agents.ap_extractor import extract_aps
from pendulum.agents.deterministic_verifier import verify_deterministic
from pendulum.agents.dwyer_to_ltl import synthesize_dwyer
from pendulum.agents.fuzzy_verifier import verify_fuzzy
from pendulum.agents.oneshot_to_ltl import synthesize_oneshot
from pendulum.agents.orchestrator import filter_candidates, finalize
from pendulum.agents.python_to_ltl import synthesize_python
from pendulum.agents.salt_to_ltl import synthesize_salt
from pendulum.deps import PendulumDeps
from pendulum.prompt_loader import render
from pendulum.schemas import AgentError, APMapping, Candidate, FinalOutput, VerificationResult

State = dict[str, Any]


def _aps(state: State) -> list[APMapping]:
    result = state.get("ap_result")
    return result.ap_nl_mapping_list if result else []


def _feedback_text(state: State) -> str:
    if state.get("feedback_round", 0) > 0 and state.get("feedback_evidence"):
        return render("feedback_round_addendum", FAILURE_EVIDENCE=state["feedback_evidence"])
    return ""


def _synth_update(envelope, stage: str) -> State:
    update: State = {"candidates": envelope.payload or []}
    if not envelope.ok:
        update["errors"] = [AgentError(stage=stage, agent=stage, message=envelope.message)]
    return update


def make_nodes(deps: PendulumDeps) -> dict[str, Any]:
    config = deps.config

    async def extract_aps_node(state: State) -> State:
        if state.get("ap_result") is not None:
            # Caller supplied a preset mapping (e.g. the eval harness using
            # the dataset's pre-defined atoms): extraction is skipped.
            deps.logger.info("extract", "preset_aps_used",
                             atoms=[m.ap for m in state["ap_result"].ap_nl_mapping_list])
            return {}
        result = await extract_aps(state["nl_input"], deps)
        return {"ap_result": result, "ap_source": "extractor"}

    async def ap_fallback_node(state: State) -> State:
        prior = state.get("ap_result")
        reason = prior.message if prior and prior.status == "ERROR" else (
            f"confidence {prior.confidence} below threshold {config.ap_confidence_threshold}"
            if prior else "extractor produced nothing"
        )
        result = await extract_aps(state["nl_input"], deps, fallback=True, failure_reason=reason)
        return {"ap_result": result, "ap_source": "orchestrator_fallback"}

    async def synth_python_node(state: State) -> State:
        env = await synthesize_python(state["nl_input"], _aps(state), deps,
                                      feedback=_feedback_text(state),
                                      round_=state.get("feedback_round", 0))
        return _synth_update(env, "synth_python")

    async def synth_dwyer_node(state: State) -> State:
        env = await synthesize_dwyer(state["nl_input"], _aps(state), deps,
                                     feedback=_feedback_text(state),
                                     round_=state.get("feedback_round", 0))
        return _synth_update(env, "synth_dwyer")

    async def synth_salt_node(state: State) -> State:
        env = await synthesize_salt(state["nl_input"], _aps(state), deps,
                                    feedback=_feedback_text(state),
                                    round_=state.get("feedback_round", 0))
        return _synth_update(env, "synth_salt")

    async def synth_oneshot_node(state: State) -> State:
        env = await synthesize_oneshot(state["nl_input"], _aps(state), deps,
                                       feedback=_feedback_text(state),
                                       round_=state.get("feedback_round", 0))
        return _synth_update(env, "synth_oneshot")

    async def filter_node(state: State) -> State:
        candidates: list[Candidate] = state.get("candidates", [])
        if not candidates:
            return {"filtered": [], "filter_reasoning": "no candidates to filter"}
        kept, reasoning = await filter_candidates(
            state["nl_input"], _aps(state), candidates, deps,
            verifications=state.get("verifications", []),
        )
        return {"filtered": kept, "filter_reasoning": reasoning}

    async def verify_candidate_node(payload: State) -> State:
        """Send target: payload = {candidate, others, nl_input, ap_result}."""
        candidate: Candidate = payload["candidate"]
        others: list[Candidate] = payload["others"]
        nl = payload["nl_input"]
        aps = payload["ap_result"].ap_nl_mapping_list if payload.get("ap_result") else []
        coros = [("fuzzy", verify_fuzzy(nl, aps, candidate, deps))]
        if config.det_verify_enabled:
            coros.append(("deterministic", verify_deterministic(nl, aps, candidate, others, deps)))
        results = await asyncio.gather(
            *(c for _, c in coros),
            return_exceptions=True,  # one verifier crashing must not cancel the other
        )
        verifications = []
        for (agent_name, _), result in zip(coros, results):
            if isinstance(result, BaseException):
                deps.logger.error("verify", "verifier_crashed", agent=agent_name,
                                  candidate=candidate.id, error=str(result))
                result = VerificationResult(
                    candidate_id=candidate.id, agent=agent_name, verdict="ERROR",
                    evidence=f"verifier crashed: {result}",
                )
            verifications.append(result)
        return {"verifications": verifications}

    async def verify_all_node(state: State) -> State:
        """Contrastive mode (PENDULUM_CONTRASTIVE_JUDGE): ONE judge call over
        the whole filtered row instead of a Send per candidate. On feedback
        rounds the full set is re-judged together (the round-2 evidence set
        differs, and the call is single anyway); the append-only verifications
        channel keeps both rounds' verdicts, which assess and the orchestrator
        table handle naturally."""
        from pendulum.agents.fuzzy_verifier import verify_row_contrastive

        candidates: list[Candidate] = state.get("filtered", [])
        nl = state["nl_input"]
        aps = _aps(state)
        verifications = await verify_row_contrastive(nl, aps, candidates, deps)
        if config.det_verify_enabled:
            det_results = await asyncio.gather(
                *(verify_deterministic(nl, aps, c, [o for o in candidates if o.id != c.id], deps)
                  for c in candidates),
                return_exceptions=True,
            )
            for c, result in zip(candidates, det_results):
                if isinstance(result, BaseException):
                    deps.logger.error("verify", "verifier_crashed", agent="deterministic",
                                      candidate=c.id, error=str(result))
                    result = VerificationResult(
                        candidate_id=c.id, agent="deterministic", verdict="ERROR",
                        evidence=f"verifier crashed: {result}",
                    )
                verifications.append(result)
        return {"verifications": verifications}

    async def assess_node(state: State) -> State:
        """The feedback-loop decision: pure code, no LLM, no tools.

        Loop back to synthesis iff EVERY filtered candidate failed
        verification (no SUPPORTS verdict) and the round budget allows.
        The explicit `assess_decision` key is what the router reads —
        stale feedback_evidence from a prior round can never re-trigger."""
        filtered: list[Candidate] = state.get("filtered", [])
        verifications: list[VerificationResult] = state.get("verifications", [])
        supported = {v.candidate_id for v in verifications if v.verdict == "SUPPORTS"}
        all_failed = bool(filtered) and not any(c.id in supported for c in filtered)
        round_ = state.get("feedback_round", 0)
        if all_failed and config.feedback_loop and round_ < config.feedback_max_rounds:
            canonical_by_id = {c.id: c.canonical for c in filtered}
            evidence = "\n".join(
                f"- {v.candidate_id} `{canonical_by_id.get(v.candidate_id, '?')}` "
                f"[{v.agent}] {v.verdict}: {v.evidence[:200]}"
                for v in verifications
            )
            deps.logger.info("assess", "feedback_round_triggered", round=round_ + 1)
            return {
                "assess_decision": "loop",
                "feedback_round": round_ + 1,
                "feedback_evidence": evidence,
            }
        return {"assess_decision": "finalize"}

    async def finalize_node(state: State) -> State:
        ap_result = state.get("ap_result")
        if ap_result is None or ap_result.status == "ERROR":
            message = ap_result.message if ap_result else "atomic-proposition extraction produced nothing"
            return {"final": FinalOutput(
                status="ERROR",
                message=f"atomic-proposition extraction failed: {message}",
                run_id=state.get("run_id", ""),
            )}
        candidates = state.get("filtered", [])
        # Recompute the compare_candidates lattice for the finalize prompt
        # when the option is on: idempotent (filter already merged) and free
        # (deterministic tool cache); avoids threading text through state.
        from pendulum.agents.orchestrator import compare_lattice

        candidates, lattice_text = await compare_lattice(candidates, deps)
        final = await finalize(
            state["nl_input"], _aps(state), candidates,
            state.get("verifications", []), deps,
            lattice_text=lattice_text,
        )
        final.run_id = state.get("run_id", "")
        return {"final": final}

    return {
        "extract_aps": extract_aps_node,
        "ap_fallback": ap_fallback_node,
        "synth_python": synth_python_node,
        "synth_dwyer": synth_dwyer_node,
        "synth_salt": synth_salt_node,
        "synth_oneshot": synth_oneshot_node,
        "filter_candidates": filter_node,
        "verify_candidate": verify_candidate_node,
        "verify_all": verify_all_node,
        "assess": assess_node,
        "finalize": finalize_node,
    }


# -- routing functions (pure, no I/O) ---------------------------------------


def route_after_extract(state: State, *, threshold: float) -> str:
    result = state.get("ap_result")
    if result is None or result.status == "ERROR":
        return "ap_fallback"
    if result.confidence is not None and result.confidence < threshold:
        return "ap_fallback"
    return "fanout"


def route_after_fallback(state: State) -> str:
    result = state.get("ap_result")
    if result is None or result.status == "ERROR":
        return "finalize"  # finalize short-circuits with an honest ERROR
    return "fanout"


def route_after_filter(state: State, *, contrastive: bool = False):
    """Contrastive mode: one verify_all node for the row. Legacy: one Send
    per filtered candidate not yet verified."""
    from langgraph.types import Send

    filtered: list[Candidate] = state.get("filtered", [])
    if not filtered:
        return "finalize"
    if contrastive:
        return "verify_all"
    already = {v.candidate_id for v in state.get("verifications", [])}
    to_verify = [c for c in filtered if c.id not in already]
    if not to_verify:
        return "assess"
    return [
        Send("verify_candidate", {
            "candidate": c,
            "others": [o for o in filtered if o.id != c.id],
            "nl_input": state["nl_input"],
            "ap_result": state.get("ap_result"),
        })
        for c in to_verify
    ]


def route_after_assess(state: State) -> str:
    return "resynthesize" if state.get("assess_decision") == "loop" else "finalize"
