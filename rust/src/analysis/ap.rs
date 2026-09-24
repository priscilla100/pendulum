//! Atomic-proposition (AP) extraction utility.
//!
//! Only [`atoms`] is exposed — the MCP `extract_ap_mapping` tool lives
//! in `mcp/server/src/tools/extract_ap_mapping.rs` and is LLM-backed;
//! it does its own NL grounding and only borrows this function to
//! collect the atom set from a parsed formula.

use crate::Formula;
use std::collections::BTreeSet;

/// Library-internal: collect atoms from a parsed formula in lex order.
///
/// O(size of formula). Used by `parse_and_canonicalize`, `equivalence`,
/// and the trace tools.
pub fn atoms(f: &Formula) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    collect(f, &mut out);
    out
}

fn collect(f: &Formula, out: &mut BTreeSet<String>) {
    match f {
        Formula::FTrue | Formula::FFalse => {}
        Formula::FAtom { name } => {
            out.insert(name.clone());
        }
        Formula::FNot { operand } | Formula::FUnary { operand, .. } => collect(operand, out),
        Formula::FAnd { left, right }
        | Formula::FOr { left, right }
        | Formula::FImplies { left, right }
        | Formula::FIff { left, right }
        | Formula::FBinary { left, right, .. } => {
            collect(left, out);
            collect(right, out);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{BinaryOp, UnaryOp};

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn atoms_of_compound() {
        // G(p -> q) ∧ Y r
        let lhs = Formula::FUnary {
            op: UnaryOp::Globally,
            operand: Box::new(Formula::FImplies {
                left: Box::new(atom("p")),
                right: Box::new(atom("q")),
            }),
        };
        let rhs = Formula::FUnary {
            op: UnaryOp::Yesterday,
            operand: Box::new(atom("r")),
        };
        let f = Formula::FAnd {
            left: Box::new(lhs),
            right: Box::new(rhs),
        };
        let a: Vec<_> = atoms(&f).into_iter().collect();
        assert_eq!(a, vec!["p".to_string(), "q".to_string(), "r".to_string()]);
    }

    #[test]
    fn atoms_under_binary_op() {
        // p U q
        let f = Formula::FBinary {
            op: BinaryOp::Until,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let a: Vec<_> = atoms(&f).into_iter().collect();
        assert_eq!(a, vec!["p".to_string(), "q".to_string()]);
    }
}
