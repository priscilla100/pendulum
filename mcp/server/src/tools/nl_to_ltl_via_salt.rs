//! `nl_to_ltl_via_salt` — compile a SALT (Structured Assertion Language
//! for Temporal Logic) specification into a propositional PLTL formula.
//!
//! SALT is a restricted natural-language-ish surface syntax developed at
//! TU München. It compiles deterministically to LTL via the upstream
//! 1.0.1 reference compiler, which we ship in `vendor/salt/`. Compared
//! to the LLM-only path (NL → formula directly), going through SALT:
//!
//! * collapses a huge class of NL patterns to a single declarative
//!   specification (scope operators, counting, sequences, regex);
//! * removes drafting errors — the SALT compiler rejects invalid
//!   specifications with a clear `ERROR:` message that we surface back
//!   to the agent verbatim;
//! * leaves the model free to focus on *paraphrasing the NL into SALT*
//!   instead of *guessing the right combination of temporal operators*.
//!
//! Implementation: shell out to `docker run --rm salt-compiler:latest
//! -notimed -smv -ltl -f "<spec>"`. The container is stateless and
//! costs ~0.8 s per call. Output line is `LTLSPEC <formula>` on success
//! (we strip the prefix); stderr carries the diagnostic on failure
//! (we surface it as `ToolError::Analysis`).
//!
//! Post-processing: the SALT compiler emits SMV-syntax LTL. The only
//! lexical difference from our OCaml parser's surface syntax is the
//! Release operator: SMV writes it `V`, our parser writes it `R`. We
//! rewrite `V` → `R` before returning so the result is directly
//! consumable by `parse_and_canonicalize`.

use crate::tool::{CachePolicy, Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::subprocess::{run_with_timeout, timeout_from_env};
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};
use std::process::{Command, Stdio};

const NAME: &str = "nl_to_ltl_via_salt";

// The DESCRIPTION is intentionally long. SALT is dense; the LLM needs
// the grammar to write a valid spec. Keeping the description
// self-contained (no doc lookup) is the only reliable way to get
// good output on the first try.
const DESCRIPTION: &str = include_str!("nl_to_ltl_via_salt_description.txt");

/// Tool input. The agent supplies a SALT spec; we don't accept raw NL —
/// the LLM is expected to do the NL → SALT paraphrase itself (that's
/// the cheap part). The structured spec then compiles deterministically
/// to LTL.
#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// SALT specification. Must contain at least one `assert <expr>`
    /// line. Multi-line specs (with `declare`, `define` macros) are
    /// supported; just join with newlines.
    spec: String,

    /// Optional: forbid past operators (`once`, `since`, etc.). Off
    /// by default — past operators are supported downstream.
    #[serde(default)]
    forbid_past: bool,

    /// Optional: forbid `next` (and anything that desugars through it
    /// — notably regular expressions). Off by default.
    #[serde(default)]
    forbid_next: bool,
}

/// Tool output. `ok` is the verdict; on success `ltl` contains the
/// compiled formula (in our OCaml parser's syntax — `V` already
/// rewritten to `R`); on failure `error` carries SALT's diagnostic.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
struct Output {
    /// True when the SALT compiler accepted the spec and we got a
    /// formula back.
    ok: bool,
    /// On success: the LTL formula, ready to feed to `parse_and_canonicalize`.
    #[serde(skip_serializing_if = "Option::is_none")]
    ltl: Option<String>,
    /// On failure: SALT's verbatim error message (parse error,
    /// undeclared variable, forbidden operator, etc.).
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    /// On success: the raw output line for debugging (`LTLSPEC ...`).
    #[serde(skip_serializing_if = "Option::is_none")]
    raw: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the
/// type is stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct NlToLtlViaSaltTool;

#[async_trait]
impl Tool for NlToLtlViaSaltTool {
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
        // The SALT compiler is fully deterministic, so the registry
        // can cache aggressively.
        CachePolicy::default()
    }
    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let parsed: Input = serde_json::from_value(input)
            .map_err(|e| ToolError::InvalidInput(format!("schema: {e}")))?;
        if parsed.spec.trim().is_empty() {
            return Err(ToolError::InvalidInput(
                "nl_to_ltl_via_salt: `spec` must be non-empty".into(),
            ));
        }
        let result = compile_via_salt(&parsed.spec, parsed.forbid_past, parsed.forbid_next)?;
        serde_json::to_value(result).map_err(|e| ToolError::Internal(format!("serialize: {e}")))
    }
}

