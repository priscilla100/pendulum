"""Top-level API: translate one NL sentence through the whole fixed workflow.

Owns the run lifecycle: config + logger, LLM clients, the pltl-mcp stdio
child, RAG indexes (built if stale), graph construction, and cleanup. Returns
a FinalOutput in every case — infrastructure failures surface as
status="ERROR" with an explanatory message, never as an exception.
"""

from __future__ import annotations

from typing import Optional

from pendulum.config import PendulumConfig
from pendulum.deps import PendulumDeps
from pendulum.graph.build import build_graph
from pendulum.llm.llamacpp import LlamaCppClient
from pendulum.llm.ollama import OllamaClient
from pendulum.llm.router import CompletionRouter
from pendulum.logging_setup import RunLogger
from pendulum.mcp.client import PendulumMCP
from pendulum.rag.embedder import OllamaEmbedder
from pendulum.rag.init import ensure_rag_dbs
from pendulum.schemas import APExtractionResult, APMapping, FinalOutput


def _final_from_state(state: dict, logger: RunLogger) -> FinalOutput:
    """Safety net for a finalize-node timeout/crash: the graph guarantees an
    honest FinalOutput, so rank the surviving candidates deterministically
    from whatever verification evidence exists rather than reporting nothing.
    (Observed in production: a 300s finalize timeout on deep formulas.)"""
    from pendulum.agents.orchestrator import _deterministic_ranking, _latest_verifications

    candidates = state.get("filtered") or []
    ap_result = state.get("ap_result")
    aps = ap_result.ap_nl_mapping_list if ap_result else []
    if not candidates:
        return FinalOutput(
            status="ERROR",
            message="finalize stage did not complete and no candidates survived",
            ap_mapping=aps, run_id=logger.run_id,
        )
    logger.warning("pipeline", "finalize_missing_deterministic_fallback",
                   candidates=[c.id for c in candidates])
    final = _deterministic_ranking(
        candidates, _latest_verifications(state.get("verifications", [])), aps,
        max_out=5, note="finalize stage timed out or crashed",
    )
    final.run_id = logger.run_id
    return final


async def translate(
    nl: str,
    config: Optional[PendulumConfig] = None,
    run_id: Optional[str] = None,
    preset_aps: Optional[list[APMapping]] = None,
) -> FinalOutput:
    """`preset_aps` short-circuits the AP-extraction stage with a known
    mapping (the eval harness uses the dataset's pre-defined atoms, matching
    how the previous agentic system was evaluated)."""
    config = config or PendulumConfig.from_env()
    logger = RunLogger(config.log_dir, level=config.log_level, run_id=run_id)
    logger.info("pipeline", "run_started", nl=nl, preset_aps=bool(preset_aps))

    ollama = OllamaClient(config.get_str("PENDULUM_DEFAULT_BASE_URL", "http://localhost:11434/v1"))
    llamacpp = LlamaCppClient(config.llamacpp_base_url)
    router = CompletionRouter(config, ollama, llamacpp, logger)
    embed_client = OllamaClient(config.rag_embed_base_url)
    embedder = OllamaEmbedder(embed_client, config.rag_embed_model)

    try:  # one lifetime scope: every exit path below closes the HTTP clients
        try:
            rag = await ensure_rag_dbs(config, embedder, logger)
        except Exception as exc:  # noqa: BLE001 — RagError or e.g. Ollama down during embedding
            logger.error("pipeline", "rag_init_failed", error=str(exc))
            return FinalOutput(status="ERROR", message=f"RAG initialization failed: {exc}",
                               run_id=logger.run_id)

        try:
            async with PendulumMCP(config, logger) as mcp:
                deps = PendulumDeps(
                    config=config, logger=logger, router=router, mcp=mcp,
                    embedder=embedder, rag=rag,
                )
                graph = build_graph(deps)
                initial: dict = {"nl_input": nl, "run_id": logger.run_id, "feedback_round": 0}
                if preset_aps:
                    initial["ap_result"] = APExtractionResult(
                        status="OK", message="preset by caller",
                        ap_nl_mapping_list=preset_aps, confidence=None,
                    )
                    initial["ap_source"] = "preset"
                state = await graph.ainvoke(initial)
        except Exception as exc:  # noqa: BLE001 — MCP spawn failure etc.
            logger.error("pipeline", "run_crashed", error=str(exc))
            return FinalOutput(status="ERROR", message=f"pipeline failure: {exc}", run_id=logger.run_id)
    finally:
        await router.aclose()  # closes ollama + any per-agent-URL clients
        await llamacpp.aclose()
        await embed_client.aclose()

    final = state.get("final") or _final_from_state(state, logger)
    logger.info(
        "pipeline", "run_finished",
        status=final.status,
        formulas=[f.canonical for f in final.formulas],
        errors=[e.message for e in state.get("errors", [])],
        stages={t.stage: t.seconds for t in state.get("timings", [])},
    )
    return final
