//! Satisfiability primitive shared across consistency, entailment,
//! equivalence, trace generation, and distinguishing-trace analyses.
//!
//! `decide_sat` is the **only** place where the Spot / BLACK backend
//! is invoked; every other analysis composes it.  Keeping the backend
//! call here means the backend choice (BLACK for PLTL, Spot for pure
//! LTL) is configurable in exactly one location.
//!
//! ## Why a separate module
//!
//! Several public tools all reduce to one or two `decide_sat` calls:
//!
//! * `check_consistency` — `decide_sat(∧ formulas)`.
//! * `gen_satisfying_trace` — `decide_sat(formula)`.
//! * `gen_violating_trace` — `decide_sat(¬formula)`.
//! * `check_entailment` — `decide_sat(antecedent ∧ ¬consequent)` + dual.
//! * `equivalent_pair` — two `decide_sat` calls.
//! * `distinguishing_trace_pair` — two `decide_sat` calls.
//!
//! Centralising the primitive means filling in one body (in this file)
//! lights up every higher-level analysis that builds on it.

use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::analysis::trace::Lasso;
use crate::Formula;

/// Outcome of a satisfiability query.
#[derive(Debug, Clone)]
pub enum SatVerdict {
    /// Formula is satisfiable; carries a witness lasso.
    Satisfiable(Lasso),
    /// Formula has no model.
    Unsatisfiable,
    /// Backend could not decide (timeout, unsupported construct,
    /// resource limit). The message is shown verbatim with the
    /// surrounding analysis's `Unsupported` wrapper.
    Unknown(String),
}

impl SatVerdict {
    /// `true` when the verdict carries a witness lasso.
    pub fn is_sat(&self) -> bool {
        matches!(self, Self::Satisfiable(_))
    }

    /// `true` when the formula has no model.
    pub fn is_unsat(&self) -> bool {
        matches!(self, Self::Unsatisfiable)
    }

    /// `true` when the backend could not decide.
    pub fn is_unknown(&self) -> bool {
        matches!(self, Self::Unknown(_))
    }

    /// Move the witness out of a `Satisfiable` verdict.
    pub fn into_witness(self) -> Option<Lasso> {
        match self {
            Self::Satisfiable(l) => Some(l),
            _ => None,
        }
    }
}

/// Decide whether `f` is satisfiable.
///
/// On `SAT`, returns a witness lasso.  On `UNSAT`, returns
/// [`SatVerdict::Unsatisfiable`].  On a backend hiccup that the
/// surrounding analysis should surface (not propagate as a hard error)
/// returns [`SatVerdict::Unknown`].
///
/// # Implementation
///
/// Delegates to
/// [`crate::analysis::black_solver::decide_sat_via_black`].  The
/// BLACK wrapper normalises Release/WeakUntil/Trigger into Until/Since/
/// Globally form, serialises to BLACK's surface syntax, invokes
/// `black solve -o json -m -f <formula>`, and decodes the lasso
/// model.
///
/// # Errors
///
/// * [`AnalysisError::Unsupported`] when BLACK is missing, the
///   subprocess fails, or BLACK returns malformed JSON.
pub fn decide_sat(f: &Formula) -> Result<SatVerdict, AnalysisError> {
    crate::analysis::black_solver::decide_sat_via_black(f)
}

/// Decide whether `f` is valid (i.e. holds on every trace).
///
/// Convenience wrapper: `decide_validity(f)` ≡
/// `decide_sat(¬f).is_unsat()`, with the counterexample lasso surfaced
/// when validity fails.
///
/// # Errors
///
/// Propagates errors from [`decide_sat`].
pub fn decide_validity(f: &Formula) -> Result<ValidityVerdict, AnalysisError> {
    match decide_sat(&form::not(f.clone()))? {
        SatVerdict::Unsatisfiable => Ok(ValidityVerdict::Valid),
        SatVerdict::Satisfiable(l) => Ok(ValidityVerdict::Invalid(l)),
        SatVerdict::Unknown(msg) => Ok(ValidityVerdict::Unknown(msg)),
    }
}

/// Outcome of [`decide_validity`].
#[derive(Debug, Clone)]
pub enum ValidityVerdict {
    /// `f` holds on every trace.
    Valid,
    /// `f` is violated by the carried witness lasso.
    Invalid(Lasso),
    /// Backend could not decide.
    Unknown(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    /// When BLACK isn't installed, `decide_sat` surfaces a clean
    /// `Unsupported` rather than a `NotImplemented` or panic.  When
    /// BLACK is installed (CI image, dev box with BLACK_BIN set), the
    /// trivially satisfiable `FTrue` formula returns SAT.  Either
    /// outcome is acceptable here — what we're asserting is "no
    /// panic, no NotImplemented, error path is the Unsupported one".
    #[test]
    fn decide_sat_returns_clean_result_or_unsupported() {
        match decide_sat(&Formula::FTrue) {
            Ok(SatVerdict::Satisfiable(_)) => {}
            Ok(other) => panic!("FTrue should be SAT, got {other:?}"),
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn decide_validity_returns_clean_result_or_unsupported() {
        match decide_validity(&Formula::FTrue) {
            Ok(ValidityVerdict::Valid) => {}
            Ok(other) => panic!("FTrue should be Valid, got {other:?}"),
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }
}
