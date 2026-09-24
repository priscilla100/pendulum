//! `check_entailment` — does `(∧ premises) → conclusion` hold?
//!
//! Operates on typed [`Formula`] ASTs.  Generalised over a slice of
//! premises; the pair primitive [`entailment_pair`] is exposed because
//! [`check_entailment`] folds the premises and delegates to it.
//!
//! The single satisfiability oracle is
//! [`crate::analysis::sat::decide_sat`].  All control flow here is
//! final plumbing.

use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::analysis::sat::{decide_sat, SatVerdict};
use crate::analysis::trace::Lasso;
use crate::Formula;
use serde::Serialize;

/// Result of an entailment query (pair and vec forms share this shape).
#[derive(Debug, Clone, Serialize)]
pub struct EntailmentResult {
    /// `antecedent → consequent` is valid.
    pub entails: bool,
    /// Strictly stronger: `antecedent → consequent` AND
    /// `NOT (consequent → antecedent)`.  Always `false` when `entails`
    /// is `false`.
    pub strict: bool,
    /// Trace satisfying the antecedent and violating the consequent,
    /// when entailment fails.  `None` when `entails == true`.
    pub counterexample: Option<Lasso>,
}

/// Pair primitive: does `antecedent → consequent` hold?
///
/// The single building block that `check_entailment` calls after
/// folding multiple premises.  Two `decide_sat` calls:
///
/// 1. `decide_sat(antecedent ∧ ¬consequent)` — entailment + counterexample.
/// 2. `decide_sat(consequent ∧ ¬antecedent)` — strict flag (skipped
///    when entailment already fails).
///
/// # Errors
///
/// * Propagates [`AnalysisError`] from [`decide_sat`].
/// * Surfaces backend `Unknown` verdicts as
///   [`AnalysisError::Unsupported`].
pub fn entailment_pair(
    antecedent: &Formula,
    consequent: &Formula,
) -> Result<EntailmentResult, AnalysisError> {
    let forward = decide_sat(&form::and_not(antecedent, consequent))?;
    let (entails, counterexample) = match forward {
        SatVerdict::Unsatisfiable => (true, None),
        SatVerdict::Satisfiable(l) => (false, Some(l)),
        SatVerdict::Unknown(msg) => {
            return Err(AnalysisError::Unsupported(format!(
                "sat backend UNKNOWN on (antecedent ∧ ¬consequent): {msg}"
            )))
        }
    };

    let strict = if entails {
        match decide_sat(&form::and_not(consequent, antecedent))? {
            SatVerdict::Satisfiable(_) => true,
            SatVerdict::Unsatisfiable => false,
            SatVerdict::Unknown(msg) => {
                return Err(AnalysisError::Unsupported(format!(
                    "sat backend UNKNOWN on (consequent ∧ ¬antecedent): {msg}"
                )))
            }
        }
    } else {
        false
    };

    Ok(EntailmentResult {
        entails,
        strict,
        counterexample,
    })
}

/// Decide whether `(∧ premises) → conclusion` is valid.
///
/// `premises.len() == 1` reduces to [`entailment_pair`].  For longer
/// lists, builds the left-folded conjunction of premises and delegates
/// to the pair primitive.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when `premises` is empty (use
///   `[Formula::FTrue]` to ask "is `conclusion` valid?").
/// * Propagates [`AnalysisError`] from [`entailment_pair`].
pub fn check_entailment(
    premises: &[Formula],
    conclusion: &Formula,
) -> Result<EntailmentResult, AnalysisError> {
    if premises.is_empty() {
        return Err(AnalysisError::InvalidInput(
            "check_entailment requires at least 1 premise (use [TRUE] for plain validity)".into(),
        ));
    }
    let Some(conjunction) = form::conjunction(premises) else {
        return Err(AnalysisError::InvalidInput(
            "internal: conjunction of non-empty premises was None".into(),
        ));
    };
    entailment_pair(&conjunction, conclusion)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn check_entailment_rejects_empty_premises() {
        let r = check_entailment(&[], &atom("p"));
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }

    #[test]
    fn entailment_pair_returns_clean_result_or_unsupported() {
        match entailment_pair(&atom("p"), &atom("q")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn check_entailment_delegates_to_pair() {
        match check_entailment(&[atom("p"), atom("q")], &atom("r")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }
}
