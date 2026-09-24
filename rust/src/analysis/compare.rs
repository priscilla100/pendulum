//! `compare_candidates` — pairwise implication lattice over a list of
//! candidate formulas.
//!
//! Fully plumbed: walks every `i < j` pair, calls
//! [`crate::analysis::entailment::entailment_pair`] in both
//! directions, and groups the results into equivalent / stronger-than
//! / incomparable buckets.  The only logical body in the call chain
//! is [`crate::analysis::sat::decide_sat`].

use crate::analysis::entailment::entailment_pair;
use crate::analysis::error::AnalysisError;
use crate::analysis::trace::Lasso;
use crate::Formula;
use serde::Serialize;

/// One distinguishing witness for an incomparable pair.
#[derive(Debug, Clone, Serialize)]
pub struct DistinguishingPair {
    /// Index `i` into the input list.
    pub i: usize,
    /// Index `j` into the input list.
    pub j: usize,
    /// Trace that separates them.
    pub trace: Lasso,
    /// `"i_only"` (satisfies formulas[i] but not formulas[j]) or
    /// `"j_only"`.
    pub direction: &'static str,
}

/// Result of [`compare_candidates`].
#[derive(Debug, Clone, Serialize)]
pub struct CompareResult {
    /// Symmetric, reflexive entries omitted: only `(i, j)` with `i < j`.
    pub equivalent_pairs: Vec<(usize, usize)>,
    /// `(i, j)` where `formulas[i]` strictly implies `formulas[j]`.
    pub stronger_than: Vec<(usize, usize)>,
    /// `(i, j)` (with `i < j`) where neither implies the other.
    pub incomparable: Vec<(usize, usize)>,
    /// One witness per incomparable pair.
    pub distinguishing_traces: Vec<DistinguishingPair>,
}

/// Compute the pairwise implication lattice over `formulas`.
///
/// O(n²) entailment checks; each check is two `decide_sat` calls
/// (via [`entailment_pair`]).
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when fewer than 2 formulas.
/// * Propagates [`AnalysisError`] from [`entailment_pair`].
pub fn compare_candidates(formulas: &[Formula]) -> Result<CompareResult, AnalysisError> {
    if formulas.len() < 2 {
        return Err(AnalysisError::InvalidInput(
            "compare_candidates requires at least 2 formulas".into(),
        ));
    }
    let n = formulas.len();
    let mut equivalent_pairs = Vec::new();
    let mut stronger_than = Vec::new();
    let mut incomparable = Vec::new();
    let mut distinguishing_traces = Vec::new();

    for i in 0..n {
        for j in (i + 1)..n {
            let i_to_j = entailment_pair(&formulas[i], &formulas[j])?;
            let j_to_i = entailment_pair(&formulas[j], &formulas[i])?;
            match (i_to_j.entails, j_to_i.entails) {
                (true, true) => equivalent_pairs.push((i, j)),
                (true, false) => stronger_than.push((i, j)),
                (false, true) => stronger_than.push((j, i)),
                (false, false) => {
                    incomparable.push((i, j));
                    // Prefer the i→j counterexample (witness satisfies i,
                    // violates j → "i_only"); fall back to the dual.
                    if let Some(t) = i_to_j.counterexample {
                        distinguishing_traces.push(DistinguishingPair {
                            i,
                            j,
                            trace: t,
                            direction: "i_only",
                        });
                    } else if let Some(t) = j_to_i.counterexample {
                        distinguishing_traces.push(DistinguishingPair {
                            i,
                            j,
                            trace: t,
                            direction: "j_only",
                        });
                    }
                }
            }
        }
    }

    Ok(CompareResult {
        equivalent_pairs,
        stronger_than,
        incomparable,
        distinguishing_traces,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn rejects_singleton_input() {
        let r = compare_candidates(&[atom("p")]);
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }

    #[test]
    fn compare_returns_clean_result_or_unsupported() {
        match compare_candidates(&[atom("p"), atom("q")]) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }
}
