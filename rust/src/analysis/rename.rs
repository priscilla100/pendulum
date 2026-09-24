//! Atom-renaming helpers.
//!
//! `rename_atoms(f, ρ)` walks the AST and substitutes every atom
//! `p` for its image `ρ(p)`; atoms not present in `ρ` are left
//! untouched.  Useful for the modulo-AP-renaming variant of
//! equivalence and for normalising AP names across NL-grounded
//! candidates.

use crate::Formula;
use std::collections::BTreeMap;

/// Apply a renaming `ρ: atom -> atom` to every atom in `formula`.
/// Atoms not present in `ρ` are left alone.
pub fn rename_atoms(formula: &Formula, rho: &BTreeMap<String, String>) -> Formula {
    match formula {
        Formula::FTrue | Formula::FFalse => formula.clone(),
        Formula::FAtom { name } => {
            let mapped = rho.get(name).cloned().unwrap_or_else(|| name.clone());
            Formula::FAtom { name: mapped }
        }
        Formula::FNot { operand } => Formula::FNot {
            operand: Box::new(rename_atoms(operand, rho)),
        },
        Formula::FAnd { left, right } => Formula::FAnd {
            left: Box::new(rename_atoms(left, rho)),
            right: Box::new(rename_atoms(right, rho)),
        },
        Formula::FOr { left, right } => Formula::FOr {
            left: Box::new(rename_atoms(left, rho)),
            right: Box::new(rename_atoms(right, rho)),
        },
        Formula::FImplies { left, right } => Formula::FImplies {
            left: Box::new(rename_atoms(left, rho)),
            right: Box::new(rename_atoms(right, rho)),
        },
        Formula::FIff { left, right } => Formula::FIff {
            left: Box::new(rename_atoms(left, rho)),
            right: Box::new(rename_atoms(right, rho)),
        },
        Formula::FUnary { op, operand } => Formula::FUnary {
            op: *op,
            operand: Box::new(rename_atoms(operand, rho)),
        },
        Formula::FBinary { op, left, right } => Formula::FBinary {
            op: *op,
            left: Box::new(rename_atoms(left, rho)),
            right: Box::new(rename_atoms(right, rho)),
        },
    }
}

/// Build a renaming `ρ: atom_b → atom_a` from two AP→NL mappings.
///
/// For each `(atom_b, fragment)` in `mapping_b`, look up the same
/// `fragment` in `mapping_a`'s NL-side; if some `atom_a` maps to it,
/// emit `atom_b → atom_a`.
///
/// The result is `ρ` plus a `total` flag.  `total == true` requires
/// **all** of:
///
/// 1. Every atom in `mapping_a` has a counterpart in `mapping_b`.
/// 2. Every atom in `mapping_b` has a counterpart in `mapping_a`.
/// 3. NL fragments are unique within `mapping_a` (its inverse is
///    well-defined).
/// 4. NL fragments are unique within `mapping_b` (so the inferred
///    renaming is injective both ways).
/// 5. The inferred renaming is itself injective (no two `atom_b`s
///    collide on the same `atom_a`).
///
/// Together these conditions ensure the renaming is a genuine
/// bijection over the supplied AP vocabularies, which is the property
/// a true "modulo-AP-renaming" check needs.  Codex review #2 flagged
/// the earlier length-only check as insufficient.
pub fn build_renaming_from_mappings(
    mapping_a: &BTreeMap<String, String>,
    mapping_b: &BTreeMap<String, String>,
) -> RenamingFromMappings {
    let mut inverse_a: BTreeMap<&str, &str> = BTreeMap::new();
    let mut frags_a_unique = true;
    for (atom, frag) in mapping_a {
        if inverse_a.insert(frag.as_str(), atom.as_str()).is_some() {
            frags_a_unique = false;
        }
    }
    let mut frags_b_seen: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
    let mut frags_b_unique = true;
    for frag in mapping_b.values() {
        if !frags_b_seen.insert(frag.as_str()) {
            frags_b_unique = false;
        }
    }

    let mut renaming: BTreeMap<String, String> = BTreeMap::new();
    for (atom_b, frag) in mapping_b {
        if let Some(atom_a) = inverse_a.get(frag.as_str()) {
            renaming.insert(atom_b.clone(), (*atom_a).to_string());
        }
    }

    // Renaming is injective iff its image set has the same size as its
    // domain (no two domain elements map to the same image).
    let image_distinct: std::collections::BTreeSet<&String> = renaming.values().collect();
    let injective = image_distinct.len() == renaming.len();

    let total = frags_a_unique
        && frags_b_unique
        && injective
        && renaming.len() == mapping_a.len()
        && renaming.len() == mapping_b.len();

    RenamingFromMappings { renaming, total }
}

