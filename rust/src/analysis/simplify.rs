//! Library-internal formula simplification.
//!
//! Bottom-up rewriting with a small fixed set of shallow boolean and
//! temporal identities. **No NNF transformation is performed here**: the
//! rules are limited to the kind of canonicalisation any LTL course
//! would teach (constant folding, idempotence on identical operands,
//! collapsing `F F p → F p`, etc.).
//!
//! Idempotent: `simplify(simplify(f)) == simplify(f)`.

use crate::analysis::error::AnalysisError;
use crate::{BinaryOp, Formula, UnaryOp};

/// Simplify a formula via bottom-up shallow rewriting.
///
/// Boolean rewrites:
/// ```text
/// true ∧ a → a            a ∧ true → a
/// false ∧ a → false       a ∧ false → false
/// a ∧ a → a               a ∨ a → a
/// true ∨ a → true         a ∨ true → true
/// false ∨ a → a           a ∨ false → a
/// ¬true → false           ¬false → true        ¬¬a → a
/// true → a ↦ a            a → true ↦ true
/// false → a ↦ true        a → false ↦ ¬a
/// a ↔ true → a            a ↔ false → ¬a       a ↔ a → true
/// ```
///
/// Temporal rewrites (safe ones only — strong-X, infinite-trace
/// semantics from the crate-level invariants):
/// ```text
/// X true → true           X false → false
/// F true → true           F false → false
/// G true → true           G false → false
/// Y false → false         O false → false      H true → true
/// F F a → F a             G G a → G a
/// O O a → O a             H H a → H a
/// a U false → false       false U a → a       a U true → true
/// a S false → false       false S a → a       a S true → true
/// ```
pub fn simplify(f: &Formula) -> Result<Formula, AnalysisError> {
    Ok(simplify_rec(f))
}

/// Bottom-up: simplify children first, then apply a single layer of
/// rewriting. Returning the rewritten formula directly is sound because
/// each rewrite either preserves the top-level shape or replaces it
/// with a constant / already-simplified subformula.
fn simplify_rec(f: &Formula) -> Formula {
    match f {
        Formula::FTrue => Formula::FTrue,
        Formula::FFalse => Formula::FFalse,
        Formula::FAtom { name } => Formula::FAtom { name: name.clone() },

        Formula::FNot { operand } => simplify_not(simplify_rec(operand)),
        Formula::FAnd { left, right } => simplify_and(simplify_rec(left), simplify_rec(right)),
        Formula::FOr { left, right } => simplify_or(simplify_rec(left), simplify_rec(right)),
        Formula::FImplies { left, right } => {
            simplify_implies(simplify_rec(left), simplify_rec(right))
        }
        Formula::FIff { left, right } => simplify_iff(simplify_rec(left), simplify_rec(right)),
        Formula::FUnary { op, operand } => simplify_unary(*op, simplify_rec(operand)),
        Formula::FBinary { op, left, right } => {
            simplify_binary(*op, simplify_rec(left), simplify_rec(right))
        }
    }
}

// ----------- per-shape simplifiers (all inputs already simplified) -----------

fn simplify_not(inner: Formula) -> Formula {
    match inner {
        Formula::FTrue => Formula::FFalse,
        Formula::FFalse => Formula::FTrue,
        // ¬¬a → a
        Formula::FNot { operand } => *operand,
        other => Formula::FNot {
            operand: Box::new(other),
        },
    }
}

fn simplify_and(left: Formula, right: Formula) -> Formula {
    match (&left, &right) {
        (Formula::FFalse, _) | (_, Formula::FFalse) => Formula::FFalse,
        (Formula::FTrue, _) => right,
        (_, Formula::FTrue) => left,
        _ if left == right => left,
        _ => Formula::FAnd {
            left: Box::new(left),
            right: Box::new(right),
        },
    }
}

fn simplify_or(left: Formula, right: Formula) -> Formula {
    match (&left, &right) {
        (Formula::FTrue, _) | (_, Formula::FTrue) => Formula::FTrue,
        (Formula::FFalse, _) => right,
        (_, Formula::FFalse) => left,
        _ if left == right => left,
        _ => Formula::FOr {
            left: Box::new(left),
            right: Box::new(right),
        },
    }
}

fn simplify_implies(left: Formula, right: Formula) -> Formula {
    // false → a ≡ true; a → true ≡ true; true → a ≡ a; a → false ≡ ¬a
    match (&left, &right) {
        (Formula::FFalse, _) => Formula::FTrue,
        (_, Formula::FTrue) => Formula::FTrue,
        (Formula::FTrue, _) => right,
        (_, Formula::FFalse) => simplify_not(left),
        _ => Formula::FImplies {
            left: Box::new(left),
            right: Box::new(right),
        },
    }
}

fn simplify_iff(left: Formula, right: Formula) -> Formula {
    // a ↔ a → true
    if left == right {
        return Formula::FTrue;
    }
    match (&left, &right) {
        (Formula::FTrue, _) => right,
        (_, Formula::FTrue) => left,
        (Formula::FFalse, _) => simplify_not(right),
        (_, Formula::FFalse) => simplify_not(left),
        _ => Formula::FIff {
            left: Box::new(left),
            right: Box::new(right),
        },
    }
}

