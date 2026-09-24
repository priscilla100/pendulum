"""CompletionRouter: one entry point for every non-PydanticAI LLM call.

Routing policy (the hybrid-backend fork decided by the user):

- `need_grammar=True` → llama-server with the GBNF grammar and logprobs,
  IF enabled and healthy (health probe cached for LLAMACPP_HEALTH_TTL_S).
  Otherwise degrade: the agent's own Ollama backend, no grammar, and the
  caller's validate-and-retry loop becomes the shape enforcement. The
  degradation is logged at warning level; confidence is whatever the fallback
  yields (usually None).
- `need_grammar=False` → the agent's configured backend (Ollama), with
  logprobs requested opportunistically when the caller wants confidence.

A llama-server failure mid-run (not just at startup) is caught per call and
falls back the same way — a dying optional service never kills a run.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from pendulum.config import AgentConfig, PendulumConfig
from pendulum.llm.base import CompletionResult, LlmError, Message
from pendulum.llm.llamacpp import LlamaCppClient
from pendulum.llm.ollama import OllamaClient
from pendulum.logging_setup import RunLogger


class CompletionRouter:
    def __init__(
        self,
        config: PendulumConfig,
        ollama: OllamaClient,
        llamacpp: Optional[LlamaCppClient],
        logger: RunLogger,
        ollama_factory: Callable[[str], OllamaClient] = OllamaClient,
    ):
        """`ollama` serves the default base URL; agents configured with a
        different <PREFIX>_BASE_URL get a client from `ollama_factory`,
        cached per URL."""
        self._config = config
        self._ollama = ollama
        self._ollama_factory = ollama_factory
        self._ollama_by_url: dict[str, OllamaClient] = {ollama.base_url: ollama}
        self._llamacpp = llamacpp if config.llamacpp_enabled else None
        self._log = logger
        self._grammar_text: Optional[str] = None
        self._health_ok = False
        self._health_checked_at = 0.0
        self._cli_clients: dict[str, object] = {}

    def _ollama_for(self, base_url: str) -> OllamaClient:
        normalized = base_url.rstrip("/").removesuffix("/v1")
        client = self._ollama_by_url.get(normalized)
        if client is None:
            client = self._ollama_factory(normalized)
            self._ollama_by_url[normalized] = client
        return client

    async def aclose(self) -> None:
        """Close every Ollama client this router owns (including ones created
        on demand for per-agent base URLs)."""
        for client in {id(c): c for c in self._ollama_by_url.values()}.values():
            await client.aclose()

    async def grammar_available(self) -> bool:
        """Can a need_grammar call actually be served constrained right now?
        Callers use this to skip pointless confidence-emission calls."""
        return self._llamacpp is not None and await self._llamacpp_healthy()

    def _cli_client(self, backend: str):
        """Lazy per-backend non-Ollama client (claude-cli / codex-cli / gemini-api)."""
        client = self._cli_clients.get(backend)
        if client is None:
            if backend == "claude-cli":
                from pendulum.llm.cli_backends import ClaudeCliClient

                client = ClaudeCliClient(self._config.claude_cli_bin)
            elif backend == "gemini-api":
                from pendulum.llm.gemini_api import GeminiApiClient

                client = GeminiApiClient()
            else:
                from pendulum.llm.cli_backends import CodexCliClient

                client = CodexCliClient(self._config.codex_cli_bin)
            self._cli_clients[backend] = client
        return client

    async def complete(
        self,
        agent_cfg: AgentConfig,
        messages: list[Message],
        *,
        need_grammar: bool = False,
        want_logprobs: bool = False,
        max_tokens: int = 2048,
        response_schema: dict | None = None,
    ) -> CompletionResult:
        if agent_cfg.backend != "ollama" and not need_grammar:
            # CLI backends (Claude Code / Codex): subprocess per completion.
            # No logprobs (lnll None), no GBNF; schema enforced best-effort
            # by the client via prompt + caller retry loops.
            result = await self._cli_client(agent_cfg.backend).complete(
                messages,
                model=agent_cfg.model,
                temperature=agent_cfg.temperature,
                max_tokens=max_tokens,
                timeout_s=agent_cfg.timeout_s,
                response_schema=response_schema,
            )
            self._log.debug("llm", "completion", agent=agent_cfg.name,
                            backend=result.backend, lnll=None, chars=len(result.text))
            return result
        if need_grammar and self._llamacpp is not None and await self._llamacpp_healthy():
            try:
                return await self._llamacpp.complete(
                    messages,
                    model=agent_cfg.model,  # informational; llama-server is single-model
                    temperature=agent_cfg.temperature,
                    max_tokens=max_tokens,
                    timeout_s=agent_cfg.timeout_s,
                    grammar=self._grammar(),
                    want_logprobs=True,
                )
            except LlmError as exc:
                # Invalidate the health cache entirely so the next call
                # re-probes (a recovered server gets picked up again).
                self._health_ok = False
                self._health_checked_at = 0.0
                self._log.warning(
                    "llm", "llamacpp_call_failed_falling_back",
                    agent=agent_cfg.name, error=str(exc),
                )
        elif need_grammar:
            self._log.warning(
                "llm", "grammar_unavailable_falling_back",
                agent=agent_cfg.name,
                reason="disabled" if self._llamacpp is None else "unhealthy",
            )

        result = await self._ollama_for(agent_cfg.base_url).complete(
            messages,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            num_ctx=agent_cfg.num_ctx,
            max_tokens=max_tokens,
            timeout_s=agent_cfg.timeout_s,
            want_logprobs=want_logprobs,
            thinking=agent_cfg.thinking,
            response_schema=response_schema,
        )
        self._log.debug(
            "llm", "completion",
            agent=agent_cfg.name, backend=result.backend, model=agent_cfg.model,
            lnll=result.lnll, chars=len(result.text),
        )
        return result

    def _grammar(self) -> str:
        if self._grammar_text is None:
            path = self._config.grammar_file
            try:
                self._grammar_text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise LlmError(f"cannot read grammar file {path}: {exc}") from exc
        return self._grammar_text

    async def _llamacpp_healthy(self) -> bool:
        now = time.monotonic()
        if now - self._health_checked_at < self._config.llamacpp_health_ttl_s:
            return self._health_ok
        assert self._llamacpp is not None
        self._health_ok = await self._llamacpp.is_healthy()
        self._health_checked_at = now
        if not self._health_ok:
            self._log.warning("llm", "llamacpp_unhealthy", base_url=self._llamacpp.base_url)
        return self._health_ok
