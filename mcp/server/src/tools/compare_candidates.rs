//! `compare_candidates` — pairwise implication lattice over multiple
//! candidate formulas.  Useful when the LLM emits several plausible
//! variants and the agent wants to know which strictly imply which.
//!
//! Plumbing-only tool body: parse each formula, call
//! [`pltl_rust::analysis::compare::compare_candidates`], serialise.

use super::parse_util::parse_all;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::compare;
use schemars::{schema_for, JsonSchema};
use serde::Deserialize;

const NAME: &str = "compare_candidates";
const DESCRIPTION: &str = r#"WHAT: Pairwise-compare 2+ PLTL candidate formulas to recover the implication lattice (which strictly imply which, which are equivalent, which are incomparable). 
WHEN: Use when you (or the LLM) produced several plausible translations and need to pick the strongest, or to confirm candidates are equivalent up to surface syntax. Especially useful when `extract_ap_mapping` returned multiple open questions and you drafted one candidate per answer. 
INPUTS: `formulas` (array of >= 2 PLTL strings). 
OUTPUTS: `{equivalent_pairs: [[i,j]], stronger_than: [[i,j]] where i strictly implies j, incomparable: [[i,j]], distinguishing_traces: [{i, j, trace}]}`. 
NOTE: keep `formulas` small (<= 5)."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Candidate formulas. Must contain at least 2.
    formulas: Vec<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct CompareCandidatesTool;

#[async_trait]
impl Tool for CompareCandidatesTool {
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
        if parsed.formulas.len() < 2 {
            return Err(ToolError::InvalidInput(
                "compare_candidates requires at least 2 formulas".into(),
            ));
        }
        let formulas = parse_all(&parsed.formulas)?;
        let result = compare::compare_candidates(&formulas)
            .map_err(|e| ToolError::Analysis(e.to_string()))?;
        serde_json::to_value(&result)
            .map_err(|e| ToolError::Internal(format!("serialise CompareResult: {e}")))
    }
}
