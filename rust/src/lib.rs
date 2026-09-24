//! Library entry points for embedding the PLTL back-end.
//!
//! For most callers, [`parse_from_str`] and [`parse_from_file`] are the
//! only items needed: they deserialise the JSON produced by the OCaml
//! front-end into a strongly-typed [`Formula`].
//!
//! # Global semantic invariants
//!
//! Every analysis in [`analysis`] (and every MCP server that wraps one)
//! assumes the same logical setting. Documenting these here keeps every
//! downstream module from having to redeclare them; they are *baked in*,
//! not configurable.
//!
//! * **Trace**: infinite ω-trace `σ₀ σ₁ σ₂ …`. No prefix / lasso
//!   truncation, no DFA-style finite acceptance. (Finite-trace logics
//!   like LTLf / PLTLf are out of scope.)
//! * **Logic**: PLTL — LTL with past *and* future operators. Pure LTL
//!   is a special case.
//! * **Past at `t = 0`**: strict, Manna-Pnueli convention.
//!   `Y p` is false at `t = 0`; `p S q` is false at `t = 0` unless
//!   `q` holds at `t = 0`.
//! * **Next**: strong (vacuous on infinite traces; included for clarity).
//! * **Primary backends**: Spot for ω-automata + LTL ops; BLACK for
//!   PLTL satisfiability (it supports past). LTLf2DFA is *out* of scope.
//!
//! There is intentionally no `set_semantics_profile` knob. Anything
//! that would have configured these settings is now an invariant; do
//! not thread a semantics parameter through the codebase.

pub mod analysis;
pub mod ast;
pub mod subprocess;

pub use ast::{BinaryOp, Formula, UnaryOp};

use std::fs;

/// Read a JSON file produced by the OCaml parser and deserialise it.
pub fn parse_from_file(filename: &str) -> Result<Formula, Box<dyn std::error::Error>> {
    let json_str = fs::read_to_string(filename)?;
    Ok(serde_json::from_str(&json_str)?)
}

/// Deserialise a JSON-encoded formula from an in-memory string.
pub fn parse_from_str(json: &str) -> Result<Formula, Box<dyn std::error::Error>> {
    Ok(serde_json::from_str(json)?)
}

/// Re-serialise a formula to a pretty-printed JSON string.
pub fn to_json_string(formula: &Formula) -> Result<String, Box<dyn std::error::Error>> {
    Ok(serde_json::to_string_pretty(formula)?)
}
