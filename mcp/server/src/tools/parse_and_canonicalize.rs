//! `parse_and_canonicalize` — single-call pipeline subsuming
//! syntax-check, NNF, simplify, atom extraction, operator listing,
//! and temporal classification (BTW_TOOLS §1).
//!
//! Plumbing-only tool body.  Calls into the logical functions in
//! `pltl_rust::analysis::{ap, temporal_class, nnf, simplify}`.  The
//! `nnf` and `simplify` logical bodies are still stubbed; while they
//! return `NotImplemented` this tool falls back to echoing the
//! canonical form and adds a warning.  No wire-format change is
//! required once those bodies land.

use crate::tool::{Tool, ToolError};
use async_trait::async_trait;
use pltl_mcp_shared::parse;
use pltl_rust::analysis::ap::atoms;
use pltl_rust::analysis::error::AnalysisError;
use pltl_rust::analysis::nnf::nnf;
use pltl_rust::analysis::simplify::simplify;
use pltl_rust::analysis::temporal_class::{classify, TemporalClass};
use pltl_rust::{BinaryOp, Formula, UnaryOp};
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

const NAME: &str = "parse_and_canonicalize";
const DESCRIPTION: &str = r#"WHAT: Parse a PLTL formula string and validate its syntax. Returns canonical form, atom set, operators used, NNF, simplified form, and Manna-Pnueli temporal class. WHEN to call: on EVERY draft formula before declaring done — the cheapest, most reliable way to catch malformed syntax, Unicode operator slips (use `->`, never `→`), wrong atom names, or unmatched parentheses. Treat any failure as a forced retry. INPUTS: `formula` (string). OUTPUTS: `{valid, canonical, aps, operators, nnf, simplified, temporal_class, warnings, error}`. `temporal_class` is one of PAST_ONLY / FUTURE_ONLY / BOTH / TIMELESS. NOTE: Atom names must match `[a-z][a-z0-9_]*` (lowercase, starts with letter). Pair this with `extract_ap_mapping` so drafted atoms are consistent with the NL grounding."#;

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// PLTL formula in surface syntax.
    formula: String,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    valid: bool,
    error: Option<String>,
    canonical: String,
    nnf: String,
    simplified: String,
    aps: Vec<String>,
    operators: Vec<String>,
    temporal_class: TemporalClass,
    warnings: Vec<String>,
}

/// Marker type. The trait impl carries the logic.
#[derive(Debug, Default, Clone, Copy)]
pub struct ParseAndCanonicalizeTool;

#[async_trait]
impl Tool for ParseAndCanonicalizeTool {
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

        // The OCaml parser is the syntax validator. Bubble up its
        // verbatim message so the caller sees the actual lexer /
        // parser diagnostic.
        let formula = match parse(&parsed.formula) {
            Ok(f) => f,
            Err(pltl_mcp_shared::SharedError::ParserRejected { stderr }) => {
                let body = Output {
                    valid: false,
                    error: Some(stderr),
                    canonical: String::new(),
                    nnf: String::new(),
                    simplified: String::new(),
                    aps: vec![],
                    operators: vec![],
                    temporal_class: TemporalClass::FutureOnly,
                    warnings: vec![],
                };
                return serde_json::to_value(&body)
                    .map_err(|e| ToolError::Internal(format!("serialise: {e}")));
            }
            Err(other) => return Err(ToolError::Internal(other.to_string())),
        };

        let canonical = format!("{formula}");
        let aps: Vec<String> = atoms(&formula).into_iter().collect();
        let operators = collect_operator_codes(&formula);
        let class = classify(&formula);

        // Try the real nnf / simplify logical functions; while their
        // bodies are still stubbed (NotImplemented), fall back to the
        // canonical form and surface a warning so the agent doesn't
        // mistake the echo for the real output.  Any other analysis
        // error escapes via ToolError::Analysis so it doesn't get lost.
        let mut warnings = Vec::new();
        let nnf_form = match nnf(&formula) {
            Ok(f) => format!("{f}"),
            Err(AnalysisError::NotImplemented(_)) => {
                warnings.push("nnf body not yet implemented; echoes canonical".into());
                canonical.clone()
            }
            Err(e) => return Err(ToolError::Analysis(format!("nnf: {e}"))),
        };
        let simplified_form = match simplify(&formula) {
            Ok(f) => format!("{f}"),
            Err(AnalysisError::NotImplemented(_)) => {
                warnings.push("simplify body not yet implemented; echoes canonical".into());
                canonical.clone()
            }
            Err(e) => return Err(ToolError::Analysis(format!("simplify: {e}"))),
        };

        let body = Output {
            valid: true,
            error: None,
            canonical,
            nnf: nnf_form,
            simplified: simplified_form,
            aps,
            operators,
            temporal_class: class,
            warnings,
        };
        serde_json::to_value(&body)
            .map_err(|e| ToolError::Internal(format!("serialise: {e}")))
    }
}

/// Walk the AST and collect operator codes used (`X`, `U`, `Y`, …).
fn collect_operator_codes(f: &Formula) -> Vec<String> {
    let mut seen: BTreeSet<&'static str> = BTreeSet::new();
    fn walk(f: &Formula, out: &mut BTreeSet<&'static str>) {
        match f {
            Formula::FTrue | Formula::FFalse | Formula::FAtom { .. } => {}
            Formula::FNot { operand } => walk(operand, out),
            Formula::FAnd { left, right } => {
                out.insert("&");
                walk(left, out);
                walk(right, out);
            }
            Formula::FOr { left, right } => {
                out.insert("|");
                walk(left, out);
                walk(right, out);
            }
            Formula::FImplies { left, right } => {
                out.insert("->");
                walk(left, out);
                walk(right, out);
            }
            Formula::FIff { left, right } => {
                out.insert("<->");
                walk(left, out);
                walk(right, out);
            }
            Formula::FUnary { op, operand } => {
                out.insert(unary_code(*op));
                walk(operand, out);
            }
            Formula::FBinary { op, left, right } => {
                out.insert(binary_code(*op));
                walk(left, out);
                walk(right, out);
            }
        }
    }
    walk(f, &mut seen);
    seen.into_iter().map(str::to_owned).collect()
}

fn unary_code(op: UnaryOp) -> &'static str {
    match op {
        UnaryOp::Next => "X",
        UnaryOp::Yesterday => "Y",
        UnaryOp::Eventually => "F",
        UnaryOp::Globally => "G",
        UnaryOp::Once => "O",
        UnaryOp::Historically => "H",
    }
}

fn binary_code(op: BinaryOp) -> &'static str {
    match op {
        BinaryOp::Until => "U",
        BinaryOp::Since => "S",
        BinaryOp::WeakUntil => "W",
        BinaryOp::Release => "R",
        BinaryOp::Trigger => "T",
    }
}
