//! Transport selection: stdio vs Streamable HTTP.
//!
//! The two transports rmcp 1.7 supports server-side are stdio
//! (`transport-io`) and Streamable HTTP (`transport-streamable-http-server`).
//! Each MCP server binary is built with both features so a single
//! image can run in either mode without recompilation.
//!
//! ## Note on naming
//!
//! As of rmcp 1.7 there is no `transport-sse-server` feature; only
//! `client-side-sse` exists, for talking to legacy SSE servers. The
//! MCP 2025-11 spec replaced SSE with Streamable HTTP for new network
//! deployments, so we expose `--transport http` rather than
//! `--transport sse`. If a future rmcp release brings back an
//! SSE-server module, plumb it through here.

use clap::{Parser, ValueEnum};

/// CLI args shared by every MCP-server binary.
///
/// Each per-analysis crate composes this into its own [`clap::Parser`]
/// so individual servers can add extra flags (logging, cache capacity
/// override, etc.) without redefining the transport surface.
#[derive(Debug, Clone, Parser)]
pub struct TransportConfig {
    /// Which MCP transport to serve over.
    #[arg(long, value_enum, default_value_t = Transport::Stdio, env = "MCP_TRANSPORT")]
    pub transport: Transport,

    /// Bind address when `--transport http` (ignored for stdio).
    ///
    /// Defaults to `0.0.0.0:8000` so the binary works in a container
    /// without extra args. Locally, override with `--bind 127.0.0.1:8000`.
    #[arg(long, default_value = "0.0.0.0:8000", env = "MCP_BIND")]
    pub bind: String,

    /// HTTP path the Streamable HTTP service is mounted at.
    ///
    /// Defaults to `/mcp` per the MCP spec. Change only if you're
    /// putting the server behind a reverse proxy that strips a prefix.
    #[arg(long, default_value = "/mcp", env = "MCP_PATH")]
    pub http_path: String,
}

/// The transport variants the MCP-server binaries support.
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum Transport {
    /// JSON-RPC over stdin/stdout; the agent launches this binary as a
    /// child process (typically `docker run -i --rm ...`).
    Stdio,
    /// MCP Streamable HTTP — long-lived HTTP server, `POST`s + SSE
    /// streaming on a single endpoint.
    Http,
}

impl Transport {
    /// Returns `true` if this binary was built with the feature for
    /// the requested transport enabled.
    ///
    /// Both features default-on, so this is mostly a guard for
    /// downstream consumers building with `--no-default-features`.
    pub const fn is_compiled_in(self) -> bool {
        match self {
            Transport::Stdio => cfg!(feature = "transport-stdio"),
            Transport::Http => cfg!(feature = "transport-http"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn cli_renders() {
        TransportConfig::command().debug_assert();
    }

    #[test]
    fn defaults_to_stdio() {
        let cfg = TransportConfig::try_parse_from(["bin"]).expect("parse");
        assert_eq!(cfg.transport, Transport::Stdio);
        assert_eq!(cfg.bind, "0.0.0.0:8000");
    }

    #[test]
    fn http_with_bind() {
        let cfg = TransportConfig::try_parse_from([
            "bin",
            "--transport",
            "http",
            "--bind",
            "127.0.0.1:9000",
        ])
        .expect("parse");
        assert_eq!(cfg.transport, Transport::Http);
        assert_eq!(cfg.bind, "127.0.0.1:9000");
    }
}
