//! `pltl-mcp` — parameterized MCP server binary.
//!
//! Subcommands: none. CLI flags only (see [`pltl_mcp_server::cli`]).
//! Workflow:
//!
//! 1. Parse CLI.
//! 2. If `--list-available`, print the tool catalogue and exit.
//! 3. Otherwise: build the [`ToolRegistry`] from `--tools`, wrap it
//!    in a [`PltlServer`], and run it under the chosen transport.
//! 4. On shutdown, log cache hit/miss/size for the session.

use anyhow::Result;
use clap::Parser;
use pltl_mcp_server::cli::Cli;
use pltl_mcp_server::registry::ToolRegistry;
use pltl_mcp_server::server::PltlServer;
use pltl_mcp_server::tools;
use pltl_mcp_shared::server::FactoryResult;
use pltl_mcp_shared::transport::TransportConfig;
use std::sync::Arc;

#[tokio::main]
async fn main() -> Result<()> {
    init_tracing();

    let cli = Cli::parse();

    if cli.list_available {
        println!("Available tools (use --tools to select a subset):");
        for n in tools::known_names() {
            println!("  {n}");
        }
        return Ok(());
    }

    let registry = ToolRegistry::new(&cli.tools, tools::all()).map_err(|e| {
        // Unknown tool name → exit non-zero with a clean message.
        anyhow::anyhow!("{e}. Available: {:?}", tools::known_names())
    })?;
    let registry = Arc::new(registry);

    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        transport = ?cli.transport,
        tools = ?registry.names(),
        "pltl-mcp",
    );

    // Build a shared TransportConfig in the shape pltl_mcp_shared::server::run expects.
    let transport_cfg = TransportConfig {
        transport: cli.transport.into(),
        bind: cli.bind.clone(),
        http_path: cli.http_path.clone(),
    };

    let registry_for_factory = registry.clone();
    let res = pltl_mcp_shared::server::run(transport_cfg, move || -> FactoryResult<PltlServer> {
        Ok(PltlServer::new(registry_for_factory.clone()))
    })
    .await;

    let stats = registry.cache_stats();
    tracing::info!(
        hits = stats.hits,
        misses = stats.misses,
        size = stats.size,
        "registry cache stats on shutdown",
    );

    res
}

fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        // stdout is reserved for MCP JSON-RPC traffic in stdio mode;
        // log everything to stderr.
        .with_writer(std::io::stderr)
        .try_init();
}
