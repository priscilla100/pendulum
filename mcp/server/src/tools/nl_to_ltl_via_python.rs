//! `nl_to_ltl_via_python` — translate NL to LTL by framing it as a
//! Python code-generation task.
//!
//! Implements the technique from Danso et al., "Syntax Is Easy,
//! Semantics Is Hard" (SecDev '26). The model is given the full LTL
//! dataclass hierarchy in Python and asked to produce a single line
//! `formulaToFind = <Python AST expression>`. We then mechanically
//! parse that Python expression into our `Formula` AST and pretty-
//! print it as canonical PLTL surface syntax.
//!
//! The premise is that LLMs are MUCH stronger at producing
//! syntactically-rigorous Python code than at producing LTL surface
//! syntax — Python is in their training distribution at scale; LTL
//! is not. By translating through Python, we cash in that strength.
//!
//! Pipeline:
//!   1. Build the Python-framing prompt (template + NL + AP map).
//!   2. Call the helper LLM via structured-output mode, schema
//!      `{python_code: string}`.
//!   3. Parse the model's `formulaToFind = <expr>` line.
//!   4. Recursive-descent parse the `<expr>` into a `Formula` AST.
//!   5. Render as PLTL surface syntax via `Formula::Display`.
//!   6. Validate the result via the OCaml parser; surface any error.

use crate::llm::ToolLlmClient;
use crate::tool::{CachePolicy, Tool, ToolError};
use async_trait::async_trait;
use pltl_rust::{BinaryOp, Formula, UnaryOp};
use schemars::{schema_for, JsonSchema};
use serde::{Deserialize, Serialize};

const NAME: &str = "nl_to_ltl_via_python";
const DESCRIPTION: &str = include_str!("nl_to_ltl_via_python_description.txt");

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct Input {
    /// Natural-language sentence to translate.
    text: String,
    /// Atomic-proposition mapping from `extract_ap_mapping`. The
    /// model is restricted to using exactly these names. Map shape:
    /// `{"req": "a request arrives", "ack": "acknowledged"}`.
    aps: serde_json::Value,
}

#[derive(Debug, Clone, Serialize)]
struct Output {
    ok: bool,
    formula: Option<String>,
    error: Option<String>,
    raw_python: Option<String>,
}

/// Tool implementation marker. Trait impl carries all logic; the
/// type is stateless so `Arc<dyn Tool>::clone` is essentially free.
#[derive(Debug, Default, Clone, Copy)]
pub struct NlToLtlViaPythonTool;

#[async_trait]
impl Tool for NlToLtlViaPythonTool {
    fn name(&self) -> &'static str {
        NAME
    }
    fn description(&self) -> &'static str {
        DESCRIPTION
    }
    fn input_schema(&self) -> serde_json::Value {
        serde_json::to_value(schema_for!(Input)).unwrap_or_else(|_| serde_json::json!({}))
    }
    fn cache_policy(&self) -> CachePolicy {
        // temperature=0 + seed=7 -> replayable.
        CachePolicy {
            temperature: Some(0.0),
            seed: Some(7),
        }
    }

    async fn call(&self, input: serde_json::Value) -> Result<serde_json::Value, ToolError> {
        let parsed: Input = serde_json::from_value(input)
            .map_err(|e| ToolError::InvalidInput(format!("schema: {e}")))?;
        if parsed.text.trim().is_empty() {
            return Err(ToolError::InvalidInput(
                "nl_to_ltl_via_python: `text` is required".into(),
            ));
        }
        let prompt = render_user_prompt(&parsed.text, &parsed.aps);

        // Use a code-specialised helper LLM by default — the tool's
        // whole pitch is that Python code-gen training transfers
        // better than NL→LTL training. Operator can override via
        // PLTL_PYTHON_TOOL_LLM_MODEL, or fall back to the generic
        // PLTL_TOOL_LLM_MODEL.
        let client = ToolLlmClient::from_env_with_model(
            "PLTL_PYTHON_TOOL_LLM_MODEL",
            "qwen2.5-coder:32b-instruct",
        )?;
        let sys = system_prompt();
        let value = client
            .structured_chat(sys.as_ref(), &prompt, response_schema())
            .await?;
        let python_code = value
            .get("python_code")
            .and_then(|v| v.as_str())
            .ok_or_else(|| {
                ToolError::Analysis(
                    "nl_to_ltl_via_python: LLM response missing `python_code` field".into(),
                )
            })?
            .trim()
            .to_string();

        // Parse the model's `formulaToFind = <expr>` line.
        let expr_src = match extract_assignment_rhs(&python_code) {
            Ok(s) => s,
            Err(e) => {
                return serde_json::to_value(Output {
                    ok: false,
                    formula: None,
                    error: Some(format!("could not extract `formulaToFind = ...`: {e}")),
                    raw_python: Some(python_code),
                })
                .map_err(|e| ToolError::Internal(format!("serialise: {e}")));
            }
        };

        // Recursive-descent parse into our Formula AST.
        let formula = match parse_python_ast(&expr_src) {
            Ok(f) => f,
            Err(e) => {
                return serde_json::to_value(Output {
                    ok: false,
                    formula: None,
                    error: Some(format!("python AST parse failed: {e}")),
                    raw_python: Some(python_code),
                })
                .map_err(|e| ToolError::Internal(format!("serialise: {e}")));
            }
        };

        // Pretty-print as canonical PLTL surface syntax.
        let formula_str = format!("{formula}");

        // Validate via the OCaml parser. This catches any AST that
        // happens to be unparseable (e.g. unknown atom names).
        match pltl_mcp_shared::parse(&formula_str) {
            Ok(_) => Ok(serde_json::to_value(Output {
                ok: true,
                formula: Some(formula_str),
                error: None,
                raw_python: Some(python_code),
            })
            .map_err(|e| ToolError::Internal(format!("serialise: {e}")))?),
            Err(e) => Ok(serde_json::to_value(Output {
                ok: false,
                formula: None,
                error: Some(format!("OCaml parser rejected `{formula_str}`: {e}")),
                raw_python: Some(python_code),
            })
            .map_err(|e| ToolError::Internal(format!("serialise: {e}")))?),
        }
    }
}

