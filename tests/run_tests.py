#!/usr/bin/env python3
"""End-to-end test runner for the PLTL pipeline.

Usage:
    ./tests/run_tests.py               # deep mode (default)
    ./tests/run_tests.py --light       # quick smoke set
    ./tests/run_tests.py --deep        # explicit deep mode
    ./tests/run_tests.py -h            # help

For each well-formed test the harness:

  1. Runs the OCaml parser → JSON1.
  2. Runs the full pipeline (OCaml parse → Rust pretty-print) → pretty string.
  3. Runs the OCaml parser on the pretty string → JSON2.
  4. Asserts JSON1 == JSON2 (round-trip preserves the AST).
  5. If a canonical pretty-form was pinned, asserts the pretty output matches.

For each ill-formed test, the harness asserts the OCaml parser exits non-zero.

Deep mode additionally runs a corpus of ~50 real-world LTL formulas
adapted from Spot, NuSMV, Dwyer specification patterns, GR(1)/SYNTECH,
and past-LTL benchmarks. Those are exercised as round-trip-only checks
(no pinned canonical form).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OCAML = ROOT / "ocaml" / "_build" / "default" / "main.exe"
RUST = ROOT / "target" / "debug" / "pltl_rust"


# ── Pipeline helpers ────────────────────────────────────────────────────────
def parse_to_json(formula: str) -> dict:
    """Run the OCaml parser; return the AST as a Python dict."""
    result = subprocess.run(
        [str(OCAML), formula, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def pretty_via_rust(formula: str) -> str:
    """Drive the full pipeline; return only the pretty-printed string."""
    result = subprocess.run(
        [str(RUST), formula],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Output: "):
            return line[len("Output: ") :]
    raise RuntimeError(f"no 'Output:' line in pipeline output:\n{result.stdout}")


def ocaml_parse_fails(formula: str) -> bool:
    """True iff the OCaml parser exits non-zero on this input."""
    result = subprocess.run(
        [str(OCAML), formula, "--json"],
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


# ── Test record types ───────────────────────────────────────────────────────
@dataclass
class WellFormed:
    formula: str
    canonical: Optional[str] = None  # if set, pretty output must equal this


@dataclass
class IllFormed:
    formula: str
    reason: str  # human-readable for the failure message


# ── Operator-spelling tests (the bulk of the light set) ─────────────────────
# Each entry pins the canonical pretty-form, which guards against
# pretty-printer regressions.
SPELLING_TESTS: list[WellFormed] = [
    # constants & atoms
    WellFormed("p", "p"),
    WellFormed("proposition42", "proposition42"),
    WellFormed("req_valid", "req_valid"),
    WellFormed("true", "true"),
    WellFormed("True", "true"),
    WellFormed("TRUE", "true"),
    WellFormed("false", "false"),
    WellFormed("False", "false"),
    WellFormed("FALSE", "false"),

    # negation
    WellFormed("!p",        "!p"),
    WellFormed("~p",        "!p"),
    WellFormed("NOT p",     "!p"),
    WellFormed("not p",     "!p"),
    WellFormed("Not p",     "!p"),
    WellFormed("\\neg p",   "!p"),
    WellFormed("\\lnot p",  "!p"),
    WellFormed("!!p",       "!!p"),

    # conjunction
    WellFormed("p & q",       "(p & q)"),
    WellFormed("p && q",      "(p & q)"),
    WellFormed("p /\\ q",     "(p & q)"),
    WellFormed("p AND q",     "(p & q)"),
    WellFormed("p and q",     "(p & q)"),
    WellFormed("p And q",     "(p & q)"),
    WellFormed("p LAND q",    "(p & q)"),
    WellFormed("p \\wedge q", "(p & q)"),
    WellFormed("p \\land q",  "(p & q)"),

    # disjunction
    WellFormed("p | q",      "(p | q)"),
    WellFormed("p || q",     "(p | q)"),
    WellFormed("p \\/ q",    "(p | q)"),
    WellFormed("p OR q",     "(p | q)"),
    WellFormed("p or q",     "(p | q)"),
    WellFormed("p LOR q",    "(p | q)"),
    WellFormed("p \\vee q",  "(p | q)"),
    WellFormed("p \\lor q",  "(p | q)"),

    # implication
    WellFormed("p -> q",            "(p -> q)"),
    WellFormed("p => q",            "(p -> q)"),
    WellFormed("p IMPLIES q",       "(p -> q)"),
    WellFormed("p implies q",       "(p -> q)"),
    WellFormed("p \\implies q",     "(p -> q)"),
    WellFormed("p \\to q",          "(p -> q)"),
    WellFormed("p \\rightarrow q",  "(p -> q)"),

    # biimplication
    WellFormed("p <-> q",               "(p <-> q)"),
    WellFormed("p <=> q",               "(p <-> q)"),
    WellFormed("p IFF q",               "(p <-> q)"),
    WellFormed("p iff q",               "(p <-> q)"),
    WellFormed("p \\iff q",             "(p <-> q)"),
    WellFormed("p \\leftrightarrow q",  "(p <-> q)"),

    # Globally / Henceforth / Always
    WellFormed("G p",          "G p"),
    WellFormed("[] p",         "G p"),
    WellFormed("Globally p",   "G p"),
    WellFormed("GLOBALLY p",   "G p"),
    WellFormed("Always p",     "G p"),
    WellFormed("Henceforth p", "G p"),
    WellFormed("\\G p",        "G p"),
    WellFormed("\\Box p",      "G p"),
    WellFormed("\\square p",   "G p"),

    # Eventually / Finally
    WellFormed("F p",            "F p"),
    WellFormed("<> p",           "F p"),
    WellFormed("Finally p",      "F p"),
    WellFormed("Eventually p",   "F p"),
    WellFormed("\\F p",          "F p"),
    WellFormed("\\Diamond p",    "F p"),
    WellFormed("\\lozenge p",    "F p"),

    # Next
    WellFormed("X p",          "X p"),
    WellFormed("Next p",       "X p"),
    WellFormed("\\X p",        "X p"),
    WellFormed("\\Next p",     "X p"),
    WellFormed("\\bigcirc p",  "X p"),
    WellFormed("\\circ p",     "X p"),

    # Yesterday
    WellFormed("Y p",          "Y p"),
    WellFormed("Yesterday p",  "Y p"),
    WellFormed("\\Y p",        "Y p"),
    WellFormed("\\prev p",     "Y p"),

    # Once
    WellFormed("O p",          "O p"),
    WellFormed("Once p",       "O p"),
    WellFormed("\\O p",        "O p"),
    WellFormed("\\Once p",     "O p"),

    # Historically
    WellFormed("H p",            "H p"),
    WellFormed("Historically p", "H p"),
    WellFormed("\\H p",          "H p"),
    WellFormed("\\boxminus p",   "H p"),

    # Until
    WellFormed("p U q",      "(p U q)"),
    WellFormed("p Until q",  "(p U q)"),
    WellFormed("p UNTIL q",  "(p U q)"),
    WellFormed("p \\U q",    "(p U q)"),

    # Since
    WellFormed("p S q",      "(p S q)"),
    WellFormed("p Since q",  "(p S q)"),
    WellFormed("p \\S q",    "(p S q)"),

    # WeakUntil
    WellFormed("p W q",          "(p W q)"),
    WellFormed("p WeakUntil q",  "(p W q)"),
    WellFormed("p \\W q",        "(p W q)"),

    # Release
    WellFormed("p R q",        "(p R q)"),
    WellFormed("p Release q",  "(p R q)"),
    WellFormed("p \\R q",      "(p R q)"),

    # Trigger
    WellFormed("p T q",        "(p T q)"),
    WellFormed("p Trigger q",  "(p T q)"),
    WellFormed("p \\T q",      "(p T q)"),
]

# ── Precedence and associativity tests ──────────────────────────────────────
# The precedence hierarchy below matches Spot, NuSMV, nuXmv, and the
# textbook conventions for LTL+past:
#
#     <->                                   right-associative  (loosest)
#     ->                                    right-associative
#     |                                     left-associative
#     &                                     left-associative
#     U  S  W  R  T  (binary temporal)      right-associative
#     !  X  Y  F  G  O  H  (unary prefix)   bind tightest
#
# Every rule above is exercised below in both directions (LHS and RHS).
PRECEDENCE_TESTS: list[WellFormed] = [
    # ── Negation binds tighter than every binary operator ──────────────
    WellFormed("!p & q",        "(!p & q)"),
    WellFormed("p & !q",        "(p & !q)"),
    WellFormed("!p | q",        "(!p | q)"),
    WellFormed("p | !q",        "(p | !q)"),
    WellFormed("!p -> q",       "(!p -> q)"),
    WellFormed("p -> !q",       "(p -> !q)"),
    WellFormed("!p <-> q",      "(!p <-> q)"),
    WellFormed("p <-> !q",      "(p <-> !q)"),
    WellFormed("!p U q",        "(!p U q)"),
    WellFormed("p U !q",        "(p U !q)"),
    WellFormed("!p S q",        "(!p S q)"),
    WellFormed("!p W q",        "(!p W q)"),
    WellFormed("!p R q",        "(!p R q)"),
    WellFormed("!p T q",        "(!p T q)"),
    WellFormed("!(p & q)",      "!(p & q)"),
    WellFormed("!(p | q)",      "!(p | q)"),
    WellFormed("!(p -> q)",     "!(p -> q)"),
    WellFormed("!(p U q)",      "!(p U q)"),

    # ── Unary temporal G binds tighter than every binary operator ──────
    WellFormed("G p & q",       "(G p & q)"),
    WellFormed("p & G q",       "(p & G q)"),
    WellFormed("G p | q",       "(G p | q)"),
    WellFormed("p | G q",       "(p | G q)"),
    WellFormed("G p -> q",      "(G p -> q)"),
    WellFormed("p -> G q",      "(p -> G q)"),
    WellFormed("G p <-> q",     "(G p <-> q)"),
    WellFormed("G p U q",       "(G p U q)"),
    WellFormed("p U G q",       "(p U G q)"),
    WellFormed("G p S q",       "(G p S q)"),
    WellFormed("G p W q",       "(G p W q)"),
    WellFormed("G p R q",       "(G p R q)"),
    WellFormed("G p T q",       "(G p T q)"),
    WellFormed("G (p & q)",     "G (p & q)"),
    WellFormed("G (p U q)",     "G (p U q)"),

    # ── Unary temporal F binds tightest, future side ───────────────────
    WellFormed("F p & q",       "(F p & q)"),
    WellFormed("F p | q",       "(F p | q)"),
    WellFormed("F p -> q",      "(F p -> q)"),
    WellFormed("F p U q",       "(F p U q)"),
    WellFormed("F (p -> q)",    "F (p -> q)"),

    # ── X (Next), Y (Yesterday) bind tightest ─────────────────────────
    WellFormed("X p & q",       "(X p & q)"),
    WellFormed("X p U q",       "(X p U q)"),
    WellFormed("p & X q",       "(p & X q)"),
    WellFormed("Y p & q",       "(Y p & q)"),
    WellFormed("Y p S q",       "(Y p S q)"),
    WellFormed("p S Y q",       "(p S Y q)"),

    # ── Past unary (O, H) bind tightest ────────────────────────────────
    WellFormed("O p & q",       "(O p & q)"),
    WellFormed("p & O q",       "(p & O q)"),
    WellFormed("H p -> q",      "(H p -> q)"),
    WellFormed("p -> H q",      "(p -> H q)"),
    WellFormed("O p S q",       "(O p S q)"),
    WellFormed("H p S q",       "(H p S q)"),

    # ── Unary chains bind right-to-left (prefix stacking) ──────────────
    WellFormed("!!p",           "!!p"),
    WellFormed("!!!p",          "!!!p"),
    WellFormed("! G p",         "!G p"),
    WellFormed("G ! p",         "G !p"),
    WellFormed("! G F p",       "!G F p"),
    WellFormed("G F p",         "G F p"),
    WellFormed("F G p",         "F G p"),
    WellFormed("X Y p",         "X Y p"),
    WellFormed("Y X p",         "Y X p"),
    WellFormed("G F G F p",     "G F G F p"),
    WellFormed("H O H O p",     "H O H O p"),

    # ── Binary temporal tighter than & ─────────────────────────────────
    WellFormed("p U q & r",     "((p U q) & r)"),
    WellFormed("p & q U r",     "(p & (q U r))"),
    WellFormed("p S q & r",     "((p S q) & r)"),
    WellFormed("p & q S r",     "(p & (q S r))"),
    WellFormed("p W q & r",     "((p W q) & r)"),
    WellFormed("p R q & r",     "((p R q) & r)"),
    WellFormed("p T q & r",     "((p T q) & r)"),

    # ── Binary temporal tighter than | ─────────────────────────────────
    WellFormed("p U q | r",     "((p U q) | r)"),
    WellFormed("p | q U r",     "(p | (q U r))"),
    WellFormed("p S q | r",     "((p S q) | r)"),
    WellFormed("p W q | r",     "((p W q) | r)"),

    # ── Binary temporal tighter than -> ────────────────────────────────
    WellFormed("p U q -> r",    "((p U q) -> r)"),
    WellFormed("p -> q U r",    "(p -> (q U r))"),
    WellFormed("p S q -> r",    "((p S q) -> r)"),

    # ── Binary temporal tighter than <-> ───────────────────────────────
    WellFormed("p U q <-> r",   "((p U q) <-> r)"),
    WellFormed("p <-> q U r",   "(p <-> (q U r))"),

    # ── & tighter than | ───────────────────────────────────────────────
    WellFormed("p & q | r",     "((p & q) | r)"),
    WellFormed("p | q & r",     "(p | (q & r))"),
    WellFormed("p & q | r & s", "((p & q) | (r & s))"),
    WellFormed("p | q & r | s", "((p | (q & r)) | s)"),

    # ── & tighter than -> ──────────────────────────────────────────────
    WellFormed("p & q -> r",    "((p & q) -> r)"),
    WellFormed("p -> q & r",    "(p -> (q & r))"),

    # ── & tighter than <-> ─────────────────────────────────────────────
    WellFormed("p & q <-> r",   "((p & q) <-> r)"),
    WellFormed("p <-> q & r",   "(p <-> (q & r))"),

    # ── | tighter than -> ──────────────────────────────────────────────
    WellFormed("p | q -> r",    "((p | q) -> r)"),
    WellFormed("p -> q | r",    "(p -> (q | r))"),

    # ── | tighter than <-> ─────────────────────────────────────────────
    WellFormed("p | q <-> r",   "((p | q) <-> r)"),
    WellFormed("p <-> q | r",   "(p <-> (q | r))"),

    # ── -> tighter than <-> ────────────────────────────────────────────
    WellFormed("p -> q <-> r",  "((p -> q) <-> r)"),
    WellFormed("p <-> q -> r",  "(p <-> (q -> r))"),

    # ── Associativity: & left ──────────────────────────────────────────
    WellFormed("a & b & c",       "((a & b) & c)"),
    WellFormed("a & b & c & d",   "(((a & b) & c) & d)"),

    # ── Associativity: | left ──────────────────────────────────────────
    WellFormed("a | b | c",       "((a | b) | c)"),
    WellFormed("a | b | c | d",   "(((a | b) | c) | d)"),

    # ── Associativity: -> right ────────────────────────────────────────
    WellFormed("a -> b -> c",       "(a -> (b -> c))"),
    WellFormed("a -> b -> c -> d",  "(a -> (b -> (c -> d)))"),

    # ── Associativity: <-> right ───────────────────────────────────────
    WellFormed("a <-> b <-> c",       "(a <-> (b <-> c))"),
    WellFormed("a <-> b <-> c <-> d", "(a <-> (b <-> (c <-> d)))"),

    # ── Associativity: binary temporal right ───────────────────────────
    WellFormed("p U q U r",       "(p U (q U r))"),
    WellFormed("p U q U r U s",   "(p U (q U (r U s)))"),
    WellFormed("p S q S r",       "(p S (q S r))"),
    WellFormed("p W q W r",       "(p W (q W r))"),
    WellFormed("p R q R r",       "(p R (q R r))"),
    WellFormed("p T q T r",       "(p T (q T r))"),

    # ── Full-stack mixed precedence (the big ones) ─────────────────────
    WellFormed("!p & q | r",
               "((!p & q) | r)"),
    WellFormed("!p | q & r",
               "(!p | (q & r))"),
    WellFormed("G p & F q | H r",
               "((G p & F q) | H r)"),
    WellFormed("p U q & r -> s",
               "(((p U q) & r) -> s)"),
    WellFormed("p U q | r & s -> t <-> u",
               "((((p U q) | (r & s)) -> t) <-> u)"),
    WellFormed("!p U q -> r",
               "((!p U q) -> r)"),
    WellFormed("G p -> F q & H r",
               "(G p -> (F q & H r))"),
    WellFormed("G p | F q & H r",
               "(G p | (F q & H r))"),
    WellFormed("p U q | r U s",
               "((p U q) | (r U s))"),
    WellFormed("p U q & r U s",
               "((p U q) & (r U s))"),
    WellFormed("p U q -> r U s",
               "((p U q) -> (r U s))"),
    WellFormed("a & b -> c | d",
               "((a & b) -> (c | d))"),
    WellFormed("a | b & c -> d | e & f",
               "((a | (b & c)) -> (d | (e & f)))"),

    # ── Parens override precedence ─────────────────────────────────────
    WellFormed("(p & q) | r",        "((p & q) | r)"),
    WellFormed("p & (q | r)",        "(p & (q | r))"),
    WellFormed("(p | q) & r",        "((p | q) & r)"),
    WellFormed("(p -> q) & r",       "((p -> q) & r)"),
    WellFormed("(p U q)",            "(p U q)"),
    WellFormed("((((p))))",          "p"),
    WellFormed("((p & q))",          "(p & q)"),
    WellFormed("G ((p))",            "G p"),
    WellFormed("! (G p)",            "!G p"),
    WellFormed("(! G p)",            "!G p"),
]

# ── Nested / composed formula tests ────────────────────────────────────────
COMPOSED_TESTS: list[WellFormed] = [
    # nested unary temporal
    WellFormed("G F p",   "G F p"),
    WellFormed("F G p",   "F G p"),
    WellFormed("G F G p", "G F G p"),
    WellFormed("H O p",   "H O p"),
    WellFormed("X X X p", "X X X p"),
    WellFormed("Y Y Y p", "Y Y Y p"),

    # past + future mixed
    WellFormed("G(p -> F q)", "G (p -> F q)"),
    WellFormed("H(p -> O q)", "H (p -> O q)"),
    WellFormed("G(p -> F q) & H(r -> O s)",
               "(G (p -> F q) & H (r -> O s))"),
    WellFormed("(p U q) -> G(p | q)",
               "((p U q) -> G (p | q))"),
    WellFormed("(p S q) -> H(p | q)",
               "((p S q) -> H (p | q))"),

    # whitespace robustness
    WellFormed("p&q",                            "(p & q)"),
    WellFormed("p   &   q",                      "(p & q)"),
    WellFormed("  G   p  ",                      "G p"),
    WellFormed("p\nU\nq",                        "(p U q)"),
    WellFormed("(* a comment *) p & q",          "(p & q)"),
    WellFormed("p (* nested (* ok *) *) & q",    "(p & q)"),

    # classical equivalences (round-trip only)
    WellFormed("!(p & q) <-> (!p | !q)"),   # De Morgan
    WellFormed("(p -> q) <-> (!q -> !p)"),  # contrapositive
    WellFormed("G p <-> !F !p"),
    WellFormed("F p <-> !G !p"),
    WellFormed("G(p -> (q U r)) | H(s -> (t S u))"),
]

# ── Real-world corpus ───────────────────────────────────────────────────────
# Sources: Spot tutorials/docs, NuSMV manuals, Dwyer specification patterns,
# SYNTECH/GR(1) patterns, ProB past-LTL examples, past-LTL literature.
# Light-rewritten where the original used uppercase, dotted, or
# parameterised atom names, or where a name collided with a reserved word
# (e.g. "release" → "release_signal").
CORPUS_TESTS: list[WellFormed] = [
    # Spot tutorials / parser docs
    WellFormed("[]<>p0 || <>[]p1"),
    WellFormed("GFp0 | FGp1"),
    WellFormed("a U b"),
    WellFormed("a U (b & GF c)"),
    WellFormed("(Ga -> Gb) W c"),
    WellFormed("(Fp1 | Gp2) & (Fp2 | Gp3) & (Fp3 | Gp4) & (Fp4 | Gp5)"),
    WellFormed("G(a -> (b R !c))"),
    WellFormed("GF(a <-> Xb)"),
    WellFormed("G(b | F(b & Fa))"),
    WellFormed("(!a | (!a R b)) & (a | (a U !b))"),
    WellFormed("!a & F((!a | FG!a) & (a | GFa))"),
    WellFormed("X(!b W a)"),
    WellFormed("!a & FGa"),

    # NuSMV / nuXmv style: mutex, counters, request-response
    WellFormed("G !(crit1 & crit2)"),
    WellFormed("G (entering1 -> F crit1)"),
    WellFormed("G (y_is_4 -> X y_is_6)"),
    WellFormed("!G F y_is_2"),
    WellFormed("G (req -> F status_busy)"),
    WellFormed("G (req -> F ack)"),

    # Dwyer specification patterns
    # Absence
    WellFormed("[](!p)"),
    WellFormed("<>r -> (!p U r)"),
    WellFormed("[](q -> [](!p))"),
    WellFormed("[]((q & !r & <>r) -> (!p U r))"),
    WellFormed("[](q & !r -> (!p W r))"),
    # Existence
    WellFormed("<>p"),
    WellFormed("!r W (p & !r)"),
    WellFormed("[](!q) | <>(q & <>p)"),
    WellFormed("[](q & !r -> (!r U (p & !r)))"),
    # Universality
    WellFormed("[](q -> [](p))"),
    WellFormed("[]((q & !r & <>r) -> (p U r))"),
    # Precedence
    WellFormed("!p W s"),
    WellFormed("<>r -> (!p U (s | r))"),
    WellFormed("[]!q | <>(q & (!p W s))"),
    WellFormed("[](q & !r -> (!p W (s | r)))"),
    # Response
    WellFormed("[](p -> <>s)"),
    WellFormed("[](q -> [](p -> <>s))"),
    WellFormed("[](q & !r -> ((p -> (!r U (s & !r))) W r))"),

    # GR(1) / SYNTECH-style assumption/guarantee shapes
    WellFormed("GF req -> GF grant"),
    WellFormed("(GF p1 & GF p2) -> GF q"),
    WellFormed("G(req -> X(busy U ack))"),
    WellFormed("G(grant -> !X grant W release_signal)"),
    WellFormed("G((req1 & !req2) -> X grant1) & G((req2 & !req1) -> X grant2)"),

    # Arbiter / fairness / classic liveness
    WellFormed("G F sched & G(req -> F grant)"),
    WellFormed("G(req -> (req U grant))"),
    WellFormed("G(!(grant1 & grant2)) & G(req1 -> F grant1) & G(req2 -> F grant2)"),
    WellFormed("G(start -> (!stop U done))"),

    # Past-time LTL (ProB / past-LTL papers / nuXmv)
    WellFormed("G(alarm -> O fault)"),
    WellFormed("G(grant -> O req)"),
    WellFormed("G(login -> Y !login)"),
    WellFormed("H(!error) -> G safe_mode"),
    WellFormed("G(ack S req)"),
    WellFormed("G(unlock -> O(key_inserted & H !tamper))"),
    WellFormed("G(write -> (read T owner))"),
    WellFormed("G(p -> Y(q S r))"),

    # Deep nesting / mixed past+future
    WellFormed("G F(p & X(q U (r & O s)))"),
    WellFormed("(G F p) <-> (F G (q | H r))"),
    WellFormed("G(req -> F(grant & O issued)) & G(!(grant & H !req))"),
]

# ── Ill-formed cases ────────────────────────────────────────────────────────
# Each entry is something the parser MUST reject; the harness asserts a
# non-zero exit. Grouped roughly by failure category for readability.
ILL_FORMED: list[IllFormed] = [
    # empty / whitespace-only / comment-only
    IllFormed("",                       "empty input"),
    IllFormed("   ",                    "whitespace-only input"),
    IllFormed("\t\n  \t",               "tabs and newlines only"),
    IllFormed("(* only a comment *)",   "comment-only input has no formula"),

    # unbalanced parentheses
    IllFormed("(p",                     "unclosed paren"),
    IllFormed("p)",                     "unopened paren"),
    IllFormed("((p)",                   "missing one closing paren"),
    IllFormed("(p))",                   "extra closing paren"),
    IllFormed("()",                     "empty parens by themselves"),
    IllFormed("p & ()",                 "empty parens as operand"),
    IllFormed("(* unterminated",        "unterminated comment"),

    # binary operator missing operand(s)
    IllFormed("p &",                    "missing right operand of &"),
    IllFormed("& p",                    "missing left operand of &"),
    IllFormed("p |",                    "missing right operand of |"),
    IllFormed("| p",                    "missing left operand of |"),
    IllFormed("p ->",                   "missing right operand of ->"),
    IllFormed("-> p",                   "missing left operand of ->"),
    IllFormed("p <->",                  "missing right operand of <->"),
    IllFormed("p U",                    "missing right operand of U"),
    IllFormed("U q",                    "missing left operand of U"),
    IllFormed("p S",                    "missing right operand of S"),
    IllFormed("p W",                    "missing right operand of W"),
    IllFormed("p R",                    "missing right operand of R"),
    IllFormed("p T",                    "missing right operand of T"),

    # unary operator missing operand
    IllFormed("!",                      "negation without operand"),
    IllFormed("!!",                     "double negation without operand"),
    IllFormed("~",                      "tilde-negation without operand"),
    IllFormed("G",                      "G (Globally) without operand"),
    IllFormed("F",                      "F (Eventually) without operand"),
    IllFormed("X",                      "X (Next) without operand"),
    IllFormed("Y",                      "Y (Yesterday) without operand"),
    IllFormed("H",                      "H (Historically) without operand"),
    IllFormed("O",                      "O (Once) without operand"),
    IllFormed("Globally",               "word-form unary missing operand"),
    IllFormed("Eventually",             "word-form unary missing operand"),
    IllFormed("[]",                     "symbolic Globally without operand"),
    IllFormed("<>",                     "symbolic Eventually without operand"),

    # consecutive / repeated operators
    IllFormed("p -> -> q",              "two implies in a row"),
    IllFormed("p && && q",              "two ANDs in a row"),
    IllFormed("p || || q",              "two ORs in a row"),
    IllFormed("p <-> <-> q",            "two IFFs in a row"),
    IllFormed("p U & q",                "U then & with no operand"),
    IllFormed("p & | q",                "& then | with no operand"),
    IllFormed("p U S q",                "two binary temporal operators"),

    # juxtaposition / missing operator
    IllFormed("p q",                    "two atoms juxtaposed"),
    IllFormed("p q r",                  "three atoms juxtaposed"),
    IllFormed("(p)(q)",                 "parenthesised atoms juxtaposed"),

    # bad identifiers
    IllFormed("Pq",                     "atom must start lowercase"),
    IllFormed("MyAtom",                 "mixed-case identifier disallowed"),
    IllFormed("123abc",                 "atom cannot start with digit"),
    IllFormed("_p",                     "atom cannot start with underscore"),

    # unknown LaTeX-style commands and stray characters
    IllFormed("\\unknown",              "unknown backslash command"),
    IllFormed("\\foo p",                "unrecognised backslash-name"),
    IllFormed("p @ q",                  "stray @ character"),
    IllFormed("p # q",                  "stray # character"),
    IllFormed("p $ q",                  "stray $ character"),
    IllFormed("p ; q",                  "stray ; character"),
    IllFormed("p . q",                  "stray . character"),
    IllFormed("p , q",                  "stray , character"),

    # arithmetic / non-propositional literals (PLTL has none)
    IllFormed("3 & p",                  "integer literal not allowed"),
    IllFormed("p + q",                  "arithmetic + not allowed"),
    IllFormed("p * q",                  "arithmetic * not allowed"),
    IllFormed("\"str\" & p",            "string literal not allowed"),

    # reserved keywords misused as atoms or in wrong position
    IllFormed("p U release",            "reserved word 'release' as right operand atom"),
    IllFormed("until p",                "reserved word 'until' used as atom"),
    IllFormed("p AND until",            "reserved word 'until' as right operand atom"),
    IllFormed("G & p",                  "unary keyword used as binary"),
    IllFormed("p G q",                  "unary keyword used as binary operator"),

    # trailing/leading operators
    IllFormed("p AND",                  "trailing AND keyword"),
    IllFormed("OR p",                   "leading OR keyword"),
    IllFormed("p ->",                   "trailing arrow"),

    # keyword glued to identifier (word-boundary checks)
    IllFormed("Globallyp",              "capitalised keyword glued to atom"),
    IllFormed("Alwaysp",                "capitalised keyword glued to atom"),
    IllFormed("Eventuallyq",            "capitalised keyword glued to atom"),
    IllFormed("Trueq",                  "boolean glued to atom"),
    IllFormed("p ANDq",                 "ALL-CAPS keyword glued to atom"),
    IllFormed("p ORq",                  "ALL-CAPS keyword glued to atom"),
    IllFormed("p UNTILq",               "ALL-CAPS keyword glued to atom"),
    IllFormed("\\Gfoo",                 "LaTeX command glued to atom"),
    IllFormed("\\Foo",                  "LaTeX-style with unknown name"),
    IllFormed("p \\tofoo",              "LaTeX implies glued to atom"),
    IllFormed("p \\wedgep",             "LaTeX wedge glued to atom"),
    IllFormed("\\Boxp",                 "LaTeX Box glued to atom"),
]


# ── Light vs deep selection ─────────────────────────────────────────────────
# Light is roughly: a representative of each operator spelling + every
# precedence rule + a handful of nested cases. Deep adds the corpus and
# the full spelling matrix.
def _light_spelling() -> list[WellFormed]:
    """One canonical spelling test per operator class."""
    return [
        WellFormed("p", "p"),
        WellFormed("true", "true"),
        WellFormed("False", "false"),
        WellFormed("!p", "!p"),
        WellFormed("NOT p", "!p"),
        WellFormed("p & q", "(p & q)"),
        WellFormed("p AND q", "(p & q)"),
        WellFormed("p | q", "(p | q)"),
        WellFormed("p OR q", "(p | q)"),
        WellFormed("p -> q", "(p -> q)"),
        WellFormed("p IMPLIES q", "(p -> q)"),
        WellFormed("p <-> q", "(p <-> q)"),
        WellFormed("G p", "G p"),
        WellFormed("[] p", "G p"),
        WellFormed("F p", "F p"),
        WellFormed("<> p", "F p"),
        WellFormed("X p", "X p"),
        WellFormed("Y p", "Y p"),
        WellFormed("O p", "O p"),
        WellFormed("H p", "H p"),
        WellFormed("p U q", "(p U q)"),
        WellFormed("p S q", "(p S q)"),
        WellFormed("p W q", "(p W q)"),
        WellFormed("p R q", "(p R q)"),
        WellFormed("p T q", "(p T q)"),
    ]


def well_formed_for(mode: str) -> list[WellFormed]:
    if mode == "light":
        return _light_spelling() + PRECEDENCE_TESTS[:6] + COMPOSED_TESTS[:5]
    # deep
    return SPELLING_TESTS + PRECEDENCE_TESTS + COMPOSED_TESTS + CORPUS_TESTS


def ill_formed_for(mode: str) -> list[IllFormed]:
    return ILL_FORMED[:10] if mode == "light" else ILL_FORMED


# ── Runner ──────────────────────────────────────────────────────────────────
def color(s: str, c: str) -> str:
    codes = {"red": 31, "green": 32, "yellow": 33, "cyan": 36, "grey": 90}
    return f"\033[{codes[c]}m{s}\033[0m" if sys.stdout.isatty() else s


def run_well_formed(t: WellFormed) -> tuple[bool, str]:
    try:
        json1 = parse_to_json(t.formula)
        pretty = pretty_via_rust(t.formula)
        json2 = parse_to_json(pretty)
        if json1 != json2:
            return False, (
                f"round-trip failed: AST changed after pretty-print\n"
                f"     before: {json1}\n     after:  {json2}"
            )
        if t.canonical is not None and pretty != t.canonical:
            return False, (
                f"canonical mismatch\n"
                f"     expected: {t.canonical!r}\n     got:      {pretty!r}"
            )
        return True, pretty
    except subprocess.CalledProcessError as e:
        return False, f"subprocess failed: {e.stderr.strip()}"


def run_ill_formed(t: IllFormed) -> tuple[bool, str]:
    if ocaml_parse_fails(t.formula):
        return True, t.reason
    return False, f"expected parse failure ({t.reason}) but parser accepted it"


def main() -> int:
    ap = argparse.ArgumentParser(description="PLTL end-to-end test runner.")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--light", action="store_true",
                     help="Run a short smoke set (~30 tests).")
    grp.add_argument("--deep", action="store_true",
                     help="Run the full suite including the real-world corpus (default).")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print each test's pretty-printed result.")
    args = ap.parse_args()

    mode = "light" if args.light else "deep"

    if not OCAML.exists():
        print(color(f"OCaml parser not built at {OCAML}", "red"))
        print("Run:  (cd ocaml && dune build)")
        return 2
    if not RUST.exists():
        print(color(f"Rust binary not built at {RUST}", "red"))
        print("Run:  (cd rust && cargo build)")
        return 2

    wf = well_formed_for(mode)
    bad = ill_formed_for(mode)

    print(color(f"=== Well-formed pipeline tests ({mode}, {len(wf)} cases) ===", "cyan"))
    print()
    wf_pass = wf_fail = 0
    failures = []
    for i, t in enumerate(wf, start=1):
        ok, msg = run_well_formed(t)
        tag = color("✓ PASS", "green") if ok else color("✗ FAIL", "red")
        print(f"  {i:03d}  {tag}  {t.formula!r}")
        if not ok:
            print(color(f"        {msg}", "yellow"))
            failures.append((t.formula, msg))
        elif args.verbose:
            print(color(f"        → {msg}", "grey"))
        if ok:
            wf_pass += 1
        else:
            wf_fail += 1

    print()
    print(color(f"=== Ill-formed parser rejection ({len(bad)} cases) ===", "cyan"))
    print()
    bad_pass = bad_fail = 0
    for i, t in enumerate(bad, start=1):
        ok, msg = run_ill_formed(t)
        tag = color("✓ PASS", "green") if ok else color("✗ FAIL", "red")
        print(f"  {i:03d}  {tag}  {t.formula!r:40s}  ({msg})")
        if ok:
            bad_pass += 1
        else:
            bad_fail += 1

    total_pass = wf_pass + bad_pass
    total_fail = wf_fail + bad_fail
    print()
    print(color("=" * 60, "cyan"))
    print(f"Well-formed:  {wf_pass}/{len(wf)} passed"
          + (f"  ({wf_fail} failed)" if wf_fail else ""))
    print(f"Ill-formed:   {bad_pass}/{len(bad)} rejected as expected"
          + (f"  ({bad_fail} failed)" if bad_fail else ""))
    print(color(
        f"TOTAL: {total_pass} passed, {total_fail} failed",
        "green" if total_fail == 0 else "red"))

    if failures and not args.verbose:
        print()
        print(color("--- Failures (rerun with -v to see all pretty outputs) ---", "yellow"))
        for f, m in failures:
            print(color(f"  {f!r}", "yellow"))
            print(color(f"    {m}", "yellow"))

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
