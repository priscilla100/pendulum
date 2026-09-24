//! `pltl_mcp_server` — the parameterized MCP server.
//!
//! Per BUILD_PLAN §3, the project ships **one** server binary (`pltl-mcp`)
//! whose tool list is decided at runtime via `--tools t1,t2,…`. Each
//! tool is a self-contained module implementing the [`tool::Tool`]
//! trait; the [`registry::ToolRegistry`] holds the selected subset and
//! the rmcp handler dispatches over it.
//!
//! ## Design rationale
//!
//! * **Single binary, single image.** OCaml parser is baked in once;
//!   `--tools` decides what's exposed. Container grouping is a
//!   deploy-time concern handled by compose profiles, not a build-time
//!   concern handled by 17 crates.
//! * **Tool trait, not enum.** Adding a tool is one new module + one
//!   line in `tools::all()` — no central match arms to update.
//! * **Cache lives at the registry layer.** Keyed on
//!   `(tool_name, canonical_input)`. Per-tool capacity via
//!   `MCP_CACHE_CAPACITY`. LLM-backed tools (when they land in Phase C)
//!   forward a `(temperature, seed)` pair to gate cacheability via the
//!   same policy as `pltl_mcp_shared::cache::should_cache`.
//!
//! ## Public modules
//!
//! | Module | Role |
//! | ------ | ---- |
//! | [`tool`]     | `Tool` trait, `ToolError`, `ToolCall` types |
//! | [`registry`] | `ToolRegistry` — name → handle, cache, dispatch |
//! | [`tools`]    | Concrete tool modules; `all()` returns the catalogue |
//! | [`server`]   | rmcp `ServerHandler` impl that delegates to the registry |
//! | [`cli`]      | clap structs for `pltl-mcp` |
//! | [`prompt_loader`] | Hot-swappable system-prompt loader for LLM-backed tools |

#![forbid(unsafe_code)]
#![warn(missing_docs)]

pub mod cli;
pub mod llm;
pub mod prompt_loader;
pub mod registry;
pub mod server;
pub mod tool;
pub mod tools;