fn simplify_unary(op: UnaryOp, inner: Formula) -> Formula {
    match (op, &inner) {
        // X true → true, X false → false  (strong-X on infinite traces)
        (UnaryOp::Next, Formula::FTrue) => Formula::FTrue,
        (UnaryOp::Next, Formula::FFalse) => Formula::FFalse,

        // F/G constants
        (UnaryOp::Eventually, Formula::FTrue) => Formula::FTrue,
        (UnaryOp::Eventually, Formula::FFalse) => Formula::FFalse,
        (UnaryOp::Globally, Formula::FTrue) => Formula::FTrue,
        (UnaryOp::Globally, Formula::FFalse) => Formula::FFalse,

        // Past constants
        (UnaryOp::Yesterday, Formula::FFalse) => Formula::FFalse,
        (UnaryOp::Once, Formula::FFalse) => Formula::FFalse,
        (UnaryOp::Historically, Formula::FTrue) => Formula::FTrue,

        // Idempotent temporal stacks
        (
            UnaryOp::Eventually,
            Formula::FUnary {
                op: UnaryOp::Eventually,
                ..
            },
        )
        | (
            UnaryOp::Globally,
            Formula::FUnary {
                op: UnaryOp::Globally,
                ..
            },
        )
        | (
            UnaryOp::Once,
            Formula::FUnary {
                op: UnaryOp::Once,
                ..
            },
        )
        | (
            UnaryOp::Historically,
            Formula::FUnary {
                op: UnaryOp::Historically,
                ..
            },
        ) => inner,

        _ => Formula::FUnary {
            op,
            operand: Box::new(inner),
        },
    }
}

