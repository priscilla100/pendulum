//! `gen_violating_trace` — find a lasso violating a formula.
//!
//! Plumbing-only tool body.  `violatable: false` ⇒ formula is a
//! tautology.  Reduces to `decide_sat(¬formula)`.

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::trace::Lasso;
use pltl_rust::analysis::trace_explain;
use pltl_rust::analysis::trace_gen;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "gen_violating_trace";
const DESCRIPTION: &str = r#"WHAT: Synthesise a lasso (`prefix · loop^ω`) that VIOLATES the given PLTL formula (i.e. satisfies `!formula`).
WHEN: Use to confirm a candidate isn't a vacuous tautology, to find a concrete counter-example to surface to the user, or to explore the boundary of an under-constrained spec.
INPUTS: `formula` (PLTL string), optional `explain` (bool, default false).
OUTPUTS: `{violatable: bool, trace?: lasso}`. `violatable=false` means the formula is a tautology — usually a sign you under-specified the meaning (e.g. wrote `G (p -> p)` by accident).
When `explain=true` and a violating trace exists, additionally `{explanation: string}` — a DETERMINISTIC (non-LLM), grounded plain-English blame path explaining exactly WHY the returned trace violates the formula (pure CPU analysis).
NOTE: For satisfying witnesses see `gen_satisfying_trace`."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Formula.
    formula: String,
    /// When true, add a deterministic (non-LLM) grounded explanation of
    /// why the returned trace violates the formula. Default false.
    explain: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    /// Whether the formula is *not* a tautology.
    violatable: bool,
    /// One violating lasso when `violatable`.
    trace: Option<Lasso>,
    /// Deterministic grounded explanation of why `trace` violates the
    /// formula. Populated only when `explain=true` and a trace exists.
    #[serde(skip_serializing_if = "Option::is_none")]
    explanation: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct GenViolatingTraceTool;

#[async_trait]
impl Tool for GenViolatingTraceTool {
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
        let formula = parse_one("formula", &parsed.formula)?;
        let want_explain = parsed.explain.unwrap_or(false);
        let result = trace_gen::gen_violating_trace(&formula)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;

        // The synthesised trace violates `formula`, so `explain_trace`
        // renders WHY the verdict is false. Deterministic, CPU-only.
        let explanation = match (want_explain, &result.trace) {
            (true, Some(trace)) => {
                Some(trace_explain::explain_trace(trace, &formula).english)
            }
            _ => None,
        };

        let body = Output {
            violatable: result.found,
            trace: result.trace,
            explanation,
        };
        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise ViolatingTrace: {e}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn explain_true_returns_violation_explanation() {
        let tool = GenViolatingTraceTool;
        // Non-tautology: a violating trace exists.
        let input = json!({"formula": "G (req -> F ack)", "explain": true});
        let out = tool.call(input).await.expect("call ok");
        assert!(out["violatable"].as_bool().unwrap());
        assert!(out.get("trace").is_some());
        let expl = out["explanation"].as_str().expect("explanation string");
        assert!(!expl.is_empty());
        // The trace violates the formula → explanation reports a violation.
        assert!(expl.contains("VIOLATES"), "explanation: {expl}");
    }

    #[tokio::test]
    async fn explain_absent_omits_explanation() {
        let tool = GenViolatingTraceTool;
        let input = json!({"formula": "G (req -> F ack)"});
        let out = tool.call(input).await.expect("call ok");
        assert!(out["violatable"].as_bool().unwrap());
        assert!(out.get("explanation").is_none());
    }
}
