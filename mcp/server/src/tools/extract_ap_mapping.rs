//! `extract_ap_mapping` — atomic propositions + NL fragment grounding.
//!
//! Takes natural-language text (and optionally a candidate formula)
//! and returns the AP vocabulary the formula uses, the NL fragment
//! each atom names, polarity (event/state), and any open grounding
//! questions.
//!
//! The prompt follows the **principle of maximum revelation**:
//! introduce one atom per atomic predicate the NL exposes, even when
//! some atoms aren't immediately used by the obvious formula — a
//! subsequent translation pass may need the extra vocabulary, and
//! discarding revealed-but-unused atoms loses information. We forbid
//! the inverse failure (folding two distinct predicates into one
//! atom).
//!
//! LLM-backed. Configurable model via `PLTL_TOOL_LLM_MODEL`.

use crate::llm::ToolLlmClient;
use crate::tool::{CachePolicy, Tool, ToolError};
use async_trait::async_trait;
use schemars::{schema_for, JsonSchema};
use serde::Deserialize;

const NAME: &str = "extract_ap_mapping";
const DESCRIPTION: &str = r#"WHAT: Extract atomic propositions from NL text (optionally also anchored to a candidate formula) following the principle of maximum revelation: one atom per distinct atomic predicate the NL exposes, even ones a minimal formula wouldn't strictly need. LLM-backed (separate helper model via PLTL_TOOL_LLM_MODEL). WHEN: Call FIRST on any NL input before drafting a formula. Skip only if the user pre-supplied a mapping verbatim. INPUTS: `text` (NL string), optional `formula` (to anchor the atom set). At least one must be present. OUTPUTS: `{aps: [{name, nl_fragment, polarity, negated?, notes?}], open_questions: [string]}`. `polarity` is `event` (transition) or `state` (sustained). `open_questions` flag aliasing decisions the user should confirm. NOTE: Names follow the lexer rule `[a-z][a-z0-9_]*`. Aliased phrases share one atom and list both in `nl_fragment` (joined by ' | ')."#;

/// Tool input schema; derived JsonSchema is published via `input_schema()`.
#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Natural-language source. At least one of `text` / `formula` must be present.
    #[serde(default)]
    text: Option<String>,
    /// Optional candidate formula whose atoms anchor the mapping.
    #[serde(default)]
    formula: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the type is
/// stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct ExtractApMappingTool;

#[async_trait]
impl Tool for ExtractApMappingTool {
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
        // temperature=0 + seed=7 -> replayable.
        CachePolicy {
            temperature: Some(0.0),
            seed: Some(7),
        }
    }

    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let parsed: Input = serde_json::from_value(input)
            .map_err(|e| ToolError::InvalidInput(format!("schema: {e}")))?;
        if parsed.text.as_deref().map(str::trim).unwrap_or("").is_empty()
            && parsed
                .formula
                .as_deref()
                .map(str::trim)
                .unwrap_or("")
                .is_empty()
        {
            return Err(ToolError::InvalidInput(
                "extract_ap_mapping requires at least one of `text` or `formula`".into(),
            ));
        }
        let client = ToolLlmClient::from_env()?;
        let format_schema = response_schema();
        let user = render_user_prompt(parsed.text.as_deref(), parsed.formula.as_deref());
        let prompt = system_prompt();
        let value = client
            .structured_chat(prompt.as_ref(), &user, format_schema)
            .await?;
        validate_response_shape(&value)?;
        Ok(value)
    }
}

const SYSTEM_PROMPT_DEFAULT: &str =
    include_str!("../../prompts/extract_ap_mapping_system.md");

/// Hot-swappable system prompt for this tool. See
/// [`crate::prompt_loader`] for resolution order.
fn system_prompt() -> std::borrow::Cow<'static, str> {
    crate::prompt_loader::load_tool_prompt(
        "extract_ap_mapping_system.md",
        SYSTEM_PROMPT_DEFAULT,
    )
}

fn render_user_prompt(text: Option<&str>, formula: Option<&str>) -> String {
    let mut out = String::new();
    if let Some(t) = text {
        if !t.trim().is_empty() {
            out.push_str("NL statement:\n");
            out.push_str(t);
            out.push_str("\n\n");
        }
    }
    if let Some(f) = formula {
        if !f.trim().is_empty() {
            out.push_str("Candidate formula (its atoms anchor the mapping):\n");
            out.push_str(f);
            out.push_str("\n\n");
        }
    }
    out.push_str(
        "Return ONLY the JSON object described in the system prompt. \
         No prose, no markdown.\n",
    );
    out
}

fn validate_response_shape(v: &serde_json::Value) -> Result<(), ToolError> {
    let obj = v.as_object().ok_or_else(|| {
        ToolError::Analysis("extract_ap_mapping: response is not an object".into())
    })?;
    let aps = obj.get("aps").and_then(|x| x.as_array()).ok_or_else(|| {
        ToolError::Analysis("extract_ap_mapping: response missing array `aps`".into())
    })?;
    for (i, a) in aps.iter().enumerate() {
        let ao = a.as_object().ok_or_else(|| {
            ToolError::Analysis(format!("extract_ap_mapping: aps[{i}] is not an object"))
        })?;
        for k in &["name", "nl_fragment", "polarity"] {
            if !ao.contains_key(*k) {
                return Err(ToolError::Analysis(format!(
                    "extract_ap_mapping: aps[{i}] missing `{k}`"
                )));
            }
        }
        let name = ao.get("name").and_then(|x| x.as_str()).unwrap_or("");
        if !is_valid_atom_name(name) {
            return Err(ToolError::Analysis(format!(
                "extract_ap_mapping: aps[{i}].name = `{name}` violates lexer rule \
                 `[a-z][a-z0-9_]*`"
            )));
        }
        let polarity = ao.get("polarity").and_then(|x| x.as_str()).unwrap_or("");
        if !matches!(polarity, "event" | "state") {
            return Err(ToolError::Analysis(format!(
                "extract_ap_mapping: aps[{i}].polarity = `{polarity}` must be `event` or `state`"
            )));
        }
    }
    Ok(())
}

fn is_valid_atom_name(s: &str) -> bool {
    let mut it = s.chars();
    match it.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return false,
    }
    it.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

fn response_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["aps", "open_questions"],
        "properties": {
            "aps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": false,
                    "required": ["name", "nl_fragment", "polarity"],
                    "properties": {
                        "name":        { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
                        "nl_fragment": { "type": "string" },
                        "polarity":    { "type": "string", "enum": ["event", "state"] },
                        "negated":     { "type": "boolean" },
                        "notes":       { "type": "string" }
                    }
                }
            },
            "open_questions": {
                "type": "array",
                "items": { "type": "string" }
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_prompt_loads_landmark() {
        let s = system_prompt();
        assert!(
            s.contains("atom-grounding specialist"),
            "expected landmark phrase in extract_ap_mapping system prompt; got: {}",
            &s[..s.len().min(120)]
        );
    }

    #[test]
    fn system_prompt_default_constant_nonempty() {
        assert!(!SYSTEM_PROMPT_DEFAULT.trim().is_empty());
    }
}
