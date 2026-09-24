//! `check_equivalence` — pure logical equivalence with optional
//! AP-renaming-modulo equivalence.
//!
//! Plumbing-only tool body.  Two paths:
//!
//! 1. **No mappings supplied** — parse `f1` and `f2`, call
//!    [`pltl_rust::analysis::equivalence::equivalent_pair`], serialise.
//!    `equivalent_modulo_aps` falls back to the raw logical
//!    equivalence (mappings are required to give the field its
//!    "modulo renaming" meaning).
//! 2. **Both `mapping1` and `mapping2` supplied** — call
//!    [`pltl_rust::analysis::equivalence::equivalent_modulo_renaming`]
//!    which builds the rename ρ from shared NL fragments, applies ρ
//!    to `f2`, and decides equivalence on the renamed pair.
//!    `equivalent_modulo_aps` now genuinely is "equivalent modulo AP
//!    renaming" because the renaming is part of the call.
//!
//! `equivalent` is true iff both formulas are equivalent (under the
//! renaming when mappings are present) AND the supplied mappings
//! cover both formulas' atoms (`renaming_total`).

use super::parse_util::parse_one;
use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::equivalence;
use pltl_rust::analysis::trace::Lasso;
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

const NAME: &str = "check_equivalence";
const DESCRIPTION: &str = r#"WHAT: Decide whether two PLTL formulas are logically equivalent. 
If AP mappings are supplied, an atom renaming is built from shared NL fragments 
and equivalence is decided modulo that renaming. 
WHEN: Use to verify that an `nnf`/`simplified` rewrite preserves meaning, 
to confirm a refactor of a candidate didn't change semantics, or to compare 
two independently-drafted translations. 
INPUTS: `f1`, `f2` (PLTL strings); 
optional `mapping1`, `mapping2` (each `{atom_name -> nl_fragment}`) 
for modulo-renaming equivalence. 
OUTPUTS: `{equivalent: bool, equivalent_modulo_aps: bool, renaming_total: bool, distinguishing_trace?: lasso}`. 
Asymmetric implication: use `check_entailment`."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// First formula.
    f1: String,
    /// Second formula.
    f2: String,
    /// AP grounding for `f1`: atom → NL fragment.
    mapping1: Option<BTreeMap<String, String>>,
    /// AP grounding for `f2`: atom → NL fragment.
    mapping2: Option<BTreeMap<String, String>>,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    /// Both equivalent (under renaming when mappings are supplied)
    /// AND `ap_mapping_compatible` is not `Some(false)`.
    equivalent: bool,
    /// Equivalent up to AP renaming.  With both mappings supplied
    /// this is "equivalent after applying the inferred renaming";
    /// without mappings it falls back to raw logical equivalence.
    equivalent_modulo_aps: bool,
    /// `true` iff both supplied mappings have a complete bijection
    /// across the inferred renaming.  `None` when at least one
    /// mapping was omitted.
    ap_mapping_compatible: Option<bool>,
    /// Distinguishing trace when not equivalent.
    witness: Option<Lasso>,
    /// `"f1_only"` / `"f2_only"` when a witness was found.
    direction: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct CheckEquivalenceTool;

#[async_trait]
impl Tool for CheckEquivalenceTool {
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

        let body = match (parsed.mapping1.as_ref(), parsed.mapping2.as_ref()) {
            (Some(m1), Some(m2)) => {
                let r = equivalence::equivalent_modulo_renaming(&f1, &f2, m1, m2)
                    .map_err(|e| ToolError::Analysis(e.to_string()))?;
                Output {
                    equivalent: r.equivalent_under_renaming && r.renaming_total,
                    equivalent_modulo_aps: r.equivalent_under_renaming,
                    ap_mapping_compatible: Some(r.renaming_total),
                    witness: r.witness,
                    direction: r.direction.map(translate_direction),
                }
            }
            _ => {
                let r = equivalence::equivalent_pair(&f1, &f2)
                    .map_err(|e| ToolError::Analysis(e.to_string()))?;
                Output {
                    equivalent: r.equivalent,
                    equivalent_modulo_aps: r.equivalent,
                    ap_mapping_compatible: None,
                    witness: r.witness,
                    direction: r.direction.map(translate_direction),
                }
            }
        };

        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise check_equivalence output: {e}")))
    }
}

fn translate_direction(tag: &'static str) -> String {
    match tag {
        "a_only" => "f1_only".to_string(),
        "b_only" => "f2_only".to_string(),
        other => other.to_string(),
    }
}
