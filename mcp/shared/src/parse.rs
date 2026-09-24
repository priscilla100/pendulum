//! End-to-end formula-string → [`pltl_rust::Formula`] glue.
//!
//! The OCaml binary lives at `ocaml/_build/default/main.exe` in the
//! source tree; in the Docker image it is copied to
//! `/usr/local/bin/pltl-parser`. The Rust side never parses surface
//! syntax — it always shells out.
//!
//! Discovery order:
//! 1. `$PLTL_PARSER_BIN` if set (absolute path);
//! 2. ancestor-walk from the running executable, looking for
//!    `ocaml/_build/default/main.exe`;
//! 3. relative fallback `../ocaml/_build/default/main.exe`.
//!
//! The MCP client launches the server with `PLTL_PARSER_BIN` baked in
//! via Docker `ENV`, so case 1 is the steady-state path.

use crate::SharedError;
use pltl_rust::subprocess::{run_with_timeout, timeout_from_env, SubprocessError};
use pltl_rust::Formula;
use std::env;
use std::path::PathBuf;
use std::process::Command;

const PARSER_DEFAULT_TIMEOUT_SECS: u64 = 30;

/// Locate the OCaml parser binary.
///
/// Returns the resolved path without checking that it exists — callers
/// will get a [`SharedError::ParserBinaryMissing`] on the first parse if
/// the path is wrong.
pub fn find_ocaml_parser() -> PathBuf {
    if let Ok(path) = env::var("PLTL_PARSER_BIN") {
        return PathBuf::from(path);
    }
    if let Ok(exe) = env::current_exe() {
        // Try several ancestor depths — the binary may live under
        // `target/debug/`, `target/release/`, or directly under the
        // workspace target dir in a docker context.
        for n in 3..=6 {
            if let Some(root) = exe.ancestors().nth(n) {
                let candidate = root.join("ocaml/_build/default/main.exe");
                if candidate.exists() {
                    return candidate;
                }
            }
        }
    }
    PathBuf::from("../ocaml/_build/default/main.exe")
}

/// Parse a PLTL surface-syntax string through the OCaml front-end.
///
/// Returns a typed [`Formula`]. Pass the result to any of the
/// analyses under `pltl_rust::analysis`.
///
/// # Errors
///
/// * [`SharedError::ParserBinaryMissing`] — the resolved path doesn't
///   point at an executable.
/// * [`SharedError::ParserRejected`] — OCaml lexer/parser returned a
///   non-zero exit code; `stderr` is included verbatim.
/// * [`SharedError::DecodeJson`] — the OCaml binary produced
///   output the Rust side couldn't deserialise (wire-format drift).
/// * [`SharedError::Io`] — couldn't spawn the OCaml binary.
pub fn parse(formula_str: &str) -> Result<Formula, SharedError> {
    let bin = find_ocaml_parser();
    if !bin.exists() {
        return Err(SharedError::ParserBinaryMissing {
            path: bin.display().to_string(),
        });
    }

    let mut cmd = Command::new(&bin);
    cmd.arg(formula_str).arg("--json");
    let timeout = timeout_from_env("PLTL_PARSER_TIMEOUT_SECS", PARSER_DEFAULT_TIMEOUT_SECS);
    let output = run_with_timeout(cmd, timeout, "OCaml parser").map_err(|e| match e {
        SubprocessError::SpawnFailed(_, io) => SharedError::Io(io),
        SubprocessError::Timeout(_, _) => SharedError::ParserTimeout(e.to_string()),
        SubprocessError::WaitFailed(_, io) | SubprocessError::OutputFailed(_, io) => {
            SharedError::Io(io)
        }
    })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(SharedError::ParserRejected { stderr });
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let formula: Formula = serde_json::from_str(&stdout)?;
    Ok(formula)
}

#[cfg(test)]
mod tests {
    use super::*;

    // The OCaml binary isn't built in CI by default — gate the live
    // round-trip test behind an env var so `cargo test --workspace`
    // stays green without it.
    #[test]
    #[ignore = "requires built OCaml binary; run with PLTL_PARSER_BIN set"]
    fn parse_p_until_q_round_trips() -> Result<(), SharedError> {
        let formula = parse("p U q")?;
        let printed = format!("{formula}");
        assert!(printed.contains('U'), "expected Until op, got: {printed}");
        Ok(())
    }

    // NB: A previous draft mutated `PLTL_PARSER_BIN` in-test, but
    // `env::set_var` is `unsafe` on modern rustc and this crate has
    // `#![forbid(unsafe_code)]`. The env-resolution path is exercised
    // end-to-end by the per-server smoke tests instead.
}
