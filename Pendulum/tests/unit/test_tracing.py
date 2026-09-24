"""Trace rendering + MCP args logging (user-requested instrumentation)."""

from __future__ import annotations

import json

import pytest

from pendulum.config import PendulumConfig
from pendulum.tracing import TraceError, iter_trace_lines, render_trace, resolve_log_path


def write_log(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events))


EVENTS = [
    {"ts": 1000.0, "level": "info", "stage": "pipeline", "event": "run_started",
     "nl": "every request is eventually acknowledged", "preset_aps": False},
    {"ts": 1002.5, "level": "info", "stage": "ap_extractor", "event": "aps_extracted",
     "atoms": ["req", "ack"], "confidence": -0.14, "open_questions": []},
    {"ts": 1003.0, "level": "debug", "stage": "mcp", "event": "tool_call",
     "tool": "parse_and_canonicalize", "args": {"formula": "G (req -> F ack)"}},
    {"ts": 1003.2, "level": "debug", "stage": "mcp", "event": "tool_result",
     "tool": "parse_and_canonicalize", "result": {"valid": True, "canonical": "G (req -> F ack)"}},
    {"ts": 1010.0, "level": "info", "stage": "orch_final", "event": "final_ranking",
     "formulas": ["G (req -> F ack)"], "reasoning": "clear winner"},
]


class TestRenderer:
    def test_timeline_offsets_and_fields(self, tmp_path):
        log = tmp_path / "run1.jsonl"
        write_log(log, EVENTS)
        lines = list(iter_trace_lines(log))
        assert lines[0] == "trace: run1.jsonl"
        assert "+    0.0s" in lines[1] and "every request" in lines[1]
        assert "+    2.5s" in lines[2] and "atoms=" in lines[2] and "req" in lines[2]
        assert "Δ   2.5s" in lines[2]  # step duration since previous event
        assert "Δ   0.5s" in lines[3]
        # tool call shows ARGS, result shows payload
        assert "tool_call" in lines[3] and "G (req -> F ack)" in lines[3]
        assert "tool_result" in lines[4] and "canonical" in lines[4]
        assert "final_ranking" in lines[5] and "clear winner" in lines[5]

    def test_unknown_events_render_all_fields(self, tmp_path):
        log = tmp_path / "run2.jsonl"
        write_log(log, [{"ts": 1.0, "level": "info", "stage": "x", "event": "novel_event", "foo": 7}])
        lines = list(iter_trace_lines(log))
        assert "novel_event" in lines[1] and "foo=7" in lines[1]

    def test_torn_lines_tolerated(self, tmp_path):
        log = tmp_path / "run3.jsonl"
        log.write_text(json.dumps(EVENTS[0]) + "\n{torn json...\n" + json.dumps(EVENTS[1]))
        lines = list(iter_trace_lines(log))
        assert len(lines) == 3  # header + 2 events, torn line skipped

    def test_long_fields_truncated(self, tmp_path):
        log = tmp_path / "run4.jsonl"
        write_log(log, [{"ts": 1.0, "level": "debug", "stage": "mcp", "event": "tool_call",
                         "tool": "t", "args": {"x": "y" * 500}}])
        line = list(iter_trace_lines(log))[1]
        assert len(line) < 400 and "…" in line

    def test_empty_or_unparseable_raises(self, tmp_path):
        log = tmp_path / "empty.jsonl"
        log.write_text("not json\nstill not json")
        with pytest.raises(TraceError, match="no parseable events"):
            list(iter_trace_lines(log))


class TestResolution:
    def test_default_is_newest(self, tmp_path):
        cfg = PendulumConfig({"PENDULUM_LOG_DIR": str(tmp_path)})
        import os, time
        old, new = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        write_log(old, EVENTS[:1])
        write_log(new, EVENTS[:1])
        os.utime(old, (time.time() - 100, time.time() - 100))
        assert resolve_log_path(None, cfg) == new

    def test_run_id_and_path_forms(self, tmp_path):
        cfg = PendulumConfig({"PENDULUM_LOG_DIR": str(tmp_path)})
        log = tmp_path / "20260704-run.jsonl"
        write_log(log, EVENTS[:1])
        assert resolve_log_path("20260704-run", cfg) == log
        assert resolve_log_path(str(log), cfg) == log

    def test_unresolvable_raises(self, tmp_path):
        cfg = PendulumConfig({"PENDULUM_LOG_DIR": str(tmp_path)})
        with pytest.raises(TraceError, match="no log found"):
            resolve_log_path("ghost-run", cfg)
        with pytest.raises(TraceError, match="no run logs"):
            resolve_log_path(None, cfg)

    def test_render_trace_end_to_end(self, tmp_path):
        cfg = PendulumConfig({"PENDULUM_LOG_DIR": str(tmp_path)})
        write_log(tmp_path / "r.jsonl", EVENTS)
        out = render_trace(None, cfg)
        assert out.count("\n") == len(EVENTS)


class TestArgsLogging:
    async def test_tool_call_event_carries_args(self, tmp_path):
        from tests.unit.test_mcp_client import FakeToolset, make_mcp

        fake = FakeToolset({"check_equivalence": {"equivalent": True}})
        mcp = make_mcp(tmp_path, fake)
        async with mcp:
            await mcp.call("check_equivalence", {"f1": "G p", "f2": "G (p)"})
            await mcp.call("check_equivalence", {"f1": "G p", "f2": "G (p)"})  # cache hit
        events = [json.loads(l) for l in (tmp_path / "mcp-test.jsonl").read_text().splitlines()]
        calls = [e for e in events if e["event"] == "tool_call"]
        hits = [e for e in events if e["event"] == "cache_hit"]
        assert calls and calls[0]["args"] == {"f1": "G p", "f2": "G (p)"}
        assert hits and hits[0]["args"]["f1"] == "G p"  # cache hits traceable too

    def test_non_dict_json_lines_skipped(self, tmp_path):
        log = tmp_path / "run5.jsonl"
        log.write_text('null\n[]\n"oops"\n123\n' + json.dumps(EVENTS[0]))
        lines = list(iter_trace_lines(log))
        assert len(lines) == 2  # header + the one real event