fn simplify_binary(op: BinaryOp, left: Formula, right: Formula) -> Formula {
    match op {
        BinaryOp::Until => match (&left, &right) {
            // a U false → false; false U a → a; a U true → true.
            (_, Formula::FFalse) => Formula::FFalse,
            (Formula::FFalse, _) => right,
            (_, Formula::FTrue) => Formula::FTrue,
            _ => Formula::FBinary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            },
        },
        BinaryOp::Since => match (&left, &right) {
            (_, Formula::FFalse) => Formula::FFalse,
            (Formula::FFalse, _) => right,
            (_, Formula::FTrue) => Formula::FTrue,
            _ => Formula::FBinary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            },
        },
        // No safe rewrites for W / R / T at this canonicalisation tier.
        _ => Formula::FBinary {
            op,
            left: Box::new(left),
            right: Box::new(right),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::form;

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

    // ----- boolean rewrites -----

    #[test]
    fn and_with_true_drops_true() {
        assert_eq!(simplify(&form::and(Formula::FTrue, p())).unwrap(), p());
        assert_eq!(simplify(&form::and(p(), Formula::FTrue)).unwrap(), p());
    }

    #[test]
    fn and_with_false_is_false() {
        assert_eq!(
            simplify(&form::and(Formula::FFalse, p())).unwrap(),
            Formula::FFalse
        );
        assert_eq!(
            simplify(&form::and(p(), Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
    }

    #[test]
    fn and_idempotent() {
        assert_eq!(simplify(&form::and(p(), p())).unwrap(), p());
    }

    #[test]
    fn or_with_true_is_true() {
        assert_eq!(
            simplify(&form::or(Formula::FTrue, p())).unwrap(),
            Formula::FTrue
        );
        assert_eq!(
            simplify(&form::or(p(), Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
    }

    #[test]
    fn or_with_false_drops_false() {
        assert_eq!(simplify(&form::or(Formula::FFalse, p())).unwrap(), p());
        assert_eq!(simplify(&form::or(p(), Formula::FFalse)).unwrap(), p());
    }

    #[test]
    fn or_idempotent() {
        assert_eq!(simplify(&form::or(p(), p())).unwrap(), p());
    }

    #[test]
    fn not_constants() {
        assert_eq!(simplify(&form::not(Formula::FTrue)).unwrap(), Formula::FFalse);
        assert_eq!(simplify(&form::not(Formula::FFalse)).unwrap(), Formula::FTrue);
    }

    #[test]
    fn double_negation_eliminated() {
        assert_eq!(simplify(&form::not(form::not(p()))).unwrap(), p());
    }

    #[test]
    fn implies_constants() {
        // true → a ≡ a
        assert_eq!(simplify(&form::implies(Formula::FTrue, p())).unwrap(), p());
        // a → true ≡ true
        assert_eq!(
            simplify(&form::implies(p(), Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
        // false → a ≡ true
        assert_eq!(
            simplify(&form::implies(Formula::FFalse, p())).unwrap(),
            Formula::FTrue
        );
        // a → false ≡ ¬a
        assert_eq!(
            simplify(&form::implies(p(), Formula::FFalse)).unwrap(),
            form::not(p())
        );
    }

    #[test]
    fn iff_constants_and_reflex() {
        // a ↔ a → true
        assert_eq!(
            simplify(&Formula::FIff {
                left: Box::new(p()),
                right: Box::new(p()),
            })
            .unwrap(),
            Formula::FTrue
        );
        // a ↔ true → a
        assert_eq!(
            simplify(&Formula::FIff {
                left: Box::new(p()),
                right: Box::new(Formula::FTrue),
            })
            .unwrap(),
            p()
        );
        // true ↔ a → a
        assert_eq!(
            simplify(&Formula::FIff {
                left: Box::new(Formula::FTrue),
                right: Box::new(p()),
            })
            .unwrap(),
            p()
        );
        // a ↔ false → ¬a
        assert_eq!(
            simplify(&Formula::FIff {
                left: Box::new(p()),
                right: Box::new(Formula::FFalse),
            })
            .unwrap(),
            form::not(p())
        );
        // false ↔ a → ¬a
        assert_eq!(
            simplify(&Formula::FIff {
                left: Box::new(Formula::FFalse),
                right: Box::new(p()),
            })
            .unwrap(),
            form::not(p())
        );
    }

    // ----- temporal rewrites -----

    #[test]
    fn x_of_constants() {
        assert_eq!(
            simplify(&unary(UnaryOp::Next, Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Next, Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
    }

    #[test]
    fn f_g_constants() {
        assert_eq!(
            simplify(&unary(UnaryOp::Eventually, Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Eventually, Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Globally, Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Globally, Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
    }

    #[test]
    fn past_constants() {
        assert_eq!(
            simplify(&unary(UnaryOp::Yesterday, Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Once, Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
        assert_eq!(
            simplify(&unary(UnaryOp::Historically, Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
    }

    #[test]
    fn idempotent_stacks_collapse() {
        // F F p → F p
        let ff = unary(UnaryOp::Eventually, unary(UnaryOp::Eventually, p()));
        assert_eq!(simplify(&ff).unwrap(), unary(UnaryOp::Eventually, p()));
        // G G p → G p
        let gg = unary(UnaryOp::Globally, unary(UnaryOp::Globally, p()));
        assert_eq!(simplify(&gg).unwrap(), unary(UnaryOp::Globally, p()));
        // O O p → O p
        let oo = unary(UnaryOp::Once, unary(UnaryOp::Once, p()));
        assert_eq!(simplify(&oo).unwrap(), unary(UnaryOp::Once, p()));
        // H H p → H p
        let hh = unary(UnaryOp::Historically, unary(UnaryOp::Historically, p()));
        assert_eq!(simplify(&hh).unwrap(), unary(UnaryOp::Historically, p()));
    }

    #[test]
    fn until_constants() {
        // a U false → false
        assert_eq!(
            simplify(&binary(BinaryOp::Until, p(), Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
        // false U a → a
        assert_eq!(
            simplify(&binary(BinaryOp::Until, Formula::FFalse, p())).unwrap(),
            p()
        );
        // a U true → true
        assert_eq!(
            simplify(&binary(BinaryOp::Until, p(), Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
    }

    #[test]
    fn since_constants() {
        assert_eq!(
            simplify(&binary(BinaryOp::Since, p(), Formula::FFalse)).unwrap(),
            Formula::FFalse
        );
        assert_eq!(
            simplify(&binary(BinaryOp::Since, Formula::FFalse, p())).unwrap(),
            p()
        );
        assert_eq!(
            simplify(&binary(BinaryOp::Since, p(), Formula::FTrue)).unwrap(),
            Formula::FTrue
        );
    }

    // ----- idempotency -----

    #[test]
    fn idempotent_on_sample_set() {
        let samples: Vec<Formula> = vec![
            // Pure constants and atoms.
            Formula::FTrue,
            Formula::FFalse,
            p(),
            // Boolean trigger cases.
            form::and(p(), Formula::FTrue),
            form::or(p(), Formula::FFalse),
            form::not(form::not(p())),
            form::implies(Formula::FFalse, p()),
            Formula::FIff {
                left: Box::new(p()),
                right: Box::new(p()),
            },
            // Temporal triggers.
            unary(UnaryOp::Eventually, unary(UnaryOp::Eventually, p())),
            unary(UnaryOp::Globally, Formula::FTrue),
            binary(BinaryOp::Until, p(), Formula::FFalse),
            binary(BinaryOp::Since, Formula::FFalse, p()),
            // Untouchable structure.
            unary(UnaryOp::Globally, form::implies(p(), unary(UnaryOp::Eventually, q()))),
        ];
        for f in samples {
            let once = simplify(&f).expect("simplify ok");
            let twice = simplify(&once).expect("simplify ok");
            assert_eq!(once, twice, "simplify not idempotent on {f}");
        }
    }

    // ----- no-op on structurally irreducible formulas -----

    #[test]
    fn noop_on_g_implies_f() {
        // G(p -> F q) — no constants, no double negs, no idempotent stacks.
        let f = unary(
            UnaryOp::Globally,
            form::implies(p(), unary(UnaryOp::Eventually, q())),
        );
        assert_eq!(simplify(&f).unwrap(), f);
    }

    #[test]
    fn noop_on_until_without_constants() {
        let f = binary(BinaryOp::Until, p(), q());
        assert_eq!(simplify(&f).unwrap(), f);
    }
}
