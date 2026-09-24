"""Robust extraction of structured content from LLM completions.

Local models routinely wrap JSON in code fences or prose despite
instructions; these helpers recover the payload or fail with a message
suitable for feeding back to the model (the retry loops do exactly that).
"""

from __future__ import annotations

import json
import re
from typing import Any

ATOM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ExtractionError(ValueError):
    """Completion did not contain the expected structure; str() is the
    model-facing explanation."""


def strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def extract_json_object(text: str) -> dict[str, Any]:
    """Find and parse the first balanced JSON object in the completion."""
    text = strip_code_fences(text)
    start = text.find("{")
    if start == -1:
        raise ExtractionError("no JSON object found in your reply — output only the JSON object")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                except ValueError as exc:
                    raise ExtractionError(f"reply looked like JSON but failed to parse: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise ExtractionError("expected a JSON object, got a different JSON value")
                return parsed
    raise ExtractionError("JSON object in your reply is unbalanced (missing closing brace)")


def extract_assignment_lines(text: str, variable: str = "formulaToFind") -> list[str]:
    """All `<variable> = <expr>` lines from a completion, fences stripped."""
    text = strip_code_fences(text)
    pattern = re.compile(rf"^\s*{re.escape(variable)}\s*=\s*(.+?)\s*$")
    lines = [m.group(1) for line in text.splitlines() if (m := pattern.match(line))]
    if not lines:
        raise ExtractionError(
            f"no line of the form `{variable} = <expression>` found — "
            f"output exactly that form, nothing else"
        )
    return lines
