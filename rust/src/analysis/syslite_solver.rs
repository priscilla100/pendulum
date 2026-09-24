//! SySLite2 integration for `synthesize_from_traces`.
//!
//! Wraps the Python SySLite2 tool (a SyGuS-based LTL/PLTL synthesiser
//! by Fareed Arif's group at U. Iowa) and exposes a single entry
//! point:
//!
//! ```ignore
//! synthesize_via_syslite2(
//!     aps, positive_lassos, negative_lassos,
//!     max_candidates, timeout
//! ) -> Result<Vec<Formula>, AnalysisError>
//! ```
//!
//! ## How it works
//!
//! 1. **Trace serialisation.** Our [`Lasso`] type is converted into
//!    the SySLite2 trace format: a comma-separated AP header, one
//!    `---` separator, one positive trace per line (`s0;s1;…;sN::K`
//!    where `K` is the loop start index), another `---`, the
//!    negative traces, and a final `---`.  Each `sI` is a
//!    comma-separated `0`/`1` per AP in the header order.
//!
//! 2. **Subprocess spawn.** `python3 $SYSLITE2_DIR/src/Driver.py
//!    -t <trace_file> -r <result_file> -n <max_candidates>
//!    -a bv_sygus -dict -l pltl`.  The `current_dir` is set to
//!    `$SYSLITE2_DIR` because SySLite2 hardcodes `resources/cvc4`
//!    relative to the working directory.
//!
//! 3. **Timeout.** SyGuS can run forever.  The wrapper polls
//!    `Child::try_wait()` and kills the process when `timeout`
//!    elapses, returning [`AnalysisError::Unsupported`] with a
//!    timeout message.
//!
//! 4. **Result parsing.** SySLite2 writes one formula per line in the
//!    result file as `(N) prefix_form_formula`.  The prefix form is
//!    converted back into our [`Formula`] AST by a small recursive
//!    descent parser.
//!
//! ## Binary / environment discovery
//!
//! 1. `$SYSLITE2_DIR` env, if set.
//! 2. Otherwise `/opt/syslite2` (the Docker default).
//! 3. Otherwise [`AnalysisError::Unsupported`].

use crate::analysis::error::AnalysisError;
use crate::analysis::synthesis::LogicMode;
use crate::analysis::trace::Lasso;
use crate::{BinaryOp, Formula, UnaryOp};
use std::collections::BTreeSet;
use std::env;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const DEFAULT_SYSLITE2_DIR: &str = "/opt/syslite2";

/// Locate the SySLite2 installation directory.
pub fn find_syslite2_dir() -> Result<PathBuf, AnalysisError> {
    if let Ok(p) = env::var("SYSLITE2_DIR") {
        let pb = PathBuf::from(&p);
        if pb.join("src/Driver.py").exists() {
            return Ok(pb);
        }
        return Err(AnalysisError::Unsupported(format!(
            "SYSLITE2_DIR={p} but src/Driver.py not present inside"
        )));
    }
    let default = PathBuf::from(DEFAULT_SYSLITE2_DIR);
    if default.join("src/Driver.py").exists() {
        return Ok(default);
    }
    Err(AnalysisError::Unsupported(
        "SySLite2 not found (set SYSLITE2_DIR or install at /opt/syslite2)".into(),
    ))
}

