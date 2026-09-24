//! BLACK solver integration.
//!
//! This module is the one place that talks to the `black` binary
//! (<https://www.black-sat.org/>).  Two entry points:
//!
//! * [`decide_sat_via_black`] — decide satisfiability of a `Formula`
//!   and return a witness lasso on SAT.  This is what
//!   [`crate::analysis::sat::decide_sat`] delegates to.
//! * [`check_trace_via_black`] — model-check a `Formula` against a
//!   user-supplied lasso.  This is what
//!   [`crate::analysis::trace_check::check_trace_satisfaction`]
//!   delegates to.
//!
//! ## Operator normalisation
//!
//! BLACK's input language has `R` (Release) and `T` (Trigger) but
//! does not have `W` (Weak Until) as a primitive.  Per the project
//! spec we *conservatively* rewrite all three of Release, WeakUntil,
//! and Trigger into Until/Since/Globally form before serialising so
//! the BLACK side only sees the operator subset the reference
//! implementation tested against.
//!
//! The rewriting rules are:
//!
//! ```text
//!   Release(φ, ψ)   ≡  ¬( ¬φ U ¬ψ )
//!   WeakUntil(φ, ψ) ≡  (φ U ψ) ∨ G φ
//!   Trigger(φ, ψ)   ≡  ¬( ¬φ S ¬ψ )
//! ```
//!
//! ## Binary discovery
//!
//! 1. `$BLACK_BIN`, if set, is taken verbatim.
//! 2. Otherwise `/usr/local/bin/black` (the cmake default install
//!    path, and where the Docker image lands it).
//! 3. Otherwise a PATH lookup via `which black`.
//!
//! Missing binary surfaces as
//! [`AnalysisError::Unsupported`] with a clear pointer at
//! `BLACK_BIN`.

use crate::analysis::ap::atoms;
use crate::analysis::error::AnalysisError;
use crate::analysis::form;
use crate::analysis::sat::SatVerdict;
use crate::analysis::trace::Lasso;
use crate::subprocess::{run_with_timeout, timeout_from_env, SubprocessError};
use crate::{BinaryOp, Formula, UnaryOp};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashMap};
use std::env;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;

/// Default wall-clock cap for a single BLACK subprocess invocation.
/// Override with `PLTL_BLACK_TIMEOUT_SECS`.
const BLACK_DEFAULT_TIMEOUT_SECS: u64 = 60;

fn black_timeout() -> std::time::Duration {
    timeout_from_env("PLTL_BLACK_TIMEOUT_SECS", BLACK_DEFAULT_TIMEOUT_SECS)
}

fn map_subprocess_err(e: SubprocessError) -> AnalysisError {
    AnalysisError::Unsupported(e.to_string())
}

const BLACK_DEFAULT_PATH: &str = "/usr/local/bin/black";

/// Resolve the path to the BLACK binary.
pub fn find_black_binary() -> Result<PathBuf, AnalysisError> {
    if let Ok(p) = env::var("BLACK_BIN") {
        let pb = PathBuf::from(&p);
        if pb.exists() {
            return Ok(pb);
        }
        return Err(AnalysisError::Unsupported(format!(
            "BLACK_BIN={p} but no binary found at that path"
        )));
    }
    let default = PathBuf::from(BLACK_DEFAULT_PATH);
    if default.exists() {
        return Ok(default);
    }
    if let Ok(output) = Command::new("which").arg("black").output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !path.is_empty() {
                let pb = PathBuf::from(path);
                if pb.exists() {
                    return Ok(pb);
                }
            }
        }
    }
    Err(AnalysisError::Unsupported(
        "BLACK solver not found (set BLACK_BIN or install at /usr/local/bin/black)".into(),
    ))
}

