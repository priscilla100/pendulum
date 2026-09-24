//! Minimal Ollama client used by the LLM-backed tools.
//!
//! The natural-language tools (`extract_ap_mapping`, `ltl_to_nl`,
//! `nl_to_ltl_via_python`) shell out to a *separate* helper LLM,
//! selectable independently of the agent that drives the loop. The
//! default is `gemma4:31b-mlx` (the session experiments used it here —
//! e.g. `ltl_to_nl` paraphrases feed the audit judge); the operator can
//! point it at a smaller, faster model (e.g. `phi4`) via
//! `PLTL_TOOL_LLM_MODEL` to trade quality for latency.
//!
//! Configuration is via env vars so the server stays decoupled from any
//! particular config file format:
//!
//! | Env var                       | Default                       |
//! | ----------------------------- | ----------------------------- |
//! | `PLTL_TOOL_LLM_BASE_URL`      | `http://localhost:11434`      |
//! | `PLTL_TOOL_LLM_MODEL`         | `gemma4:31b-mlx`              |
//! | `PLTL_TOOL_LLM_TIMEOUT_SECS`  | `300`                         |
//!
//! Requests use Ollama's `/api/chat` endpoint with `format = <json
//! schema>` so the model is forced to emit a JSON object matching the
//! per-tool response schema. We use chat (rather than `/api/generate`)
//! because chat honours system + user roles and `format` is also
//! supported there since Ollama 0.5.

use crate::tool::ToolError;
use serde::Deserialize;
use std::time::Duration;

/// Resolved env-driven configuration for the tool-side LLM.
#[derive(Debug, Clone)]
pub struct ToolLlmConfig {
    /// Ollama base URL, no trailing slash.
    pub base_url: String,
    /// Model id to invoke (must be `ollama pull`'d locally).
    pub model: String,
    /// Per-call HTTP timeout.
    pub timeout: Duration,
}

impl ToolLlmConfig {
    /// Build from env vars, applying the defaults documented at the
    /// module level.
    pub fn from_env() -> Self {
        let base_url = std::env::var("PLTL_TOOL_LLM_BASE_URL")
            .unwrap_or_else(|_| "http://localhost:11434".into())
            .trim_end_matches('/')
            .to_string();
        let model = std::env::var("PLTL_TOOL_LLM_MODEL").unwrap_or_else(|_| "gemma4:31b-mlx".into());
        // Use the shared parser that warns on bad input rather than
        // silently falling back to the default.
        let secs = pltl_rust::subprocess::timeout_from_env("PLTL_TOOL_LLM_TIMEOUT_SECS", 300)
            .as_secs();
        Self {
            base_url,
            model,
            timeout: Duration::from_secs(secs),
        }
    }
}

/// Ollama tool-side client. Stateless beyond an HTTP client + config.
#[derive(Debug, Clone)]
pub struct ToolLlmClient {
    cfg: ToolLlmConfig,
    http: reqwest::Client,
}

impl ToolLlmClient {
    /// Build a client from environment-supplied config.
    pub fn from_env() -> Result<Self, ToolError> {
        let cfg = ToolLlmConfig::from_env();
        Self::with_config(cfg)
    }

