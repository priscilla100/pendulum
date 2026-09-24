//! Symbolic analyses over the typed PLTL AST.
//!
//! All analyses operate under the global semantic invariants documented
//! in [`crate`]'s crate-level docs (infinite ω-trace, PLTL with strict
//! past at `t = 0`, strong Next, BLACK backend for sat).
//!
//! ## Public surface
//!
//! Each of these is exposed as an MCP tool via `mcp/server/src/tools/`:
//!
//! | Module               | Tool name                      |
//! | -------------------- | ------------------------------ |
//! | [`ap`]               | `atoms()` helper (LLM tool in server) |
//! | [`ltl_to_tnl`]       | `ltl_to_nl` (paraphrase)       |
//! | [`equivalence`]      | `check_equivalence`            |
//! | [`entailment`]       | `check_entailment`             |
//! | [`compare`]          | `compare_candidates`           |
//! | [`trace_gen`]        | `gen_satisfying_trace`         |
//! | [`trace_gen`]        | `gen_violating_trace`          |
//! | [`trace_gen`]        | `distinguishing_trace`         |
//! | [`trace_check`]      | `check_trace_satisfaction`     |
//! | [`synthesis`]        | `synthesize_from_traces`       |
//! | [`consistency`]      | `check_consistency`            |
//!
//! ## Library-internal
//!
//! Not exposed to the agent; used by the public surface above.
//!
//! * [`simplify`]       — formula simplification
//! * [`nnf`]            — push negations inward
//! * [`temporal_class`] — past / future / both classification

pub mod error;
pub mod trace;

pub mod temporal_class;

pub mod black_solver;
pub mod form;
pub mod rename;
pub mod sat;
pub mod syslite_solver;

pub mod ap;
pub mod compare;
pub mod consistency;
pub mod entailment;
pub mod equivalence;
pub mod ltl_to_tnl;
pub mod synthesis;
pub mod trace_check;
pub mod trace_explain;
pub mod trace_gen;

pub mod nnf;
pub mod simplify;
