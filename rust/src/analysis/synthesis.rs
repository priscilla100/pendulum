//! `synthesize_from_traces` — formula learning from positive +
//! negative lasso examples, delegated to SySLite2.
//!
//! The heavy lifting lives in
//! [`crate::analysis::syslite_solver::synthesize_via_syslite2`],
//! which shells out to the Python SySLite2 tool (a SyGuS-based PLTL
//! synthesiser).  This module is the orchestrator: validate input,
//! call SySLite2 with the configured timeout / candidate cap, and
//! optionally double-check each returned candidate via
//! [`is_consistent_with`].

use crate::analysis::error::AnalysisError;
use crate::analysis::syslite_solver::synthesize_via_syslite2;
use crate::analysis::trace::Lasso;
use crate::analysis::trace_check::check_trace_satisfaction;
use crate::Formula;
use std::time::Duration;

/// Default per-call timeout for SySLite2 (60 seconds).  SyGuS can
/// run forever; this caps the wall-clock budget unless the caller
/// overrides via [`SynthesisOptions::timeout_seconds`].
pub const DEFAULT_TIMEOUT_SECONDS: u64 = 60;

/// Default cap on the number of candidate formulas returned when the
/// caller doesn't specify [`SynthesisOptions::max_results`].
pub const DEFAULT_MAX_RESULTS: u32 = 5;

/// Which fragment of LTL SySLite2 should synthesise.
///
/// The default ([`LogicMode::Ltl`]) is **future-time** LTL — that's
/// what the user's `Driver.py -l ltl` example uses for the
/// emergency-alert system trace.  Callers should switch to
/// [`LogicMode::Pltl`] only when the input prompt explicitly asks for
/// past-time operators.
#[derive(Debug, Clone, Copy, Default)]
pub enum LogicMode {
    /// Future-time LTL (X / F / G / U).  This is the SySLite2 default
    /// and the right pick for most synthesis tasks.
    #[default]
    Ltl,
    /// Past-time LTL (Y / O / H / S).  Use only when the user
    /// explicitly asks for the past-only fragment.
    Pltl,
}

impl LogicMode {
    /// CLI string passed to SySLite2's `-l` flag.
    pub fn as_cli_arg(self) -> &'static str {
        match self {
            LogicMode::Ltl => "ltl",
            LogicMode::Pltl => "pltl",
        }
    }
}

/// Options for synthesis.
#[derive(Debug, Clone, Default)]
pub struct SynthesisOptions {
    /// Cap on the number of candidates returned (SySLite2's `-n` flag).
    pub max_results: Option<u32>,
    /// Cap on AST size of any returned candidate (SySLite2's `-s`
    /// flag).  Currently unused at the wrapper layer; SySLite2 has
    /// its own default and we let it decide.
    pub max_size: Option<u32>,
    /// Per-call wall-clock timeout in seconds.  SyGuS-based synthesis
    /// can run forever; the wrapper kills SySLite2 after this elapses.
    pub timeout_seconds: Option<u64>,
    /// Which fragment of LTL to synthesise.  Defaults to
    /// [`LogicMode::Ltl`] (future-time only).  Set to
    /// [`LogicMode::Pltl`] only when the request explicitly asks for
    /// past-time operators.
    pub logic_mode: Option<LogicMode>,
}

/// Synthesise formulas consistent with the given positive / negative
/// example lassos.
///
/// Delegates the enumeration step to SySLite2.  By default we trust
/// SySLite2's verdict (it only emits candidates that satisfy its
/// internal positive/negative constraints); set
/// `PLTL_SYNTHESIS_DOUBLECHECK=1` in the environment to additionally
/// validate each returned formula against the example traces via
/// [`check_trace_satisfaction`].  The double-check is off by default
/// because it doubles BLACK work on every candidate.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when no examples are supplied.
/// * Propagates [`AnalysisError`] from
///   [`synthesize_via_syslite2`] (SySLite2 missing, timeout,
///   subprocess failure, unparseable output).
pub fn synthesize_from_traces(
    aps: &[String],
    positive: &[Lasso],
    negative: &[Lasso],
    opts: &SynthesisOptions,
) -> Result<Vec<Formula>, AnalysisError> {
    if positive.is_empty() && negative.is_empty() {
        return Err(AnalysisError::InvalidInput(
            "synthesize_from_traces requires at least one positive or negative trace".into(),
        ));
    }
    let max_candidates = opts.max_results.unwrap_or(DEFAULT_MAX_RESULTS);
    let timeout = Duration::from_secs(opts.timeout_seconds.unwrap_or(DEFAULT_TIMEOUT_SECONDS));
    let logic = opts.logic_mode.unwrap_or_default();

    let candidates =
        synthesize_via_syslite2(aps, positive, negative, max_candidates, timeout, logic)?;

    // Optional double-check via the trace evaluator.
    if std::env::var("PLTL_SYNTHESIS_DOUBLECHECK").is_ok_and(|v| v == "1") {
        let mut accepted = Vec::with_capacity(candidates.len());
        for f in candidates {
            if is_consistent_with(&f, positive, negative)? {
                accepted.push(f);
            }
        }
        Ok(accepted)
    } else {
        Ok(candidates)
    }
}

/// `f` is consistent with the example traces iff every positive trace
/// satisfies it AND every negative trace violates it.
///
/// Plumbing-only; calls
/// [`crate::analysis::trace_check::check_trace_satisfaction`] for
/// each example.  Errors and `NotImplemented` propagate.
///
/// # Errors
///
/// Propagates [`AnalysisError`] from `check_trace_satisfaction`.
pub fn is_consistent_with(
    f: &Formula,
    positive: &[Lasso],
    negative: &[Lasso],
) -> Result<bool, AnalysisError> {
    for p in positive {
        if !check_trace_satisfaction(p, f)? {
            return Ok(false);
        }
    }
    for n in negative {
        if check_trace_satisfaction(n, f)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_examples() {
        let r = synthesize_from_traces(&[], &[], &[], &SynthesisOptions::default());
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }
}