/// Synthesise candidate formulas from positive + negative example
/// lassos via SySLite2.
///
/// # Errors
///
/// * [`AnalysisError::InvalidInput`] when neither positive nor
///   negative traces are supplied.
/// * [`AnalysisError::Unsupported`] for SySLite2 missing, subprocess
///   spawn failure, timeout, or unparseable output.
pub fn synthesize_via_syslite2(
    aps: &[String],
    positive: &[Lasso],
    negative: &[Lasso],
    max_candidates: u32,
    timeout: Duration,
    logic: LogicMode,
) -> Result<Vec<Formula>, AnalysisError> {
    if positive.is_empty() && negative.is_empty() {
        return Err(AnalysisError::InvalidInput(
            "synthesize_via_syslite2 requires at least one positive or negative trace".into(),
        ));
    }
    if max_candidates == 0 {
        return Ok(Vec::new());
    }

    let syslite2_dir = find_syslite2_dir()?;

    // Canonical AP order.  Explicit `aps` wins; otherwise infer from
    // the traces (BTreeSet for deterministic ordering).
    let ap_order: Vec<String> = if aps.is_empty() {
        infer_aps_from_traces(positive, negative).into_iter().collect()
    } else {
        aps.to_vec()
    };

    if ap_order.is_empty() {
        return Err(AnalysisError::InvalidInput(
            "synthesize_via_syslite2 needs at least one atomic proposition (either in `aps` or appearing in some trace)"
                .into(),
        ));
    }

    // Build the trace text in SySLite2's format.
    let trace_text = build_trace_text(&ap_order, positive, negative);

    // Write to a temp file inside syslite2_dir so cleanup is local.
    let mut trace_file = tempfile::Builder::new()
        .prefix("pltl-syn-")
        .suffix(".trace")
        .tempfile_in(&syslite2_dir)
        .map_err(|e| AnalysisError::Unsupported(format!("create trace file: {e}")))?;
    trace_file
        .write_all(trace_text.as_bytes())
        .map_err(|e| AnalysisError::Unsupported(format!("write trace: {e}")))?;
    trace_file
        .flush()
        .map_err(|e| AnalysisError::Unsupported(format!("flush trace: {e}")))?;

    let result_file = tempfile::Builder::new()
        .prefix("pltl-syn-result-")
        .suffix(".txt")
        .tempfile_in(&syslite2_dir)
        .map_err(|e| AnalysisError::Unsupported(format!("create result file: {e}")))?;

    let trace_path = trace_file.path().to_string_lossy().to_string();
    let result_path = result_file.path().to_string_lossy().to_string();

    let mut cmd = Command::new("python3");
    cmd.arg(syslite2_dir.join("src/Driver.py"))
        .arg("-t")
        .arg(&trace_path)
        .arg("-r")
        .arg(&result_path)
        .arg("-n")
        .arg(max_candidates.to_string())
        .arg("-a")
        .arg("bv_sygus")
        .arg("-dict")
        .arg("-l")
        .arg(logic.as_cli_arg())
        .current_dir(&syslite2_dir);

    let output = run_with_timeout(cmd, timeout)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AnalysisError::Unsupported(format!(
            "SySLite2 exited with {}: {}",
            output.status,
            stderr.trim()
        )));
    }

    let result_text = std::fs::read_to_string(&result_path)
        .map_err(|e| AnalysisError::Unsupported(format!("read result file: {e}")))?;

    parse_result_file(&result_text)
}

/// Encode the (aps, positive, negative) triple into SySLite2's text
/// trace format.
fn build_trace_text(aps: &[String], positive: &[Lasso], negative: &[Lasso]) -> String {
    let mut s = String::new();
    s.push_str(&aps.join(","));
    s.push('\n');
    s.push_str("---\n");
    for trace in positive {
        s.push_str(&encode_lasso(aps, trace));
        s.push('\n');
    }
    s.push_str("---\n");
    for trace in negative {
        s.push_str(&encode_lasso(aps, trace));
        s.push('\n');
    }
    s.push_str("---\n");
    s
}

/// Encode a [`Lasso`] as `s0;s1;…;sN::K` where each `sI` is a
/// comma-separated `0`/`1` over `aps` in order, and `K` is the loop
/// start index (always `prefix.len()` in our representation).
fn encode_lasso(aps: &[String], lasso: &Lasso) -> String {
    let mut parts: Vec<String> = Vec::new();
    for state in lasso.prefix.iter().chain(lasso.loop_.iter()) {
        let cells: Vec<&str> = aps
            .iter()
            .map(|ap| if state.contains(ap) { "1" } else { "0" })
            .collect();
        parts.push(cells.join(","));
    }
    let loop_idx = lasso.prefix.len();
    format!("{}::{}", parts.join(";"), loop_idx)
}