const SYSTEM_PROMPT_DEFAULT: &str =
    include_str!("../../prompts/nl_to_ltl_via_python_system.md");

/// Hot-swappable system prompt for this tool. See
/// [`crate::prompt_loader`] for resolution order.
fn system_prompt() -> std::borrow::Cow<'static, str> {
    crate::prompt_loader::load_tool_prompt(
        "nl_to_ltl_via_python_system.md",
        SYSTEM_PROMPT_DEFAULT,
    )
}

fn render_user_prompt(text: &str, aps: &serde_json::Value) -> String {
    let template = include_str!("nl_to_ltl_via_python_prompt.txt");
    let aps_pretty = serde_json::to_string(aps).unwrap_or_else(|_| "{}".into());
    template
        .replace("{NATURAL_LANGUAGE}", text)
        .replace("{ATOMIC_PROPOSITIONS}", &aps_pretty)
}

fn response_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["python_code"],
        "properties": {
            "python_code": { "type": "string", "minLength": 1 }
        }
    })
}

// ============================================================
// Assignment extraction
// ============================================================

/// Pull the right-hand side out of a `formulaToFind = <expr>` line.
/// Tolerates surrounding whitespace, markdown ``` fences, and a
/// trailing newline. Errors if the line is missing or malformed.
fn extract_assignment_rhs(src: &str) -> Result<String, String> {
    let stripped = strip_code_fences(src);
    // Look for `formulaToFind = ` anywhere; tolerate prefix.
    let needle = "formulaToFind";
    let idx = stripped
        .find(needle)
        .ok_or_else(|| "no `formulaToFind` token in output".to_string())?;
    let after = &stripped[idx + needle.len()..];
    let after = after.trim_start();
    if !after.starts_with('=') {
        return Err("expected `=` after `formulaToFind`".into());
    }
    let rhs = after[1..].trim().to_string();
    // RHS may end at a newline; cut there.
    let rhs = rhs.lines().next().unwrap_or("").trim().to_string();
    if rhs.is_empty() {
        return Err("right-hand side is empty".into());
    }
    Ok(rhs)
}

fn strip_code_fences(s: &str) -> String {
    let s = s.trim();
    // Remove any leading/trailing ``` block markers (python or bare).
    let s = s
        .trim_start_matches("```python")
        .trim_start_matches("```py")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim();
    s.to_string()
}

// ============================================================
// Python AST parser
// ============================================================
//
// Recursive-descent parser for a small subset of Python: function
// calls (constructor invocations) with positional arguments that are
// either string literals or nested calls. No operators, no
// attributes, no list/dict literals. The grammar:
//
//   expr     := call
//   call     := IDENT '(' arglist? ')'
//   arglist  := arg (',' arg)*
//   arg      := STRING | call
//   STRING   := '"' .* '"'  |  "'" .* "'"
//   IDENT    := [A-Za-z_][A-Za-z0-9_]*

