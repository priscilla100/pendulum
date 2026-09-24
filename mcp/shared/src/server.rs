//! Generic rmcp server runtime used by every MCP-server binary.
//!
//! Each per-analysis crate (`mcp/<name>/`) builds a concrete handler
//! type that implements [`rmcp::ServerHandler`] (typically via the
//! `#[tool_router]` / `#[tool_handler]` macros) and calls
//! [`run`] with a factory closure and the parsed
//! [`TransportConfig`]. This module dispatches on
//! `config.transport` and wires up the appropriate rmcp transport.
//!
//! ## Why a factory closure
//!
//! The Streamable HTTP transport spawns a fresh handler per client
//! session, so it needs a way to construct handlers on demand. The
//! stdio transport runs exactly one handler — calling the factory
//! once is harmless.

use crate::transport::{Transport, TransportConfig};
use anyhow::Result;
use rmcp::ServerHandler;
use tracing::info;

/// Result type the handler factory returns. `std::io::Error` is what
/// rmcp's Streamable HTTP service expects from its inner factory; the
/// stdio path adapts the same shape so callers only write one closure.
pub type FactoryResult<H> = std::result::Result<H, std::io::Error>;

/// Dispatch on the chosen transport and run the server until it exits.
///
/// `factory` builds a handler. For stdio it's called once; for HTTP it
/// is wrapped in a [`StreamableHttpService`] and called per session.
/// The closure must be `Send + Sync` and return `Result<H, RmcpError>`
/// so failures during handler construction surface cleanly to the
/// client.
///
/// # Errors
///
/// Returns whatever the underlying transport propagates — typically
/// I/O on bind, or a graceful-shutdown signal turning into `Ok`.
pub async fn run<H, F>(config: TransportConfig, factory: F) -> Result<()>
where
    H: ServerHandler + Send + Sync + 'static,
    F: Fn() -> FactoryResult<H> + Send + Sync + 'static,
{
    info!(
        transport = ?config.transport,
        "starting MCP server",
    );
    match config.transport {
        Transport::Stdio => run_stdio(factory).await,
        Transport::Http => run_http(factory, &config.bind, &config.http_path).await,
    }
}

#[cfg(feature = "transport-stdio")]
async fn run_stdio<H, F>(factory: F) -> Result<()>
where
    H: ServerHandler + Send + Sync + 'static,
    F: Fn() -> FactoryResult<H> + Send + Sync + 'static,
{
    use rmcp::transport::stdio;
    use rmcp::ServiceExt;

    let handler = factory().map_err(|e| anyhow::anyhow!("factory failed: {e}"))?;
    let service = handler.serve(stdio()).await?;
    service.waiting().await?;
    Ok(())
}

#[cfg(not(feature = "transport-stdio"))]
async fn run_stdio<H, F>(_factory: F) -> Result<()>
where
    H: ServerHandler + Send + Sync + 'static,
    F: Fn() -> FactoryResult<H> + Send + Sync + 'static,
{
    anyhow::bail!("binary built without `transport-stdio` feature; rebuild with --features transport-stdio")
}

#[cfg(feature = "transport-http")]
async fn run_http<H, F>(factory: F, bind: &str, path: &str) -> Result<()>
where
    H: ServerHandler + Send + Sync + 'static,
    F: Fn() -> FactoryResult<H> + Send + Sync + 'static,
{
    use rmcp::transport::streamable_http_server::{
        session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
    };
    use std::sync::Arc;

    let service = StreamableHttpService::new(
        factory,
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default(),
    );

    let router = axum::Router::new().nest_service(path, service);
    let listener = tokio::net::TcpListener::bind(bind).await?;
    info!(addr = bind, path = path, "Streamable HTTP listening");

    let server = axum::serve(listener, router).with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    });
    server.await?;
    Ok(())
}

#[cfg(not(feature = "transport-http"))]
async fn run_http<H, F>(_factory: F, _bind: &str, _path: &str) -> Result<()>
where
    H: ServerHandler + Send + Sync + 'static,
    F: Fn() -> FactoryResult<H> + Send + Sync + 'static,
{
    anyhow::bail!("binary built without `transport-http` feature; rebuild with --features transport-http")
}