/// Collect every atom appearing anywhere in the example traces.
/// Stable across invocations because `BTreeSet` is ordered.
fn infer_aps_from_traces(positive: &[Lasso], negative: &[Lasso]) -> BTreeSet<String> {
    let mut s = BTreeSet::new();
    for trace in positive.iter().chain(negative.iter()) {
        for state in trace.prefix.iter().chain(trace.loop_.iter()) {
            for atom in state {
                s.insert(atom.clone());
            }
        }
    }
    s
}

/// Parse a SySLite2 result file: lines of the form `(N) prefix_form`.
fn parse_result_file(text: &str) -> Result<Vec<Formula>, AnalysisError> {
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        // Format: "(1) X(p)"
        let Some((_idx, rest)) = line.split_once(')') else {
            continue;
        };
        let rest = rest.trim();
        if rest.is_empty() {
            continue;
        }
        let f = parse_syslite_formula(rest).map_err(|e| {
            AnalysisError::Unsupported(format!("parse SySLite2 formula `{rest}`: {e}"))
        })?;
        out.push(f);
    }
    Ok(out)
}

/// Parse one SySLite2 prefix-form formula string.
fn parse_syslite_formula(s: &str) -> Result<Formula, AnalysisError> {
    let mut p = PrefixParser::new(s);
    let f = p.parse_formula()?;
    p.skip_ws();
    if !p.at_end() {
        return Err(AnalysisError::Unsupported(format!(
            "trailing input after formula at offset {} in `{}`",
            p.pos, s
        )));
    }
    Ok(f)
}

/// Recursive-descent parser for SySLite2's prefix output syntax.
///
/// Grammar (matching SySLite2's `LarkParser.py` output shapes):
///
/// ```text
///   formula ::= "(" formula ")"
///             | "!" formula
///             | UNARY "(" formula ")"          (* X / F / G / Y / O / H *)
///             | BINARY "(" formula "," formula ")"   (* U / S / & / | / => *)
///             | atom                           (* [a-zA-Z][a-zA-Z0-9_]* | "true" | "false" *)
/// ```
struct PrefixParser<'a> {
    input: &'a [u8],
    pos: usize,
}

