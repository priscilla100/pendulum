//! Library-internal: Negation Normal Form.
//!
//! Push every `¬` down to the atoms. The strong-yesterday convention
//! (matching the crate-level "past at t=0 strict" invariant):
//! `¬Y p ≡ Y ¬p`. Other dualities follow the standard PLTL table.

use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::{BinaryOp, Formula, UnaryOp};

/// Return the Negation Normal Form of `f`.
///
/// NNF is obtained by recursively pushing `¬` toward the leaves using
/// the standard PLTL duality table:
///
/// ```text
/// ¬¬p      ≡ p
/// ¬(A & B) ≡ ¬A | ¬B
/// ¬(A | B) ≡ ¬A & ¬B
/// ¬(A→B)   ≡ A & ¬B
/// ¬(A↔B)   ≡ (A & ¬B) | (¬A & B)
/// ¬G p     ≡ F ¬p          ¬F p ≡ G ¬p          ¬X p ≡ X ¬p
/// ¬H p     ≡ O ¬p          ¬O p ≡ H ¬p          ¬Y p ≡ Y ¬p   (strong-Y)
/// ¬(p U q) ≡ ¬q W (¬p ∧ ¬q)
/// ¬(p W q) ≡ ¬q U (¬p ∧ ¬q)
/// ¬(p R q) ≡ ¬p U ¬q
/// ¬(p S q) ≡ ¬q T (¬p ∧ ¬q)
/// ¬(p T q) ≡ ¬p S ¬q
/// ```
///
/// Convention choice: for `¬(p U q)` we emit `¬q W (¬p ∧ ¬q)` rather than
/// the equivalent `¬p R ¬q`; this keeps the W/U pair self-dual under
/// `nnf` and mirrors `¬(p S q)` which has no Release-equivalent in PLTL.
pub fn nnf(f: &Formula) -> Result<Formula, AnalysisError> {
    Ok(nnf_pos(f))
}

/// NNF of `f` with no outstanding negation to push down.
fn nnf_pos(f: &Formula) -> Formula {
    match f {
        Formula::FTrue => Formula::FTrue,
        Formula::FFalse => Formula::FFalse,
        Formula::FAtom { name } => Formula::FAtom { name: name.clone() },
        Formula::FNot { operand } => nnf_neg(operand),
        Formula::FAnd { left, right } => form::and(nnf_pos(left), nnf_pos(right)),
        Formula::FOr { left, right } => form::or(nnf_pos(left), nnf_pos(right)),
        Formula::FImplies { left, right } => {
            // A → B ≡ ¬A ∨ B
            form::or(nnf_neg(left), nnf_pos(right))
        }
        Formula::FIff { left, right } => {
            // A ↔ B ≡ (A ∧ B) ∨ (¬A ∧ ¬B)
            let l_pos = nnf_pos(left);
            let r_pos = nnf_pos(right);
            let l_neg = nnf_neg(left);
            let r_neg = nnf_neg(right);
            form::or(form::and(l_pos, r_pos), form::and(l_neg, r_neg))
        }
        Formula::FUnary { op, operand } => Formula::FUnary {
            op: *op,
            operand: Box::new(nnf_pos(operand)),
        },
        Formula::FBinary { op, left, right } => Formula::FBinary {
            op: *op,
            left: Box::new(nnf_pos(left)),
            right: Box::new(nnf_pos(right)),
        },
    }
}

