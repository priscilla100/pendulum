//! `check_trace_satisfaction` — does a lasso satisfy a formula?
//!
//! Plumbing-only tool body: parse the formula through the OCaml
//! front-end, deserialise the lasso, call
//! [`pltl_rust::analysis::trace_check::check_trace_satisfaction`],
//! serialise the result.
//!
//! `explain=true` adds a deterministic (non-LLM), grounded explanation of
//! WHY the trace satisfies/violates the formula, produced by the pure-Rust
//! [`pltl_rust::analysis::trace_explain::explain_trace`] blame-path
//! analysis (CPU-only; no subprocess, no LLM).

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::trace::Lasso;
use pltl_rust::analysis::trace_check;
use pltl_rust::analysis::trace_explain;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "check_trace_satisfaction";
const DESCRIPTION: &str = r#"WHAT: Decide whether a specific lasso trace (a finite prefix followed by an infinitely-repeating loop body) satisfies a PLTL formula. 
WHEN: Use to sanity-check a draft formula against a concrete scenario the user described, to verify a synthesized trace from 
`gen_satisfying_trace`, or to confirm a counter-example from `gen_violating_trace`. 
INPUTS: `formula` (string), `trace` (`{prefix: [step], loop: [step]}` where each `step`
is a list of atom names that hold at that position), optional `explain` (bool, default false).
OUTPUTS: `{satisfies: bool}`. When `explain=true`, additionally `{explanation: string}` — a
DETERMINISTIC (non-LLM), grounded plain-English blame path explaining exactly why the trace
satisfies or violates the formula (pure CPU analysis; consistent with `satisfies`).
NOTE: Both `prefix` and `loop` are arrays of arrays.
Empty `loop` is rejected (must be `[[...]]` minimum)."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Formula in surface syntax.
    formula: String,
    /// Lasso shape: `{"prefix": [..], "loop": [..]}`.
    trace: serde_json::Value,
    /// When true, include a deterministic (non-LLM) grounded explanation.
    explain: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    /// Whether the trace models the formula.
    satisfies: bool,
    /// Deterministic grounded explanation of the verdict. Populated only
    /// when the input set `explain = true`; omitted otherwise. Produced by
    /// the pure-Rust `trace_explain::explain_trace` blame path — no LLM.
    #[serde(skip_serializing_if = "Option::is_none")]
    explanation: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct CheckTraceSatisfactionTool;

#[async_trait]
impl Tool for CheckTraceSatisfactionTool {
    fn name(&self) -> &'static str {
        NAME
    }
    fn description(&self) -> &'static str {
        DESCRIPTION
    }
    fn input_schema(&self) -> serde_json::Value {
        serde_json::to_value(schema_for!(Input)).unwrap_or_else(|_| serde_json::json!({}))
    }
    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let parsed: Input = serde_json::from_value(input)
            .map_err(|e| ToolError::InvalidInput(format!("schema: {e}")))?;
        let trace: Lasso = serde_json::from_value(parsed.trace)
            .map_err(|e| ToolError::InvalidInput(format!("trace shape: {e}")))?;
        // `Lasso` derives `Deserialize`, which bypasses the
        // constructor invariant that the loop body must be non-empty.
        // Reject the empty-loop shape here so we never feed
        // BLACK / SySLite2 a finite trace pretending to be infinite.
        if trace.loop_.is_empty() {
            return Err(ToolError::InvalidInput(
                "trace.loop must be non-empty (a Lasso represents an infinite ω-trace)".into(),
            ));
        }
        let formula = parse_one("formula", &parsed.formula)?;

        let want_explain = parsed.explain.unwrap_or(false);

        let satisfies = trace_check::check_trace_satisfaction(&trace, &formula)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;

        // Deterministic, CPU-only grounded explanation. `explain_trace`
        // uses the identical frozen semantics as BLACK, so its verdict
        // agrees with `satisfies`; we surface only the English rendering.
        let explanation = if want_explain {
            Some(trace_explain::explain_trace(&trace, &formula).english)
        } else {
            None
        };

        let body = Output {
            satisfies,
            explanation,
        };
        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise TraceCheckOutput: {e}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// `G (req -> F ack)` on `{req}` then nothing forever: violates, and
    /// with explain=true we get a non-empty grounded explanation.
    #[tokio::test]
    async fn explain_true_returns_explanation_consistent_with_satisfies() {
        let tool = CheckTraceSatisfactionTool;
        let input = json!({
            "formula": "G (req -> F ack)",
            "trace": {"prefix": [["req"]], "loop": [[]]},
            "explain": true,
        });
        let out = tool.call(input).await.expect("call ok");
        let satisfies = out["satisfies"].as_bool().expect("satisfies bool");
        assert!(!satisfies, "req then nothing violates G(req -> F ack)");
        let expl = out["explanation"].as_str().expect("explanation string");
        assert!(!expl.is_empty());
        // The rendering states the verdict; must be consistent with `satisfies`.
        assert!(expl.contains("VIOLATES"), "explanation: {expl}");
    }

    /// explain absent/false: no `explanation` key, behaviour unchanged.
    #[tokio::test]
    async fn explain_absent_omits_explanation() {
        let tool = CheckTraceSatisfactionTool;
        let input = json!({
            "formula": "G (req -> F ack)",
            "trace": {"prefix": [["req"], ["ack"]], "loop": [[]]},
        });
        let out = tool.call(input).await.expect("call ok");
        assert!(out["satisfies"].as_bool().unwrap());
        assert!(out.get("explanation").is_none(), "explanation omitted when explain absent");
    }

    #[tokio::test]
    async fn explain_true_satisfying_says_satisfies() {
        let tool = CheckTraceSatisfactionTool;
        let input = json!({
            "formula": "G (req -> F ack)",
            "trace": {"prefix": [["req"], ["ack"]], "loop": [[]]},
            "explain": true,
        });
        let out = tool.call(input).await.expect("call ok");
        assert!(out["satisfies"].as_bool().unwrap());
        let expl = out["explanation"].as_str().expect("explanation string");
        assert!(expl.contains("SATISFIES"), "explanation: {expl}");
    }
}