impl<'a> PrefixParser<'a> {
    fn new(s: &'a str) -> Self {
        Self {
            input: s.as_bytes(),
            pos: 0,
        }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.input.len() && self.input[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn at_end(&self) -> bool {
        self.pos >= self.input.len()
    }

    fn peek(&self) -> Option<u8> {
        self.input.get(self.pos).copied()
    }

    fn peek_at(&self, offset: usize) -> Option<u8> {
        self.input.get(self.pos + offset).copied()
    }

    fn eat(&mut self, c: u8) -> Result<(), AnalysisError> {
        match self.peek() {
            Some(b) if b == c => {
                self.pos += 1;
                Ok(())
            }
            Some(b) => Err(AnalysisError::Unsupported(format!(
                "expected '{}' but found '{}' at offset {}",
                c as char, b as char, self.pos
            ))),
            None => Err(AnalysisError::Unsupported(format!(
                "expected '{}' but found end-of-input at offset {}",
                c as char, self.pos
            ))),
        }
    }

    fn parse_formula(&mut self) -> Result<Formula, AnalysisError> {
        self.skip_ws();
        let c = self
            .peek()
            .ok_or_else(|| AnalysisError::Unsupported("empty formula".into()))?;
        match c {
            b'!' => {
                self.pos += 1;
                let inner = self.parse_formula()?;
                Ok(Formula::FNot {
                    operand: Box::new(inner),
                })
            }
            b'(' => {
                self.pos += 1;
                let inner = self.parse_formula()?;
                self.skip_ws();
                self.eat(b')')?;
                Ok(inner)
            }
            // Unary operator keywords are single-character identifiers
            // followed by `(`.  If the character is one of these AND
            // the next non-space byte is `(`, treat as the operator
            // call; otherwise it's an atom that happens to start with
            // a capital.
            b'X' | b'F' | b'G' | b'Y' | b'O' | b'H' if self.next_is_paren_after(1) => {
                let op = match c {
                    b'X' => UnaryOp::Next,
                    b'F' => UnaryOp::Eventually,
                    b'G' => UnaryOp::Globally,
                    b'Y' => UnaryOp::Yesterday,
                    b'O' => UnaryOp::Once,
                    b'H' => UnaryOp::Historically,
                    _ => unreachable!(),
                };
                self.pos += 1; // skip the operator char
                self.skip_ws();
                self.eat(b'(')?;
                let arg = self.parse_formula()?;
                self.skip_ws();
                self.eat(b')')?;
                Ok(Formula::FUnary {
                    op,
                    operand: Box::new(arg),
                })
            }
            // Binary single-char operators followed by `(`.
            b'U' | b'S' | b'&' | b'|' if self.next_is_paren_after(1) => {
                let op_byte = c;
                self.pos += 1;
                self.skip_ws();
                self.eat(b'(')?;
                let a = self.parse_formula()?;
                self.skip_ws();
                self.eat(b',')?;
                self.skip_ws();
                let b = self.parse_formula()?;
                self.skip_ws();
                self.eat(b')')?;
                Ok(match op_byte {
                    b'U' => Formula::FBinary {
                        op: BinaryOp::Until,
                        left: Box::new(a),
                        right: Box::new(b),
                    },
                    b'S' => Formula::FBinary {
                        op: BinaryOp::Since,
                        left: Box::new(a),
                        right: Box::new(b),
                    },
                    b'&' => Formula::FAnd {
                        left: Box::new(a),
                        right: Box::new(b),
                    },
                    b'|' => Formula::FOr {
                        left: Box::new(a),
                        right: Box::new(b),
                    },
                    _ => unreachable!(),
                })
            }
            // Two-char binary operator `=>` followed by `(`.
            b'=' if self.peek_at(1) == Some(b'>') && self.next_is_paren_after(2) => {
                self.pos += 2;
                self.skip_ws();
                self.eat(b'(')?;
                let a = self.parse_formula()?;
                self.skip_ws();
                self.eat(b',')?;
                self.skip_ws();
                let b = self.parse_formula()?;
                self.skip_ws();
                self.eat(b')')?;
                Ok(Formula::FImplies {
                    left: Box::new(a),
                    right: Box::new(b),
                })
            }
            _ => self.parse_atom(),
        }
    }

    /// Check whether, after skipping `offset` bytes and any
    /// whitespace, the next non-space character is `(`.
    fn next_is_paren_after(&self, offset: usize) -> bool {
        let mut i = self.pos + offset;
        while let Some(&b) = self.input.get(i) {
            if b.is_ascii_whitespace() {
                i += 1;
                continue;
            }
            return b == b'(';
        }
        false
    }

    fn parse_atom(&mut self) -> Result<Formula, AnalysisError> {
        self.skip_ws();
        let start = self.pos;
        while self.pos < self.input.len() {
            let b = self.input[self.pos];
            if b.is_ascii_alphanumeric() || b == b'_' {
                self.pos += 1;
            } else {
                break;
            }
        }
        if start == self.pos {
            return Err(AnalysisError::Unsupported(format!(
                "expected atom at offset {}",
                start
            )));
        }
        let name = std::str::from_utf8(&self.input[start..self.pos])
            .map_err(|e| AnalysisError::Unsupported(format!("non-UTF8 atom: {e}")))?;
        Ok(match name {
            "true" | "True" | "TRUE" => Formula::FTrue,
            "false" | "False" | "FALSE" => Formula::FFalse,
            _ => Formula::FAtom {
                name: name.to_string(),
            },
        })
    }
}

/// Spawn `cmd` and poll until it exits or `timeout` elapses, killing
/// the **entire process group** on timeout.
///
/// On Unix, the child is spawned as a new process-group leader via
/// `Command::process_group(0)`.  SySLite2 (Python) spawns its CVC4
/// grandchild via `subprocess.Popen(...)`; without a group-wide kill,
/// only the Python parent would receive the signal and CVC4 could
/// keep solving long after the MCP call returned.  On timeout we
/// `kill(-pgid, SIGKILL)` so both Python and CVC4 die together.
///
/// On non-Unix (Windows), the group machinery is absent; we fall
/// back to a best-effort `Child::kill` on the parent.
fn run_with_timeout(
    mut cmd: Command,
    timeout: Duration,
) -> Result<std::process::Output, AnalysisError> {
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    setup_process_group(&mut cmd);

    let mut child = cmd
        .spawn()
        .map_err(|e| AnalysisError::Unsupported(format!("spawn: {e}")))?;
    let pid = child.id();

    let start = Instant::now();
    let poll_interval = Duration::from_millis(100);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let mut stdout = Vec::new();
                let mut stderr = Vec::new();
                if let Some(mut so) = child.stdout.take() {
                    let _ = so.read_to_end(&mut stdout);
                }
                if let Some(mut se) = child.stderr.take() {
                    let _ = se.read_to_end(&mut stderr);
                }
                return Ok(std::process::Output {
                    status,
                    stdout,
                    stderr,
                });
            }
            Ok(None) => {
                if start.elapsed() >= timeout {
                    kill_process_group(pid, &mut child);
                    return Err(AnalysisError::Unsupported(format!(
                        "SySLite2 timed out after {timeout:?}"
                    )));
                }
                std::thread::sleep(poll_interval);
            }
            Err(e) => return Err(AnalysisError::Unsupported(format!("wait: {e}"))),
        }
    }
}

