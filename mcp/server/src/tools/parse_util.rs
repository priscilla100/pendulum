//! Tool-side helpers for parsing surface-syntax formulas through the
//! OCaml front-end and mapping parser failures to [`ToolError`].
//!
//! Every deterministic tool that takes one or more `formula: String`
//! arguments goes through these helpers, so the parser-failure
//! diagnostic shape stays consistent across the tool family.

use crate::tool::ToolError;
use pltl_mcp_shared::{parse, SharedError};
use pltl_rust::Formula;

/// Parse a single formula string.  Surface-form rejection becomes
/// `InvalidInput`; everything else (binary missing, IO, decode) is
/// `Internal`.
pub fn parse_one(label: &str, formula_str: &str) -> Result<Formula, ToolError> {
    match parse(formula_str) {
        Ok(f) => Ok(f),
        Err(SharedError::ParserRejected { stderr }) => Err(ToolError::InvalidInput(format!(
            "{label} rejected by parser: {stderr}"
        ))),
        Err(other) => Err(ToolError::Internal(format!("{label}: {other}"))),
    }
}

/// Parse a slice of formula strings.  The first parser rejection
/// surfaces as `InvalidInput` with the offending index.
pub fn parse_all(strings: &[String]) -> Result<Vec<Formula>, ToolError> {
    let mut out = Vec::with_capacity(strings.len());
    for (i, s) in strings.iter().enumerate() {
        out.push(parse_one(&format!("formula[{i}]"), s)?);
    }
    Ok(out)
}