/// NNF of `¬f`. Applies one duality step at the top, then recurses
/// via `nnf_pos` / `nnf_neg` on the sub-results.
fn nnf_neg(f: &Formula) -> Formula {
    match f {
        Formula::FTrue => Formula::FFalse,
        Formula::FFalse => Formula::FTrue,
        // ¬p stays as ¬p (negation rests on atom).
        Formula::FAtom { name } => form::not(Formula::FAtom { name: name.clone() }),
        // ¬¬a ≡ a
        Formula::FNot { operand } => nnf_pos(operand),
        // ¬(A & B) ≡ ¬A ∨ ¬B
        Formula::FAnd { left, right } => form::or(nnf_neg(left), nnf_neg(right)),
        // ¬(A | B) ≡ ¬A ∧ ¬B
        Formula::FOr { left, right } => form::and(nnf_neg(left), nnf_neg(right)),
        // ¬(A → B) ≡ A ∧ ¬B
        Formula::FImplies { left, right } => form::and(nnf_pos(left), nnf_neg(right)),
        // ¬(A ↔ B) ≡ (A ∧ ¬B) ∨ (¬A ∧ B)
        Formula::FIff { left, right } => {
            let l_pos = nnf_pos(left);
            let r_pos = nnf_pos(right);
            let l_neg = nnf_neg(left);
            let r_neg = nnf_neg(right);
            form::or(form::and(l_pos, r_neg), form::and(l_neg, r_pos))
        }
        Formula::FUnary { op, operand } => {
            // Dual operator with negated operand.
            let dual = match op {
                UnaryOp::Next => UnaryOp::Next,
                UnaryOp::Yesterday => UnaryOp::Yesterday, // strong-Y convention
                UnaryOp::Eventually => UnaryOp::Globally,
                UnaryOp::Globally => UnaryOp::Eventually,
                UnaryOp::Once => UnaryOp::Historically,
                UnaryOp::Historically => UnaryOp::Once,
            };
            Formula::FUnary {
                op: dual,
                operand: Box::new(nnf_neg(operand)),
            }
        }
        Formula::FBinary { op, left, right } => match op {
            // ¬(p U q) ≡ ¬q W (¬p ∧ ¬q)
            BinaryOp::Until => {
                let np = nnf_neg(left);
                let nq = nnf_neg(right);
                Formula::FBinary {
                    op: BinaryOp::WeakUntil,
                    left: Box::new(nq.clone()),
                    right: Box::new(form::and(np, nq)),
                }
            }
            // ¬(p W q) ≡ ¬q U (¬p ∧ ¬q)
            BinaryOp::WeakUntil => {
                let np = nnf_neg(left);
                let nq = nnf_neg(right);
                Formula::FBinary {
                    op: BinaryOp::Until,
                    left: Box::new(nq.clone()),
                    right: Box::new(form::and(np, nq)),
                }
            }
            // ¬(p R q) ≡ ¬p U ¬q
            BinaryOp::Release => Formula::FBinary {
                op: BinaryOp::Until,
                left: Box::new(nnf_neg(left)),
                right: Box::new(nnf_neg(right)),
            },
            // ¬(p S q) ≡ ¬q T (¬p ∧ ¬q)
            BinaryOp::Since => {
                let np = nnf_neg(left);
                let nq = nnf_neg(right);
                Formula::FBinary {
                    op: BinaryOp::Trigger,
                    left: Box::new(nq.clone()),
                    right: Box::new(form::and(np, nq)),
                }
            }
            // ¬(p T q) ≡ ¬p S ¬q
            BinaryOp::Trigger => Formula::FBinary {
                op: BinaryOp::Since,
                left: Box::new(nnf_neg(left)),
                right: Box::new(nnf_neg(right)),
            },
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    fn p() -> Formula {
        atom("p")
    }
    fn q() -> Formula {
        atom("q")
    }

    fn unary(op: UnaryOp, f: Formula) -> Formula {
        Formula::FUnary {
            op,
            operand: Box::new(f),
        }
    }
    fn binary(op: BinaryOp, l: Formula, r: Formula) -> Formula {
        Formula::FBinary {
            op,
            left: Box::new(l),
            right: Box::new(r),
        }
    }

    // ---------- idempotency ----------

    #[test]
    fn idempotent_on_sample_set() {
        let samples: Vec<Formula> = vec![
            Formula::FTrue,
            Formula::FFalse,
            p(),
            form::not(p()),
            form::not(form::not(p())),
            form::and(p(), q()),
            form::or(form::not(p()), q()),
            form::implies(p(), q()),
            Formula::FIff {
                left: Box::new(p()),
                right: Box::new(q()),
            },
            unary(UnaryOp::Globally, form::implies(p(), unary(UnaryOp::Eventually, q()))),
            form::not(unary(UnaryOp::Globally, p())),
            form::not(binary(BinaryOp::Until, p(), q())),
            form::not(binary(BinaryOp::Since, p(), q())),
            form::not(binary(BinaryOp::Release, p(), q())),
            form::not(binary(BinaryOp::Trigger, p(), q())),
            form::not(binary(BinaryOp::WeakUntil, p(), q())),
        ];
        for f in samples {
            let once = nnf(&f).expect("nnf ok");
            let twice = nnf(&once).expect("nnf ok");
            assert_eq!(once, twice, "nnf not idempotent on {f}");
        }
    }

    // ---------- duality table spot-checks ----------

    #[test]
    fn double_negation_collapses() {
        let f = form::not(form::not(p()));
        assert_eq!(nnf(&f).unwrap(), p());
    }

    #[test]
    fn neg_true_false() {
        assert_eq!(nnf(&form::not(Formula::FTrue)).unwrap(), Formula::FFalse);
        assert_eq!(nnf(&form::not(Formula::FFalse)).unwrap(), Formula::FTrue);
    }

    #[test]
    fn neg_atom_stays() {
        let f = form::not(p());
        assert_eq!(nnf(&f).unwrap(), form::not(p()));
    }

    #[test]
    fn de_morgan_and() {
        // ¬(p & q) ≡ ¬p | ¬q
        let f = form::not(form::and(p(), q()));
        assert_eq!(nnf(&f).unwrap(), form::or(form::not(p()), form::not(q())));
    }

    #[test]
    fn de_morgan_or() {
        let f = form::not(form::or(p(), q()));
        assert_eq!(nnf(&f).unwrap(), form::and(form::not(p()), form::not(q())));
    }

    #[test]
    fn neg_implies() {
        // ¬(p → q) ≡ p ∧ ¬q
        let f = form::not(form::implies(p(), q()));
        assert_eq!(nnf(&f).unwrap(), form::and(p(), form::not(q())));
    }

    #[test]
    fn neg_iff() {
        let f = form::not(Formula::FIff {
            left: Box::new(p()),
            right: Box::new(q()),
        });
        // (p ∧ ¬q) ∨ (¬p ∧ q)
        assert_eq!(
            nnf(&f).unwrap(),
            form::or(
                form::and(p(), form::not(q())),
                form::and(form::not(p()), q())
            )
        );
    }

    #[test]
    fn neg_globally_to_eventually_negated() {
        let f = form::not(unary(UnaryOp::Globally, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Eventually, form::not(p())));
    }

    #[test]
    fn neg_eventually_to_globally_negated() {
        let f = form::not(unary(UnaryOp::Eventually, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Globally, form::not(p())));
    }

    #[test]
    fn neg_next_passes_through() {
        let f = form::not(unary(UnaryOp::Next, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Next, form::not(p())));
    }

    #[test]
    fn neg_yesterday_strong_convention() {
        let f = form::not(unary(UnaryOp::Yesterday, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Yesterday, form::not(p())));
    }

    #[test]
    fn neg_historically_to_once_negated() {
        let f = form::not(unary(UnaryOp::Historically, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Once, form::not(p())));
    }

    #[test]
    fn neg_once_to_historically_negated() {
        let f = form::not(unary(UnaryOp::Once, p()));
        assert_eq!(nnf(&f).unwrap(), unary(UnaryOp::Historically, form::not(p())));
    }

    #[test]
    fn neg_until_to_weak_until() {
        // ¬(p U q) ≡ ¬q W (¬p ∧ ¬q)
        let f = form::not(binary(BinaryOp::Until, p(), q()));
        let expected = binary(
            BinaryOp::WeakUntil,
            form::not(q()),
            form::and(form::not(p()), form::not(q())),
        );
        assert_eq!(nnf(&f).unwrap(), expected);
    }

    #[test]
    fn neg_weak_until_to_until() {
        let f = form::not(binary(BinaryOp::WeakUntil, p(), q()));
        let expected = binary(
            BinaryOp::Until,
            form::not(q()),
            form::and(form::not(p()), form::not(q())),
        );
        assert_eq!(nnf(&f).unwrap(), expected);
    }

    #[test]
    fn neg_release_to_until() {
        // ¬(p R q) ≡ ¬p U ¬q
        let f = form::not(binary(BinaryOp::Release, p(), q()));
        let expected = binary(BinaryOp::Until, form::not(p()), form::not(q()));
        assert_eq!(nnf(&f).unwrap(), expected);
    }

    #[test]
    fn neg_since_to_trigger() {
        let f = form::not(binary(BinaryOp::Since, p(), q()));
        let expected = binary(
            BinaryOp::Trigger,
            form::not(q()),
            form::and(form::not(p()), form::not(q())),
        );
        assert_eq!(nnf(&f).unwrap(), expected);
    }

    #[test]
    fn neg_trigger_to_since() {
        let f = form::not(binary(BinaryOp::Trigger, p(), q()));
        let expected = binary(BinaryOp::Since, form::not(p()), form::not(q()));
        assert_eq!(nnf(&f).unwrap(), expected);
    }

    // ---------- no-op on already-NNF formulas ----------

    #[test]
    fn no_negations_unchanged() {
        // G(p -> F q) contains an implication which expands to ¬p ∨ F q.
        // Without negations on compound things, the structurally-unchanged
        // claim is on a formula that has neither implies nor iff nor not.
        let f = unary(
            UnaryOp::Globally,
            form::or(form::not(p()), unary(UnaryOp::Eventually, q())),
        );
        assert_eq!(nnf(&f).unwrap(), f);
    }

    #[test]
    fn implies_expands_even_without_outer_neg() {
        // Implies always becomes ¬A ∨ B (no negation pushed onto a
        // compound — onto an atom only).
        let f = form::implies(p(), q());
        assert_eq!(nnf(&f).unwrap(), form::or(form::not(p()), q()));
    }
}
