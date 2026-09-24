//! `check_consistency` — multi-formula joint satisfiability.
//!
//! Plumbing-only tool body: parse each surface-syntax formula through
//! the OCaml front-end, hand the typed `Formula` slice to
//! [`pltl_rust::analysis::consistency::check_consistency`], then
//! serialise the result.  The logical body lives in
//! `pltl_rust::analysis::consistency`.

use super::parse_util::parse_all;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::consistency;
use pltl_rust::Formula;
use schemars::{schema_for, JsonSchema};
use serde::Deserialize;

const NAME: &str = "check_consistency";
const DESCRIPTION: &str = r#"WHAT: Decide whether a set of PLTL formulas can all hold on some single infinite trace (joint satisfiability). 
WHEN: Use when the NL has multiple clauses joined by 'and', or when you suspect two requirements contradict each other (e.g. 'always X' + 'never X'). 
Also useful for sanity-checking that an extracted assumption set is internally coherent. 
INPUTS: `formulas` (array of PLTL strings, length >= 1). 
OUTPUTS: `{consistent: bool, max_satisfiable_subset: [idx], conflicting_pairs: [[i,j]]}`. 
On UNSAT, the indices identify the minimal subset that conflicts. "#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Formulas to check jointly.
    formulas: Vec<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct CheckConsistencyTool;

#[async_trait]
impl Tool for CheckConsistencyTool {
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
        if parsed.formulas.is_empty() {
            return Err(ToolError::InvalidInput(
                "check_consistency requires at least 1 formula".into(),
            ));
        }

        let formulas: Vec<Formula> = parse_all(&parsed.formulas)?;
        let result = consistency::check_consistency(&formulas)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;

        serde_json::to_value(&result)
            .map_err(|e| ToolError::Internal(format!("serialise ConsistencyResult: {e}")))
    }
}
