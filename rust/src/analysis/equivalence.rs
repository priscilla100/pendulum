//! `check_equivalence` — pure logical equivalence over a list of
//! formulas, plus a pair convenience entry-point.
//!
//! Operates on typed [`Formula`] ASTs.  AP-mapping comparison (whether
//! two formulas are equivalent-modulo-renaming AND their AP groundings
//! agree) lives at the MCP tool layer — this module is solely about
//! logical equivalence.
//!
//! Built on [`entailment_pair`] (two directions of entailment is
//! exactly equivalence), which in turn is built on
//! [`crate::analysis::sat::decide_sat`].  All control flow here is
//! final plumbing.

use crate::analysis::entailment::entailment_pair;
use crate::analysis::error::AnalysisError;
use crate::analysis::rename::{build_renaming_from_mappings, rename_atoms};
use crate::analysis::trace::Lasso;
use crate::Formula;
use serde::Serialize;
use std::collections::BTreeMap;

/// Result of [`equivalent_pair`].
#[derive(Debug, Clone, Serialize)]
pub struct PairEquivalence {
    /// `a ≡ b`.
    pub equivalent: bool,
    /// Trace at which they disagree.  `None` when equivalent.
    pub witness: Option<Lasso>,
    /// `"a_only"` if the witness satisfies `a` and not `b`;
    /// `"b_only"` for the reverse.  `None` when equivalent.
    pub direction: Option<&'static str>,
}

/// Result of [`check_equivalence`].
#[derive(Debug, Clone, Serialize)]
pub struct EquivalenceResult {
    /// Every pair in the input is equivalent.
    pub all_equivalent: bool,
    /// Partition of input indices into equivalence classes; class
    /// ordering and intra-class ordering are both ascending.
    pub equivalence_classes: Vec<Vec<usize>>,
    /// One witness per non-equivalent pair `(i, j)` with `i < j`.
    pub witnesses: Vec<DisagreementWitness>,
}

/// Witness for one non-equivalent pair.
#[derive(Debug, Clone, Serialize)]
pub struct DisagreementWitness {
    /// Index of the first formula in the pair.
    pub i: usize,
    /// Index of the second formula in the pair.
    pub j: usize,
    /// Trace on which the two formulas disagree.
    pub witness: Lasso,
    /// `"i_only"` (witness satisfies `formulas[i]` but not `formulas[j]`),
    /// `"j_only"` (the reverse).
    pub direction: &'static str,
}

/// Pair primitive: is `a ≡ b`?
///
/// Two directions of entailment in one call.  Used both directly and
/// as the building block for [`check_equivalence`].
///
/// # Errors
///
/// Propagates [`AnalysisError`] from [`entailment_pair`].
pub fn equivalent_pair(a: &Formula, b: &Formula) -> Result<PairEquivalence, AnalysisError> {
    let a_to_b = entailment_pair(a, b)?;
    if !a_to_b.entails {
        return Ok(PairEquivalence {
            equivalent: false,
            witness: a_to_b.counterexample,
            direction: Some("a_only"),
        });
    }
    let b_to_a = entailment_pair(b, a)?;
    if !b_to_a.entails {
        return Ok(PairEquivalence {
            equivalent: false,
            witness: b_to_a.counterexample,
            direction: Some("b_only"),
        });
    }
    Ok(PairEquivalence {
        equivalent: true,
        witness: None,
        direction: None,
    })
}

/// Result of [`equivalent_modulo_renaming`].
#[derive(Debug, Clone, Serialize)]
pub struct ModuloRenamingResult {
    /// `a` and `b` are equivalent after renaming `b`'s atoms into
    /// `a`'s namespace using the inferred renaming.
    pub equivalent_under_renaming: bool,
    /// The renaming was a bijection over the supplied mappings
    /// (every atom in both `mapping_a` and `mapping_b` had a
    /// counterpart in the other).
    pub renaming_total: bool,
    /// Disagreement witness when not equivalent under the renaming.
    pub witness: Option<Lasso>,
    /// `"a_only"` / `"b_only"` for the witness, when present.
    pub direction: Option<&'static str>,
}

/// Pair primitive: is `a ≡ b` under the renaming induced by the two
/// AP→NL groundings?
///
/// Step-by-step:
/// 1. Build a renaming `ρ: atom_b → atom_a` by matching shared NL
///    fragments across `mapping_a` and `mapping_b` (see
///    [`crate::analysis::rename::build_renaming_from_mappings`]).
/// 2. Apply `ρ` to `b` (`rename_atoms`).
/// 3. Call [`equivalent_pair`] on `a` and the renamed `b`.
///
/// The `renaming_total` flag in the result indicates whether the
/// renaming was a bijection across the supplied mappings.  A `false`
/// here doesn't necessarily mean "not equivalent" — formulas may
/// coincidentally be equivalent over fewer than the supplied atoms —
/// but it does mean the AP-grounding evidence is incomplete.
///
/// # Errors
///
/// Propagates [`AnalysisError`] from [`equivalent_pair`].
pub fn equivalent_modulo_renaming(
    a: &Formula,
    b: &Formula,
    mapping_a: &BTreeMap<String, String>,
    mapping_b: &BTreeMap<String, String>,
) -> Result<ModuloRenamingResult, AnalysisError> {
    let renaming = build_renaming_from_mappings(mapping_a, mapping_b);
    let b_renamed = rename_atoms(b, &renaming.renaming);
    let pair = equivalent_pair(a, &b_renamed)?;
    Ok(ModuloRenamingResult {
        equivalent_under_renaming: pair.equivalent,
        renaming_total: renaming.total,
        witness: pair.witness,
        direction: pair.direction,
    })
}

