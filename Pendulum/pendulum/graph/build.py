"""Assemble and compile the Pendulum StateGraph.

Topology (fixed workflow — control flow lives HERE, not in any LLM):

    START → extract_aps ──(ok)──────────────► {synth_python, synth_dwyer, synth_salt}
                └─(error/low conf)→ ap_fallback ──(ok)──┘         (parallel)
                                        └─(error)→ finalize
    {all three} ──barrier──► filter_candidates
    filter_candidates ──Send per unverified candidate──► verify_candidate
                └─(nothing to verify)→ finalize / assess
    verify_candidate ──(all Sends complete)──► assess
    assess ──(all failed & round budget)──► back to the three synth nodes
        └─(otherwise)──► finalize → END
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from pendulum.deps import PendulumDeps
from pendulum.graph.guard import node_guard
from pendulum.graph.nodes import (
    make_nodes,
    route_after_assess,
    route_after_extract,
    route_after_fallback,
    route_after_filter,
)
from pendulum.graph.state import PendulumState

def synth_nodes_for(cfg) -> list[str]:
    """The active synthesis fan-out. Dwyer is opt-in (default off since the
    forensic run showed ~0 usable yield on realistic corpora)."""
    nodes = ["synth_python", "synth_salt"]
    if cfg.dwyer_enabled:
        nodes.insert(1, "synth_dwyer")
    if cfg.oneshot_enabled:
        nodes.append("synth_oneshot")
    return nodes


def build_graph(deps: PendulumDeps):
    cfg = deps.config
    nodes = make_nodes(deps)
    active_synth = synth_nodes_for(cfg)

    verify_timeout = cfg.agent("FUZZY").timeout_s
    if cfg.det_verify_enabled:
        verify_timeout = max(verify_timeout, cfg.agent("DET").timeout_s)

    timeouts = {
        "extract_aps": cfg.agent("AP").timeout_s,
        "ap_fallback": cfg.agent("ORCH").timeout_s,
        "synth_python": cfg.agent("PYTHON").timeout_s,
        "synth_dwyer": cfg.agent("DWYER").timeout_s,
        "synth_salt": cfg.agent("SALT").timeout_s,
        "synth_oneshot": cfg.agent("ONESHOT").timeout_s,
        "filter_candidates": cfg.agent("ORCH").timeout_s,
        "verify_candidate": verify_timeout + 30,
        # contrastive: evidence gathering (traces/lattice/paraphrases) + one judge call
        "verify_all": verify_timeout + 60,
        "assess": 10.0,  # pure code
        "finalize": cfg.agent("ORCH").timeout_s,
    }

    graph: StateGraph = StateGraph(PendulumState)
    for name, fn in nodes.items():
        if name.startswith("synth_") and name not in active_synth:
            continue  # disabled synthesis agent: node not added at all
        graph.add_node(name, node_guard(name, timeouts[name], deps.logger)(fn))

    graph.add_edge(START, "extract_aps")

    def extract_router(state):
        target = route_after_extract(state, threshold=cfg.ap_confidence_threshold)
        return active_synth if target == "fanout" else target

    def fallback_router(state):
        target = route_after_fallback(state)
        return active_synth if target == "fanout" else target

    def assess_router(state):
        target = route_after_assess(state)
        return active_synth if target == "resynthesize" else target

    graph.add_conditional_edges("extract_aps", extract_router, ["ap_fallback", *active_synth])
    graph.add_conditional_edges("ap_fallback", fallback_router, ["finalize", *active_synth])
    graph.add_edge(active_synth, "filter_candidates")  # barrier join
    def filter_router(state):
        return route_after_filter(state, contrastive=cfg.contrastive_judge)

    graph.add_conditional_edges(
        "filter_candidates", filter_router,
        ["finalize", "assess", "verify_candidate", "verify_all"],
    )
    graph.add_edge("verify_candidate", "assess")
    graph.add_edge("verify_all", "assess")
    graph.add_conditional_edges("assess", assess_router, ["finalize", *active_synth])
    graph.add_edge("finalize", END)

    return graph.compile()
