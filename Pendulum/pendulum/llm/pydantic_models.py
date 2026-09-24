"""Factory for PydanticAI model objects (deterministic verifier, orchestrator).

Only the two genuinely agentic nodes use PydanticAI; everything
confidence-bearing goes through CompletionRouter instead (PydanticAI does not
expose token logprobs — that asymmetry is a deliberate design decision, see
llm/lnll.py and the README).
"""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from pendulum.config import AgentConfig


def build_chat_model(agent_cfg: AgentConfig) -> OpenAIChatModel:
    """OpenAI-compatible chat model pointed at the agent's configured server.

    Works for Ollama's /v1 endpoint and any other OpenAI-compatible server
    (e.g. ds4-server). `num_ctx` cannot be conveyed over the OpenAI protocol;
    Ollama uses its model default on this path (documented in .env.example).
    """
    base_url = agent_cfg.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    provider = OpenAIProvider(base_url=base_url, api_key=agent_cfg.api_key)
    settings = ModelSettings(temperature=agent_cfg.temperature, timeout=agent_cfg.timeout_s)
    return OpenAIChatModel(agent_cfg.model, provider=provider, settings=settings)
