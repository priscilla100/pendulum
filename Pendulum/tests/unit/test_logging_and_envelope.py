"""logging_setup.py verbosity filtering + envelope helpers."""

from __future__ import annotations

import json

import pytest

from pendulum.agents.envelope import AgentEnvelope, error_envelope, ok_envelope
from pendulum.logging_setup import RunLogger


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestRunLogger:
    def test_writes_jsonl_events(self, tmp_path):
        log = RunLogger(tmp_path, level="info", run_id="t1")
        log.info("extract", "started", nl="p until q")
        log.error("extract", "failed", reason="boom")
        events = read_events(log.path)
        assert [e["event"] for e in events] == ["started", "failed"]
        assert events[0]["stage"] == "extract" and events[0]["nl"] == "p until q"
        assert events[1]["level"] == "error"

    def test_verbosity_filters_below_threshold(self, tmp_path):
        log = RunLogger(tmp_path, level="warning", run_id="t2")
        log.debug("s", "hidden")
        log.info("s", "hidden_too")
        log.warning("s", "kept")
        assert [e["event"] for e in read_events(log.path)] == ["kept"]

    def test_debug_level_captures_everything(self, tmp_path):
        log = RunLogger(tmp_path, level="debug", run_id="t3")
        log.debug("s", "prompt", text="x" * 500)
        events = read_events(log.path)
        assert len(events) == 1 and len(events[0]["text"]) == 500  # file gets full payload

    def test_unserializable_fields_fall_back_to_repr(self, tmp_path):
        log = RunLogger(tmp_path, level="info", run_id="t4")
        log.info("s", "odd", obj=object())
        assert "object" in read_events(log.path)[0]["obj"]

    def test_bad_level_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            RunLogger(tmp_path, level="loud")
        log = RunLogger(tmp_path, level="info", run_id="t5")
        with pytest.raises(ValueError):
            log.event("loud", "s", "e")


class TestEnvelope:
    def test_ok(self):
        env = ok_envelope({"a": 1}, confidence=-0.3, attempts=2)
        assert env.ok and env.payload == {"a": 1} and env.confidence == -0.3

    def test_error_has_no_payload(self):
        env = error_envelope("nope", attempts=3)
        assert not env.ok and env.payload is None and env.attempts == 3

    def test_generic_typing_roundtrip(self):
        env: AgentEnvelope[list[str]] = ok_envelope(["p", "q"])
        assert env.model_dump()["payload"] == ["p", "q"]
