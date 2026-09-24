"""Safe evaluation of the PYTHON_TO_LTL agent's constructor expressions.

The coding model returns lines like
    formulaToFind = Always(LImplies(AtomicProposition("req"), Eventually(AtomicProposition("ack"))))
This module turns that expression into canonical LTL surface syntax WITHOUT
executing any Python: the string is parsed with `ast` and only whitelisted
constructor Calls over string constants are interpreted. Everything else —
names, attributes, operators, comprehensions, dunder tricks — is rejected with
a message written for the model (the retry loop feeds it back verbatim).
"""

from __future__ import annotations

import ast
from typing import Optional

from pendulum.agents.parsing import ATOM_NAME_RE

_UNARY = {
    "LNot": "!",
    "Next": "X",
    "Always": "G",
    "Eventually": "F",
    "Once": "O",
    "Historically": "H",
    "Yesterday": "Y",
}
_BINARY = {
    "LAnd": "&",
    "LOr": "|",
    "LImplies": "->",
    "LEquiv": "<->",
    "Until": "U",
    "WeakUntil": "W",
    "Since": "S",
}
CONSTRUCTORS = set(_UNARY) | set(_BINARY) | {"AtomicProposition", "Literal"}


class PythonAstError(ValueError):
    """Expression rejected; str() is the model-facing explanation."""


def eval_formula_expr(expr: str, allowed_atoms: Optional[set[str]] = None) -> str:
    """Constructor expression → canonical LTL surface string."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise PythonAstError(f"not valid Python syntax: {exc.msg}") from exc
    return _convert(tree.body, allowed_atoms)


def _convert(node: ast.expr, allowed_atoms: Optional[set[str]]) -> str:
    if not isinstance(node, ast.Call):
        raise PythonAstError(
            f"only constructor calls are allowed, found {type(node).__name__} — "
            f"do not use Python operators (and/or/not/&/|); compose constructors instead"
        )
    if not isinstance(node.func, ast.Name):
        raise PythonAstError("constructor must be a bare name like Always(...), no attributes/lambdas")
    name = node.func.id
    if name not in CONSTRUCTORS:
        raise PythonAstError(f"unknown constructor {name!r} — use only: {', '.join(sorted(CONSTRUCTORS))}")
    if node.keywords:
        raise PythonAstError(f"{name}: keyword arguments are not allowed, use positional")

    if name == "AtomicProposition":
        atom = _string_arg(node, name)
        if not ATOM_NAME_RE.match(atom):
            raise PythonAstError(f"atom name {atom!r} must match [a-z][a-z0-9_]*")
        if allowed_atoms is not None and atom not in allowed_atoms:
            raise PythonAstError(
                f"atom {atom!r} is not in the provided mapping — use only: {', '.join(sorted(allowed_atoms))}"
            )
        return atom

    if name == "Literal":
        value = _string_arg(node, name).lower()
        if value not in ("true", "false"):
            raise PythonAstError(f'Literal takes "True" or "False", got {value!r}')
        return value

    if name in _UNARY:
        if len(node.args) != 1:
            raise PythonAstError(f"{name} takes exactly 1 argument, got {len(node.args)}")
        return f"{_UNARY[name]} {_convert(node.args[0], allowed_atoms)}"

    # binary
    if len(node.args) != 2:
        raise PythonAstError(f"{name} takes exactly 2 arguments, got {len(node.args)}")
    left = _convert(node.args[0], allowed_atoms)
    right = _convert(node.args[1], allowed_atoms)
    return f"({left} {_BINARY[name]} {right})"


def _string_arg(node: ast.Call, name: str) -> str:
    if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        raise PythonAstError(f'{name} takes exactly one string literal argument, e.g. {name}("req")')
    return node.args[0].value