#[derive(Debug, Clone)]
enum PyExpr {
    /// `"name"` or `'name'`
    Str(String),
    /// `Func(arg1, arg2, ...)`
    Call(String, Vec<PyExpr>),
}

fn parse_python_ast(src: &str) -> Result<Formula, String> {
    let mut parser = Parser::new(src);
    let expr = parser.parse_expr()?;
    parser.skip_ws();
    if parser.pos != parser.bytes.len() {
        return Err(format!(
            "unexpected trailing input at position {}: {:?}",
            parser.pos,
            &src[parser.pos..]
        ));
    }
    py_expr_to_formula(&expr)
}

struct Parser<'a> {
    src: &'a str,
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(src: &'a str) -> Self {
        Self {
            src,
            bytes: src.as_bytes(),
            pos: 0,
        }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len() && self.bytes[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn consume(&mut self, ch: u8) -> Result<(), String> {
        self.skip_ws();
        if self.peek() == Some(ch) {
            self.pos += 1;
            Ok(())
        } else {
            Err(format!(
                "expected `{}` at position {}, got {:?}",
                ch as char,
                self.pos,
                self.peek().map(|b| b as char)
            ))
        }
    }

    fn parse_ident(&mut self) -> Result<String, String> {
        self.skip_ws();
        let start = self.pos;
        while let Some(b) = self.peek() {
            let ok = b.is_ascii_alphanumeric() || b == b'_';
            if !ok {
                break;
            }
            self.pos += 1;
        }
        if start == self.pos {
            return Err(format!(
                "expected identifier at position {}, got {:?}",
                self.pos,
                self.peek().map(|b| b as char)
            ));
        }
        Ok(self.src[start..self.pos].to_string())
    }

    fn parse_string(&mut self) -> Result<String, String> {
        self.skip_ws();
        let quote = self
            .peek()
            .ok_or_else(|| "unexpected end of input parsing string".to_string())?;
        if quote != b'"' && quote != b'\'' {
            return Err(format!(
                "expected string quote at position {}, got {:?}",
                self.pos, quote as char
            ));
        }
        self.pos += 1;
        let start = self.pos;
        while let Some(b) = self.peek() {
            if b == quote {
                let s = self.src[start..self.pos].to_string();
                self.pos += 1;
                return Ok(s);
            }
            // We don't support escape sequences inside the string —
            // the model is generating short atom identifiers, not
            // arbitrary text. If escape support is ever needed, add
            // a small handler here.
            self.pos += 1;
        }
        Err("unterminated string literal".into())
    }

    fn parse_expr(&mut self) -> Result<PyExpr, String> {
        self.skip_ws();
        let next = self.peek();
        if matches!(next, Some(b'"') | Some(b'\'')) {
            return Ok(PyExpr::Str(self.parse_string()?));
        }
        // Otherwise it's a call `Ident(...)`.
        let name = self.parse_ident()?;
        self.consume(b'(')?;
        let mut args = Vec::new();
        // Empty arg list?
        self.skip_ws();
        if self.peek() != Some(b')') {
            loop {
                args.push(self.parse_expr()?);
                self.skip_ws();
                match self.peek() {
                    Some(b',') => {
                        self.pos += 1;
                    }
                    Some(b')') => break,
                    other => {
                        return Err(format!(
                            "expected `,` or `)` in argument list, got {:?}",
                            other.map(|b| b as char)
                        ))
                    }
                }
            }
        }
        self.consume(b')')?;
        Ok(PyExpr::Call(name, args))
    }
}

/// Map a parsed Python AST expression into our `Formula` enum.
fn py_expr_to_formula(expr: &PyExpr) -> Result<Formula, String> {
    match expr {
        PyExpr::Str(s) => Err(format!(
            "bare string literal `\"{s}\"` is not a Formula — wrap it in `AtomicProposition(...)`"
        )),
        PyExpr::Call(name, args) => match name.as_str() {
            "AtomicProposition" => {
                let s = expect_string(args, "AtomicProposition")?;
                if !is_valid_atom_name(&s) {
                    return Err(format!(
                        "atom name `{s}` violates lexer rule `[a-z][a-z0-9_]*`"
                    ));
                }
                Ok(Formula::FAtom { name: s })
            }
            "Literal" => {
                let s = expect_string(args, "Literal")?;
                match s.as_str() {
                    "True" => Ok(Formula::FTrue),
                    "False" => Ok(Formula::FFalse),
                    other => Err(format!("Literal expects \"True\" or \"False\", got `{other}`")),
                }
            }
            "LNot" => {
                let inner = expect_one_formula(args, "LNot")?;
                Ok(Formula::FNot { operand: Box::new(inner) })
            }
            "LAnd" => {
                let (l, r) = expect_two_formulas(args, "LAnd")?;
                Ok(Formula::FAnd { left: Box::new(l), right: Box::new(r) })
            }
            "LOr" => {
                let (l, r) = expect_two_formulas(args, "LOr")?;
                Ok(Formula::FOr { left: Box::new(l), right: Box::new(r) })
            }
            "LImplies" => {
                let (l, r) = expect_two_formulas(args, "LImplies")?;
                Ok(Formula::FImplies { left: Box::new(l), right: Box::new(r) })
            }
            "LEquiv" => {
                let (l, r) = expect_two_formulas(args, "LEquiv")?;
                Ok(Formula::FIff { left: Box::new(l), right: Box::new(r) })
            }
            "Next" => unary(args, "Next", UnaryOp::Next),
            "Always" => unary(args, "Always", UnaryOp::Globally),
            "Eventually" => unary(args, "Eventually", UnaryOp::Eventually),
            "Yesterday" => unary(args, "Yesterday", UnaryOp::Yesterday),
            "Once" => unary(args, "Once", UnaryOp::Once),
            "Historically" => unary(args, "Historically", UnaryOp::Historically),
            "Until" => binary(args, "Until", BinaryOp::Until),
            "Since" => binary(args, "Since", BinaryOp::Since),
            // PLTL extras the paper doesn't define but we should
            // accept defensively if the model produces them.
            "WeakUntil" => binary(args, "WeakUntil", BinaryOp::WeakUntil),
            "Release" => binary(args, "Release", BinaryOp::Release),
            "Trigger" => binary(args, "Trigger", BinaryOp::Trigger),
            other => Err(format!("unknown constructor `{other}`")),
        },
    }
}

fn unary(args: &[PyExpr], label: &str, op: UnaryOp) -> Result<Formula, String> {
    let inner = expect_one_formula(args, label)?;
    Ok(Formula::FUnary { op, operand: Box::new(inner) })
}

fn binary(args: &[PyExpr], label: &str, op: BinaryOp) -> Result<Formula, String> {
    let (l, r) = expect_two_formulas(args, label)?;
    Ok(Formula::FBinary { op, left: Box::new(l), right: Box::new(r) })
}

fn expect_string(args: &[PyExpr], label: &str) -> Result<String, String> {
    if args.len() != 1 {
        return Err(format!("{label} expects 1 string argument, got {}", args.len()));
    }
    match &args[0] {
        PyExpr::Str(s) => Ok(s.clone()),
        _ => Err(format!("{label} expects a string argument, got a constructor call")),
    }
}

fn expect_one_formula(args: &[PyExpr], label: &str) -> Result<Formula, String> {
    if args.len() != 1 {
        return Err(format!("{label} expects 1 argument, got {}", args.len()));
    }
    py_expr_to_formula(&args[0])
}

fn expect_two_formulas(args: &[PyExpr], label: &str) -> Result<(Formula, Formula), String> {
    if args.len() != 2 {
        return Err(format!("{label} expects 2 arguments, got {}", args.len()));
    }
    Ok((py_expr_to_formula(&args[0])?, py_expr_to_formula(&args[1])?))
}

fn is_valid_atom_name(s: &str) -> bool {
    let mut it = s.chars();
    match it.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return false,
    }
    it.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(s: &str) -> Formula {
        parse_python_ast(s).expect(s)
    }

    #[test]
    fn parse_atomic() {
        let f = parse(r#"AtomicProposition("p")"#);
        assert_eq!(format!("{f}"), "p");
    }

    #[test]
    fn parse_unary() {
        let f = parse(r#"Always(AtomicProposition("p"))"#);
        assert_eq!(format!("{f}"), "G p");
    }

    #[test]
    fn parse_nested_implies() {
        // G (p -> F q)
        let f = parse(r#"Always(LImplies(AtomicProposition("p"), Eventually(AtomicProposition("q"))))"#);
        assert_eq!(format!("{f}"), "G (p -> F q)");
    }

    #[test]
    fn parse_until() {
        let f = parse(r#"Until(AtomicProposition("p"), AtomicProposition("q"))"#);
        assert_eq!(format!("{f}"), "(p U q)");
    }

    #[test]
    fn parse_since() {
        let f = parse(r#"Since(LNot(AtomicProposition("revoke")), AtomicProposition("grant"))"#);
        assert_eq!(format!("{f}"), "(!revoke S grant)");
    }

    #[test]
    fn parse_handles_single_quotes() {
        let f = parse(r#"AtomicProposition('p')"#);
        assert_eq!(format!("{f}"), "p");
    }

    #[test]
    fn parse_handles_whitespace_and_newlines() {
        let f = parse(
            r#"Always(
                  LImplies(
                    AtomicProposition("p"),
                    Eventually(AtomicProposition("q"))
                  )
                )"#,
        );
        assert_eq!(format!("{f}"), "G (p -> F q)");
    }

    #[test]
    fn parse_literal_constants() {
        assert_eq!(format!("{}", parse(r#"Literal("True")"#)), "true");
        assert_eq!(format!("{}", parse(r#"Literal("False")"#)), "false");
    }

    #[test]
    fn parse_rejects_invalid_atom_name() {
        let err = parse_python_ast(r#"AtomicProposition("P")"#).unwrap_err();
        assert!(err.contains("lexer rule"), "got: {err}");
    }

    #[test]
    fn parse_rejects_unknown_constructor() {
        let err = parse_python_ast(r#"Foo(AtomicProposition("p"))"#).unwrap_err();
        assert!(err.contains("unknown constructor"), "got: {err}");
    }

    #[test]
    fn parse_rejects_bare_string() {
        let err = parse_python_ast(r#""p""#).unwrap_err();
        assert!(err.contains("bare string"), "got: {err}");
    }

    #[test]
    fn parse_rejects_wrong_arity() {
        let err = parse_python_ast(r#"LAnd(AtomicProposition("p"))"#).unwrap_err();
        assert!(err.contains("2 arguments"), "got: {err}");
    }

    #[test]
    fn extract_rhs_strips_code_fences() {
        let rhs = extract_assignment_rhs(
            "```python\nformulaToFind = Always(AtomicProposition(\"p\"))\n```",
        )
        .unwrap();
        assert_eq!(rhs, r#"Always(AtomicProposition("p"))"#);
    }

    #[test]
    fn extract_rhs_tolerates_prefix() {
        let rhs = extract_assignment_rhs("# explanation\nformulaToFind = Always(AtomicProposition(\"p\"))").unwrap();
        assert_eq!(rhs, r#"Always(AtomicProposition("p"))"#);
    }

    #[test]
    fn extract_rhs_fails_when_missing() {
        let err = extract_assignment_rhs("# no assignment here").unwrap_err();
        assert!(err.contains("no `formulaToFind`"), "got: {err}");
    }

    #[test]
    fn end_to_end_response_pattern() {
        let rhs = extract_assignment_rhs(
            r#"formulaToFind = Always(LImplies(AtomicProposition("req"), Eventually(AtomicProposition("ack"))))"#,
        ).unwrap();
        let f = parse_python_ast(&rhs).unwrap();
        assert_eq!(format!("{f}"), "G (req -> F ack)");
    }

    #[test]
    fn end_to_end_past_since() {
        let rhs = extract_assignment_rhs(
            r#"formulaToFind = Always(LImplies(AtomicProposition("auth"), Since(LNot(AtomicProposition("revoke")), AtomicProposition("grant"))))"#,
        ).unwrap();
        let f = parse_python_ast(&rhs).unwrap();
        assert_eq!(format!("{f}"), "G (auth -> (!revoke S grant))");
    }

    #[test]
    fn system_prompt_loads_landmark() {
        let s = system_prompt();
        assert!(
            s.contains("formulaToFind"),
            "expected landmark `formulaToFind` in nl_to_ltl_via_python system prompt; got: {}",
            &s[..s.len().min(120)]
        );
    }

    #[test]
    fn system_prompt_default_constant_nonempty() {
        assert!(!SYSTEM_PROMPT_DEFAULT.trim().is_empty());
    }

    #[tokio::test]
    async fn rejects_blank_text() {
        let t = NlToLtlViaPythonTool;
        let r = t.call(serde_json::json!({"text": "  ", "aps": {}})).await;
        assert!(matches!(r, Err(ToolError::InvalidInput(_))));
    }
}