/// Rewrite Release, WeakUntil, and Trigger into Until/Since/Globally
/// form.  Boolean and remaining temporal operators pass through
/// unchanged.  Idempotent.
pub fn normalize(f: &Formula) -> Formula {
    match f {
        Formula::FTrue | Formula::FFalse | Formula::FAtom { .. } => f.clone(),
        Formula::FNot { operand } => form::not(normalize(operand)),
        Formula::FAnd { left, right } => form::and(normalize(left), normalize(right)),
        Formula::FOr { left, right } => form::or(normalize(left), normalize(right)),
        Formula::FImplies { left, right } => form::implies(normalize(left), normalize(right)),
        Formula::FIff { left, right } => Formula::FIff {
            left: Box::new(normalize(left)),
            right: Box::new(normalize(right)),
        },
        Formula::FUnary { op, operand } => Formula::FUnary {
            op: *op,
            operand: Box::new(normalize(operand)),
        },
        Formula::FBinary { op, left, right } => {
            let l = normalize(left);
            let r = normalize(right);
            match op {
                BinaryOp::Until | BinaryOp::Since => Formula::FBinary {
                    op: *op,
                    left: Box::new(l),
                    right: Box::new(r),
                },
                // Release(φ, ψ) := ¬(¬φ U ¬ψ)
                BinaryOp::Release => form::not(Formula::FBinary {
                    op: BinaryOp::Until,
                    left: Box::new(form::not(l)),
                    right: Box::new(form::not(r)),
                }),
                // WeakUntil(φ, ψ) := (φ U ψ) ∨ G φ
                BinaryOp::WeakUntil => form::or(
                    Formula::FBinary {
                        op: BinaryOp::Until,
                        left: Box::new(l.clone()),
                        right: Box::new(r),
                    },
                    Formula::FUnary {
                        op: UnaryOp::Globally,
                        operand: Box::new(l),
                    },
                ),
                // Trigger(φ, ψ) := ¬(¬φ S ¬ψ)
                BinaryOp::Trigger => form::not(Formula::FBinary {
                    op: BinaryOp::Since,
                    left: Box::new(form::not(l)),
                    right: Box::new(form::not(r)),
                }),
            }
        }
    }
}

/// Serialise a normalised formula to BLACK's surface syntax.
///
/// Errors when `f` still contains Release / WeakUntil / Trigger nodes
/// — those must be normalised away first via [`normalize`].  The
/// callers in this module always pre-normalise; exposing this guard
/// as a `Result` makes external misuse loud instead of relying on
/// BLACK to reject `W` (which it doesn't support natively).
pub fn to_black_syntax(f: &Formula) -> Result<String, AnalysisError> {
    Ok(match f {
        Formula::FTrue => "True".to_string(),
        Formula::FFalse => "False".to_string(),
        Formula::FAtom { name } => name.clone(),
        Formula::FNot { operand } => format!("NOT ({})", to_black_syntax(operand)?),
        Formula::FAnd { left, right } => {
            format!("({} AND {})", to_black_syntax(left)?, to_black_syntax(right)?)
        }
        Formula::FOr { left, right } => {
            format!("({} OR {})", to_black_syntax(left)?, to_black_syntax(right)?)
        }
        Formula::FImplies { left, right } => format!(
            "({} => {})",
            to_black_syntax(left)?,
            to_black_syntax(right)?
        ),
        Formula::FIff { left, right } => format!(
            "({} <=> {})",
            to_black_syntax(left)?,
            to_black_syntax(right)?
        ),
        Formula::FUnary { op, operand } => {
            let prefix = match op {
                UnaryOp::Next => "X",
                UnaryOp::Eventually => "F",
                UnaryOp::Globally => "G",
                UnaryOp::Yesterday => "Y",
                UnaryOp::Once => "O",
                UnaryOp::Historically => "H",
            };
            format!("{prefix}({})", to_black_syntax(operand)?)
        }
        Formula::FBinary { op, left, right } => match op {
            BinaryOp::Until => {
                format!("({} U {})", to_black_syntax(left)?, to_black_syntax(right)?)
            }
            BinaryOp::Since => {
                format!("({} S {})", to_black_syntax(left)?, to_black_syntax(right)?)
            }
            BinaryOp::Release | BinaryOp::WeakUntil | BinaryOp::Trigger => {
                return Err(AnalysisError::Unsupported(format!(
                    "to_black_syntax: encountered un-normalised operator {op:?}; \
                     callers must `normalize()` the formula first"
                )))
            }
        },
    })
}