/// Output of [`build_renaming_from_mappings`].
#[derive(Debug, Clone)]
pub struct RenamingFromMappings {
    /// `atom_b → atom_a` substitution.
    pub renaming: BTreeMap<String, String>,
    /// `true` iff every atom in `mapping_a` has a counterpart in
    /// `mapping_b` and vice-versa.
    pub total: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn rename_swaps_atoms() {
        let f = Formula::FAnd {
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let mut rho = BTreeMap::new();
        rho.insert("p".to_string(), "x".to_string());
        rho.insert("q".to_string(), "y".to_string());
        let renamed = rename_atoms(&f, &rho);
        assert_eq!(format!("{renamed}"), "(x & y)");
    }

    #[test]
    fn rename_leaves_unmapped_atoms() {
        let mut rho = BTreeMap::new();
        rho.insert("p".to_string(), "x".to_string());
        let renamed = rename_atoms(&atom("q"), &rho);
        assert_eq!(format!("{renamed}"), "q");
    }

    #[test]
    fn build_renaming_complete() {
        let mut a = BTreeMap::new();
        a.insert("p".to_string(), "the gate is open".to_string());
        a.insert("q".to_string(), "the train arrives".to_string());
        let mut b = BTreeMap::new();
        b.insert("x".to_string(), "the gate is open".to_string());
        b.insert("y".to_string(), "the train arrives".to_string());
        let r = build_renaming_from_mappings(&a, &b);
        assert!(r.total);
        assert_eq!(r.renaming.get("x"), Some(&"p".to_string()));
        assert_eq!(r.renaming.get("y"), Some(&"q".to_string()));
    }

    #[test]
    fn build_renaming_incomplete_when_extra_atom() {
        let mut a = BTreeMap::new();
        a.insert("p".to_string(), "gate".to_string());
        let mut b = BTreeMap::new();
        b.insert("x".to_string(), "gate".to_string());
        b.insert("y".to_string(), "train".to_string());
        let r = build_renaming_from_mappings(&a, &b);
        assert!(!r.total);
        assert_eq!(r.renaming.get("x"), Some(&"p".to_string()));
        assert_eq!(r.renaming.get("y"), None);
    }

    #[test]
    fn build_renaming_rejects_duplicate_fragments_in_a() {
        // mapping_a has two atoms pointing at the same fragment — the
        // resulting renaming cannot be a bijection.
        let mut a = BTreeMap::new();
        a.insert("p".to_string(), "gate".to_string());
        a.insert("q".to_string(), "gate".to_string());
        let mut b = BTreeMap::new();
        b.insert("x".to_string(), "gate".to_string());
        b.insert("y".to_string(), "gate".to_string());
        let r = build_renaming_from_mappings(&a, &b);
        assert!(!r.total);
    }

    #[test]
    fn build_renaming_rejects_duplicate_fragments_in_b() {
        let mut a = BTreeMap::new();
        a.insert("p".to_string(), "gate".to_string());
        let mut b = BTreeMap::new();
        b.insert("x".to_string(), "gate".to_string());
        b.insert("y".to_string(), "gate".to_string());
        let r = build_renaming_from_mappings(&a, &b);
        assert!(!r.total);
    }
}