/// Make the spawned child its own process-group leader so we can
/// later kill the whole group (parent + any descendants) on timeout.
#[cfg(unix)]
fn setup_process_group(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    cmd.process_group(0);
}

/// Non-Unix builds: no process-group machinery; the per-platform
/// `Child::kill` below is the best we can do.
#[cfg(not(unix))]
fn setup_process_group(_cmd: &mut Command) {}

/// Kill the entire process group on Unix; fall back to the
/// `Child::kill` parent kill elsewhere.  Reaps the parent so it
/// doesn't linger as a zombie.
#[cfg(unix)]
fn kill_process_group(pid: u32, child: &mut std::process::Child) {
    // `kill(-pgid, SIGKILL)` — the negative pid targets every
    // process in the group.  The child's pid == its pgid because we
    // made it group leader via `process_group(0)`.
    //
    // SAFETY: `libc::kill` is a syscall that never reads or writes
    // Rust-owned memory.  We pass a pid we just received from
    // `Child::id()`; the kernel handles invalid pids by returning
    // -1 with errno=ESRCH, which we ignore.
    unsafe {
        libc::kill(-(pid as i32), libc::SIGKILL);
    }
    let _ = child.wait();
}

#[cfg(not(unix))]
fn kill_process_group(_pid: u32, child: &mut std::process::Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    fn lasso(prefix: Vec<Vec<&str>>, loop_: Vec<Vec<&str>>) -> Lasso {
        let prefix: Vec<BTreeSet<String>> = prefix
            .into_iter()
            .map(|s| s.into_iter().map(String::from).collect())
            .collect();
        let loop_: Vec<BTreeSet<String>> = loop_
            .into_iter()
            .map(|s| s.into_iter().map(String::from).collect())
            .collect();
        Lasso::new(prefix, loop_).expect("ok")
    }

    #[test]
    fn encode_lasso_basic() {
        // aps = [p, q]; prefix = [{p}], loop = [{p, q}]
        let aps = vec!["p".to_string(), "q".to_string()];
        let l = lasso(vec![vec!["p"]], vec![vec!["p", "q"]]);
        let encoded = encode_lasso(&aps, &l);
        // states: (1,0), (1,1); loop_idx = 1
        assert_eq!(encoded, "1,0;1,1::1");
    }

    #[test]
    fn encode_lasso_no_prefix() {
        let aps = vec!["p".to_string()];
        let l = lasso(vec![], vec![vec!["p"]]);
        // single state, loop starts at 0
        assert_eq!(encode_lasso(&aps, &l), "1::0");
    }

    #[test]
    fn build_trace_text_full_shape() {
        let aps = vec!["p".to_string(), "q".to_string()];
        let pos = vec![lasso(vec![vec!["p"]], vec![vec!["p", "q"]])];
        let neg = vec![lasso(vec![], vec![vec![]])];
        let s = build_trace_text(&aps, &pos, &neg);
        assert!(s.starts_with("p,q\n---\n1,0;1,1::1\n---\n0,0::0\n---\n"));
    }

    #[test]
    fn parse_atom_simple() {
        let f = parse_syslite_formula("p").expect("ok");
        assert_eq!(f, atom("p"));
    }

    #[test]
    fn parse_unary() {
        // X(p) → FUnary{Next, p}
        let f = parse_syslite_formula("X(p)").expect("ok");
        assert_eq!(
            f,
            Formula::FUnary {
                op: UnaryOp::Next,
                operand: Box::new(atom("p"))
            }
        );
    }

    #[test]
    fn parse_binary_until() {
        let f = parse_syslite_formula("U(p, q)").expect("ok");
        assert_eq!(
            f,
            Formula::FBinary {
                op: BinaryOp::Until,
                left: Box::new(atom("p")),
                right: Box::new(atom("q"))
            }
        );
    }

    #[test]
    fn parse_nested_pltl() {
        // S(&(Y(failure), alarm), p1)
        let f = parse_syslite_formula("S(&(Y(failure), alarm), p1)").expect("ok");
        assert_eq!(
            f,
            Formula::FBinary {
                op: BinaryOp::Since,
                left: Box::new(Formula::FAnd {
                    left: Box::new(Formula::FUnary {
                        op: UnaryOp::Yesterday,
                        operand: Box::new(atom("failure"))
                    }),
                    right: Box::new(atom("alarm"))
                }),
                right: Box::new(atom("p1"))
            }
        );
    }

    #[test]
    fn parse_negation_chain() {
        let f = parse_syslite_formula("!!p").expect("ok");
        assert_eq!(
            f,
            Formula::FNot {
                operand: Box::new(Formula::FNot {
                    operand: Box::new(atom("p"))
                })
            }
        );
    }

    #[test]
    fn parse_implies() {
        let f = parse_syslite_formula("=>(p, q)").expect("ok");
        assert_eq!(
            f,
            Formula::FImplies {
                left: Box::new(atom("p")),
                right: Box::new(atom("q"))
            }
        );
    }

    #[test]
    fn parse_result_file_multiline() {
        let text = "(1) X(p)\n(2) Y(q)\n";
        let v = parse_result_file(text).expect("ok");
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn parse_result_file_skips_blank_lines() {
        let text = "\n(1) X(p)\n\n(2) p\n";
        let v = parse_result_file(text).expect("ok");
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn synth_rejects_empty_inputs() {
        let r = synthesize_via_syslite2(&[], &[], &[], 5, Duration::from_secs(30), LogicMode::Ltl);
        assert!(matches!(r, Err(AnalysisError::InvalidInput(_))));
    }

    #[test]
    fn synth_returns_empty_for_zero_candidates() {
        let pos = vec![lasso(vec![], vec![vec!["p"]])];
        // max_candidates = 0 → don't even invoke SySLite2.
        let r = synthesize_via_syslite2(
            &["p".to_string()],
            &pos,
            &[],
            0,
            Duration::from_secs(30),
            LogicMode::Ltl,
        )
        .expect("ok");
        assert!(r.is_empty());
    }
}
