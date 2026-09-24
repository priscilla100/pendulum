//! BLACK-gated end-to-end tests for the deterministic analyses.
//!
//! These tests are `#[ignore]` by default so `cargo test --workspace`
//! stays green on hosts without BLACK installed.  Run with:
//!
//! ```bash
//! BLACK_BIN=/usr/local/bin/black cargo test -p pltl_rust \
//!     --test black_integration -- --ignored --nocapture
//! ```
//!
//! Each test exercises one entry of the deterministic-analysis surface
//! end-to-end with a real BLACK invocation.

use pltl_rust::analysis::compare::compare_candidates;
use pltl_rust::analysis::consistency::check_consistency;
use pltl_rust::analysis::entailment::{check_entailment, entailment_pair};
use pltl_rust::analysis::equivalence::{check_equivalence, equivalent_pair};
use pltl_rust::analysis::sat::{decide_sat, SatVerdict};
use pltl_rust::analysis::trace::Lasso;
use pltl_rust::analysis::trace_check::check_trace_satisfaction;
use pltl_rust::analysis::trace_gen::{
    distinguishing_trace_pair, gen_satisfying_trace, gen_violating_trace,
};
use pltl_rust::{BinaryOp, Formula, UnaryOp};
use std::collections::BTreeSet;

fn atom(s: &str) -> Formula {
    Formula::FAtom { name: s.into() }
}

fn skip_if_no_black() -> bool {
    std::env::var("BLACK_BIN").is_err()
        && !std::path::Path::new("/usr/local/bin/black").exists()
}

#[test]
#[ignore = "requires BLACK solver in PATH or BLACK_BIN env"]
fn decide_sat_p_is_satisfiable() {
    if skip_if_no_black() {
        eprintln!("BLACK not found; skipping");
        return;
    }
    let v = decide_sat(&atom("p")).expect("decide_sat ok");
    assert!(matches!(v, SatVerdict::Satisfiable(_)), "got {v:?}");
}

#[test]
#[ignore = "requires BLACK"]
fn decide_sat_false_is_unsatisfiable() {
    if skip_if_no_black() {
        return;
    }
    let v = decide_sat(&Formula::FFalse).expect("decide_sat ok");
    assert!(matches!(v, SatVerdict::Unsatisfiable), "got {v:?}");
}

#[test]
#[ignore = "requires BLACK"]
fn decide_sat_p_and_not_p_is_unsat() {
    if skip_if_no_black() {
        return;
    }
    // p ∧ ¬p
    let f = Formula::FAnd {
        left: Box::new(atom("p")),
        right: Box::new(Formula::FNot {
            operand: Box::new(atom("p")),
        }),
    };
    let v = decide_sat(&f).expect("ok");
    assert!(matches!(v, SatVerdict::Unsatisfiable), "got {v:?}");
}

#[test]
#[ignore = "requires BLACK"]
fn entailment_p_implies_p_or_q_holds() {
    if skip_if_no_black() {
        return;
    }
    // p |= (p ∨ q)
    let r = entailment_pair(
        &atom("p"),
        &Formula::FOr {
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        },
    )
    .expect("ok");
    assert!(r.entails, "entailment should hold");
    assert!(r.counterexample.is_none(), "no counterexample expected");
}

#[test]
#[ignore = "requires BLACK"]
fn entailment_q_does_not_imply_p() {
    if skip_if_no_black() {
        return;
    }
    let r = entailment_pair(&atom("q"), &atom("p")).expect("ok");
    assert!(!r.entails, "q should not entail p");
    assert!(r.counterexample.is_some(), "counterexample expected");
}

#[test]
#[ignore = "requires BLACK"]
fn equivalence_of_globally_eq_dual() {
    if skip_if_no_black() {
        return;
    }
    // G p ≡ ¬F ¬p
    let lhs = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let rhs = Formula::FNot {
        operand: Box::new(Formula::FUnary {
            op: UnaryOp::Eventually,
            operand: Box::new(Formula::FNot {
                operand: Box::new(atom("p")),
            }),
        }),
    };
    let r = equivalent_pair(&lhs, &rhs).expect("ok");
    assert!(r.equivalent, "G p should be equivalent to ¬F ¬p");
}

#[test]
#[ignore = "requires BLACK"]
fn check_equivalence_vec_partitions() {
    if skip_if_no_black() {
        return;
    }
    // [G p, ¬F ¬p, F p]: first two are equivalent, third is incomparable.
    let g_p = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let neg_f_neg_p = Formula::FNot {
        operand: Box::new(Formula::FUnary {
            op: UnaryOp::Eventually,
            operand: Box::new(Formula::FNot {
                operand: Box::new(atom("p")),
            }),
        }),
    };
    let f_p = Formula::FUnary {
        op: UnaryOp::Eventually,
        operand: Box::new(atom("p")),
    };
    let r = check_equivalence(&[g_p, neg_f_neg_p, f_p]).expect("ok");
    assert!(!r.all_equivalent);
    // {0, 1} should be one class, {2} should be its own class.
    assert_eq!(r.equivalence_classes.len(), 2);
    let has_pair = r.equivalence_classes.iter().any(|c| c == &vec![0, 1]);
    assert!(has_pair, "expected {{0,1}} class, got {:?}", r.equivalence_classes);
}

#[test]
#[ignore = "requires BLACK"]
fn check_entailment_multi_premise() {
    if skip_if_no_black() {
        return;
    }
    // p, p → q |= q
    let r = check_entailment(
        &[
            atom("p"),
            Formula::FImplies {
                left: Box::new(atom("p")),
                right: Box::new(atom("q")),
            },
        ],
        &atom("q"),
    )
    .expect("ok");
    assert!(r.entails);
}

