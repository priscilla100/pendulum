//! Subprocess helpers with bounded execution time.
//!
//! The MCP stack shells out to a handful of external tools — the
//! OCaml PLTL parser, the BLACK satisfiability solver, the SALT
//! compiler, and (when wired) SySLite2. None of them have built-in
//! deadlines: a stuck child can hold an MCP request open forever.
//! [`run_with_timeout`] enforces a wall-clock cap, killing AND
//! reaping the child on expiry so the OS doesn't leak zombies.

use std::process::{Child, Command, Output};
use std::time::{Duration, Instant};

/// Failure modes when running a bounded subprocess.
#[derive(Debug)]
pub enum SubprocessError {
    /// `spawn()` failed (binary missing, permissions, etc.).
    SpawnFailed(String, std::io::Error),
    /// The child was still running after `timeout` and was killed.
    Timeout(String, Duration),
    /// `try_wait` returned an error.
    WaitFailed(String, std::io::Error),
    /// `wait_with_output` failed to collect stdout/stderr.
    OutputFailed(String, std::io::Error),
}

impl std::fmt::Display for SubprocessError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::SpawnFailed(l, e) => write!(f, "failed to spawn `{l}`: {e}"),
            Self::Timeout(l, d) => write!(f, "subprocess `{l}` timed out after {d:?}"),
            Self::WaitFailed(l, e) => write!(f, "error waiting on `{l}`: {e}"),
            Self::OutputFailed(l, e) => write!(f, "error collecting output of `{l}`: {e}"),
        }
    }
}

impl std::error::Error for SubprocessError {}

/// Read an env var as a non-zero u64; fall back to `default` if unset
/// or unparseable. Emits a warning on stderr when the var is set but
/// unparseable so silent misconfiguration is visible during dev.
pub fn timeout_from_env(name: &str, default_secs: u64) -> Duration {
    match std::env::var(name) {
        Err(_) => Duration::from_secs(default_secs),
        Ok(s) => match s.trim().parse::<u64>() {
            Ok(n) if n > 0 => Duration::from_secs(n),
            Ok(_) => {
                eprintln!(
                    "warning: env var {name}=`{s}` is zero; using default {default_secs}s"
                );
                Duration::from_secs(default_secs)
            }
            Err(_) => {
                eprintln!(
                    "warning: env var {name}=`{s}` is not a positive integer; using default {default_secs}s"
                );
                Duration::from_secs(default_secs)
            }
        },
    }
}

/// Spawn `cmd` and wait up to `timeout` for it to exit. On timeout
/// the child is killed and reaped before the error is returned.
/// `label` is included in error messages to identify the subprocess.
///
/// Pipes stdout/stderr by default to match `Command::output()`'s
/// behaviour — callers expect `Output { stdout, stderr, status }`
/// rather than the child's pipes being inherited from the parent.
/// Override by setting `stdout` / `stderr` on `cmd` before calling.
pub fn run_with_timeout(
    mut cmd: Command,
    timeout: Duration,
    label: &str,
) -> Result<Output, SubprocessError> {
    cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let child = cmd
        .spawn()
        .map_err(|e| SubprocessError::SpawnFailed(label.into(), e))?;
    wait_with_timeout(child, timeout, label)
}

/// Wait for `child` to exit, killing AND REAPING it after `timeout`
/// elapses. Reaping (`wait()` after `kill()`) is essential: a `kill`
/// without `wait` leaves a zombie process until the parent itself
/// exits.
pub fn wait_with_timeout(
    mut child: Child,
    timeout: Duration,
    label: &str,
) -> Result<Output, SubprocessError> {
    let start = Instant::now();
    let poll = Duration::from_millis(50);
    loop {
        match child.try_wait() {
            Ok(Some(_status)) => break,
            Ok(None) => {
                if start.elapsed() >= timeout {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(SubprocessError::Timeout(label.into(), timeout));
                }
                std::thread::sleep(poll);
            }
            Err(e) => return Err(SubprocessError::WaitFailed(label.into(), e)),
        }
    }
    child
        .wait_with_output()
        .map_err(|e| SubprocessError::OutputFailed(label.into(), e))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quick_command_returns_output() {
        let cmd = Command::new("true");
        let out = run_with_timeout(cmd, Duration::from_secs(5), "true").unwrap();
        assert!(out.status.success());
    }

    #[test]
    fn missing_binary_surfaces_spawn_error() {
        let cmd = Command::new("/nonexistent/binary/zzz");
        let err = run_with_timeout(cmd, Duration::from_secs(1), "missing").unwrap_err();
        assert!(matches!(err, SubprocessError::SpawnFailed(_, _)));
    }

    #[test]
    fn long_command_times_out_and_is_reaped() {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "sleep 10"]);
        let start = Instant::now();
        let err = run_with_timeout(cmd, Duration::from_millis(200), "sleep").unwrap_err();
        let elapsed = start.elapsed();
        assert!(matches!(err, SubprocessError::Timeout(_, _)));
        // Must return promptly after the timeout, not wait for full sleep.
        assert!(
            elapsed < Duration::from_secs(2),
            "timeout did not kill child promptly: {elapsed:?}"
        );
    }

    #[test]
    fn timeout_from_env_uses_default_when_unset() {
        std::env::remove_var("PLTL_TEST_TIMEOUT_UNSET");
        assert_eq!(
            timeout_from_env("PLTL_TEST_TIMEOUT_UNSET", 17),
            Duration::from_secs(17)
        );
    }

    #[test]
    fn timeout_from_env_parses_valid() {
        std::env::set_var("PLTL_TEST_TIMEOUT_VALID", "42");
        assert_eq!(
            timeout_from_env("PLTL_TEST_TIMEOUT_VALID", 17),
            Duration::from_secs(42)
        );
        std::env::remove_var("PLTL_TEST_TIMEOUT_VALID");
    }

    #[test]
    fn timeout_from_env_falls_back_on_garbage() {
        std::env::set_var("PLTL_TEST_TIMEOUT_BAD", "not-a-number");
        assert_eq!(
            timeout_from_env("PLTL_TEST_TIMEOUT_BAD", 17),
            Duration::from_secs(17)
        );
        std::env::remove_var("PLTL_TEST_TIMEOUT_BAD");
    }

    #[test]
    fn timeout_from_env_rejects_zero() {
        std::env::set_var("PLTL_TEST_TIMEOUT_ZERO", "0");
        assert_eq!(
            timeout_from_env("PLTL_TEST_TIMEOUT_ZERO", 17),
            Duration::from_secs(17)
        );
        std::env::remove_var("PLTL_TEST_TIMEOUT_ZERO");
    }
}
