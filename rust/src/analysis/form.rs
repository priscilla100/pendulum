//! Small constructor helpers for building `Formula` trees in the
//! analyses' orchestration plumbing.
//!
//! Every analysis that calls into `sat::decide_sat` ends up wanting
//! `a & b`, `!b`, or `∧ formulas`. Keeping the boxing details here means
//! callers don't repeat `Box::new(...)` rituals at every entailment /
//! equivalence / consistency site.
//!
//! These helpers *clone* their inputs. Cloning a `Formula` is O(size),
//! and the analyses that use these helpers already pay that cost when
//! building the SAT query — pulling clones into the helpers keeps the
//! call sites short.

use crate::Formula;

/// `a ∧ b`.
pub fn and(a: Formula, b: Formula) -> Formula {
    Formula::FAnd {
        left: Box::new(a),
        right: Box::new(b),
    }
}

/// `a ∨ b`.
pub fn or(a: Formula, b: Formula) -> Formula {
    Formula::FOr {
        left: Box::new(a),
        right: Box::new(b),
    }
}

/// `¬a`.
pub fn not(a: Formula) -> Formula {
    Formula::FNot {
        operand: Box::new(a),
    }
}

/// `a → b`.
pub fn implies(a: Formula, b: Formula) -> Formula {
    Formula::FImplies {
        left: Box::new(a),
        right: Box::new(b),
    }
}

/// `a ∧ ¬b`. Used by entailment / equivalence to encode "violates".
pub fn and_not(a: &Formula, b: &Formula) -> Formula {
    and(a.clone(), not(b.clone()))
}

/// Fold a slice of formulas into a single conjunction.
///
/// Returns `None` when the slice is empty (the caller is expected to
/// reject empty input upstream — using `None` here keeps this helper
/// total without an unwrap).
pub fn conjunction(formulas: &[Formula]) -> Option<Formula> {
    let mut iter = formulas.iter().cloned();
    let mut acc = iter.next()?;
    for f in iter {
        acc = and(acc, f);
    }
    Some(acc)
}

/// Fold a slice of formulas into a single disjunction.
pub fn disjunction(formulas: &[Formula]) -> Option<Formula> {
    let mut iter = formulas.iter().cloned();
    let mut acc = iter.next()?;
    for f in iter {
        acc = or(acc, f);
    }
    Some(acc)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn conjunction_of_one_is_identity() {
        let p = atom("p");
        assert_eq!(conjunction(std::slice::from_ref(&p)), Some(p));
    }

    #[test]
    fn conjunction_of_empty_is_none() {
        assert_eq!(conjunction(&[]), None);
    }

    #[test]
    fn conjunction_left_folds() {
        let p = atom("p");
        let q = atom("q");
        let r = atom("r");
        // ((p ∧ q) ∧ r)
        let expected = and(and(p.clone(), q.clone()), r.clone());
        assert_eq!(conjunction(&[p, q, r]), Some(expected));
    }

    #[test]
    fn and_not_shape() {
        let p = atom("p");
        let q = atom("q");
        let got = and_not(&p, &q);
        let expected = and(p, not(q));
        assert_eq!(got, expected);
    }
}
