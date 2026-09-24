# `pltl_mcp_server` — architecture

## What this crate does

One binary, `pltl-mcp`, that registers any subset of the PLTL analysis
tools at runtime via `--tools t1,t2,...`. Packaging is a deploy
decision, not a build-time concern.

## File layout

```
mcp/server/
├── Cargo.toml
├── Dockerfile
├── ARCHITECTURE.md           — this file
├── src/
│   ├── lib.rs                — module map, crate-level docs
│   ├── main.rs               — pltl-mcp entry point
│   ├── cli.rs                — clap structs (--tools, --transport, --bind)
│   ├── tool.rs               — `Tool` trait + `ToolError`
│   ├── registry.rs           — ToolRegistry: name → Arc<dyn Tool> + cache
│   ├── server.rs             — rmcp ServerHandler delegating to the registry
│   └── tools/
│       ├── mod.rs            — `all()` catalogue (15 tools, authoritative)
│       └── <name>.rs         — one module per tool, wrapping pltl_rust::analysis::*
└── tests/smoke.rs            — stdio + sse end-to-end + cache behaviour
```

## Adding a new tool

1. Add `pub mod <name>;` to `src/tools/mod.rs` and a corresponding
   `Arc::new(<name>::<Type>::default()) as Arc<dyn Tool>` entry in
   `all()`.
2. Implement the trait in `src/tools/<name>.rs`. Standard shape:
   - `Input` struct deriving `Deserialize + JsonSchema`.
   - `Output` struct deriving `Serialize`.
   - Trait body calls into `pltl_rust::analysis::<name>`.
3. If the tool is LLM-backed, override `cache_policy()` to declare the
   tool's session-wide `(temperature, seed)`. The registry will only
   cache when `temperature == 0` and `seed.is_some()`.
4. Smoke tests in `tests/smoke.rs` if the tool warrants one beyond the
   shared transport tests.

That's it — no central match arms, no router changes.

## Transport story

Two transports, runtime-selectable:

| `--transport` | rmcp feature                              | Wire                          |
| ------------- | ----------------------------------------- | ----------------------------- |
| `stdio`       | `transport-io`                            | JSON-RPC over stdin/stdout    |
| `sse`         | `transport-streamable-http-server`        | HTTP POST + SSE event stream  |

> **Naming note.** BUILD_PLAN §3 names the network transport `sse` (a
> reference to the legacy MCP SSE transport). rmcp 1.7 dropped the
> standalone SSE server module and folded its capability into
> `transport-streamable-http-server` — what we use under the hood. The
> wire format is still HTTP POSTs with SSE-streamed responses, so
> calling the user-facing flag `sse` is accurate enough; documenting
> here so the deviation isn't a surprise.

`--transport stdio` is the default.

## CLI surface

```
pltl-mcp [OPTIONS]

Options:
  --tools <t1,t2,...>    Tool subset to register; `all` = everything.
                         Default: all
  --list-available       Print catalogue and exit
  --transport <T>        stdio (default) | sse
  --bind <addr>          SSE bind addr; default 0.0.0.0:8000
  --http-path <path>     SSE mount path; default /mcp

Environment:
  MCP_TOOLS              Same as --tools
  MCP_TRANSPORT          Same as --transport
  MCP_BIND               Same as --bind
  MCP_PATH               Same as --http-path
  MCP_CACHE_CAPACITY     Registry LRU capacity (default 1024)
  PLTL_PARSER_BIN        OCaml parser binary (required at runtime)
  RUST_LOG               tracing filter
```

## Cache layer

`ToolRegistry` owns a `pltl_mcp_shared::cache::AnalysisCache<String,
String>` keyed on `(tool_name, canonical_input_json)`. Values are
stored as JSON strings (re-parsed on hit) so the cache is generic
over output shape. Cache stats are logged on shutdown.

Cacheability gate (BUILD_PLAN §3): every `Tool` implementation
declares a `CachePolicy` via the trait. Deterministic tools (default)
always cache; LLM-backed tools must return their session-wide
`(temperature, seed)` pair, and the registry uses
`pltl_mcp_shared::cache::should_cache` to enforce the policy.

## Error mapping

`tool::ToolError` → MCP protocol error:

| `ToolError`           | MCP                | Notes                                  |
| --------------------- | ------------------ | -------------------------------------- |
| `InvalidInput(_)`     | `invalid_params`   | Schema mismatch, unknown tool name.    |
| `Analysis(_)`         | `invalid_params`   | Prefixed `tool_error:` per the agent's |
|                       |                    | best-practice item #10.                |
| `NotImplemented(_)`   | `invalid_params`   | Same prefix; identifies the stub.      |
| `Internal(_)`         | `internal_error`   | Server-side issue.                     |