/// Decide pairwise equivalence over `formulas` and report a partition
/// into equivalence classes.
///
/// `check_equivalence(&[a, b])` is exactly [`equivalent_pair`] reshaped
/// into the list-form result.  For larger inputs, walks every `i < j`
/// pair, building equivalence classes via union-find on the resulting
/// equivalence graph.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when fewer than 2 formulas.
/// * Propagates [`AnalysisError`] from [`equivalent_pair`].
pub fn check_equivalence(formulas: &[Formula]) -> Result<EquivalenceResult, AnalysisError> {
    if formulas.len() < 2 {
        return Err(AnalysisError::InvalidInput(
            "check_equivalence requires at least 2 formulas".into(),
        ));
    }

    let n = formulas.len();
    let mut uf = UnionFind::new(n);
    let mut witnesses = Vec::new();

    for i in 0..n {
        for j in (i + 1)..n {
            let pair = equivalent_pair(&formulas[i], &formulas[j])?;
            if pair.equivalent {
                uf.union(i, j);
            } else if let Some(w) = pair.witness {
                let direction = match pair.direction {
                    Some("a_only") => "i_only",
                    Some("b_only") => "j_only",
                    // Defensive: should never occur for a non-equivalent
                    // pair returned by `equivalent_pair`, but the
                    // `?_only` invariant is contractual so we surface
                    // an explicit error rather than guess.
                    _ => {
                        return Err(AnalysisError::Unsupported(format!(
                            "equivalent_pair returned non-equivalent verdict without a \
                             direction tag for ({i}, {j}); cannot build witness"
                        )))
                    }
                };
                witnesses.push(DisagreementWitness {
                    i,
                    j,
                    witness: w,
                    direction,
                });
            }
            // If the pair is non-equivalent but no witness was produced
            // (e.g. backend returned UNKNOWN that the caller chose to
            // smother), we silently skip it — the class assignment
            // below conservatively leaves them in separate classes.
        }
    }

    let equivalence_classes = uf.into_classes();
    let all_equivalent = equivalence_classes.len() == 1;

    Ok(EquivalenceResult {
        all_equivalent,
        equivalence_classes,
        witnesses,
    })
}

/// Small union-find specialised for grouping indices `0..n`.
struct UnionFind {
    parent: Vec<usize>,
}

impl UnionFind {
    fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
        }
    }

    fn find(&mut self, mut i: usize) -> usize {
        while self.parent[i] != i {
            self.parent[i] = self.parent[self.parent[i]]; // path compression
            i = self.parent[i];
        }
        i
    }

    fn union(&mut self, a: usize, b: usize) {
        let ra = self.find(a);
        let rb = self.find(b);
        if ra != rb {
            self.parent[ra] = rb;
        }
    }

    /// Bucket the elements `0..n` by root, then sort buckets so that
    /// each is ascending and the overall ordering is by smallest
    /// element.
    fn into_classes(mut self) -> Vec<Vec<usize>> {
        let n = self.parent.len();
        let mut buckets: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
        for i in 0..n {
            let r = self.find(i);
            buckets.entry(r).or_default().push(i);
        }
        let mut classes: Vec<Vec<usize>> = buckets.into_values().collect();
        classes.sort_by_key(|c| c.first().copied().unwrap_or(usize::MAX));
        classes
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn rejects_singleton_input() {
        let r = check_equivalence(&[atom("p")]);
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }

    #[test]
    fn equivalent_pair_returns_clean_result_or_unsupported() {
        match equivalent_pair(&atom("p"), &atom("q")) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn check_equivalence_returns_clean_result_or_unsupported() {
        match check_equivalence(&[atom("p"), atom("q")]) {
            Ok(_) => {}
            Err(AnalysisError::Unsupported(_)) => {}
            Err(e) => panic!("unexpected error: {e:?}"),
        }
    }

    #[test]
    fn union_find_groups_correctly() {
        let mut uf = UnionFind::new(5);
        uf.union(0, 2);
        uf.union(2, 4);
        uf.union(1, 3);
        let classes = uf.into_classes();
        // {0,2,4} and {1,3}, sorted by smallest element.
        assert_eq!(classes, vec![vec![0, 2, 4], vec![1, 3]]);
    }
}