/// Shell out to docker and run the SALT compiler. Errors surface as
/// `ToolError::Analysis` (input rejected) or `ToolError::Internal`
/// (infrastructure problem — docker missing, image missing, timeout).
fn compile_via_salt(
    spec: &str,
    forbid_past: bool,
    forbid_next: bool,
) -> Result<Output, ToolError> {
    let docker = std::env::var("SALT_DOCKER_BIN").unwrap_or_else(|_| "docker".to_string());
    let image = std::env::var("SALT_IMAGE").unwrap_or_else(|_| "salt-compiler:latest".to_string());
    let timeout = timeout_from_env("SALT_TIMEOUT_SECS", 30);

    let mut args: Vec<String> = vec![
        "run".into(),
        "--rm".into(),
        "-i".into(),
        image.clone(),
        "-notimed".into(),
        "-smv".into(),
        "-ltl".into(),
    ];
    if forbid_past {
        args.push("-nopast".into());
    }
    if forbid_next {
        args.push("-nonext".into());
    }
    args.push("-f".into());
    args.push(spec.to_string());

    let mut cmd = Command::new(&docker);
    cmd.args(&args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = run_with_timeout(cmd, timeout, "SALT compiler")
        .map_err(|e| ToolError::Internal(e.to_string()))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    // The README is explicit: exit 0 + stdout starting with `LTLSPEC` is
    // success; anything else is rejection.
    if output.status.success() && stdout.trim_start().starts_with("LTLSPEC") {
        let raw = stdout.trim().to_string();
        let formula = extract_formula_from_ltlspec(&raw);
        let rewritten = rewrite_smv_to_ocaml(&formula);
        // Defensive check per README §2.2 — SALT 1.0.1 never emits `Z`
        // in SMV mode, but if a future version does, we surface it as
        // an error rather than feed garbage downstream.
        if contains_word(&rewritten, "Z") {
            return Ok(Output {
                ok: false,
                ltl: None,
                error: Some(format!(
                    "SALT emitted the `Z` (weak previous) operator, which our \
                     parser does not support. Rewrite the spec to avoid \
                     `previous weak`. Raw output: {raw}"
                )),
                raw: Some(raw),
            });
        }
        Ok(Output {
            ok: true,
            ltl: Some(rewritten),
            error: None,
            raw: Some(raw),
        })
    } else {
        // SALT writes diagnostics to stderr. If the image is missing,
        // docker itself surfaces an error on stderr too — same surface,
        // different cause.
        let msg = if !stderr.trim().is_empty() {
            stderr.trim().to_string()
        } else if !stdout.trim().is_empty() {
            stdout.trim().to_string()
        } else {
            format!(
                "SALT compiler exited with status {} but produced no output",
                output.status
            )
        };
        // Detect the "image missing" case so we can give a clearer message.
        let is_image_missing = msg.contains("Unable to find image") || msg.contains("not found");
        let error = if is_image_missing {
            format!(
                "SALT docker image `{image}` not found. Build it once with: \
                 `docker build -t {image} vendor/salt/`. Underlying error: {msg}"
            )
        } else {
            msg
        };
        Ok(Output {
            ok: false,
            ltl: None,
            error: Some(error),
            raw: None,
        })
    }
}

/// Strip the `LTLSPEC ` prefix from SALT's output. If the input doesn't
/// start with `LTLSPEC`, return it unchanged.
pub fn extract_formula_from_ltlspec(s: &str) -> String {
    let trimmed = s.trim();
    trimmed
        .strip_prefix("LTLSPEC")
        .map(|rest| rest.trim().to_string())
        .unwrap_or_else(|| trimmed.to_string())
}

/// Rewrite SMV-only operator letters into the equivalents our OCaml
/// parser accepts. Currently only `V` → `R`. Other SMV letters
/// (`G F X U Y H O S T`) already match our parser. `Z` is filtered
/// upstream as a hard rejection.
pub fn rewrite_smv_to_ocaml(s: &str) -> String {
    rewrite_word(s, 'V', 'R')
}

/// Replace standalone-letter occurrences of `from` with `to`. A
/// standalone letter is one that is preceded and followed by non-
/// alphanumeric, non-underscore characters (or by the boundary).
fn rewrite_word(s: &str, from: char, to: char) -> String {
    let bytes = s.as_bytes();
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == from {
            let prev_ok = i == 0 || !is_word_byte(bytes[i - 1]);
            let next_ok = i + 1 == bytes.len() || !is_word_byte(bytes[i + 1]);
            if prev_ok && next_ok {
                out.push(to);
                i += 1;
                continue;
            }
        }
        out.push(c);
        i += 1;
    }
    out
}

