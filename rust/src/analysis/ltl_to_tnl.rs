//! LTL → temporary natural-language (TNL).
//!
//! Pure-function, recursive translation from [`Formula`] to a verbose,
//! literally-faithful NL string. Output is intentionally clunky —
//! every operator is glossed in explicit English so the renderer never
//! ambiguates an obligation, reflexivity, or scope. The MCP tool
//! `ltl_to_nl` then asks a helper LLM to paraphrase this TNL into five
//! natural variants while preserving meaning.
//!
//! Semantics applied here:
//!   * Infinite ω-trace.
//!   * Strong-Y: `Y p` is false at the initial step.
//!   * Reflexive `F`, `G`, `O`, `H` (include the current step).
//!   * Until's `q` is *required* to occur; WeakUntil drops that
//!     requirement.

use crate::{BinaryOp, Formula, UnaryOp};

/// Render `f` into a verbose, semantics-preserving English string.
pub fn ltl_to_tnl(f: &Formula) -> String {
    render(f)
}

fn render(f: &Formula) -> String {
    match f {
        Formula::FTrue => "TRUE (trivially holds)".to_string(),
        Formula::FFalse => "FALSE (never holds)".to_string(),
        Formula::FAtom { name } => format!("`{name}` holds"),
        Formula::FNot { operand } => {
            format!("it is NOT the case that ({})", render(operand))
        }
        Formula::FAnd { left, right } => format!(
            "BOTH of the following hold: (i) {}; AND (ii) {}",
            render(left),
            render(right),
        ),
        Formula::FOr { left, right } => format!(
            "AT LEAST ONE of the following holds: (i) {}; OR (ii) {}",
            render(left),
            render(right),
        ),
        Formula::FImplies { left, right } => format!(
            "IF ({}) THEN ({})",
            render(left),
            render(right),
        ),
        Formula::FIff { left, right } => format!(
            "({}) HOLDS IF AND ONLY IF ({})",
            render(left),
            render(right),
        ),
        Formula::FUnary { op, operand } => render_unary(*op, operand),
        Formula::FBinary { op, left, right } => render_binary(*op, left, right),
    }
}

fn render_unary(op: UnaryOp, operand: &Formula) -> String {
    let inner = render(operand);
    match op {
        UnaryOp::Next => format!(
            "at the NEXT time step (the one immediately after the current step), ({})",
            inner
        ),
        UnaryOp::Yesterday => format!(
            "the current step is NOT the initial step, AND at the PREVIOUS time step (the one \
             immediately before the current step), ({})",
            inner
        ),
        UnaryOp::Eventually => format!(
            "at SOME time step from now onwards (the current step or any later step), ({})",
            inner
        ),
        UnaryOp::Globally => format!(
            "at EVERY time step from now onwards (the current step and every later step), ({})",
            inner
        ),
        UnaryOp::Once => format!(
            "at SOME time step in the past (the current step or any earlier step), ({})",
            inner
        ),
        UnaryOp::Historically => format!(
            "at EVERY time step in the past (the current step and every earlier step), ({})",
            inner
        ),
    }
}

fn render_binary(op: BinaryOp, left: &Formula, right: &Formula) -> String {
    let l = render(left);
    let r = render(right);
    match op {
        BinaryOp::Until => format!(
            "({}) holds at every time step from now up to (but NOT including) some future time \
             step at which ({}) holds; that future step at which ({}) holds MUST exist",
            l, r, r,
        ),
        BinaryOp::WeakUntil => format!(
            "({}) holds at every time step from now up to (but NOT including) some future time \
             step at which ({}) holds; OR, alternatively, ({}) holds at every time step from now \
             onwards forever (with ({}) never holding)",
            l, r, l, r,
        ),
        BinaryOp::Release => format!(
            "({}) holds at every time step from now up to and INCLUDING the first future time \
             step at which ({}) holds; OR, alternatively, ({}) holds at every time step from now \
             onwards forever (with ({}) never holding)",
            r, l, r, l,
        ),
        BinaryOp::Since => format!(
            "({}) held at some past time step (the current step or any earlier step), AND ({}) \
             has held at every step strictly between that past step and the current step (the \
             current step itself NOT required to satisfy ({}))",
            r, l, l,
        ),
        BinaryOp::Trigger => format!(
            "EITHER (a) ({}) held at some past time step (the current step or any earlier step) \
             AND ({}) has held at every step from that past step up to and including the \
             current step, OR (b) ({}) has held at every past time step (the current step and \
             every earlier step) without ({}) ever having occurred",
            l, r, r, l,
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn tnl_atom() {
        assert_eq!(ltl_to_tnl(&atom("p")), "`p` holds");
    }

    #[test]
    fn tnl_true_false() {
        assert!(ltl_to_tnl(&Formula::FTrue).contains("trivially"));
        assert!(ltl_to_tnl(&Formula::FFalse).contains("never"));
    }

    #[test]
    fn tnl_not_atom() {
        let f = Formula::FNot { operand: Box::new(atom("p")) };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("NOT the case"));
        assert!(s.contains("`p` holds"));
    }

    #[test]
    fn tnl_and_or_implies_iff() {
        let p = atom("p");
        let q = atom("q");
        let and = Formula::FAnd { left: Box::new(p.clone()), right: Box::new(q.clone()) };
        let or  = Formula::FOr  { left: Box::new(p.clone()), right: Box::new(q.clone()) };
        let imp = Formula::FImplies { left: Box::new(p.clone()), right: Box::new(q.clone()) };
        let iff = Formula::FIff { left: Box::new(p),         right: Box::new(q)         };
        assert!(ltl_to_tnl(&and).contains("BOTH"));
        assert!(ltl_to_tnl(&or).contains("AT LEAST ONE"));
        assert!(ltl_to_tnl(&imp).contains("IF"));
        assert!(ltl_to_tnl(&iff).contains("IF AND ONLY IF"));
    }

    #[test]
    fn tnl_globally_implies() {
        // G(p -> F q)
        let f = Formula::FUnary {
            op: UnaryOp::Globally,
            operand: Box::new(Formula::FImplies {
                left: Box::new(atom("p")),
                right: Box::new(Formula::FUnary {
                    op: UnaryOp::Eventually,
                    operand: Box::new(atom("q")),
                }),
            }),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("EVERY time step from now onwards"));
        assert!(s.contains("SOME time step from now onwards"));
        assert!(s.contains("IF"));
    }

    #[test]
    fn tnl_until_mentions_obligation() {
        let f = Formula::FBinary {
            op: BinaryOp::Until,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("MUST exist"));
    }

    #[test]
    fn tnl_weak_until_mentions_forever_alternative() {
        let f = Formula::FBinary {
            op: BinaryOp::WeakUntil,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("forever"));
    }

    #[test]
    fn tnl_release_mentions_inclusive_step() {
        let f = Formula::FBinary {
            op: BinaryOp::Release,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("INCLUDING"));
    }

    #[test]
    fn tnl_since_past_dual_of_until() {
        let f = Formula::FBinary {
            op: BinaryOp::Since,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("past time step"));
    }

    #[test]
    fn tnl_yesterday_marks_initial_step() {
        let f = Formula::FUnary {
            op: UnaryOp::Yesterday,
            operand: Box::new(atom("p")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("PREVIOUS"));
        assert!(s.contains("NOT the initial step"));
    }

    #[test]
    fn tnl_once_reflexive() {
        let f = Formula::FUnary {
            op: UnaryOp::Once,
            operand: Box::new(atom("p")),
        };
        let s = ltl_to_tnl(&f);
        assert!(s.contains("the current step or any earlier step"));
    }
}
