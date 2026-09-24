You are a teacher who is proficient in propositional linear temporal logic (LTL) and Python. You are given the following Python class structure that defines how LTL formulas should be represented:

```python
from dataclasses import dataclass
from typing import *

class Formula:
    pass

@dataclass
class AtomicProposition(Formula):
    name : str

@dataclass
class Literal(Formula):
    name : str

@dataclass
class LNot(Formula):
    Formula: Formula

@dataclass
class LAnd(Formula):
    left: Formula
    right: Formula

@dataclass
class LOr(Formula):
    left: Formula
    right: Formula

@dataclass
class LImplies(Formula):
    left: Formula
    right: Formula

@dataclass
class LEquiv(Formula):
    left: Formula
    right: Formula

@dataclass
class Since(Formula):
    a : Formula
    b : Formula

@dataclass
class Until(Formula):
    a : Formula
    b : Formula

@dataclass
class WeakUntil(Formula):
    a : Formula
    b : Formula

@dataclass
class Next(Formula):
    Formula: Formula

@dataclass
class Always(Formula):
    Formula: Formula

@dataclass
class Eventually(Formula):
    Formula: Formula

@dataclass
class Once(Formula):
    Formula: Formula

@dataclass
class Historically(Formula):
    Formula: Formula

@dataclass
class Yesterday(Formula):
    Formula: Formula
```

These dataclasses are the AST. An LTL formula is built from them by nesting constructors. The semantics is standard propositional LTL with both past and future operators over an infinite trace:

* `AtomicProposition(name)`          — the atomic proposition `name` is true at the current step.
* `Literal("True")` / `Literal("False")` — constants.
* `LNot(f)`                          — `f` is false at the current step.
* `LAnd(a, b)` / `LOr(a, b)`         — boolean composition.
* `LImplies(a, b)`                   — `a` implies `b` at the current step.
* `LEquiv(a, b)`                     — `a` if and only if `b` at the current step.
* `Next(f)`                          — strict next step: `f` holds at position current+1.
* `Always(f)`                        — `f` holds at every step from the current step onwards (reflexive).
* `Eventually(f)`                    — `f` holds at the current step or some future step (reflexive).
* `Until(a, b)`                      — there is a future step where `b` holds; `a` holds at every step from now up to but not including that step. `b` is GUARANTEED to occur.
* `WeakUntil(a, b)`                  — like Until, but `b` is not guaranteed: either `Until(a, b)`, or `a` holds forever.
* `Yesterday(f)`                     — at the previous step, `f` holds. False at the initial step (strong Y).
* `Once(f)`                          — `f` holds at the current step or some past step (reflexive).
* `Historically(f)`                  — `f` holds at every past step including the current step (reflexive).
* `Since(a, b)`                      — `b` held at some past step (current or earlier); at every step strictly between that past step and now, `a` has held.

Your task: given a natural-language requirement and a mapping from NL fragments to atomic-proposition variable names, write Python expressions that build the AST node representing the formula. Assign each to the variable `formulaToFind`.

CONSTRAINTS — read carefully:

1. You MUST use ONLY the Python class constructors listed above. Do not invent constructor names. Do not use Python operators (`and`, `or`, `not`, `&`, `|`, etc.) — they are NOT valid in the AST representation. Only constructor calls compose.
2. The `AtomicProposition` constructor takes a SINGLE string argument: the atom name from the mapping. Atom names are lowercase identifiers matching `[a-z][a-z0-9_]*`.
3. You MUST only use the atom names provided in the Atomic Propositions mapping. Do NOT invent new atoms.
4. TENSE: the atoms are tense-neutral present-tense predicates. Tense in the NL is YOUR job to express with temporal operators: past tense ("played", "occurred") → `Once(...)` / `Yesterday(...)` / `Since(...)`; future ("will open") → `Eventually(...)` / `Next(...)`; "has always" → `Historically(...)`.
5. Output 1 to {MAX_CANDIDATES} lines. Each line MUST be exactly of the form `formulaToFind = <expression>` and represent one complete reading of the requirement. If the NL admits genuinely different formalizations (e.g. strong vs weak until), emit each as its own line, most faithful reading FIRST. No surrounding prose, no markdown code fences, no commentary, no `print(...)`.
6. Common patterns to recognise:
   * "every X is eventually Y" → `Always(LImplies(AtomicProposition("x"), Eventually(AtomicProposition("y"))))`
   * "X only if Y has held"    → `Always(LImplies(AtomicProposition("x"), Once(AtomicProposition("y"))))`
   * "X until Y, Y guaranteed" → `Until(AtomicProposition("x"), AtomicProposition("y"))`
   * "X unless Y / X until possibly Y" → `WeakUntil(AtomicProposition("x"), AtomicProposition("y"))`
   * "X since Y"               → `Since(AtomicProposition("x"), AtomicProposition("y"))`
   * "never X"                 → `Always(LNot(AtomicProposition("x")))`
   * "always X"                → `Always(AtomicProposition("x"))`
   * "X at the very next step" → `Next(AtomicProposition("x"))`
