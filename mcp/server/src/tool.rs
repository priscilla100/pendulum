//! `Tool` trait — the shared interface every analysis tool implements.
//!
//! A tool is identified by a stable name, advertises a JSON schema for
//! its input, and exposes an `async fn call(input) -> Result<output,
//! ToolError>`. The registry handles caching + dispatch; tools stay
//! pure with respect to MCP transport details.
//!
//! Tools are stored as `Arc<dyn Tool>` so the same instance can be
//! shared across the rmcp handler clones rmcp makes per session.

use async_trait::async_trait;
use thiserror::Error;

/// Errors a tool can produce. Map to MCP error codes in
/// [`crate::server`].
#[derive(Debug, Error)]
pub enum ToolError {
    /// Caller supplied bad input — return `invalid_params`.
    #[error("invalid input: {0}")]
    InvalidInput(String),

    /// The analysis itself reported a problem (e.g. parser rejected
    /// the formula, IR validation failed). The message is shown
    /// verbatim with a `tool_error:` prefix so the agent can reason
    /// about it (best-practice item #10).
    #[error("{0}")]
    Analysis(String),

    /// The tool is a typed stub waiting for `// TODO(omar):`
    /// implementation. Surfaces cleanly so the agent never sees a
    /// panic.
    #[error("analysis `{0}` not yet implemented (Phase C stub)")]
    NotImplemented(&'static str),

    /// Anything else — IO, serialisation, backend connection.
    #[error("internal error: {0}")]
    Internal(String),
}

/// One MCP tool.
///
/// `Send + Sync + 'static` so handles can flow through the rmcp
/// service registry, which clones the server type per session. The
/// `call` body is `async` to accommodate tools that shell out to the
/// OCaml parser or, in Phase C, talk to BLACK / Spot.
#[async_trait]
pub trait Tool: Send + Sync + 'static {
    /// Stable name advertised to the LLM (e.g. `parse_and_canonicalize`).
    fn name(&self) -> &'static str;

    /// One-line description shown in `tools/list`.
    fn description(&self) -> &'static str;

    /// JSON schema for the input. Generated via `schemars::schema_for!`
    /// in most implementations.
    fn input_schema(&self) -> serde_json::Value;

    /// Run the analysis. Returns the JSON result body that the rmcp
    /// handler wraps in a `CallToolResult`.
    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError>;

    /// Cache policy parameters. Default: deterministic (no
    /// temperature, no seed). Tools that wrap an LLM call override
    /// this to return their session-wide `(temperature, seed)` so the
    /// registry cache only stores replayable answers.
    ///
    /// Mirrors `pltl_mcp_shared::cache::should_cache`'s policy.
    fn cache_policy(&self) -> CachePolicy {
        CachePolicy::default()
    }
}

/// Cache parameters a tool can declare to the registry.
#[derive(Debug, Clone, Copy, Default)]
pub struct CachePolicy {
    /// Sampling temperature the tool used internally, or `None` if
    /// the tool is deterministic. The registry treats `None` as
    /// "always cacheable".
    pub temperature: Option<f32>,
    /// Seed the tool used. Required (alongside `temperature == 0`)
    /// for an LLM-backed tool's result to be cached.
    pub seed: Option<u64>,
}

impl CachePolicy {
    /// Default policy for LLM-backed tools: positive temperature,
    /// no seed. This deliberately *fails* the shared
    /// `pltl_mcp_shared::cache::should_cache` gate so the registry
    /// never caches an LLM result unless the tool itself overrides
    /// this with the configured `(temperature == 0.0, seed = Some(_))`
    /// once a real client lands in Phase 3+.
    ///
    /// Codex Phase C review #2: previously LLM-backed tools returned
    /// `CachePolicy::default()` (i.e. deterministic-cacheable),
    /// which would have polluted the cache the moment the LLM
    /// bodies started returning real results.
    pub const NON_DETERMINISTIC_LLM: Self = Self {
        temperature: Some(1.0),
        seed: None,
    };
}
