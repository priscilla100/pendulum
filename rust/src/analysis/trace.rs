//! Lasso (ultimately periodic infinite ω-trace) representation.
//!
//! Per the crate-level semantic invariants, every trace in this system
//! is an *infinite* ω-trace. The only finite encoding we tolerate is
//! the **lasso**: a finite prefix followed by a finite, indefinitely
//! repeating loop body.
//!
//! ```text
//!     trace ≜  prefix · (loop)^ω
//! ```
//!
//! Each step is a [`State`] — a set of atomic propositions that hold
//! at that point in time. Atoms not present are interpreted as false.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// One time step of a trace.
///
/// `BTreeSet` (not `HashSet`) so the JSON serialisation is order-
/// stable; downstream cache keys and trace equality checks depend on
/// it.
pub type State = BTreeSet<String>;

/// Ultimately periodic infinite trace: `prefix · (loop)^ω`.
///
/// `loop_` is the period; an empty loop is invalid (the trace would
/// not be infinite). `prefix` may be empty.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Lasso {
    /// Finite prefix.
    pub prefix: Vec<State>,
    /// Finite loop body, repeated forever. `loop` is a Rust keyword,
    /// so the field is named `loop_` on the Rust side and renamed on
    /// the JSON side so the wire format matches the spec.
    #[serde(rename = "loop")]
    pub loop_: Vec<State>,
}

impl Lasso {
    /// Construct a lasso, validating the loop body is non-empty.
    pub fn new(prefix: Vec<State>, loop_: Vec<State>) -> Result<Self, &'static str> {
        if loop_.is_empty() {
            return Err("lasso loop body must be non-empty");
        }
        Ok(Self { prefix, loop_ })
    }

    /// Total length of one unrolling: `|prefix| + |loop|`.
    pub fn unrolled_len(&self) -> usize {
        self.prefix.len() + self.loop_.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_loop_rejected() {
        let err = Lasso::new(vec![], vec![]).unwrap_err();
        assert!(err.contains("loop body"));
    }

    #[test]
    fn round_trips_through_json() {
        let l = Lasso::new(
            vec![BTreeSet::from(["p".into()])],
            vec![BTreeSet::from(["q".into()])],
        )
        .expect("ok");
        let s = serde_json::to_string(&l).expect("ser");
        // Field is renamed to "loop" on the wire.
        assert!(s.contains("\"loop\""));
        let back: Lasso = serde_json::from_str(&s).expect("de");
        assert_eq!(back.prefix.len(), 1);
        assert_eq!(back.loop_.len(), 1);
    }
}
