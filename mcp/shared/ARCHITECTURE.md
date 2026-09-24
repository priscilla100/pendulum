# `pltl_mcp_shared` — Shared infrastructure for PLTL MCP servers

## What lives here

```
mcp/shared/
├── src/
│   ├── lib.rs        — public surface + module docs
│   ├── parse.rs      — formula-string → Formula via OCaml binary
│   ├── error.rs      — SharedError (used by every server)
│   ├── cache.rs      — AnalysisCache<K, V> (LRU, env-driven capacity)
│   ├── transport.rs  — clap-parsed TransportConfig + Transport enum
│   └── server.rs     — generic run<H, F>(config, factory) → ()
```

The per-analysis crates (`mcp/<name>/`) depend on this one for *all*
cross-cutting concerns. They contribute exactly: a `ServerHandler` type,
a factory closure, and any tool-specific input schemas.

## Wire-format contract

The OCaml parser's JSON shape is the cross-language contract. We do not
own it here — we deserialise it via `pltl_rust::Formula`. Touching
variant names or operator codes means changing `ocaml/ast.ml` and
`rust/src/ast.rs` *in lockstep*; this crate is downstream of both.

## Transport story

This crate is the **shared** infrastructure (parser glue, cache,
transport runtime). The user-facing CLI flag names live in the
**consumer** binaries:

| Binary                  | User-facing flag        | Shared `Transport` variant |
| ----------------------- | ----------------------- | -------------------------- |
| `pltl-mcp` (Phase B+)   | `--transport stdio\|sse`| `Transport::Stdio` / `Http`|
| `pltl-agent-mcp` (agent-as-MCP-server stub)        | `--transport stdio\|http`| same                      |

The agent-as-MCP-server stub uses `--transport http`; the
parameterized `pltl-mcp` server uses `--transport sse` per
BUILD_PLAN §3. Both map to this crate's `Transport::Http` and
ultimately to rmcp 1.7's `transport-streamable-http-server` feature.

### Why two names

The MCP spec calls the network transport "Streamable HTTP" since
2025-11. BUILD_PLAN §3 keeps the historical `sse` flag name on
`pltl-mcp` for continuity. Internally rmcp 1.7 maps both to the same
implementation:

| Transport            | rmcp feature                            | Status               |
| -------------------- | --------------------------------------- | -------------------- |
| stdio                | `transport-io`                          | first-class          |
| Streamable HTTP      | `transport-streamable-http-server`      | first-class          |
| SSE (server side)    | —                                       | **removed in 1.x**   |
| SSE (client side)    | `client-side-sse`                       | legacy compat only   |

If you need true SSE compatibility — say, to talk to an existing SSE
server that hasn't migrated — drop in `rmcp-actix-web` or write a
thin wrapper around rmcp's `sse-stream` optional dep behind a new
`transport-sse` feature.

## Cache invalidation policy

`AnalysisCache::should_cache(temperature, seed)` is the single chokepoint
for deciding whether to insert. The rule, summarised:

- Deterministic analysis (`temperature == None`) → always cache.
- LLM-backed analysis with `temperature == 0.0` and `seed == Some(_)` →
  cache.
- Anything else → skip the cache (results aren't reproducible).

Per-server wrappers MUST call this; bypassing it pollutes the cache
with non-replayable answers and turns the "deterministic with seed"
promise into a lie.

## Adding a new analysis (cookbook)

1. Add `pub mod <name>;` under `rust/src/analysis/mod.rs` and an
   analysis function over `&Formula`. Unit-test it.
2. Create `mcp/<name>/` (Cargo.toml, src/main.rs, tests/smoke.rs).
3. In `main.rs`: parse `TransportConfig` via clap, build a handler
   that uses `pltl_mcp_shared::parse` and the analysis function, call
   `pltl_mcp_shared::server::run(config, || Ok(MyHandler::new()))`.
4. Add the crate as a workspace member in the top-level `Cargo.toml`.
5. (Server-side Dockerfile lives once at `mcp/server/Dockerfile` —
   the parameterized binary handles every tool, no per-tool image.)
6. Register the server in `mcp/docker-compose.yml` (both profiles).
7. Register the tool in `agent/config.toml` so the LLM sees it.
