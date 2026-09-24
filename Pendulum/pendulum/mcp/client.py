"""PendulumMCP: the one gateway to the pltl-mcp stdio tool server.

Responsibilities:
- spawn `pltl-mcp --tools ... --transport stdio` with the env contract the
  parent repo requires (absolute PLTL_PARSER_BIN, helper-LLM coordinates,
  BLACK_BIN), inheriting the parent environment so PATH lookups still work;
- give fixed-workflow code typed async methods instead of raw JSON dicts;
- LRU-cache results of deterministic tools only (user requirement — see
  toolsets.is_cacheable); hits are logged at debug level;
- survive one server death per run: a failed call triggers one
  restart-and-retry before the error surfaces (as McpError).

PydanticAI agents (deterministic verifier, orchestrator) get a *filtered
toolset view* over the same live connection via `black_toolset()`.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import OrderedDict
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from mcp.shared.exceptions import McpError as _ProtocolError
from pydantic_ai.mcp import MCPToolset, StdioTransport, ToolError as _ToolError

from pendulum.config import PendulumConfig
from pendulum.logging_setup import RunLogger
from pendulum.mcp.toolsets import ALL_TOOLS, BLACK_TOOLS, is_cacheable
from pendulum.schemas import LtlToNlResult, ParseResult, SaltResult


def _pendulum_trace_tool(tool: str, args: Any, response: Any, cached: bool = False) -> None:
    """PRINT-ONLY debug trace (no logic change). When PENDULUM_TRACE=<file> is set,
    append one JSON record per tool call so the original can be diffed 3-way against
    the ports (same flag + format as the ports' support.trace())."""
    path = os.environ.get("PENDULUM_TRACE")
    if not path:
        return
    rec: dict[str, Any] = {"kind": "tool", "tool": tool, "args": args, "response": response}
    if cached:
        rec["cached"] = True
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — tracing must never break a run
        pass


class McpError(Exception):
    """A tool call failed even after one server restart."""


class McpToolError(McpError):
    """The SERVER rejected the call (e.g. invalid_params: unparseable formula).

    Deliberate: this does not trigger a restart — the server is fine, the
    arguments are not. Synthesis/verification loops catch this to feed the
    server's message (parser or compiler output) back to their LLM.
    """

    def __init__(self, tool: str, server_message: str):
        super().__init__(f"{tool}: {server_message}")
        self.tool = tool
        self.server_message = server_message


class PendulumMCP:
    def __init__(self, config: PendulumConfig, logger: RunLogger):
        self._config = config
        self._log = logger
        self._toolset: Optional[MCPToolset] = None
        self._cache: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self._cache_enabled = config.tool_cache_enabled
        self._cache_size = config.tool_cache_size
        # Restart coordination: parallel graph branches share this client, so
        # a restart must drain in-flight direct calls before swapping the
        # toolset, and calls arriving mid-restart must wait for the new one.
        # (PydanticAI toolset views bypass this gate; a restart only ever
        # happens when the transport is already dead, in which case their
        # in-flight calls were failing anyway and surface as ERROR verdicts.)
        self._cond = asyncio.Condition()
        self._inflight = 0
        self._restarting = False

    # -- lifecycle ---------------------------------------------------------

    def _build_toolset(self) -> MCPToolset:
        cfg = self._config
        env = {
            **os.environ,
            "PLTL_PARSER_BIN": str(cfg.pltl_parser_bin),
            "PLTL_TOOL_LLM_BASE_URL": cfg.tool_llm_base_url,
            "PLTL_TOOL_LLM_MODEL": cfg.tool_llm_model,
            "RUST_LOG": "warn",
        }
        if cfg.black_bin:
            env["BLACK_BIN"] = cfg.black_bin
        transport = StdioTransport(
            command=str(cfg.mcp_server_bin),
            args=["--tools", ",".join(sorted(ALL_TOOLS)), "--transport", "stdio"],
            env=env,
        )
        return MCPToolset(transport, id="pltl")

    async def __aenter__(self) -> "PendulumMCP":
        self._toolset = self._build_toolset()
        await self._toolset.__aenter__()
        self._log.debug("mcp", "server_started", bin=str(self._config.mcp_server_bin))
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._toolset is not None:
            await self._toolset.__aexit__(*exc_info)
            self._toolset = None

    async def _begin_call(self) -> None:
        async with self._cond:
            while self._restarting:
                await self._cond.wait()
            self._inflight += 1

    async def _end_call(self) -> None:
        async with self._cond:
            self._inflight -= 1
            self._cond.notify_all()

    async def _restart(self) -> None:
        async with self._cond:
            if self._restarting:
                # Another failing call is already restarting; wait for it.
                while self._restarting:
                    await self._cond.wait()
                return
            self._restarting = True
            while self._inflight > 0:
                await self._cond.wait()
        try:
            self._log.warning("mcp", "server_restarting")
            if self._toolset is not None:
                try:
                    await self._toolset.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001 — the old process may already be dead
                    pass
            self._toolset = self._build_toolset()
            await self._toolset.__aenter__()
        finally:
            async with self._cond:
                self._restarting = False
                self._cond.notify_all()

    # -- calling -----------------------------------------------------------

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        """Call any tool by name; returns the tool's JSON payload (parsed)."""
        if self._toolset is None:
            raise McpError("PendulumMCP used outside 'async with' context")

        key = (tool, json.dumps(args, sort_keys=True, ensure_ascii=False))
        use_cache = self._cache_enabled and is_cacheable(tool, args)
        if use_cache and key in self._cache:
            self._cache.move_to_end(key)
            self._log.debug("mcp", "cache_hit", tool=tool, args=args)
            _pendulum_trace_tool(tool, args, self._cache[key], cached=True)  # print-only
            return self._cache[key]
        # trace instrumentation (user request): the call itself, with arguments
        self._log.debug("mcp", "tool_call", tool=tool, args=args)

        try:
            await self._begin_call()
            try:
                raw = await self._toolset.direct_call_tool(tool, args)
            finally:
                await self._end_call()
        except (_ProtocolError, _ToolError) as exc:
            # Server answered with an error: bad arguments, not a dead server.
            message = getattr(getattr(exc, "error", None), "message", None) or str(exc)
            self._log.debug("mcp", "tool_error", tool=tool, error=message)
            raise McpToolError(tool, message) from exc
        except Exception as first_exc:  # noqa: BLE001 — transport-level failure
            self._log.warning("mcp", "call_failed_retrying", tool=tool, error=str(first_exc))
            try:
                await self._restart()
                await self._begin_call()
                try:
                    raw = await self._toolset.direct_call_tool(tool, args)
                finally:
                    await self._end_call()
            except (_ProtocolError, _ToolError) as exc:
                message = getattr(getattr(exc, "error", None), "message", None) or str(exc)
                raise McpToolError(tool, message) from exc
            except Exception as second_exc:  # noqa: BLE001
                raise McpError(
                    f"{tool} failed after restart: {second_exc} (first failure: {first_exc})"
                ) from second_exc

        result = _normalize(raw)
        self._log.debug("mcp", "tool_result", tool=tool, result=result)
        _pendulum_trace_tool(tool, args, result)  # print-only
        if use_cache:
            self._cache[key] = result
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    # -- typed wrappers (the calls fixed-workflow code makes constantly) ----

    async def parse_and_canonicalize(self, formula: str) -> ParseResult:
        data = await self.call("parse_and_canonicalize", {"formula": formula})
        return _validated(ParseResult, data, "parse_and_canonicalize")

    async def nl_to_ltl_via_salt(self, spec: str) -> SaltResult:
        data = await self.call("nl_to_ltl_via_salt", {"spec": spec})
        return _validated(SaltResult, data, "nl_to_ltl_via_salt")

    async def ltl_to_nl(self, formula: str) -> LtlToNlResult:
        data = await self.call("ltl_to_nl", {"formula": formula})
        return _validated(LtlToNlResult, data, "ltl_to_nl")

    async def salt_help(self) -> str:
        data = await self.call("salt_help", {})
        return _as_dict(data).get("reference", "")

    # -- toolset views for PydanticAI agents --------------------------------

    def black_toolset(self):
        """The 8 BLACK solver tools, as a PydanticAI toolset (live connection)."""
        if self._toolset is None:
            raise McpError("PendulumMCP used outside 'async with' context")
        return self._toolset.filtered(lambda ctx, tool_def: tool_def.name in BLACK_TOOLS)


def _normalize(raw: Any) -> Any:
    """pltl-mcp encodes its payload as JSON text inside the MCP content block;
    depending on the client version we may see that string, an already-parsed
    dict, or a content-block list. Normalize to parsed JSON."""
    if isinstance(raw, dict) or isinstance(raw, list) and not _looks_like_content(raw):
        return raw
    if _looks_like_content(raw):
        raw = raw[0].get("text", "") if isinstance(raw[0], dict) else getattr(raw[0], "text", "")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def _looks_like_content(raw: Any) -> bool:
    if not isinstance(raw, list) or not raw:
        return False
    first = raw[0]
    return (isinstance(first, dict) and "text" in first) or hasattr(first, "text")


def _as_dict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise McpError(f"expected a JSON object from tool, got {type(data).__name__}: {data!r:.200}")
    return data


def _validated(model_cls: type[BaseModel], data: Any, tool: str):
    """Shape errors surface as McpError so every caller's degradation path
    (which catches McpError) applies to malformed server payloads too."""
    try:
        return model_cls.model_validate(_as_dict(data))
    except ValidationError as exc:
        raise McpError(f"{tool} returned a malformed payload: {exc}") from exc
