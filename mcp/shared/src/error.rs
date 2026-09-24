//! Shared error type used across the MCP-server family.
//!
//! Each analysis crate may also define its own narrower error enum, but
//! everything that bubbles out to an MCP client goes through
//! [`SharedError`] so the client sees a consistent error vocabulary.

use thiserror::Error;

/// Errors that any PLTL MCP server can surface.
///
/// The variants are intentionally narrow: I/O, OCaml-side parse failures,
/// JSON deserialisation, and a catch-all `Analysis` for analysis-specific
/// problems. Anything domain-specific (e.g. "expected future-only
/// formula") goes through `Analysis(String)` so the message can be
/// passed verbatim into an `rmcp::ErrorData::invalid_params` reply.
#[derive(Debug, Error)]
pub enum SharedError {
    /// The configured OCaml parser binary is missing or unreadable.
    ///
    /// `path` is the resolved path that was tried — either
    /// `$PLTL_PARSER_BIN` or the ancestor-walk fallback (see
    /// [`crate::parse::find_ocaml_parser`]).
    #[error("OCaml parser binary not found at {path}: set PLTL_PARSER_BIN or build it via `dune build main.exe`")]
    ParserBinaryMissing {
        /// Resolved path that was tried.
        path: String,
    },

    /// The OCaml parser ran but returned a non-zero exit code.
    ///
    /// `stderr` carries the verbatim lexer/parser diagnostic so a
    /// caller can show it to the user without further interpretation.
    #[error("OCaml parser rejected formula: {stderr}")]
    ParserRejected {
        /// Captured stderr from the OCaml binary.
        stderr: String,
    },

    /// Failed to deserialise the OCaml parser's JSON output.
    ///
    /// This shouldn't happen in steady state — if it does, the JSON
    /// wire format has drifted between `ocaml/ast.ml` and
    /// `rust/src/ast.rs`, which must change in lockstep.
    #[error("failed to decode parser JSON: {0}")]
    DecodeJson(#[from] serde_json::Error),

    /// Generic I/O error (e.g. failed to spawn the OCaml process).
    #[error("io: {0}")]
    Io(#[from] std::io::Error),

    /// The OCaml parser took longer than the configured timeout
    /// (`PLTL_PARSER_TIMEOUT_SECS`, default 30s).
    #[error("OCaml parser timed out: {0}")]
    ParserTimeout(String),

    /// Analysis-specific failure. Carries the message verbatim so the
    /// per-analysis crate can pick its own vocabulary.
    #[error("{0}")]
    Analysis(String),
}

impl SharedError {
    /// Convenience constructor for an analysis-level failure.
    pub fn analysis<S: Into<String>>(msg: S) -> Self {
        SharedError::Analysis(msg.into())
    }
}
