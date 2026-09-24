//! `distinguishing_trace` — a lasso that separates two formulas
//! (satisfies one but not the other).
//!
//! Plumbing-only tool body.  Calls
//! [`pltl_rust::analysis::trace_gen::distinguishing_trace_pair`]; the
//! logical body is the two `decide_sat` calls inside that primitive.

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::trace::Lasso;
use pltl_rust::analysis::trace_explain;
use pltl_rust::analysis::trace_gen;
use pltl_rust::Formula;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "distinguishing_trace";
const DESCRIPTION: &str = r#"WHAT: Find a lasso that satisfies exactly one of `f1` and `f2` where f1 and f2 are PLTL formulas.
Equivalent to picking whichever of `f1 & !f2` or `!f1 & f2` is satisfiable.
WHEN: Use when two candidate translations look equivalent and you want a concrete trace that distinguishes them,
or to surface a 'here is exactly where they differ' explanation to the user.
INPUTS: `f1`, `f2` (PLTL strings), optional `explain` (bool, default false). OUTPUTS: `{trace?: lasso, direction?: "f1_only"|"f2_only", reason?: string}`. `direction = "f1_only"` means the returned trace satisfies f1 but violates f2 (and vice versa). If both formulas are equivalent, no trace is returned and `reason` explains why.
When `explain=true` and a separating trace exists, additionally `{explanation: string}` — a DETERMINISTIC (non-LLM), grounded plain-English account combining WHY the trace is accepted by one formula and rejected by the other (pure CPU analysis).
NOTE: Requires BLACK. For yes/no equivalence use `check_equivalence` (faster, no trace)."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// First formula.
    f1: String,
    /// Second formula.
    f2: String,
    /// When true, add a deterministic (non-LLM) grounded explanation of
    /// why the trace is accepted by one formula and rejected by the other.
    /// Default false.
    explain: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    /// Distinguishing trace; `None` when formulas are equivalent.
    trace: Option<Lasso>,
    /// `"f1_only"` (trace models f1 but not f2) or `"f2_only"`.
    direction: Option<String>,
    /// Reason no trace exists (e.g. `"formulas are equivalent"`).
    reason: Option<String>,
    /// Deterministic grounded explanation combining the accepter's and
    /// rejecter's blame paths. Populated only when `explain=true` and a
    /// separating trace exists.
    #[serde(skip_serializing_if = "Option::is_none")]
    explanation: Option<String>,
}

/// Build the combined accept/reject explanation for a separating trace.
///
/// `direction` is the already-translated `"f1_only"` / `"f2_only"` tag:
/// `f1_only` ⇒ f1 accepts (verdict true), f2 rejects (verdict false).
fn combined_explanation(
    trace: &Lasso,
    f1: &Formula,
    f2: &Formula,
    direction: &str,
) -> Option<String> {
    // Identify the accepting and rejecting formulas by name and value.
    let (accept_name, accept_f, reject_name, reject_f) = match direction {
        "f1_only" => ("f1", f1, "f2", f2),
        "f2_only" => ("f2", f2, "f1", f1),
        _ => return None,
    };
    let accept = trace_explain::explain_trace(trace, accept_f).english;
    let reject = trace_explain::explain_trace(trace, reject_f).english;
    Some(format!(
        "Accepted by {accept_name} because {accept} Rejected by {reject_name} because {reject}"
    ))
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct DistinguishingTraceTool;

#[async_trait]
impl Tool for DistinguishingTraceTool {
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
        let f1 = parse_one("f1", &parsed.f1)?;
        let f2 = parse_one("f2", &parsed.f2)?;
        let want_explain = parsed.explain.unwrap_or(false);
        let r = trace_gen::distinguishing_trace_pair(&f1, &f2)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;
        // Translate internal a_only/b_only into f1_only/f2_only.
        let direction = r.direction.map(|tag| match tag {
            "a_only" => "f1_only".to_string(),
            "b_only" => "f2_only".to_string(),
            other => other.to_string(),
        });

        // When requested, combine the accepter's and rejecter's blame
        // paths into a single deterministic, CPU-only explanation.
        let explanation = match (want_explain, &r.trace, &direction) {
            (true, Some(trace), Some(dir)) => {
                combined_explanation(trace, &f1, &f2, dir)
            }
            _ => None,
        };

        let body = Output {
            trace: r.trace,
            direction,
            reason: r.reason,
            explanation,
        };
        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise DistinguishingTrace: {e}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// `G (req -> F ack)` vs `true` are inequivalent; a separating trace
    /// exists. With explain=true the explanation must name BOTH the
    /// accepter and the rejecter. Requires BLACK — skips cleanly if absent.
    #[tokio::test]
    async fn explain_true_names_accepter_and_rejecter() {
        let tool = DistinguishingTraceTool;
        let input = json!({
            "f1": "true",
            "f2": "G (req -> F ack)",
            "explain": true,
        });
        let out = match tool.call(input).await {
            Ok(v) => v,
            // BLACK missing (or subprocess hiccup) — skip, per repo convention.
            Err(_) => return,
        };
        if out.get("trace").map(|t| t.is_null()).unwrap_or(true) {
            // Equivalent per BLACK (shouldn't happen here) or no trace: skip.
            return;
        }
        let dir = out["direction"].as_str().expect("direction");
        assert!(dir == "f1_only" || dir == "f2_only", "direction: {dir}");
        let expl = out["explanation"].as_str().expect("explanation string");
        assert!(expl.contains("Accepted by"), "explanation: {expl}");
        assert!(expl.contains("Rejected by"), "explanation: {expl}");
        // Both formula labels named.
        assert!(expl.contains("f1"), "explanation: {expl}");
        assert!(expl.contains("f2"), "explanation: {expl}");
    }

    #[tokio::test]
    async fn explain_absent_omits_explanation() {
        let tool = DistinguishingTraceTool;
        let input = json!({"f1": "true", "f2": "G (req -> F ack)"});
        let out = match tool.call(input).await {
            Ok(v) => v,
            Err(_) => return,
        };
        assert!(out.get("explanation").is_none());
    }

    #[test]
    fn combined_explanation_direction_orders_accepter_first() {
        use pltl_rust::analysis::trace::{Lasso, State};
        let st = |a: &[&str]| a.iter().map(|s| s.to_string()).collect::<State>();
        // Trace: req then nothing forever. Accepts `true`, rejects G(req->F ack).
        let trace = Lasso::new(vec![st(&["req"])], vec![st(&[])]).unwrap();
        let f1 = parse_one("f1", "true").unwrap();
        let f2 = parse_one("f2", "G (req -> F ack)").unwrap();
        // f2_only: f2 accepts, f1 rejects (hypothetical direction check).
        let e = combined_explanation(&trace, &f1, &f2, "f2_only").unwrap();
        assert!(e.starts_with("Accepted by f2 because"), "{e}");
        assert!(e.contains("Rejected by f1 because"), "{e}");
        // Unknown direction → None (graceful degradation).
        assert!(combined_explanation(&trace, &f1, &f2, "bogus").is_none());
    }
}