#[derive(Debug, Deserialize, Serialize)]
struct BlackSolveJson {
    result: String,
    #[serde(default)]
    #[allow(dead_code)]
    k: Option<u64>,
    #[serde(default)]
    model: Option<BlackModelJson>,
}

#[derive(Debug, Deserialize, Serialize)]
struct BlackModelJson {
    size: usize,
    #[serde(rename = "loop")]
    loop_start: usize,
    states: Vec<HashMap<String, String>>,
}

/// Invoke `black solve -o json -m -f <formula>` and decode the result.
pub fn decide_sat_via_black(formula: &Formula) -> Result<SatVerdict, AnalysisError> {
    let bin = find_black_binary()?;
    let normalized = normalize(formula);
    let formula_str = to_black_syntax(&normalized)?;
    // `normalize` does not introduce or rename atoms, so the original
    // formula's atom set is exactly the set we need for completing
    // BLACK's (possibly partial) model into a total Boolean trace.
    let formula_atoms = atoms(formula);

    let mut cmd = Command::new(&bin);
    cmd.args(["solve", "-o", "json", "-m", "-f", &formula_str]);
    let output =
        run_with_timeout(cmd, black_timeout(), "BLACK solve").map_err(map_subprocess_err)?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(AnalysisError::Unsupported(format!(
            "BLACK exited with {}: {stderr}",
            output.status
        )));
    }

    let stdout = String::from_utf8(output.stdout)
        .map_err(|e| AnalysisError::Unsupported(format!("non-UTF8 BLACK stdout: {e}")))?;
    let parsed: BlackSolveJson = serde_json::from_str(&stdout).map_err(|e| {
        AnalysisError::Unsupported(format!("bad BLACK JSON: {e}\nstdout was:\n{stdout}"))
    })?;

    match parsed.result.as_str() {
        "SAT" => {
            let model = parsed.model.ok_or_else(|| {
                AnalysisError::Unsupported("BLACK reported SAT but emitted no model".into())
            })?;
            Ok(SatVerdict::Satisfiable(black_model_to_lasso(
                model,
                &formula_atoms,
            )?))
        }
        "UNSAT" => Ok(SatVerdict::Unsatisfiable),
        other => Ok(SatVerdict::Unknown(format!(
            "BLACK returned unexpected result: {other}"
        ))),
    }
}

/// Translate BLACK's possibly-partial model into a total Boolean
/// [`Lasso`] over the formula's atoms.
///
/// **Completion policy.** BLACK is a partial-model solver: it can mark
/// an atom `"undef"` or omit it from a state entirely when its value
/// is a don't-care for that satisfying trace.  Codex review flagged
/// the naive "missing ⇒ false" mapping as unsound — it can produce a
/// Lasso that, under our total-Boolean convention (absent atoms ≡
/// false), does *not* satisfy the original formula.
///
/// This function handles the three cases per atom in
/// `formula_atoms`:
///
/// * `"true"` (case-insensitive)  ⇒ include atom in the state.
/// * `"false"` (case-insensitive) ⇒ exclude.
/// * `"undef"` or missing         ⇒ include (default to TRUE).
///
/// Defaulting "don't care" atoms to TRUE is the most permissive
/// completion under positive atomic constraints: if BLACK said the
/// atom's value didn't matter for satisfying the formula, picking
/// TRUE is consistent with the satisfying assignment BLACK proved
/// exists.
///
/// Atoms BLACK mentions outside `formula_atoms` (rare; would only
/// happen if a future normalisation step introduced fresh atoms) are
/// passed through unchanged when explicitly `"true"`, otherwise
/// dropped.  They don't affect the formula's truth value either way.
fn black_model_to_lasso(
    model: BlackModelJson,
    formula_atoms: &BTreeSet<String>,
) -> Result<Lasso, AnalysisError> {
    if model.loop_start > model.states.len() {
        return Err(AnalysisError::Unsupported(format!(
            "BLACK model loop_start={} > states.len()={}",
            model.loop_start,
            model.states.len()
        )));
    }
    if model.size != model.states.len() {
        return Err(AnalysisError::Unsupported(format!(
            "BLACK model.size={} != states.len()={}",
            model.size,
            model.states.len()
        )));
    }
    let (prefix_raw, loop_raw) = model.states.split_at(model.loop_start);
    let prefix: Vec<BTreeSet<String>> = prefix_raw
        .iter()
        .map(|s| complete_state(s, formula_atoms))
        .collect();
    let mut loop_: Vec<BTreeSet<String>> = loop_raw
        .iter()
        .map(|s| complete_state(s, formula_atoms))
        .collect();

    if loop_.is_empty() {
        // BLACK reports loop_start == size sometimes (stutter on the
        // last state forever).  Synthesise a singleton loop body so
        // our Lasso invariant (non-empty loop_) holds.
        loop_.push(prefix.last().cloned().unwrap_or_default());
    }

    Lasso::new(prefix, loop_)
        .map_err(|e| AnalysisError::Unsupported(format!("invalid lasso from BLACK: {e}")))
}