fn is_word_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// True iff `s` contains the single character `letter` as a standalone
/// word (same boundary rules as `rewrite_word`).
fn contains_word(s: &str, letter: &str) -> bool {
    if letter.is_empty() {
        return false;
    }
    let bytes = s.as_bytes();
    let lbytes = letter.as_bytes();
    let mut i = 0;
    while i + lbytes.len() <= bytes.len() {
        if &bytes[i..i + lbytes.len()] == lbytes {
            let prev_ok = i == 0 || !is_word_byte(bytes[i - 1]);
            let next_ok = i + lbytes.len() == bytes.len() || !is_word_byte(bytes[i + lbytes.len()]);
            if prev_ok && next_ok {
                return true;
            }
        }
        i += 1;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_formula_strips_ltlspec_prefix() {
        let raw = "LTLSPEC G (p -> (F q))";
        assert_eq!(extract_formula_from_ltlspec(raw), "G (p -> (F q))");
    }

    #[test]
    fn extract_formula_handles_no_prefix() {
        // Pathological: the prefix should always be there in SALT
        // output, but if it isn't we don't crash.
        assert_eq!(extract_formula_from_ltlspec(" G p "), "G p");
    }

    #[test]
    fn rewrite_v_to_r_replaces_standalone_v() {
        // `V` is SMV's Release operator letter; our parser uses `R`.
        let smv = "a V b";
        assert_eq!(rewrite_smv_to_ocaml(smv), "a R b");
    }

    #[test]
    fn rewrite_v_to_r_preserves_atom_names() {
        // `vacant` and `V_NAME` are atom names; don't touch their `V`s.
        let s = "vacant & V_NAME & a V b";
        assert_eq!(rewrite_smv_to_ocaml(s), "vacant & V_NAME & a R b");
    }

    #[test]
    fn rewrite_v_to_r_handles_parens() {
        let smv = "((a) V (b))";
        assert_eq!(rewrite_smv_to_ocaml(smv), "((a) R (b))");
    }

    #[test]
    fn contains_word_detects_standalone_z() {
        assert!(contains_word("a Z b", "Z"));
        assert!(contains_word("Z & b", "Z"));
        assert!(contains_word("a & Z", "Z"));
    }

    #[test]
    fn contains_word_ignores_atoms_containing_z() {
        assert!(!contains_word("zoo & abz & azZ_z", "Z"));
    }

    #[test]
    fn schema_is_object() {
        let t = NlToLtlViaSaltTool;
        let schema = t.input_schema();
        assert_eq!(schema["type"], "object");
    }

    /// Live round-trip against the docker container. Ignored by
    /// default — opt-in via `--ignored`. Requires
    /// `salt-compiler:latest` to be built locally:
    ///   `docker build -t salt-compiler:latest vendor/salt/`
    #[tokio::test]
    #[ignore = "requires docker + salt-compiler:latest image"]
    async fn live_round_trip_simple_response_pattern() {
        let t = NlToLtlViaSaltTool;
        let input = serde_json::json!({
            "spec": "assert always (request implies eventually answer)"
        });
        let raw = t.call(input).await.expect("tool ran");
        let out: Output = serde_json::from_value(raw).expect("output schema");
        assert!(out.ok, "expected ok=true, got error: {:?}", out.error);
        assert_eq!(out.ltl.as_deref(), Some("G (request -> (F answer))"));
        assert_eq!(out.raw.as_deref(), Some("LTLSPEC G (request -> (F answer))"));
    }

    /// Live test that the V→R rewrite triggers on a release pattern.
    #[tokio::test]
    #[ignore = "requires docker + salt-compiler:latest image"]
    async fn live_round_trip_release_emits_r_not_v() {
        let t = NlToLtlViaSaltTool;
        let input = serde_json::json!({
            "spec": "assert a releases b"
        });
        let raw = t.call(input).await.expect("tool ran");
        let out: Output = serde_json::from_value(raw).expect("output schema");
        assert!(out.ok, "expected ok=true, got error: {:?}", out.error);
        let ltl = out.ltl.unwrap();
        assert!(ltl.contains(" R "), "expected R operator in {ltl}");
        assert!(!ltl.contains(" V "), "V not rewritten in {ltl}");
        let raw_line = out.raw.unwrap();
        assert!(raw_line.contains(" V "), "expected raw to keep V: {raw_line}");
    }

    /// Live test that a deliberately-broken spec is surfaced as
    /// `ok=false` with the SALT compiler's verbatim error.
    #[tokio::test]
    #[ignore = "requires docker + salt-compiler:latest image"]
    async fn live_round_trip_invalid_spec_surfaces_error() {
        let t = NlToLtlViaSaltTool;
        let input = serde_json::json!({
            // Missing the right-side modifiers on `upto` — SALT
            // rejects with a specific error.
            "spec": "assert always p upto q"
        });
        let raw = t.call(input).await.expect("tool ran");
        let out: Output = serde_json::from_value(raw).expect("output schema");
        assert!(!out.ok, "expected failure, got ltl: {:?}", out.ltl);
        let err = out.error.unwrap_or_default();
        assert!(
            err.contains("ERROR") || err.contains("inclusive") || err.contains("modifier"),
            "expected SALT-style diagnostic, got: {err}"
        );
    }
}
