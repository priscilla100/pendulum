"""Prompt loading: every LLM prompt lives in prompts/*.md, editable without
touching code.

Placeholders are `{ALL_CAPS_TOKENS}`. Rendering replaces exactly the provided
keys and then verifies no placeholder tokens remain — a typo'd or forgotten
placeholder fails loudly at call time instead of silently prompting the model
with a literal `{NATURAL_LANGUAGE}`. JSON braces in prompt bodies are safe:
only `{IDENTIFIER}` tokens in ALL-CAPS count as placeholders.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pendulum.config import PENDULUM_ROOT

PROMPTS_DIR = PENDULUM_ROOT / "prompts"

_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


class PromptError(Exception):
    """Missing prompt file or unresolved placeholder."""


@lru_cache(maxsize=64)
def load(name: str) -> str:
    """Raw prompt text of prompts/<name>.md."""
    path = PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"prompt file missing: {path}") from exc


def render(name: str, **substitutions: str) -> str:
    """Load and substitute. All {TOKENS} must be covered by `substitutions`."""
    text = load(name)
    for key, value in substitutions.items():
        token = "{" + key + "}"
        if token not in text:
            raise PromptError(f"prompt {name!r} has no placeholder {token}")
        text = text.replace(token, str(value))
    leftover = _PLACEHOLDER.findall(text)
    if leftover:
        raise PromptError(f"prompt {name!r}: unresolved placeholders {sorted(set(leftover))}")
    return text
