//! rmcp `ServerHandler` impl that delegates to [`crate::ToolRegistry`].
//!
//! The handler is cheap to clone (`Arc<ToolRegistry>` inside) so rmcp
//! can spawn one per session in the Streamable HTTP transport.

use crate::registry::ToolRegistry;
use crate::tool::ToolError;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::model::{
    CallToolRequestParams, CallToolResult, Content, ListToolsResult, PaginatedRequestParams,
    ServerCapabilities, ServerInfo,
};
use rmcp::service::RequestContext;
use rmcp::{tool_handler, tool_router, ErrorData as McpError, RoleServer, ServerHandler};
use std::sync::Arc;

/// Server handler. Wraps the [`ToolRegistry`] so dispatch is a
/// straightforward registry lookup.
///
/// The struct also carries a `ToolRouter<Self>` field for compatibility
/// with the `#[tool_handler]` macro, even though the actual tool list
/// is *runtime-decided* via the registry rather than the macro-static
/// `#[tool]` annotations. The macro field is left empty (no `#[tool]`
/// methods on this impl); we override `list_tools` and `call_tool`
/// directly to delegate to the registry.
#[derive(Clone)]
pub struct PltlServer {
    registry: Arc<ToolRegistry>,
    #[allow(dead_code)]
    tool_router: ToolRouter<Self>,
}

impl PltlServer {
    /// Build the handler from a registry. The registry must outlive
    /// the rmcp service.
    pub fn new(registry: Arc<ToolRegistry>) -> Self {
        Self {
            registry,
            tool_router: Self::tool_router(),
        }
    }
}

#[tool_router]
impl PltlServer {
    // Intentionally empty — the runtime-decided tool list lives in
    // the registry, not in `#[tool]`-annotated methods. The macro
    // still requires a `tool_router()` method to exist; an empty impl
    // generates one with an empty route table.
}

#[tool_handler]
impl ServerHandler for PltlServer {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.instructions = Some(
            "PLTL analysis tools, registered at runtime via --tools. \
             Call `tools/list` for the active set."
                .into(),
        );
        info.capabilities = ServerCapabilities::builder().enable_tools().build();
        info
    }

    async fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, McpError> {
        let mut tools = Vec::with_capacity(self.registry.iter().count());
        for (name, tool) in self.registry.iter() {
            let schema_arc = match tool.input_schema() {
                serde_json::Value::Object(obj) => std::sync::Arc::new(obj),
                _ => std::sync::Arc::new(serde_json::Map::new()),
            };
            // Use rmcp 1.7's public `Tool::new` and `with_all_items`
            // builders instead of constructing the non-exhaustive
            // structs directly (Phase B codex finding #10).
            tools.push(rmcp::model::Tool::new(
                *name,
                tool.description(),
                schema_arc,
            ));
        }
        Ok(ListToolsResult::with_all_items(tools))
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> Result<CallToolResult, McpError> {
        let args_value = request
            .arguments
            .map(serde_json::Value::Object)
            .unwrap_or_else(|| serde_json::json!({}));
        let outcome = self
            .registry
            .dispatch(&request.name, args_value)
            .await
            .map_err(map_tool_error)?;
        let payload = serde_json::to_string(&outcome.body)
            .map_err(|e| McpError::internal_error(format!("ser: {e}"), None))?;
        Ok(CallToolResult::success(vec![Content::text(payload)]))
    }
}

/// Map a [`ToolError`] to the rmcp protocol error shape.
fn map_tool_error(e: ToolError) -> McpError {
    match e {
        ToolError::InvalidInput(msg) => McpError::invalid_params(msg, None),
        ToolError::Analysis(msg) => {
            // Per BUILD_PLAN best-practice item #10, tool errors are
            // surfaced verbatim to the LLM with a `tool_error:` prefix.
            McpError::invalid_params(format!("tool_error: {msg}"), None)
        }
        ToolError::NotImplemented(name) => {
            McpError::invalid_params(
                format!("tool_error: `{name}` not yet implemented (Phase C stub)"),
                None,
            )
        }
        ToolError::Internal(msg) => McpError::internal_error(msg, None),
    }
}

