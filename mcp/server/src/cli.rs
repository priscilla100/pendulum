//! CLI for `pltl-mcp`.
//!
//! Per BUILD_PLAN §3:
//!
//! ```text
//! pltl-mcp --tools t1,t2,… --transport {stdio|sse} [--bind host:port]
//! ```
//!
//! `--tools all` registers everything. `--list-available` prints the
//! catalogue without starting the server.

use clap::{Parser, ValueEnum};

/// Transport selector. "sse" here matches the BUILD_PLAN flag name;
/// rmcp 1.7's `transport-streamable-http-server` is what actually
/// handles the HTTP + event-stream wire format (see
/// `mcp/shared/ARCHITECTURE.md`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum TransportArg {
    /// JSON-RPC over stdin / stdout.
    Stdio,
    /// MCP Streamable HTTP (label "sse" per BUILD_PLAN).
    Sse,
}

/// Top-level CLI.
#[derive(Debug, Parser)]
#[command(
    name = "pltl-mcp",
    version,
    about = "PLTL analysis MCP server. One binary, runtime-selectable tool subset."
)]
pub struct Cli {
    /// Comma-separated tool names to register. `all` registers every
    /// known tool. Defaults to `all`.
    #[arg(long, value_delimiter = ',', default_value = "all", env = "MCP_TOOLS")]
    pub tools: Vec<String>,

    /// Print the available tool catalogue and exit. Useful for
    /// CI / scripting.
    #[arg(long, conflicts_with_all = ["transport", "bind"])]
    pub list_available: bool,

    /// Transport. `stdio` (default) for child-process MCP; `sse` for
    /// network deployment (Streamable HTTP under the hood).
    #[arg(long, value_enum, default_value_t = TransportArg::Stdio, env = "MCP_TRANSPORT")]
    pub transport: TransportArg,

    /// Bind address when `--transport sse`. Ignored for stdio.
    #[arg(long, default_value = "0.0.0.0:8000", env = "MCP_BIND")]
    pub bind: String,

    /// HTTP path the Streamable HTTP service is mounted at.
    #[arg(long, default_value = "/mcp", env = "MCP_PATH")]
    pub http_path: String,
}

impl From<TransportArg> for pltl_mcp_shared::transport::Transport {
    fn from(value: TransportArg) -> Self {
        match value {
            TransportArg::Stdio => pltl_mcp_shared::transport::Transport::Stdio,
            TransportArg::Sse => pltl_mcp_shared::transport::Transport::Http,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn cli_renders() {
        Cli::command().debug_assert();
    }

    #[test]
    fn default_is_stdio_all() {
        let cli = Cli::try_parse_from(["pltl-mcp"]).expect("parse");
        assert_eq!(cli.transport, TransportArg::Stdio);
        assert_eq!(cli.tools, vec!["all"]);
    }

    #[test]
    fn tools_comma_split() {
        let cli = Cli::try_parse_from([
            "pltl-mcp",
            "--tools",
            "ltl_to_nl,parse_and_canonicalize",
        ])
        .expect("parse");
        assert_eq!(
            cli.tools,
            vec![
                "ltl_to_nl".to_string(),
                "parse_and_canonicalize".to_string(),
            ]
        );
    }

    #[test]
    fn sse_with_bind() {
        let cli = Cli::try_parse_from([
            "pltl-mcp",
            "--transport",
            "sse",
            "--bind",
            "127.0.0.1:9000",
        ])
        .expect("parse");
        assert_eq!(cli.transport, TransportArg::Sse);
        assert_eq!(cli.bind, "127.0.0.1:9000");
    }
}