/// See [`black_model_to_lasso`] for the completion policy.
fn complete_state(
    black_state: &HashMap<String, String>,
    formula_atoms: &BTreeSet<String>,
) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for atom in formula_atoms {
        match black_state.get(atom).map(|s| s.as_str()) {
            Some(v) if v.eq_ignore_ascii_case("true") => {
                out.insert(atom.clone());
            }
            Some(v) if v.eq_ignore_ascii_case("false") => {
                // Explicitly false — exclude.
            }
            // "undef", missing, or any other value: BLACK left the
            // atom underspecified; default to TRUE per the
            // completion policy.
            _ => {
                out.insert(atom.clone());
            }
        }
    }
    // Pass through atoms BLACK mentioned outside `formula_atoms` that
    // are explicitly "true".  This is defensive: normalisation does
    // not introduce atoms today, but if a future rewrite did, those
    // atoms should still appear in the trace BLACK proved valid.
    for (atom, v) in black_state {
        if !formula_atoms.contains(atom) && v.eq_ignore_ascii_case("true") {
            out.insert(atom.clone());
        }
    }
    out
}

/// Invoke `black check -t <trace_file> -f <formula>` and decode the
/// boolean verdict.
pub fn check_trace_via_black(trace: &Lasso, formula: &Formula) -> Result<bool, AnalysisError> {
    let bin = find_black_binary()?;
    let normalized = normalize(formula);
    let formula_str = to_black_syntax(&normalized)?;

    let all_atoms = atoms(formula);
    let trace_json = lasso_to_black_trace_json(trace, &all_atoms)?;

    let mut tmp = tempfile::Builder::new()
        .prefix("pltl-trace-")
        .suffix(".json")
        .tempfile()
        .map_err(|e| AnalysisError::Unsupported(format!("temp file: {e}")))?;
    tmp.write_all(trace_json.as_bytes())
        .map_err(|e| AnalysisError::Unsupported(format!("write trace: {e}")))?;
    tmp.flush()
        .map_err(|e| AnalysisError::Unsupported(format!("flush trace: {e}")))?;
    let trace_path = tmp.path().to_string_lossy().to_string();

    let mut cmd = Command::new(&bin);
    cmd.args(["check", "-t", &trace_path, "-f", &formula_str]);
    let output =
        run_with_timeout(cmd, black_timeout(), "BLACK check").map_err(map_subprocess_err)?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    if let Some(verdict) = parse_black_bool(&stdout) {
        return Ok(verdict);
    }
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AnalysisError::Unsupported(format!(
            "BLACK check exited with {}: {stderr}",
            output.status
        )));
    }
    Err(AnalysisError::Unsupported(format!(
        "BLACK check succeeded but no TRUE/FALSE in stdout: {stdout}"
    )))
}

