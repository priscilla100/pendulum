//! Shared infrastructure for the family of PLTL analysis MCP servers.
//!
//! Each MCP server under `mcp/<analysis>/` is intentionally thin: parse
//! the input formula, run the analysis from
//! `pltl_rust::analysis::<name>`, return the result. The shared
//! cross-cutting pieces live here so every server crate gets them
//! consistently:
//!
//! * [`parse`] — shells out to the OCaml front-end and deserialises
//!   its JSON into a typed [`pltl_rust::Formula`].
//! * [`error`] — common error type used by every analysis wrapper.
//! * [`cache`] — in-process LRU cache keyed on the canonical
//!   pretty-printed form of the input.
//! * [`transport`] — CLI parsing for `--transport stdio|http` and the
//!   typed config that the per-server `main` consumes.
//! * [`server`] — runs an `rmcp` `ServerHandler` under the chosen
//!   transport; tools just plug in their handler type.
//!
//! See `ARCHITECTURE.md` next to this file for the high-level design
//! (notably: SSE was dropped in favour of Streamable HTTP, per the
//! MCP 2025-11 spec — see `transport.rs`).

#![forbid(unsafe_code)]
#![warn(missing_docs)]

pub mod cache;
pub mod error;
pub mod parse;
pub mod server;
pub mod transport;

pub use error::SharedError;
pub use parse::parse;
pub use transport::{Transport, TransportConfig};
