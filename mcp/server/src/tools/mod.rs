//! Concrete tool modules.
//!
//! Each tool lives in its own file and implements
//! [`crate::tool::Tool`]. [`all`] returns every tool the server
//! knows about; the CLI `--tools` selector then narrows it.
//!
//! ## Catalogue — 14 tools
//!
//! Every tool listed here is fully plumbed: tool wrappers parse the
//! surface-syntax formula(s) via the OCaml front-end, call into the
//! corresponding `pltl_rust::analysis::*` function, and serialise the
//! result. Sat-dependent tools shell out to the BLACK solver via
//! [`pltl_rust::analysis::sat::decide_sat`].
//!
//! | Tool                         | Logical fn (`pltl_rust::analysis::…`)    |
//! | ---------------------------- | ---------------------------------------- |
//! | `parse_and_canonicalize`     | `ap`, `temporal_class`, `nnf`, `simplify` |
//! | `extract_ap_mapping`         | LLM-backed (helper model)                |
//! | `nl_to_ltl_via_salt`         | shells out to the SALT compiler          |
//! | `nl_to_ltl_via_python`       | LLM-backed (helper model)                |
//! | `salt_help`                  | static SALT-syntax reference             |
//! | `ltl_to_nl`                  | `ltl_to_tnl` + helper LLM paraphrase     |
//! | `check_equivalence`          | `equivalence::equivalent_pair`           |
//! | `check_entailment`           | `entailment::entailment_pair`            |
//! | `compare_candidates`         | `compare::compare_candidates`            |
//! | `gen_satisfying_trace`       | `trace_gen::gen_satisfying_trace`        |
//! | `gen_violating_trace`        | `trace_gen::gen_violating_trace`         |
//! | `distinguishing_trace`       | `trace_gen::distinguishing_trace_pair`   |
//! | `check_trace_satisfaction`   | `trace_check::check_trace_satisfaction`  |
//! | `check_consistency`          | `consistency::check_consistency`         |
//!
//! ## Adding a tool
//!
//! 1. Add `pub mod <name>;` here.
//! 2. Append `Arc::new(<name>::<Type>::default()) as Arc<dyn Tool>` to
//!    [`all`].
//! 3. Implement the trait in `src/tools/<name>.rs`. No central match
//!    arms to update.

use crate::tool::Tool;
use std::sync::Arc;

mod parse_util;

pub mod check_consistency;
pub mod check_entailment;
pub mod check_equivalence;
pub mod check_trace_satisfaction;
pub mod compare_candidates;
pub mod distinguishing_trace;
pub mod extract_ap_mapping;
pub mod gen_satisfying_trace;
pub mod gen_violating_trace;
pub mod ltl_to_nl;
pub mod nl_to_ltl_via_python;
pub mod nl_to_ltl_via_salt;
pub mod parse_and_canonicalize;
pub mod salt_help;

/// Build the full catalogue. Order is irrelevant — the registry
/// indexes by name. Keep the entries alphabetical so diffs are
/// trivially readable.
pub fn all() -> Vec<Arc<dyn Tool>> {
    vec![
        Arc::new(check_consistency::CheckConsistencyTool) as Arc<dyn Tool>,
        Arc::new(check_entailment::CheckEntailmentTool) as Arc<dyn Tool>,
        Arc::new(check_equivalence::CheckEquivalenceTool) as Arc<dyn Tool>,
        Arc::new(check_trace_satisfaction::CheckTraceSatisfactionTool) as Arc<dyn Tool>,
        Arc::new(compare_candidates::CompareCandidatesTool) as Arc<dyn Tool>,
        Arc::new(distinguishing_trace::DistinguishingTraceTool) as Arc<dyn Tool>,
        Arc::new(extract_ap_mapping::ExtractApMappingTool) as Arc<dyn Tool>,
        Arc::new(gen_satisfying_trace::GenSatisfyingTraceTool) as Arc<dyn Tool>,
        Arc::new(gen_violating_trace::GenViolatingTraceTool) as Arc<dyn Tool>,
        Arc::new(ltl_to_nl::LtlToNlTool) as Arc<dyn Tool>,
        Arc::new(nl_to_ltl_via_python::NlToLtlViaPythonTool) as Arc<dyn Tool>,
        Arc::new(nl_to_ltl_via_salt::NlToLtlViaSaltTool) as Arc<dyn Tool>,
        Arc::new(parse_and_canonicalize::ParseAndCanonicalizeTool) as Arc<dyn Tool>,
        Arc::new(salt_help::SaltHelpTool) as Arc<dyn Tool>,
    ]
}

/// All tool names this server *could* expose. Used by the CLI's
/// `--list-available` flag and by error messages.
pub fn known_names() -> Vec<&'static str> {
    all().iter().map(|t| t.name()).collect()
}
