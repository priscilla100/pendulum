//! Classify a PLTL formula by which temporal operators it uses.
//!
//! Past-time ops, per `pltl_rust::{UnaryOp, BinaryOp}`:
//!   * unary — [`UnaryOp::Yesterday`], [`UnaryOp::Once`],
//!     [`UnaryOp::Historically`]
//!   * binary — [`BinaryOp::Since`], [`BinaryOp::Trigger`]
//!
//! Future-time ops:
//!   * unary — [`UnaryOp::Next`], [`UnaryOp::Eventually`],
//!     [`UnaryOp::Globally`]
//!   * binary — [`BinaryOp::Until`], [`BinaryOp::WeakUntil`],
//!     [`BinaryOp::Release`]
//!
//! Pure-boolean formulas (no temporal operators at all) are classified
//! as [`TemporalClass::FutureOnly`] by convention — they're trivially
//! satisfiable in any future-only fragment. This matches how all the
//! downstream tools (`check_sat`, `synthesize_from_traces`) treat them.

use crate::{BinaryOp, Formula, UnaryOp};

/// Classification of a formula's temporal operator usage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TemporalClass {
    /// Uses only past-time operators (Y, O, H, S, T).
    PastOnly,
    /// Uses only future-time operators (X, F, G, U, W, R), or no
    /// temporal operators at all.
    FutureOnly,
    /// Uses operators from both fragments.
    BothPastAndFuture,
}

/// Run the classification.
///
/// O(size of formula). One recursive pass, two boolean accumulators.
pub fn classify(f: &Formula) -> TemporalClass {
    let mut has_past = false;
    let mut has_future = false;
    walk(f, &mut has_past, &mut has_future);
    match (has_past, has_future) {
        (true, true) => TemporalClass::BothPastAndFuture,
        (true, false) => TemporalClass::PastOnly,
        (false, _) => TemporalClass::FutureOnly,
    }
}

fn walk(f: &Formula, past: &mut bool, future: &mut bool) {
    match f {
        Formula::FTrue | Formula::FFalse | Formula::FAtom { .. } => {}
        Formula::FNot { operand } => walk(operand, past, future),
        Formula::FAnd { left, right }
        | Formula::FOr { left, right }
        | Formula::FImplies { left, right }
        | Formula::FIff { left, right } => {
            walk(left, past, future);
            walk(right, past, future);
        }
        Formula::FUnary { op, operand } => {
            match op {
                UnaryOp::Yesterday | UnaryOp::Once | UnaryOp::Historically => *past = true,
                UnaryOp::Next | UnaryOp::Eventually | UnaryOp::Globally => *future = true,
            }
            walk(operand, past, future);
        }
        Formula::FBinary { op, left, right } => {
            match op {
                BinaryOp::Since | BinaryOp::Trigger => *past = true,
                BinaryOp::Until | BinaryOp::WeakUntil | BinaryOp::Release => *future = true,
            }
            walk(left, past, future);
            walk(right, past, future);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    fn unary(op: UnaryOp, inner: Formula) -> Formula {
        Formula::FUnary {
            op,
            operand: Box::new(inner),
        }
    }

    fn binary(op: BinaryOp, l: Formula, r: Formula) -> Formula {
        Formula::FBinary {
            op,
            left: Box::new(l),
            right: Box::new(r),
        }
    }

    #[test]
    fn pure_boolean_is_future_only() {
        assert_eq!(classify(&atom("p")), TemporalClass::FutureOnly);
    }

    #[test]
    fn yesterday_atom_is_past_only() {
        let f = unary(UnaryOp::Yesterday, atom("p"));
        assert_eq!(classify(&f), TemporalClass::PastOnly);
    }

    #[test]
    fn until_is_future_only() {
        let f = binary(BinaryOp::Until, atom("p"), atom("q"));
        assert_eq!(classify(&f), TemporalClass::FutureOnly);
    }

    #[test]
    fn since_is_past_only() {
        let f = binary(BinaryOp::Since, atom("p"), atom("q"));
        assert_eq!(classify(&f), TemporalClass::PastOnly);
    }

    #[test]
    fn mixed_is_both() {
        // (Y p) U q
        let f = binary(
            BinaryOp::Until,
            unary(UnaryOp::Yesterday, atom("p")),
            atom("q"),
        );
        assert_eq!(classify(&f), TemporalClass::BothPastAndFuture);
    }

    #[test]
    fn negation_of_past_stays_past() {
        let f = Formula::FNot {
            operand: Box::new(unary(UnaryOp::Once, atom("p"))),
        };
        assert_eq!(classify(&f), TemporalClass::PastOnly);
    }

    #[test]
    fn serde_emits_screaming_snake() {
        let s = serde_json::to_string(&TemporalClass::BothPastAndFuture).unwrap();
        assert_eq!(s, r#""BOTH_PAST_AND_FUTURE""#);
    }
}