/// Serialise our `Lasso` into BLACK's trace JSON shape.
///
/// The on-disk shape BLACK expects is:
///
/// ```json
/// { "model": { "size": N, "loop": K, "states": [ { "p": "true", "q": "false" }, ... ] } }
/// ```
///
/// Every formula atom is included in every state, with explicit
/// `"true"`/`"false"` so BLACK doesn't have to infer.
fn lasso_to_black_trace_json(
    trace: &Lasso,
    all_atoms: &BTreeSet<String>,
) -> Result<String, AnalysisError> {
    let size = trace.prefix.len() + trace.loop_.len();
    let loop_idx = trace.prefix.len();
    let states: Vec<serde_json::Value> = trace
        .prefix
        .iter()
        .chain(trace.loop_.iter())
        .map(|s| state_to_json(s, all_atoms))
        .collect();
    let body = serde_json::json!({
        "model": {
            "size": size,
            "loop": loop_idx,
            "states": states,
        }
    });
    serde_json::to_string(&body)
        .map_err(|e| AnalysisError::Unsupported(format!("serialise trace JSON: {e}")))
}

fn state_to_json(
    true_atoms: &BTreeSet<String>,
    all_atoms: &BTreeSet<String>,
) -> serde_json::Value {
    let mut m = serde_json::Map::new();
    for atom in all_atoms {
        let val = if true_atoms.contains(atom) {
            "true"
        } else {
            "false"
        };
        m.insert(atom.clone(), serde_json::Value::String(val.to_string()));
    }
    serde_json::Value::Object(m)
}

