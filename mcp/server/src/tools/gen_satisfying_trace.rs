//! `gen_satisfying_trace` — find a satisfying lasso for a formula.
//!
//! Plumbing-only tool body: parse the formula through the OCaml
//! front-end, call
//! [`pltl_rust::analysis::trace_gen::gen_satisfying_trace`], serialise.
//! The logical body reduces to a single `decide_sat` call.

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::trace::Lasso;
use pltl_rust::analysis::trace_gen;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "gen_satisfying_trace";
const DESCRIPTION: &str = r#"WHAT: Synthesise a witness lasso (`prefix · loop^ω`) that satisfies the given PLTL formula. BLACK-backed. 
WHEN: Use to confirm a candidate formula is satisfiable at all (rules out `false`/`G p & G !p` shapes), to extract a representative execution for the user, or to feed into `check_trace_satisfaction` as a regression test. 
INPUTS: `formula` (PLTL string). 
OUTPUTS: `{satisfiable: bool, trace?: {prefix: [step], loop: [step]}}`. If `satisfiable=false`, the formula is unsatisfiable — surface this back to the user since the NL is likely self-contradictory or you mis-translated. NOTE: To find a violating trace see `gen_violating_trace`."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Formula.
    formula: String,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    /// Whether any model exists.
    satisfiable: bool,
    /// One lasso when satisfiable.
    trace: Option<Lasso>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct GenSatisfyingTraceTool;

#[async_trait]
impl Tool for GenSatisfyingTraceTool {
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
        let result = trace_gen::gen_satisfying_trace(&formula)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;
        let body = Output {
            satisfiable: result.found,
            trace: result.trace,
        };
        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise SatisfyingTrace: {e}")))
    }
}
