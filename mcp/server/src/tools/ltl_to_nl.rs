//! `ltl_to_nl` — verify a candidate formula by paraphrasing it back to NL.
//!
//! Three-step pipeline:
//!   1. Parse the formula via the OCaml front-end into a typed `Formula`.
//!   2. Render it as a verbose, semantics-preserving "temporary NL" (TNL)
//!      string via [`pltl_rust::analysis::ltl_to_tnl::ltl_to_tnl`].
//!   3. Ask a helper LLM (`PLTL_TOOL_LLM_MODEL`) to produce **5
//!      paraphrases** of the TNL that read naturally while preserving
//!      its meaning exactly.
//!
//! The agent should call this tool after committing to a candidate
//! formula and BEFORE returning a final answer. Comparing the 5
//! paraphrases against the user's original sentence is how the agent
//! catches its own translation mistakes without re-asking the user.
//!
//! LLM-backed. The TNL renderer is deterministic; only the paraphrase
//! step touches the model.

use crate::llm::ToolLlmClient;
use crate::tool::{CachePolicy, Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::analysis::ltl_to_tnl::ltl_to_tnl;
use schemars::{schema_for, JsonSchema};
use serde::Deserialize;

const NAME: &str = "ltl_to_nl";
const DESCRIPTION: &str = r#"WHAT: Convert a PLTL formula into 5 natural-language paraphrases with semantics preserved. 
WHEN: Call AFTER drafting a candidate formula, BEFORE returning the final answer. 
Compare each paraphrase to the user's original sentence; if none matches the user's meaning, 
the formula is wrong - revise and re-verify. 
INPUTS: `formula` (PLTL surface syntax). 
OUTPUTS: `{tnl: string, paraphrases: [string; 5]}`. `tnl` is the literal recursive translation (verbose but exact); 
`paraphrases` are the natural-English rephrasings of `tnl`. 
NOTE: the TNL is a faithful witness; if a paraphrase contradicts the TNL the paraphrase is wrong, not the TNL."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// PLTL formula in any accepted surface syntax.
    formula: String,
}

/// Tool implementation marker. Trait impl carries all logic; the
/// type is stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct LtlToNlTool;

#[async_trait]
impl Tool for LtlToNlTool {
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
        CachePolicy {
            temperature: Some(0.0),
            seed: Some(7),
        }
    }

    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let parsed: Input = serde_json::from_value(input)
            .map_err(|e| ToolError::InvalidInput(format!("schema: {e}")))?;
        if parsed.formula.trim().is_empty() {
            return Err(ToolError::InvalidInput(
                "ltl_to_nl: `formula` is required".into(),
            ));
        }
        let formula = pltl_mcp_shared::parse(&parsed.formula)
            .map_err(|e| ToolError::InvalidInput(format!("parser: {e}")))?;
        let tnl = ltl_to_tnl(&formula);

        let client = ToolLlmClient::from_env()?;
        let format_schema = response_schema();
        let user = render_user_prompt(&tnl, &parsed.formula);
        let prompt = system_prompt();
        let value = client
            .structured_chat(prompt.as_ref(), &user, format_schema)
            .await?;
        let paraphrases = extract_paraphrases(&value)?;

        Ok(serde_json::json!({
            "tnl": tnl,
            "paraphrases": paraphrases,
        }))
    }
}

fn render_user_prompt(tnl: &str, formula: &str) -> String {
    format!(
        "Formula (PLTL surface syntax): {formula}\n\n\
         Temporary NL (TNL — faithful but stilted):\n{tnl}\n\n\
         Return ONLY a JSON object {{\"paraphrases\": [s1, s2, s3, s4, s5]}}.\n\
         Each si is a paraphrase of the TNL that reads as natural English while \
         preserving the TNL's meaning EXACTLY. Vary phrasing across the 5 \
         paraphrases. No prose outside the JSON. No markdown."
    )
}