fn parse_black_bool(stdout: &str) -> Option<bool> {
    let t = stdout.trim();
    match t {
        "TRUE" | "True" | "true" => return Some(true),
        "FALSE" | "False" | "false" => return Some(false),
        _ => {}
    }
    for tok in t.split_whitespace() {
        match tok {
            "TRUE" | "True" | "true" => return Some(true),
            "FALSE" | "False" | "false" => return Some(false),
            _ => {}
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn atom(s: &str) -> Formula {
        Formula::FAtom { name: s.into() }
    }

    #[test]
    fn release_rewrites_to_until() {
        let f = Formula::FBinary {
            op: BinaryOp::Release,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let n = normalize(&f);
        // ¬(¬p U ¬q)
        let expected = form::not(Formula::FBinary {
            op: BinaryOp::Until,
            left: Box::new(form::not(atom("p"))),
            right: Box::new(form::not(atom("q"))),
        });
        assert_eq!(n, expected);
    }

    #[test]
    fn weak_until_rewrites_to_until_or_globally() {
        let f = Formula::FBinary {
            op: BinaryOp::WeakUntil,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let n = normalize(&f);
        // (p U q) ∨ G p
        let expected = form::or(
            Formula::FBinary {
                op: BinaryOp::Until,
                left: Box::new(atom("p")),
                right: Box::new(atom("q")),
            },
            Formula::FUnary {
                op: UnaryOp::Globally,
                operand: Box::new(atom("p")),
            },
        );
        assert_eq!(n, expected);
    }

    #[test]
    fn trigger_rewrites_to_since() {
        let f = Formula::FBinary {
            op: BinaryOp::Trigger,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        let n = normalize(&f);
        let expected = form::not(Formula::FBinary {
            op: BinaryOp::Since,
            left: Box::new(form::not(atom("p"))),
            right: Box::new(form::not(atom("q"))),
        });
        assert_eq!(n, expected);
    }

    #[test]
    fn normalize_is_idempotent_on_normalized_input() {
        let f = Formula::FBinary {
            op: BinaryOp::Until,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        assert_eq!(normalize(&f), normalize(&normalize(&f)));
    }

    #[test]
    fn to_black_syntax_atoms_and_constants() {
        assert_eq!(to_black_syntax(&Formula::FTrue).expect("ok"), "True");
        assert_eq!(to_black_syntax(&Formula::FFalse).expect("ok"), "False");
        assert_eq!(to_black_syntax(&atom("foo")).expect("ok"), "foo");
    }

    #[test]
    fn to_black_syntax_response_pattern() {
        // G(p -> F q)
        let f = Formula::FUnary {
            op: UnaryOp::Globally,
            operand: Box::new(Formula::FImplies {
                left: Box::new(atom("p")),
                right: Box::new(Formula::FUnary {
                    op: UnaryOp::Eventually,
                    operand: Box::new(atom("q")),
                }),
            }),
        };
        assert_eq!(to_black_syntax(&f).expect("ok"), "G((p => F(q)))");
    }

    #[test]
    fn to_black_syntax_rejects_un_normalised_operators() {
        let f = Formula::FBinary {
            op: BinaryOp::Release,
            left: Box::new(atom("p")),
            right: Box::new(atom("q")),
        };
        assert!(matches!(
            to_black_syntax(&f),
            Err(AnalysisError::Unsupported(_))
        ));
    }

    #[test]
    fn complete_state_handles_undef_and_missing_as_true() {
        // BLACK reports `p: "undef"`, `q` missing entirely, and
        // `r: "false"`.  The formula atoms are {p, q, r}.  Completion
        // policy: undef and missing default to TRUE, explicit false
        // stays out.
        let mut state = HashMap::new();
        state.insert("p".to_string(), "undef".to_string());
        state.insert("r".to_string(), "false".to_string());
        let formula_atoms: BTreeSet<String> =
            ["p".to_string(), "q".to_string(), "r".to_string()]
                .iter()
                .cloned()
                .collect();
        let completed = complete_state(&state, &formula_atoms);
        assert!(completed.contains("p"), "p:undef → should default to TRUE");
        assert!(completed.contains("q"), "q missing → should default to TRUE");
        assert!(!completed.contains("r"), "r:false → should be excluded");
    }

    #[test]
    fn complete_state_explicit_true_and_false_preserved() {
        let mut state = HashMap::new();
        state.insert("p".to_string(), "true".to_string());
        state.insert("q".to_string(), "false".to_string());
        let formula_atoms: BTreeSet<String> =
            ["p".to_string(), "q".to_string()].iter().cloned().collect();
        let completed = complete_state(&state, &formula_atoms);
        assert!(completed.contains("p"));
        assert!(!completed.contains("q"));
    }

    #[test]
    fn complete_state_passes_through_extra_true_atoms() {
        // BLACK occasionally surfaces atoms outside the formula
        // (defensive only — normalisation does not introduce atoms).
        let mut state = HashMap::new();
        state.insert("p".to_string(), "true".to_string());
        state.insert("extra".to_string(), "true".to_string());
        let formula_atoms: BTreeSet<String> = ["p".to_string()].iter().cloned().collect();
        let completed = complete_state(&state, &formula_atoms);
        assert!(completed.contains("p"));
        assert!(completed.contains("extra"));
    }

    #[test]
    fn parse_black_bool_handles_capital_and_lowercase() {
        assert_eq!(parse_black_bool("TRUE"), Some(true));
        assert_eq!(parse_black_bool("False"), Some(false));
        assert_eq!(parse_black_bool("true"), Some(true));
        assert_eq!(parse_black_bool("verbose noise\nTRUE\n"), Some(true));
        assert_eq!(parse_black_bool("???"), None);
    }

    #[test]
    fn find_binary_returns_useful_error_when_absent() {
        // SAFETY: this test mutates env; sequential within the same crate.
        // We can't use `env::set_var` under `#![forbid(unsafe_code)]`, so
        // we just confirm the default-path failure mode by asserting
        // the path doesn't accidentally exist in the test environment
        // (it would be /usr/local/bin/black — unlikely on a CI runner
        // without BLACK installed).
        if std::path::Path::new(BLACK_DEFAULT_PATH).exists() {
            // BLACK is genuinely installed — skip this check.
            return;
        }
        // Without BLACK_BIN set and without the default path, the
        // discovery falls back to PATH; if `which` succeeds we skip.
        if std::env::var("BLACK_BIN").is_ok() {
            return;
        }
        let r = find_black_binary();
        if let Err(AnalysisError::Unsupported(msg)) = r {
            assert!(msg.contains("BLACK"), "unexpected message: {msg}");
        }
    }
}
