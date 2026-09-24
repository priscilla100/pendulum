"""PendulumDeps: everything agents and graph nodes need, in one container.

Nodes receive this via LangGraph's configurable channel; tests build one from
fakes (see tests/conftest.py). No module-level singletons anywhere — the
container is constructed once per run in pipeline.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from pendulum.config import AgentConfig, PendulumConfig
from pendulum.logging_setup import RunLogger

if TYPE_CHECKING:  # imports for type hints only — keeps import graph acyclic
    from pendulum.llm.router import CompletionRouter
    from pendulum.mcp.client import PendulumMCP
    from pendulum.rag.embedder import OllamaEmbedder
    from pendulum.rag.init import RagStores


@dataclass
class PendulumDeps:
    config: PendulumConfig
    logger: RunLogger
    router: "CompletionRouter"
    mcp: "PendulumMCP"
    embedder: Optional["OllamaEmbedder"] = None
    rag: Optional["RagStores"] = None
    # Test hook: when set, PydanticAI agents use this model instead of the
    # configured one (pydantic_ai TestModel / FunctionModel).
    test_model: object = None

    def agent_cfg(self, prefix: str) -> AgentConfig:
        return self.config.agent(prefix)