fn extract_paraphrases(v: &serde_json::Value) -> Result<Vec<String>, ToolError> {
    let arr = v
        .get("paraphrases")
        .and_then(|x| x.as_array())
        .ok_or_else(|| {
            ToolError::Analysis("ltl_to_nl: response missing array `paraphrases`".into())
        })?;
    if arr.len() != 5 {
        return Err(ToolError::Analysis(format!(
            "ltl_to_nl: expected 5 paraphrases, got {}",
            arr.len()
        )));
    }
    let mut out = Vec::with_capacity(5);
    for (i, x) in arr.iter().enumerate() {
        let s = x.as_str().ok_or_else(|| {
            ToolError::Analysis(format!("ltl_to_nl: paraphrases[{i}] is not a string"))
        })?;
        if s.trim().is_empty() {
            return Err(ToolError::Analysis(format!(
                "ltl_to_nl: paraphrases[{i}] is empty"
            )));
        }
        out.push(s.to_string());
    }
    Ok(out)
}

fn response_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["paraphrases"],
        "properties": {
            "paraphrases": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": { "type": "string", "minLength": 1 }
            }
        }
    })
}

const SYSTEM_PROMPT_DEFAULT: &str =
    include_str!("../../prompts/ltl_to_nl_system.md");

/// Hot-swappable system prompt for this tool. See
/// [`crate::prompt_loader`] for resolution order.
fn system_prompt() -> std::borrow::Cow<'static, str> {
    crate::prompt_loader::load_tool_prompt(
        "ltl_to_nl_system.md",
        SYSTEM_PROMPT_DEFAULT,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_well_formed() {
        let s = response_schema();
        assert!(s.is_object());
        assert!(s.get("required").is_some());
    }

    #[test]
    fn input_schema_requires_formula() {
        let t = LtlToNlTool;
        let s = t.input_schema();
        let req = s.get("required").and_then(|x| x.as_array()).unwrap();
        let names: Vec<&str> = req.iter().filter_map(|v| v.as_str()).collect();
        assert!(names.contains(&"formula"));
    }

    #[test]
    fn extract_rejects_short_array() {
        let v = serde_json::json!({"paraphrases": ["a", "b"]});
        assert!(extract_paraphrases(&v).is_err());
    }

    #[test]
    fn extract_rejects_long_array() {
        let v = serde_json::json!({
            "paraphrases": ["a", "b", "c", "d", "e", "f"]
        });
        assert!(extract_paraphrases(&v).is_err());
    }

    #[test]
    fn extract_rejects_empty_string() {
        let v = serde_json::json!({"paraphrases": ["a", "b", "c", "d", ""]});
        assert!(extract_paraphrases(&v).is_err());
    }

    #[test]
    fn extract_rejects_non_string_element() {
        let v = serde_json::json!({"paraphrases": ["a", "b", "c", "d", 42]});
        assert!(extract_paraphrases(&v).is_err());
    }

    #[test]
    fn extract_rejects_missing_field() {
        let v = serde_json::json!({"oops": []});
        assert!(extract_paraphrases(&v).is_err());
    }

    #[test]
    fn extract_accepts_five() {
        let v = serde_json::json!({
            "paraphrases": ["one", "two", "three", "four", "five"]
        });
        let r = extract_paraphrases(&v).unwrap();
        assert_eq!(r.len(), 5);
        assert_eq!(r[0], "one");
        assert_eq!(r[4], "five");
    }

    #[test]
    fn system_prompt_loads_landmark() {
        let s = system_prompt();
        assert!(
            s.contains("paraphrasing specialist"),
            "expected landmark phrase in ltl_to_nl system prompt; got: {}",
            &s[..s.len().min(120)]
        );
    }

    #[test]
    fn system_prompt_default_constant_nonempty() {
        assert!(!SYSTEM_PROMPT_DEFAULT.trim().is_empty());
    }

    #[tokio::test]
    async fn rejects_blank_formula() {
        let t = LtlToNlTool;
        let r = t
            .call(serde_json::json!({"formula": "   "}))
            .await;
        assert!(matches!(r, Err(ToolError::InvalidInput(_))));
    }

    #[tokio::test]
    async fn rejects_missing_formula() {
        let t = LtlToNlTool;
        let r = t.call(serde_json::json!({})).await;
        assert!(matches!(r, Err(ToolError::InvalidInput(_))));
    }
}