    /// Build a client whose model is the FIRST defined of:
    ///   1. `tool_specific_env_var` if set (e.g.
    ///      `PLTL_PYTHON_TOOL_LLM_MODEL`),
    ///   2. `PLTL_TOOL_LLM_MODEL` (the shared default for all
    ///      helper-LLM tools),
    ///   3. the provided `fallback_default`.
    ///
    /// Base URL and timeout still come from the shared
    /// `PLTL_TOOL_LLM_BASE_URL` / `PLTL_TOOL_LLM_TIMEOUT_SECS` env
    /// vars — only the model id is overridden per tool.
    pub fn from_env_with_model(
        tool_specific_env_var: &str,
        fallback_default: &str,
    ) -> Result<Self, ToolError> {
        let mut cfg = ToolLlmConfig::from_env();
        let model = std::env::var(tool_specific_env_var)
            .ok()
            .filter(|s| !s.trim().is_empty())
            .or_else(|| std::env::var("PLTL_TOOL_LLM_MODEL").ok())
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| fallback_default.to_string());
        cfg.model = model;
        Self::with_config(cfg)
    }

    fn with_config(cfg: ToolLlmConfig) -> Result<Self, ToolError> {
        let http = reqwest::Client::builder()
            .timeout(cfg.timeout)
            .user_agent(concat!("pltl-mcp/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|e| ToolError::Internal(format!("reqwest build: {e}")))?;
        Ok(Self { cfg, http })
    }

    /// Model id this client is bound to. Useful for logging.
    pub fn model(&self) -> &str {
        &self.cfg.model
    }

    /// Issue one structured-output chat. `format_schema` is the JSON
    /// schema the model must emit — passed via Ollama's `format`
    /// field. Returns the parsed JSON `Value`.
    pub async fn structured_chat(
        &self,
        system: &str,
        user: &str,
        format_schema: serde_json::Value,
    ) -> Result<serde_json::Value, ToolError> {
        let url = format!("{}/api/chat", self.cfg.base_url);
        let body = serde_json::json!({
            "model": self.cfg.model,
            "messages": [
                { "role": "system", "content": system },
                { "role": "user",   "content": user   },
            ],
            "stream": false,
            "think":  false,
            "format": format_schema,
            "options": {
                "temperature": 0.0,
                "seed":        7,
            },
        });
        let resp = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .map_err(|e| ToolError::Internal(format!("ollama send: {e}")))?
            .error_for_status()
            .map_err(|e| ToolError::Internal(format!("ollama status: {e}")))?;
        let parsed: OllamaChatResponse = resp
            .json()
            .await
            .map_err(|e| ToolError::Internal(format!("ollama decode: {e}")))?;
        let content = parsed
            .message
            .and_then(|m| m.content)
            .unwrap_or_default();
        if content.trim().is_empty() {
            return Err(ToolError::Analysis(format!(
                "LLM `{}` returned empty content (model misconfigured?)",
                self.cfg.model
            )));
        }
        // Some helper models (observed: gemma4:12b) wrap valid JSON in a
        // markdown ```json fence; strip it before parsing rather than fail
        // the whole tool call (this broke 44/44 verifications in one eval).
        let cleaned = strip_json_fences(&content);
        serde_json::from_str::<serde_json::Value>(cleaned).map_err(|e| {
            ToolError::Analysis(format!(
                "LLM `{}` returned non-JSON content: {e}; raw = {}",
                self.cfg.model,
                truncate(&content, 240)
            ))
        })
    }
}

/// Strip a surrounding markdown code fence (``` or ```json) if present,
/// returning the inner payload; otherwise the trimmed input unchanged.
fn strip_json_fences(s: &str) -> &str {
    let t = s.trim();
    if let Some(rest) = t.strip_prefix("```") {
        // drop an optional language tag on the fence line
        let body = match rest.split_once('\n') {
            Some((_lang, body)) => body,
            None => rest,
        };
        if let Some(inner) = body.trim_end().strip_suffix("```") {
            return inner.trim();
        }
    }
    t
}

/// Truncate `s` to roughly `n` bytes, but only on UTF-8 char
/// boundaries — naive byte-index slicing panics on multi-byte runes.
fn truncate(s: &str, n: usize) -> String {
    if s.len() <= n {
        return s.to_string();
    }
    // Walk char_indices to find the largest boundary ≤ n.
    let cut = s
        .char_indices()
        .map(|(i, _)| i)
        .take_while(|&i| i <= n)
        .last()
        .unwrap_or(0);
    format!("{}…", &s[..cut])
}

#[derive(Debug, Deserialize)]
struct OllamaChatResponse {
    message: Option<OllamaMessage>,
}

#[derive(Debug, Deserialize)]
struct OllamaMessage {
    #[serde(default)]
    content: Option<String>,
}

#[cfg(test)]
mod fence_tests {
    use super::strip_json_fences;

    #[test]
    fn plain_json_untouched() {
        assert_eq!(strip_json_fences(r#"{"a": 1}"#), r#"{"a": 1}"#);
    }

    #[test]
    fn json_fence_stripped() {
        let fenced = "```json\n{\"paraphrases\": [\"x\"]}\n```";
        assert_eq!(strip_json_fences(fenced), "{\"paraphrases\": [\"x\"]}");
    }

    #[test]
    fn bare_fence_stripped() {
        assert_eq!(strip_json_fences("```\n{\"a\": 1}\n```"), "{\"a\": 1}");
    }

    #[test]
    fn unterminated_fence_left_alone() {
        // no closing fence: return trimmed input so the JSON error surfaces
        assert_eq!(strip_json_fences("```json\n{\"a\": 1}"), "```json\n{\"a\": 1}");
    }
}
