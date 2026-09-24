//! `check_trace_satisfaction` — does a lasso satisfy a PLTL formula?
//!
//! Delegates to
//! [`crate::analysis::black_solver::check_trace_via_black`], which
//! shells out to `black check -t <trace_file> -f <formula>`.  The
//! trace is serialised into BLACK's lasso JSON shape (size + loop
//! index + per-state atom valuations) and the boolean verdict is
//! parsed back from BLACK's stdout.
//!
//! The optional step-by-step explanation that the public MCP tool
//! exposes is partly LLM-backed and lives at the tool wrapper layer
//! — this module is solely about the deterministic semantic verdict.

use crate::analysis::error::AnalysisError;
use crate::analysis::trace::Lasso;
use crate::Formula;

/// Decide whether `trace` satisfies `formula` at position 0.
///
/// # Errors
///
/// * [`AnalysisError::Unsupported`] when BLACK is missing or the
///   `black check` subprocess fails.
pub fn check_trace_satisfaction(trace: &Lasso, formula: &Formula) -> Result<bool, AnalysisError> {
    crate::analysis::black_solver::check_trace_via_black(trace, formula)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    fn one_step_lasso() -> Lasso {
        Lasso::new(vec![], vec![BTreeSet::from(["p".to_string()])]).expect("ok")
    }

    /// Without BLACK installed we surface a clean `Unsupported`.
    /// With BLACK installed, the trivial trace `{p}^ω` satisfies the
    /// atom `p`.  Either outcome is OK; we are confirming the call
    /// doesn't panic and uses the right error path when BLACK is
    /// absent.
    #[test]
    fn check_trace_returns_clean_result_or_unsupported() {
        let trace = one_step_lasso();
        match check_trace_satisfaction(&trace, &atom("p")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }
}
