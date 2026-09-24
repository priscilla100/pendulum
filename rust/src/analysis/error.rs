//! Analysis-level error type, shared by every analysis under
//! [`crate::analysis`]. The MCP-server wrappers translate this into
//! the protocol's `invalid_params` / `internal_error` codes.
//!
//! No analysis function ever panics — even the "not yet implemented"
//! state is a `Result::Err(NotImplemented)`, so a misconfigured tool
//! call surfaces as a clean MCP error frame rather than crashing the
//! server.

use std::fmt;

/// Error type returned by every analysis function.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnalysisError {
    /// The analysis body is still a Phase-1 stub — fill in the logic
    /// under [`crate::analysis::*`] before relying on the result.
    /// Carries the analysis name for clarity in tool-error frames.
    NotImplemented(&'static str),

    /// The analysis received a formula it can't process — e.g. an
    /// analysis that requires future-only formulas but got a past op.
    /// Message is shown verbatim to the caller.
    Unsupported(String),

    /// Invalid input (out-of-range int, malformed trace, etc.).
    InvalidInput(String),
}

impl fmt::Display for AnalysisError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AnalysisError::NotImplemented(name) => {
                write!(f, "analysis `{name}` not yet implemented (Phase 4 stub)")
            }
            AnalysisError::Unsupported(msg) => write!(f, "unsupported: {msg}"),
            AnalysisError::InvalidInput(msg) => write!(f, "invalid input: {msg}"),
        }
    }
}

impl std::error::Error for AnalysisError {}
