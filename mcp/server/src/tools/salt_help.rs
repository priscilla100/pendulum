//! `salt_help` — return the SALT spec-syntax reference on demand.
//!
//! The SALT grammar is dense (~250 lines of operator/pattern/anti-
//! pattern reference). Including it inline in every system prompt
//! costs ~4K tokens per call, even when the agent doesn't pick the
//! SALT path. This tool externalises the reference: the agent calls
//! `salt_help` only when it has committed to using
//! `nl_to_ltl_via_salt`.
//!
//! No subprocess, no LLM — just returns a static string baked at
//! compile time.

use crate::tool::{CachePolicy, Tool, ToolError};
use async_trait::async_trait;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "salt_help";

const DESCRIPTION: &str = r#"WHAT: Returns the SALT spec-syntax reference (operators, scope modifiers, regex, past operators, counting, macros, common NL→SALT translation patterns, and anti-patterns). WHEN: Call this BEFORE your first `nl_to_ltl_via_salt` invocation in a session if you don't already know the SALT grammar, or after a SALT rejection if the error references a construct you're unsure of (scope boundary modifiers, regex constraints, reserved words). INPUTS: none. OUTPUTS: `{ reference: string }` — the full SALT syntax reference."#;

const SALT_REFERENCE: &str = include_str!("salt_help_content.txt");

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
struct Output {
    /// The SALT syntax reference, as a single multi-line string.
    reference: String,
}

/// `salt_help` tool — returns the SALT spec-syntax reference. Stateless.
#[derive(Debug, Default, Clone, Copy)]
pub struct SaltHelpTool;

#[async_trait]
impl Tool for SaltHelpTool {
    fn name(&self) -> &'static str {
        NAME
    }
    fn description(&self) -> &'static str {
        DESCRIPTION
    }
    fn input_schema(&self) -> serde_json::Value {
        serde_json::to_value(schema_for!(Input)).unwrap_or_else(|_| serde_json::json!({}))
    }
    fn cache_policy(&self) -> CachePolicy {
        // The reference is a baked-in constant. Cache forever.
        CachePolicy::default()
    }
    async fn call(&self, _input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let out = Output { reference: SALT_REFERENCE.to_string() };
        serde_json::to_value(out).map_err(|e| ToolError::Internal(format!("serialize: {e}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reference_is_nonempty() {
        assert!(!SALT_REFERENCE.trim().is_empty());
        // sanity: must mention `assert` and `upto` — the two anchor concepts.
        assert!(SALT_REFERENCE.contains("assert"));
        assert!(SALT_REFERENCE.contains("upto"));
    }

    #[tokio::test]
    async fn call_returns_reference() {
        let t = SaltHelpTool;
        let raw = t.call(serde_json::json!({})).await.unwrap();
        let out: Output = serde_json::from_value(raw).unwrap();
        assert!(out.reference.contains("assert"));
    }
}
