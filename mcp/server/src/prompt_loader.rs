//! Runtime-loadable prompt files for MCP tools.
//!
//! Each MCP tool that uses a helper LLM has a system prompt that can
//! be edited on-disk at `mcp/server/prompts/<tool_name>_system.md`
//! without recompiling. Falls back to the compile-time `include_str!`
//! default if the file is missing or unreadable.
//!
//! Mirrors the pattern in `agent/src/agent_loop.rs::load_prompt` so
//! the agent and the MCP tools have a single hot-swap discipline.
//!
//! Resolution order (first hit wins):
//!   1. `$PLTL_MCP_PROMPTS_DIR/<file_name>`
//!   2. ancestor walk from `current_exe()` looking for
//!      `mcp/server/prompts/<file_name>`
//!   3. `./mcp/server/prompts/<file_name>` relative to CWD
//!   4. compile-time default (the `include_str!`'d copy baked in)

use std::borrow::Cow;
use std::path::PathBuf;

/// Env var that, when set to a directory, is searched FIRST for prompt
/// overrides. Same convention as `PLTL_AGENT_PROMPTS_DIR`.
const ENV_OVERRIDE: &str = "PLTL_MCP_PROMPTS_DIR";

/// Relative path used during the ancestor walk and CWD fallback.
const REL_SUBDIR: &str = "mcp/server/prompts";

/// Load a prompt file by base name (e.g. `"extract_ap_mapping_system.md"`).
///
/// Returns the on-disk version if any resolution step finds it, else
/// the compile-time `default`. Logs at debug level which path won so
/// operators can verify hot-swaps are taking effect (`RUST_LOG=debug`).
pub fn load_tool_prompt(file_name: &str, default: &'static str) -> Cow<'static, str> {
    // 1. Explicit env override.
    if let Ok(dir) = std::env::var(ENV_OVERRIDE) {
        let path = PathBuf::from(&dir).join(file_name);
        match std::fs::read_to_string(&path) {
            Ok(s) => {
                tracing::debug!(
                    path = %path.display(),
                    source = "env:PLTL_MCP_PROMPTS_DIR",
                    "loaded MCP tool prompt from disk"
                );
                return Cow::Owned(s);
            }
            Err(e) => {
                tracing::debug!(
                    path = %path.display(),
                    err = %e,
                    "PLTL_MCP_PROMPTS_DIR set but file unreadable; trying fallbacks"
                );
            }
        }
    }

    // 2. Ancestor walk from current_exe(). The release MCP binary lives
    //    at `<repo>/target/release/pltl-mcp` (3 levels up = repo root).
    //    The debug binary lives at `<repo>/target/debug/pltl-mcp` (also
    //    3 levels). When run via `cargo test` it lives somewhere under
    //    `target/debug/deps/`, so widen the walk a bit.
    if let Ok(exe) = std::env::current_exe() {
        for n in 2..=6 {
            if let Some(anc) = exe.ancestors().nth(n) {
                let candidate = anc.join(REL_SUBDIR).join(file_name);
                if candidate.is_file() {
                    match std::fs::read_to_string(&candidate) {
                        Ok(s) => {
                            tracing::debug!(
                                path = %candidate.display(),
                                source = "ancestor_walk",
                                "loaded MCP tool prompt from disk"
                            );
                            return Cow::Owned(s);
                        }
                        Err(e) => {
                            tracing::debug!(
                                path = %candidate.display(),
                                err = %e,
                                "found prompt file in ancestor walk but unreadable"
                            );
                        }
                    }
                }
            }
        }
    }

    // 3. CWD-relative fallback (handy when launched from the repo root).
    let cwd_path = PathBuf::from(REL_SUBDIR).join(file_name);
    if cwd_path.is_file() {
        match std::fs::read_to_string(&cwd_path) {
            Ok(s) => {
                tracing::debug!(
                    path = %cwd_path.display(),
                    source = "cwd_relative",
                    "loaded MCP tool prompt from disk"
                );
                return Cow::Owned(s);
            }
            Err(e) => {
                tracing::debug!(
                    path = %cwd_path.display(),
                    err = %e,
                    "cwd-relative prompt file present but unreadable"
                );
            }
        }
    }

    // 4. Baked-in default.
    tracing::debug!(file_name, "using compile-time default MCP tool prompt");
    Cow::Borrowed(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// Serialise env-var-mutating tests so they don't race with one
    /// another (env access is process-global in `std`).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    const DEFAULT: &str = "default-prompt-content";

    #[test]
    fn env_override_wins_when_present() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let dir = tempdir();
        let file = dir.join("loader_test_a.md");
        std::fs::write(&file, "OVERRIDE-A").unwrap();

        // Safety: tests in this module are serialised via ENV_LOCK so
        // the env mutation can't race with other threads in this binary.
        let prev = std::env::var(ENV_OVERRIDE).ok();
        std::env::set_var(ENV_OVERRIDE, &dir);

        let got = load_tool_prompt("loader_test_a.md", DEFAULT);
        assert_eq!(got.as_ref(), "OVERRIDE-A");

        // Restore.
        match prev {
            Some(v) => std::env::set_var(ENV_OVERRIDE, v),
            None => std::env::remove_var(ENV_OVERRIDE),
        }
        let _ = std::fs::remove_file(&file);
    }

    #[test]
    fn falls_back_to_default_when_missing() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prev = std::env::var(ENV_OVERRIDE).ok();
        // Point at a directory that has no matching file.
        let dir = tempdir();
        std::env::set_var(ENV_OVERRIDE, &dir);

        let got = load_tool_prompt("definitely_not_a_real_prompt_file.md", DEFAULT);
        // The ancestor walk / cwd fallback may or may not find a
        // prompts/ directory in the test harness's tree — what we
        // strictly require is that *something* unreadable produces
        // the baked-in default. Since the file name is nonsense, no
        // other layer can produce it either.
        assert_eq!(got.as_ref(), DEFAULT);

        match prev {
            Some(v) => std::env::set_var(ENV_OVERRIDE, v),
            None => std::env::remove_var(ENV_OVERRIDE),
        }
    }

    /// Create a fresh per-test temp directory. We don't pull in the
    /// `tempfile` crate just for this — the OS temp dir + a unique
    /// suffix is enough.
    fn tempdir() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let pid = std::process::id();
        let p = std::env::temp_dir().join(format!("pltl_mcp_prompts_{pid}_{nanos}"));
        std::fs::create_dir_all(&p).unwrap();
        p
    }
}
