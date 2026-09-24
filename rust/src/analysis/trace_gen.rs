//! Trace-generation analyses.
//!
//! Three public tools share this module:
//!
//! * `gen_satisfying_trace` — find a model lasso for `formula`.
//! * `gen_violating_trace` — find a model lasso for `¬formula`.
//! * `distinguishing_trace` — find a lasso that satisfies at least
//!   one of a list of formulas but not all.
//!
//! All three reduce to one or two calls to
//! [`crate::analysis::sat::decide_sat`].  The bodies here are final
//! plumbing; filling in `decide_sat` lights up every entry point.

use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::analysis::sat::{decide_sat, SatVerdict};
use crate::analysis::trace::Lasso;
use crate::Formula;
use serde::Serialize;

/// Polarity of the trace we want.
#[derive(Debug, Clone, Copy)]
pub enum Polarity {
    /// Trace must satisfy the formula.
    Satisfying,
    /// Trace must violate the formula.
    Violating,
}

/// Result of a single-formula trace search.
#[derive(Debug, Clone, Serialize)]
pub struct TraceGenResult {
    /// `true` when a trace satisfying the polarity exists.
    pub found: bool,
    /// One trace witnessing the verdict; `None` when `found == false`.
    pub trace: Option<Lasso>,
}

/// Find a trace for `formula` under the given `polarity`.
///
/// The single SAT call: `Satisfying ⇒ decide_sat(formula)`,
/// `Violating ⇒ decide_sat(¬formula)`.
///
/// # Errors
///
/// Propagates [`AnalysisError`] from [`decide_sat`].
pub fn gen_trace(
    formula: &Formula,
    polarity: Polarity,
) -> Result<TraceGenResult, AnalysisError> {
    let target = match polarity {
        Polarity::Satisfying => formula.clone(),
        Polarity::Violating => form::not(formula.clone()),
    };
    match decide_sat(&target)? {
        SatVerdict::Satisfiable(l) => Ok(TraceGenResult {
            found: true,
            trace: Some(l),
        }),
        SatVerdict::Unsatisfiable => Ok(TraceGenResult {
            found: false,
            trace: None,
        }),
        SatVerdict::Unknown(msg) => Err(AnalysisError::Unsupported(msg)),
    }
}

/// Convenience: `gen_trace(formula, Polarity::Satisfying)`.
pub fn gen_satisfying_trace(formula: &Formula) -> Result<TraceGenResult, AnalysisError> {
    gen_trace(formula, Polarity::Satisfying)
}

/// Convenience: `gen_trace(formula, Polarity::Violating)`.
pub fn gen_violating_trace(formula: &Formula) -> Result<TraceGenResult, AnalysisError> {
    gen_trace(formula, Polarity::Violating)
}

/// Result of a distinguishing-trace search.
#[derive(Debug, Clone, Serialize)]
pub struct DistinguishingResult {
    /// `true` iff a trace separating at least one pair of formulas
    /// was found.
    pub distinguishable: bool,
    /// Witness trace, or `None` when no separator exists.
    pub trace: Option<Lasso>,
    /// `"i_only"` / `"j_only"` describing which side of the
    /// disagreeing pair the witness satisfies.  `None` when
    /// `distinguishable == false`.
    pub direction: Option<&'static str>,
    /// Indices `(i, j)` of the disagreeing pair, with `i < j`.
    /// `None` when `distinguishable == false`.
    pub disagreeing_pair: Option<(usize, usize)>,
    /// Free-text explanation when no separator was found
    /// (e.g. `"all formulas pairwise equivalent"`).
    pub reason: Option<String>,
}

/// Pair primitive: find a trace satisfying exactly one of `a`, `b`.
///
/// Two SAT calls: `a ∧ ¬b` (returns `"a_only"` witness) and
/// `¬a ∧ b` (returns `"b_only"`).
///
/// # Errors
///
/// Propagates [`AnalysisError`] from [`decide_sat`].
pub fn distinguishing_trace_pair(
    a: &Formula,
    b: &Formula,
) -> Result<DistinguishingResult, AnalysisError> {
    match decide_sat(&form::and_not(a, b))? {
        SatVerdict::Satisfiable(l) => {
            return Ok(DistinguishingResult {
                distinguishable: true,
                trace: Some(l),
                direction: Some("a_only"),
                disagreeing_pair: None,
                reason: None,
            });
        }
        SatVerdict::Unsatisfiable => {}
        SatVerdict::Unknown(msg) => return Err(AnalysisError::Unsupported(msg)),
    }
    match decide_sat(&form::and_not(b, a))? {
        SatVerdict::Satisfiable(l) => Ok(DistinguishingResult {
            distinguishable: true,
            trace: Some(l),
            direction: Some("b_only"),
            disagreeing_pair: None,
            reason: None,
        }),
        SatVerdict::Unsatisfiable => Ok(DistinguishingResult {
            distinguishable: false,
            trace: None,
            direction: None,
            disagreeing_pair: None,
            reason: Some("formulas are equivalent".into()),
        }),
        SatVerdict::Unknown(msg) => Err(AnalysisError::Unsupported(msg)),
    }
}

/// Vec form: find the first `i < j` with a distinguishing trace and
/// return that witness.
///
/// Walks pairs in lexicographic order; the first non-equivalent pair
/// wins.  When every pair is pairwise equivalent, returns
/// `distinguishable == false`.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when fewer than 2 formulas.
/// * Propagates [`AnalysisError`] from [`distinguishing_trace_pair`].
pub fn distinguishing_trace(
    formulas: &[Formula],
) -> Result<DistinguishingResult, AnalysisError> {
    if formulas.len() < 2 {
        return Err(AnalysisError::InvalidInput(
            "distinguishing_trace requires at least 2 formulas".into(),
        ));
    }
    for i in 0..formulas.len() {
        for j in (i + 1)..formulas.len() {
            let pair = distinguishing_trace_pair(&formulas[i], &formulas[j])?;
            if pair.distinguishable {
                let direction = match pair.direction {
                    Some("a_only") => Some("i_only"),
                    Some("b_only") => Some("j_only"),
                    other => other,
                };
                return Ok(DistinguishingResult {
                    distinguishable: true,
                    trace: pair.trace,
                    direction,
                    disagreeing_pair: Some((i, j)),
                    reason: None,
                });
            }
        }
    }
    Ok(DistinguishingResult {
        distinguishable: false,
        trace: None,
        direction: None,
        disagreeing_pair: None,
        reason: Some("all formulas pairwise equivalent".into()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn gen_satisfying_returns_clean_result_or_unsupported() {
        match gen_satisfying_trace(&atom("p")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn gen_violating_returns_clean_result_or_unsupported() {
        match gen_violating_trace(&atom("p")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn distinguishing_pair_returns_clean_result_or_unsupported() {
        match distinguishing_trace_pair(&atom("p"), &atom("q")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn distinguishing_vec_rejects_short_input() {
        let r = distinguishing_trace(&[atom("p")]);
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }
}
