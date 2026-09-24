//! `check_consistency` — joint satisfiability of multiple formulas.
//!
//! Operates on a slice of typed [`Formula`] ASTs. The MCP tool wrapper
//! does the surface-syntax parsing and the JSON serialisation; this
//! module is pure logic over the AST.
//!
//! The single satisfiability oracle is
//! [`crate::analysis::sat::decide_sat`].  All control flow here —
//! conjoining the input, enumerating subsets, finding pairwise
//! conflicts — is final plumbing.

use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::analysis::sat::{decide_sat, SatVerdict};
use crate::analysis::trace::Lasso;
use crate::Formula;
use serde::Serialize;

/// Result of [`check_consistency`].
#[derive(Debug, Clone, Serialize)]
pub struct ConsistencyResult {
    /// `true` iff `∧ formulas` is satisfiable.
    pub consistent: bool,
    /// Satisfying lasso when `consistent == true`.
    pub witness: Option<Lasso>,
    /// Indices of a maximum satisfiable subset of the input.  `None`
    /// when `consistent == true` (the whole set is the answer) or
    /// when the input is too large to enumerate exhaustively (see
    /// [`MAX_SUBSET_ENUM_N`]).  In the pathological "every individual
    /// formula is unsatisfiable" case the result is `Some(vec![])`
    /// because the empty conjunction is trivially satisfiable.
    pub maximal_subset: Option<Vec<usize>>,
    /// Pairs `(i, j)` with `i < j` whose two-formula conjunction is
    /// itself unsatisfiable. Empty when `consistent == true`.
    pub conflicts: Vec<(usize, usize)>,
}

/// Cap on input size for exhaustive max-satisfiable-subset enumeration.
/// 2^12 = 4096 subsets — small enough to stay snappy, large enough to
/// cover every realistic agent-emitted candidate set.
pub const MAX_SUBSET_ENUM_N: usize = 12;

/// Decide whether `formulas` are jointly satisfiable.
///
/// When inconsistent, also reports a maximum satisfiable subset (cap:
/// [`MAX_SUBSET_ENUM_N`]) and every pairwise conflict.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] if `formulas` is empty.
/// * Propagates [`AnalysisError`] from [`decide_sat`] for backend
///   issues.
pub fn check_consistency(formulas: &[Formula]) -> Result<ConsistencyResult, AnalysisError> {
    if formulas.is_empty() {
        return Err(AnalysisError::InvalidInput(
            "check_consistency requires at least 1 formula".into(),
        ));
    }

    let Some(conjunction) = form::conjunction(formulas) else {
        // Unreachable given the guard above, but a clean error rather
        // than an unwrap.
        return Err(AnalysisError::InvalidInput(
            "internal: conjunction of non-empty input was None".into(),
        ));
    };

    match decide_sat(&conjunction)? {
        SatVerdict::Satisfiable(l) => Ok(ConsistencyResult {
            consistent: true,
            witness: Some(l),
            maximal_subset: None,
            conflicts: Vec::new(),
        }),
        SatVerdict::Unsatisfiable => {
            let conflicts = pairwise_conflicts(formulas)?;
            let maximal_subset = if formulas.len() <= MAX_SUBSET_ENUM_N {
                max_satisfiable_subset(formulas)?
            } else {
                None
            };
            Ok(ConsistencyResult {
                consistent: false,
                witness: None,
                maximal_subset,
                conflicts,
            })
        }
        SatVerdict::Unknown(msg) => Err(AnalysisError::Unsupported(format!(
            "sat backend returned UNKNOWN for ∧ formulas: {msg}"
        ))),
    }
}

/// All `(i, j)` with `i < j` such that `formulas[i] ∧ formulas[j]`
/// is unsatisfiable.
fn pairwise_conflicts(formulas: &[Formula]) -> Result<Vec<(usize, usize)>, AnalysisError> {
    let n = formulas.len();
    let mut out = Vec::new();
    for i in 0..n {
        for j in (i + 1)..n {
            let pair = form::and(formulas[i].clone(), formulas[j].clone());
            if matches!(decide_sat(&pair)?, SatVerdict::Unsatisfiable) {
                out.push((i, j));
            }
        }
    }
    Ok(out)
}

/// Find an inclusion-maximal subset of `formulas` whose conjunction is
/// satisfiable.  Searches in decreasing size order; the first SAT hit
/// wins.  When every non-empty subset is unsatisfiable (e.g. each
/// individual formula is `false`), returns `Some(vec![])` — the empty
/// conjunction is trivially `true` and is the maximum satisfiable
/// subset in that pathological case.
fn max_satisfiable_subset(formulas: &[Formula]) -> Result<Option<Vec<usize>>, AnalysisError> {
    let n = formulas.len();
    // We already know the full conjunction is UNSAT, so start at n-1.
    for size in (1..n).rev() {
        if let Some(idx) = first_sat_subset(formulas, size)? {
            return Ok(Some(idx));
        }
    }
    // No non-empty subset was satisfiable.  The empty subset is
    // trivially SAT (∧ ∅ ≡ ⊤), so that *is* the maximum satisfiable
    // subset in this case.
    Ok(Some(Vec::new()))
}

/// Test every subset of `formulas` of the given size in
/// lexicographic order; return the first one whose conjunction is
/// satisfiable.
fn first_sat_subset(
    formulas: &[Formula],
    size: usize,
) -> Result<Option<Vec<usize>>, AnalysisError> {
    let n = formulas.len();
    debug_assert!(size > 0 && size <= n);
    let mut idx: Vec<usize> = (0..size).collect();
    loop {
        let subset: Vec<Formula> = idx.iter().map(|&i| formulas[i].clone()).collect();
        if let Some(conj) = form::conjunction(&subset) {
            if matches!(decide_sat(&conj)?, SatVerdict::Satisfiable(_)) {
                return Ok(Some(idx));
            }
        }
        if !advance_combination(&mut idx, n) {
            return Ok(None);
        }
    }
}

/// Advance `idx` to the next combination of indices from `[0, n)` in
/// lexicographic order. Returns `false` if there is no next combination.
fn advance_combination(idx: &mut [usize], n: usize) -> bool {
    let size = idx.len();
    if size == 0 {
        return false;
    }
    // Find rightmost index that can still be incremented.
    let mut k = size;
    while k > 0 && idx[k - 1] == n - (size - k + 1) {
        k -= 1;
    }
    if k == 0 {
        return false;
    }
    idx[k - 1] += 1;
    for j in k..size {
        idx[j] = idx[j - 1] + 1;
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn empty_input_rejected() {
        let r = check_consistency(&[]);
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }

    #[test]
    fn single_formula_call_is_clean() {
        // `decide_sat` is now wired to BLACK.  On a host with BLACK
        // installed, `check_consistency(&[atom("p")])` returns Ok
        // (the atom `p` is satisfiable).  On a host without BLACK,
        // the call surfaces `Unsupported`.  Either is fine —
        // the contract here is "no panic, no NotImplemented".
        match check_consistency(&[atom("p")]) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn advance_combination_walks_lexicographically() {
        let mut idx = vec![0, 1, 2];
        // Expected sequence over n=5, size=3.
        let mut seq = vec![idx.clone()];
        while advance_combination(&mut idx, 5) {
            seq.push(idx.clone());
        }
        assert_eq!(seq.len(), 10); // C(5,3) = 10
        assert_eq!(seq[0], vec![0, 1, 2]);
        assert_eq!(seq[9], vec![2, 3, 4]);
    }
}
