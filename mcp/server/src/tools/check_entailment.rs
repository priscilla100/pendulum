//! `check_entailment` — `f1 → f2` with strict-flag + counterexample.
//!
//! Plumbing-only tool body: parse `f1` and `f2` through the OCaml
//! front-end, hand the typed pair to
//! [`pltl_rust::analysis::entailment::entailment_pair`], then
//! serialise the [`EntailmentResult`].  The logical body lives in
//! `pltl_rust::analysis::entailment` (and ultimately in
//! `pltl_rust::analysis::sat::decide_sat`).

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::entailment;
use schemars::{schema_for, JsonSchema};
use serde::Deserialize;

const NAME: &str = "check_entailment";
const DESCRIPTION: &str = r#"WHAT: Decide whether PLTL formulas `f1` entails `f2` — i.e. whether `f1 -> f2` is a tautology. 
WHEN: Use to check 'rewording A logically implies rewording B', to test whether 
a candidate is at least as strong as a reference translation, or to verify an 
assumption pins a requirement. 
INPUTS: `f1` (antecedent formula), `f2` (consequent formula). 
OUTPUTS: `{entails: bool, strict: bool, counterexample?: lasso}`. 
`strict = true` means f1 strictly refines f2 (entails but is not entailed); 
`counterexample` is present only when `entails = false` and shows a trace 
satisfying f1 but violating f2. 
For symmetric comparison use `check_equivalence`; for many candidates at once use `compare_candidates`."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Antecedent formula.
    f1: String,
    /// Consequent formula.
    f2: String,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct CheckEntailmentTool;

#[async_trait]
impl Tool for CheckEntailmentTool {
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

        let result = entailment::entailment_pair(&f1, &f2)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;

        serde_json::to_value(&result)
            .map_err(|e| ToolError::Internal(format!("serialise EntailmentResult: {e}")))
    }
}
