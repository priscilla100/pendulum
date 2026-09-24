"""AP extractor: happy path, tense-neutral validation, retry, exhaustion, fallback."""

from __future__ import annotations

import json

GOOD = json.dumps({
    "aps": [
        {"name": "req", "nl_fragment": "a request occurs", "polarity": "event"},
        {"name": "ack", "nl_fragment": "an acknowledgment occurs", "polarity": "event"},
    ],
    "open_questions": [],
})

from pendulum.agents.ap_extractor import extract_aps


async def test_happy_path_with_confidence(make_deps):
    deps = make_deps(script=[GOOD])
    result = await extract_aps("after a request, an ack eventually follows", deps)
    assert result.status == "OK"
    assert [m.ap for m in result.ap_nl_mapping_list] == ["req", "ack"]
    assert result.confidence == -0.5  # FakeRouter lnll
    assert deps.router.calls[0]["agent"] == "ap"
    assert deps.router.calls[0]["want_logprobs"] is True


async def test_open_questions_surface_in_message(make_deps):
    payload = json.loads(GOOD)
    payload["open_questions"] = ["is ack the same as reply?"]
    deps = make_deps(script=[json.dumps(payload)])
    result = await extract_aps("x", deps)
    assert result.status == "OK" and "is ack the same as reply?" in result.message


async def test_bad_atom_name_triggers_retry_then_succeeds(make_deps):
    bad = json.dumps({"aps": [{"name": "Req-1", "nl_fragment": "x"}], "open_questions": []})
    deps = make_deps(script=[bad, GOOD])
    result = await extract_aps("x", deps)
    assert result.status == "OK" and len(deps.router.calls) == 2
    # the retry message carries the validation error back to the model
    retry_user = deps.router.calls[1]["messages"][-1]["content"]
    assert "Req-1" in retry_user and "[a-z]" in retry_user


async def test_fenced_json_accepted(make_deps):
    deps = make_deps(script=[f"```json\n{GOOD}\n```"])
    result = await extract_aps("x", deps)
    assert result.status == "OK"


async def test_duplicate_names_rejected_then_exhaustion(make_deps):
    dup = json.dumps({"aps": [
        {"name": "req", "nl_fragment": "a"}, {"name": "req", "nl_fragment": "b"},
    ], "open_questions": []})
    # default max_retries=2 → 3 attempts, all bad → ERROR envelope
    deps = make_deps(script=[dup, dup, dup])
    result = await extract_aps("x", deps)
    assert result.status == "ERROR"
    assert "duplicate atom name" in result.message
    assert result.ap_nl_mapping_list == []


async def test_fallback_uses_orchestrator_model_and_preamble(make_deps):
    deps = make_deps(script=[GOOD])
    result = await extract_aps("x", deps, fallback=True, failure_reason="low confidence (-2.1)")
    assert result.status == "OK"
    call = deps.router.calls[0]
    assert call["agent"] == "orch"
    system = call["messages"][0]["content"]
    assert "ESCALATION CONTEXT" in system and "low confidence (-2.1)" in system
    assert "TENSE NEUTRALITY" in system  # full extractor prompt still included