#[test]
#[ignore = "requires BLACK"]
fn gen_satisfying_trace_returns_lasso() {
    if skip_if_no_black() {
        return;
    }
    // F p — should return a satisfying trace where p eventually holds.
    let f = Formula::FUnary {
        op: UnaryOp::Eventually,
        operand: Box::new(atom("p")),
    };
    let r = gen_satisfying_trace(&f).expect("ok");
    assert!(r.found, "F p is satisfiable");
    assert!(r.trace.is_some(), "expected a witness");
    let trace = r.trace.expect("witness");
    let total_states = trace.prefix.len() + trace.loop_.len();
    assert!(total_states >= 1, "non-empty trace");
}

#[test]
#[ignore = "requires BLACK"]
fn gen_violating_trace_returns_lasso() {
    if skip_if_no_black() {
        return;
    }
    // G p — violating trace has ¬p somewhere.
    let f = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let r = gen_violating_trace(&f).expect("ok");
    assert!(r.found, "G p is not a tautology");
    assert!(r.trace.is_some(), "expected a witness");
}

#[test]
#[ignore = "requires BLACK"]
fn distinguishing_pair_returns_direction() {
    if skip_if_no_black() {
        return;
    }
    // F p vs G p — F p doesn't imply G p; a one-tick witness suffices.
    let f_p = Formula::FUnary {
        op: UnaryOp::Eventually,
        operand: Box::new(atom("p")),
    };
    let g_p = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let r = distinguishing_trace_pair(&f_p, &g_p).expect("ok");
    assert!(r.distinguishable);
    assert!(r.trace.is_some());
    assert!(r.direction.is_some());
}

#[test]
#[ignore = "requires BLACK"]
fn consistency_detects_conflict() {
    if skip_if_no_black() {
        return;
    }
    // [p, ¬p] is inconsistent.
    let r = check_consistency(&[
        atom("p"),
        Formula::FNot {
            operand: Box::new(atom("p")),
        },
    ])
    .expect("ok");
    assert!(!r.consistent);
    assert_eq!(r.conflicts, vec![(0, 1)]);
}

#[test]
#[ignore = "requires BLACK"]
fn check_trace_satisfaction_atom_on_singleton() {
    if skip_if_no_black() {
        return;
    }
    let trace = Lasso::new(vec![], vec![BTreeSet::from(["p".to_string()])]).expect("ok");
    let r = check_trace_satisfaction(&trace, &atom("p")).expect("ok");
    assert!(r, "{{p}}^ω satisfies p");
}

#[test]
#[ignore = "requires BLACK"]
fn check_trace_satisfaction_globally_pass() {
    if skip_if_no_black() {
        return;
    }
    // Trace: {p}, {p}, {p}^ω.  G p should hold.
    let g_p = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let trace = Lasso::new(
        vec![
            BTreeSet::from(["p".to_string()]),
            BTreeSet::from(["p".to_string()]),
        ],
        vec![BTreeSet::from(["p".to_string()])],
    )
    .expect("ok");
    let r = check_trace_satisfaction(&trace, &g_p).expect("ok");
    assert!(r, "G p on {{p}},{{p}},{{p}}^ω should hold");
}

#[test]
#[ignore = "requires BLACK"]
fn check_trace_satisfaction_globally_fail() {
    if skip_if_no_black() {
        return;
    }
    // Trace: {p}, {} (loops); G p fails at step 1.
    let g_p = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let trace = Lasso::new(
        vec![BTreeSet::from(["p".to_string()])],
        vec![BTreeSet::new()],
    )
    .expect("ok");
    let r = check_trace_satisfaction(&trace, &g_p).expect("ok");
    assert!(!r, "G p on {{p}},{{}}^ω should fail");
}

#[test]
#[ignore = "requires BLACK"]
fn release_normalizes_correctly_for_black() {
    if skip_if_no_black() {
        return;
    }
    // p R q  ≡  ¬(¬p U ¬q).  Check the rewrite preserves
    // satisfiability: SAT iff Until form is SAT.
    let release = Formula::FBinary {
        op: BinaryOp::Release,
        left: Box::new(atom("p")),
        right: Box::new(atom("q")),
    };
    // p R q should be satisfiable (e.g. trace where q holds always).
    let v = decide_sat(&release).expect("ok");
    assert!(matches!(v, SatVerdict::Satisfiable(_)));
}

#[test]
#[ignore = "requires BLACK"]
fn weak_until_normalizes_correctly_for_black() {
    if skip_if_no_black() {
        return;
    }
    // p W q  ≡  (p U q) ∨ G p.  Should be satisfiable.
    let w = Formula::FBinary {
        op: BinaryOp::WeakUntil,
        left: Box::new(atom("p")),
        right: Box::new(atom("q")),
    };
    let v = decide_sat(&w).expect("ok");
    assert!(matches!(v, SatVerdict::Satisfiable(_)));
}

#[test]
#[ignore = "requires BLACK"]
fn compare_finds_strictly_stronger() {
    if skip_if_no_black() {
        return;
    }
    // [G p, F p]: G p strictly implies F p.
    let g_p = Formula::FUnary {
        op: UnaryOp::Globally,
        operand: Box::new(atom("p")),
    };
    let f_p = Formula::FUnary {
        op: UnaryOp::Eventually,
        operand: Box::new(atom("p")),
    };
    let r = compare_candidates(&[g_p, f_p]).expect("ok");
    // (0, 1) should be in stronger_than: G p → F p.
    assert!(r.stronger_than.contains(&(0, 1)));
    assert!(r.equivalent_pairs.is_empty());
}
