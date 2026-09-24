"""Render a run's JSONL log as a human-readable execution trace.

`python -m pendulum trace [run-id-or-path]` — no argument means the newest
run. Shows, in order with relative timestamps: proposition extraction, each
agent's candidates, every MCP tool call with its arguments and result (debug-
level runs), retrieval, filter decisions, verdicts, feedback rounds, the
final ranking, and errors. Pure rendering — reads the log, changes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional

from pendulum.config import PendulumConfig


class TraceError(Exception):
    """Log file missing/empty or run id unresolvable."""


def resolve_log_path(spec: Optional[str], config: PendulumConfig) -> Path:
    """None → newest .jsonl in the log dir; else run id or explicit path."""
    if spec:
        direct = Path(spec)
        if direct.exists():
            return direct
        candidate = config.log_dir / f"{spec}.jsonl"
        if candidate.exists():
            return candidate
        raise TraceError(f"no log found for {spec!r} (looked at {direct} and {candidate})")
    logs = sorted(config.log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise TraceError(f"no run logs in {config.log_dir}")
    return logs[-1]


def _compact(value: Any, limit: int = 200) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: event -> (glyph, fields to show). Unlisted events fall back to all fields.
_RENDERERS: dict[str, tuple[str, list[str]]] = {
    "run_started": ("▶", ["nl", "preset_aps"]),
    "preset_aps_used": ("◆", ["atoms"]),
    "aps_extracted": ("◆", ["atoms", "confidence", "open_questions"]),
    "extraction_failed": ("✗", ["error"]),
    "patterns_retrieved": ("⌕", ["ids", "scores"]),
    "reference_retrieved": ("⌕", ["sections"]),
    "reserved_atoms_mangled": ("~", ["renames"]),
    "tool_call": ("→", ["tool", "args"]),
    "tool_result": ("←", ["tool", "result"]),
    "cache_hit": ("↩", ["tool", "args"]),
    "json_completion": ("🗩", ["attempt", "lnll", "text"]),
    "completion": ("🗩", ["agent", "backend", "model", "lnll"]),
    "candidates": ("＋", ["formulas", "attempt"]),
    "compile_failed_retrying": ("✗", ["attempt", "error"]),
    "kept": ("⚖", ["ids", "reasoning"]),
    "compare_merge": ("≡", ["kept", "merged"]),
    "verdict": ("✓", ["candidate", "verdict", "confidence", "evidence"]),
    "feedback_round_triggered": ("↻", ["round"]),
    "final_ranking": ("★", ["formulas", "reasoning"]),
    "best_guess_emitted": ("★", ["candidates", "reasoning"]),
    "survivors_appended": ("＋", ["ids"]),
    "run_finished": ("■", ["status", "formulas", "errors", "stages"]),
    "node_timeout": ("⏱", ["timeout_s"]),
    "node_crashed": ("✗", ["error"]),
}


def iter_trace_lines(log_path: Path) -> Iterator[str]:
    try:
        raw_lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TraceError(f"cannot read {log_path}: {exc}") from exc

    t0: Optional[float] = None
    prev: Optional[float] = None
    yield f"trace: {log_path.name}"
    for raw in raw_lines:
        try:
            event = json.loads(raw)
        except ValueError:
            continue  # tolerate torn/partial lines from live runs
        if not isinstance(event, dict):
            continue  # a bare JSON scalar/array is not an event (codex audit)
        ts = event.get("ts")
        if t0 is None and isinstance(ts, (int, float)):
            t0 = ts
        if isinstance(ts, (int, float)) and t0 is not None:
            # offset from run start + Δ since the previous event = how long
            # the step that ENDED at this event took
            delta = f"Δ{ts - prev:6.1f}s" if prev is not None else "        "
            offset = f"+{ts - t0:7.1f}s {delta}"
            prev = ts
        else:
            offset = " " * 18
        stage = str(event.get("stage", "?"))
        name = str(event.get("event", "?"))
        glyph, fields = _RENDERERS.get(name, ("·", []))
        payload = {k: v for k, v in event.items() if k not in ("ts", "level", "stage", "event")}
        if fields:
            shown = {k: payload[k] for k in fields if k in payload}
            extra = ""
        else:
            shown, extra = payload, ""
        details = "  ".join(f"{k}={_compact(v)}" for k, v in shown.items())
        yield f"{offset} {glyph} {stage:<14} {name:<28} {details}{extra}"
    if t0 is None:
        raise TraceError(f"{log_path} contains no parseable events")


def render_trace(spec: Optional[str], config: Optional[PendulumConfig] = None) -> str:
    config = config or PendulumConfig.from_env()
    return "\n".join(iter_trace_lines(resolve_log_path(spec, config)))
