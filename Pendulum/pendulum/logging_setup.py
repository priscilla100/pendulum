"""Run logging: structured JSONL per run + console, with selectable verbosity.

Every pipeline event goes through a `RunLogger`. An event has a level
(debug|info|warning|error), a stage, an event name and arbitrary JSON fields.
Events at or above `PENDULUM_LOG_LEVEL` are written to
`logs/<run_id>.jsonl` (full JSON, machine-readable) and mirrored to the
`pendulum` stdlib logger (compact line, human-readable). Debug level captures
everything, including prompts, raw completions and tool-cache hits.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}

_console = logging.getLogger("pendulum")


def _ensure_console_handler(level: str) -> None:
    if not _console.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        _console.addHandler(handler)
    _console.setLevel(_LEVELS[level])


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


class RunLogger:
    """One instance per pipeline run; safe to pass around freely."""

    def __init__(self, log_dir: Path, level: str = "info", run_id: Optional[str] = None):
        if level not in _LEVELS:
            raise ValueError(f"unknown log level {level!r}")
        self.run_id = run_id or new_run_id()
        self.level = level
        self._threshold = _LEVELS[level]
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{self.run_id}.jsonl"
        _ensure_console_handler(level)

    def event(self, level: str, stage: str, event: str, **fields: Any) -> None:
        """Record one event. `fields` must be JSON-serializable."""
        numeric = _LEVELS.get(level)
        if numeric is None:
            raise ValueError(f"unknown log level {level!r}")
        if numeric < self._threshold:
            return
        record = {"ts": time.time(), "level": level, "stage": stage, "event": event, **fields}
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            line = json.dumps({**record, **{k: repr(v) for k, v in fields.items()}}, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        summary = ", ".join(f"{k}={_truncate(v)}" for k, v in fields.items())
        _console.log(numeric, "[%s] %s %s%s", self.run_id, stage, event, f" ({summary})" if summary else "")

    # Convenience wrappers so call sites read naturally.

    def debug(self, stage: str, event: str, **fields: Any) -> None:
        self.event("debug", stage, event, **fields)

    def info(self, stage: str, event: str, **fields: Any) -> None:
        self.event("info", stage, event, **fields)

    def warning(self, stage: str, event: str, **fields: Any) -> None:
        self.event("warning", stage, event, **fields)

    def error(self, stage: str, event: str, **fields: Any) -> None:
        self.event("error", stage, event, **fields)


def _truncate(value: Any, limit: int = 120) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
