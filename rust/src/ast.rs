//! PLTL AST mirroring the OCaml front-end.
//!
//! The JSON shape is fixed by `ocaml/ast.ml`. Every variant carries the
//! `"type"` discriminant via `#[serde(tag = "type")]`; unary/binary
//! temporal operator codes (`"X"`, `"U"`, …) are serde-renamed so that
//! the on-wire form matches the OCaml side exactly.

use serde::{Deserialize, Serialize};
use std::fmt;

/// Unary temporal operator. Past-time duals: Yesterday↔Next,
/// Once↔Eventually, Historically↔Globally.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum UnaryOp {
    #[serde(rename = "X")] Next,
    #[serde(rename = "Y")] Yesterday,
    #[serde(rename = "F")] Eventually,
    #[serde(rename = "G")] Globally,
    #[serde(rename = "O")] Once,
    #[serde(rename = "H")] Historically,
}

/// Binary temporal operator. Trigger is the past-time dual of Release.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BinaryOp {
    #[serde(rename = "U")] Until,
    #[serde(rename = "S")] Since,
    #[serde(rename = "W")] WeakUntil,
    #[serde(rename = "R")] Release,
    #[serde(rename = "T")] Trigger,
}

/// PLTL formula. Variant names match the OCaml `formula` constructors so
/// the `"type"` discriminant in the JSON serialises bit-for-bit identically.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Formula {
    FTrue,
    FFalse,
    FAtom { name: String },
    FNot { operand: Box<Formula> },
    FAnd { left: Box<Formula>, right: Box<Formula> },
    FOr { left: Box<Formula>, right: Box<Formula> },
    FImplies { left: Box<Formula>, right: Box<Formula> },
    FIff { left: Box<Formula>, right: Box<Formula> },
    FUnary { op: UnaryOp, operand: Box<Formula> },
    FBinary { op: BinaryOp, left: Box<Formula>, right: Box<Formula> },
}

impl fmt::Display for UnaryOp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            UnaryOp::Next         => "X",
            UnaryOp::Yesterday    => "Y",
            UnaryOp::Eventually   => "F",
            UnaryOp::Globally     => "G",
            UnaryOp::Once         => "O",
            UnaryOp::Historically => "H",
        })
    }
}

impl fmt::Display for BinaryOp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            BinaryOp::Until     => "U",
            BinaryOp::Since     => "S",
            BinaryOp::WeakUntil => "W",
            BinaryOp::Release   => "R",
            BinaryOp::Trigger   => "T",
        })
    }
}

/// Pretty-printer.
///
/// Binary nodes always emit their own surrounding parentheses, mirroring
/// the OCaml printer so a round-trip through pretty-print → re-parse yields
/// the same AST shape.
impl fmt::Display for Formula {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Formula::FTrue              => f.write_str("true"),
            Formula::FFalse             => f.write_str("false"),
            Formula::FAtom { name }     => f.write_str(name),
            Formula::FNot  { operand }  => write!(f, "!{}", operand),
            Formula::FUnary { op, operand } => write!(f, "{} {}", op, operand),
            Formula::FAnd     { left, right } => write!(f, "({} & {})",   left, right),
            Formula::FOr      { left, right } => write!(f, "({} | {})",   left, right),
            Formula::FImplies { left, right } => write!(f, "({} -> {})",  left, right),
            Formula::FIff     { left, right } => write!(f, "({} <-> {})", left, right),
            Formula::FBinary  { op, left, right } => {
                write!(f, "({} {} {})", left, op, right)
            }
        }
    }
}
