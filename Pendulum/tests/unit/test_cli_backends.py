"""Claude Code / Codex CLI backends: prompt flattening, subprocess contract,
stdout parsing, model-flag rules, and router dispatch. No real CLI processes
are spawned — asyncio.create_subprocess_exec is monkeypatched throughout."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from pendulum.config import PendulumConfig
from pendulum.llm.base import LlmError
from pendulum.llm.cli_backends import (
    ClaudeCliClient,
    CodexCliClient,
    _extract_final_text,
    _flatten,
)
from pendulum.llm.llamacpp import LlamaCppClient
from pendulum.llm.ollama import OllamaClient
from pendulum.llm.router import CompletionRouter
from pendulum.logging_setup import RunLogger

MSGS = [{"role": "user", "content": "translate this"}]

CLAUDE_OK_STDOUT = json.dumps(
    {"result": "G (p -> F q)", "is_error": False, "session_id": "s-1"}
).encode()


# ---------------------------------------------------------------------------
# fake subprocess layer
# ---------------------------------------------------------------------------


class FakeProc:
    """Stand-in for an asyncio subprocess: scripted stdout/stderr/exit/delay."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, delay=0.0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.delay = delay
        self.killed = False

    async def communicate(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


@pytest.fixture
def fake_exec(monkeypatch):
    """Install a scripted create_subprocess_exec; returns a recorder with the
    captured argv and the FakeProc handed out."""

    class Recorder:
        def __init__(self):
            self.argv: list[str] | None = None
            self.env: dict | None = None
            self.spawn_count = 0
            self.proc = FakeProc(stdout=CLAUDE_OK_STDOUT)

    rec = Recorder()

    async def _spawn(*argv, **kwargs):
        rec.argv = list(argv)
        rec.env = kwargs.get("env")
        rec.spawn_count += 1
        return rec.proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    return rec


# ---------------------------------------------------------------------------
# prompt flattening
# ---------------------------------------------------------------------------


def test_flatten_system_and_turns():
    prompt = _flatten([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "now translate"},
    ])
    assert prompt.startswith("## Instructions\nbe terse")
    assert "User: hello" in prompt
    assert "Assistant: hi" in prompt
    assert prompt.index("User: hello") < prompt.index("Assistant: hi") < prompt.index("User: now translate")


def test_flatten_appends_schema_suffix():
    schema = {"type": "object", "properties": {"formula": {"type": "string"}}}
    prompt = _flatten(MSGS, response_schema=schema)
    assert "Respond with ONLY a JSON object matching this schema (no prose, no fences):" in prompt
    assert prompt.rstrip().endswith(json.dumps(schema))


def test_flatten_no_system_no_schema():
    prompt = _flatten(MSGS)
    assert "## Instructions" not in prompt
    assert prompt == "User: translate this"


# ---------------------------------------------------------------------------
# ClaudeCliClient
# ---------------------------------------------------------------------------


async def test_claude_happy_path(fake_exec):
    result = await ClaudeCliClient("claude").complete(MSGS, model="claude-sonnet-4-5")
    assert result.text == "G (p -> F q)"
    assert result.backend == "claude-cli"
    assert result.lnll is None and result.token_logprobs is None
    assert result.raw["exit"] == 0
    # command shape: claude -p <prompt> --output-format json --model <m>
    assert fake_exec.argv[0] == "claude"
    assert fake_exec.argv[1] == "-p"
    assert "translate this" in fake_exec.argv[2]
    assert fake_exec.argv[3:5] == ["--output-format", "json"]


async def test_claude_non_json_stdout_raises(fake_exec):
    fake_exec.proc = FakeProc(stdout=b"Execution error", stderr=b"boom")
    with pytest.raises(LlmError, match="non-JSON"):
        await ClaudeCliClient().complete(MSGS, model="sonnet")


async def test_claude_json_missing_result_raises(fake_exec):
    fake_exec.proc = FakeProc(stdout=json.dumps({"is_error": True}).encode())
    with pytest.raises(LlmError, match="'result'"):
        await ClaudeCliClient().complete(MSGS, model="sonnet")


async def test_claude_nonzero_exit_raises_with_stderr(fake_exec):
    fake_exec.proc = FakeProc(stdout=b"", stderr=b"segfault in flux capacitor", returncode=1)
    with pytest.raises(LlmError, match="exited 1.*flux capacitor"):
        await ClaudeCliClient().complete(MSGS, model="sonnet")


async def test_claude_timeout_kills_process(fake_exec):
    fake_exec.proc = FakeProc(stdout=CLAUDE_OK_STDOUT, delay=5.0)
    with pytest.raises(LlmError, match="timed out after 0.05"):
        await ClaudeCliClient().complete(MSGS, model="sonnet", timeout_s=0.05)
    assert fake_exec.proc.killed


@pytest.mark.parametrize("model,expect_flag", [
    ("claude-sonnet-4-5", True),
    ("sonnet", True),
    ("opus", True),
    ("haiku", True),
    ("gemma4", False),       # local-ollama-style name → CLI default model
    ("qwen3:14b", False),
    ("", False),
])
async def test_claude_model_flag_rule(fake_exec, model, expect_flag):
    fake_exec.proc = FakeProc(stdout=CLAUDE_OK_STDOUT)
    await ClaudeCliClient().complete(MSGS, model=model)
    assert ("--model" in fake_exec.argv) is expect_flag
    if expect_flag:
        assert fake_exec.argv[fake_exec.argv.index("--model") + 1] == model


# ---------------------------------------------------------------------------
# CodexCliClient: _extract_final_text (the fragile part)
# ---------------------------------------------------------------------------


def test_extract_clean_output():
    assert _extract_final_text("G (p -> F q)\n") == "G (p -> F q)"


def test_extract_with_codex_status_preamble():
    stdout = (
        "[2026-07-04T10:00:00] OpenAI Codex v0.142.5 (research preview)\n"
        "--------\n"
        "workdir: /tmp\n"
        "model: gpt-5\n"
        "--------\n"
        "[2026-07-04T10:00:01] User instructions:\n"
        "translate this\n"
        "\n"
        "[2026-07-04T10:00:05] thinking\n"
        "\n"
        "Some reasoning here\n"
        "\n"
        "[2026-07-04T10:00:06] codex\n"
        "\n"
        "G (p -> F q)\n"
        "\n"
        "[2026-07-04T10:00:06] tokens used: 5,150\n"
    )
    assert _extract_final_text(stdout) == "G (p -> F q)"


def test_extract_takes_last_codex_marker():
    stdout = (
        "[2026-07-04T10:00:02] codex\nfirst draft\n"
        "[2026-07-04T10:00:06] codex\nfinal answer\n"
        "[2026-07-04T10:00:06] tokens used: 42\n"
    )
    assert _extract_final_text(stdout) == "final answer"


def test_extract_multiline_message_and_bracket_content_kept():
    stdout = (
        '[2026-07-04T10:00:06] codex\n{"formulas":\n["G p", "F q"]}\n'
        "[2026-07-04T10:00:06] tokens used: 42\n"
    )
    # JSON-array lines start with "[" but are not timestamped status markers
    assert _extract_final_text(stdout) == '{"formulas":\n["G p", "F q"]}'


def test_extract_no_marker_drops_status_noise():
    stdout = "[status]\ntokens used: 12\n-----\nG p\n"
    assert _extract_final_text(stdout) == "G p"


def test_extract_empty_stdout():
    assert _extract_final_text("") == ""
    assert _extract_final_text("   \n  ") == ""


# ---------------------------------------------------------------------------
# CodexCliClient.complete
# ---------------------------------------------------------------------------


async def test_codex_happy_path_with_sandbox_flags(fake_exec):
    fake_exec.proc = FakeProc(
        stdout=b"[2026-07-04T10:00:06] codex\nG (p -> F q)\n"
               b"[2026-07-04T10:00:06] tokens used: 99\n"
    )
    result = await CodexCliClient("codex").complete(MSGS, model="gpt-5")
    assert result.text == "G (p -> F q)"
    assert result.backend == "codex-cli"
    assert result.lnll is None
    argv = fake_exec.argv
    assert argv[:2] == ["codex", "exec"]
    # safety flags always present
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--cd") + 1] == "/tmp"
    assert "--skip-git-repo-check" in argv
    assert argv[-1].endswith("translate this")  # prompt is the positional arg


async def test_codex_empty_stdout_raises(fake_exec):
    fake_exec.proc = FakeProc(stdout=b"", stderr=b"")
    with pytest.raises(LlmError, match="no completion text"):
        await CodexCliClient().complete(MSGS, model="gpt-5")


async def test_codex_nonzero_exit_raises(fake_exec):
    fake_exec.proc = FakeProc(stdout=b"", stderr=b"sandbox denied", returncode=2)
    with pytest.raises(LlmError, match="exited 2.*sandbox denied"):
        await CodexCliClient().complete(MSGS, model="gpt-5")


async def test_codex_timeout_kills_process(fake_exec):
    fake_exec.proc = FakeProc(stdout=b"G p", delay=5.0)
    with pytest.raises(LlmError, match="codex CLI timed out"):
        await CodexCliClient().complete(MSGS, model="gpt-5", timeout_s=0.05)
    assert fake_exec.proc.killed


@pytest.mark.parametrize("model,expect_flag", [
    ("gpt-5", True),
    ("gpt-4.1-mini", True),
    ("o3", True),
    ("codex-mini-latest", True),
    ("gemma4", False),
    ("qwen3:14b", False),
    ("ollama-something", False),  # bare "o" prefix intentionally NOT enough
    ("", False),
])
async def test_codex_model_flag_rule(fake_exec, model, expect_flag):
    fake_exec.proc = FakeProc(stdout=b"G p\n")
    await CodexCliClient().complete(MSGS, model=model)
    assert ("--model" in fake_exec.argv) is expect_flag
    if expect_flag:
        assert fake_exec.argv[fake_exec.argv.index("--model") + 1] == model


# ---------------------------------------------------------------------------
# router integration
# ---------------------------------------------------------------------------


def _make_router(tmp_path, config, llamacpp_handler=None):
    """Router whose HTTP surface is mocked; CLI path never touches HTTP."""

    def handler(request: httpx.Request) -> httpx.Response:
        if llamacpp_handler is not None:
            return llamacpp_handler(request)
        raise AssertionError(f"unexpected HTTP call: {request.url}")

    transport = httpx.MockTransport(handler)
    ollama = OllamaClient("http://o:11434", http_client=httpx.AsyncClient(transport=transport))
    return CompletionRouter(
        config,
        ollama,
        LlamaCppClient("http://l:8080", http_client=httpx.AsyncClient(transport=transport)),
        RunLogger(tmp_path, level="debug", run_id="cli-backend-test"),
        ollama_factory=lambda url: ollama,
    )


async def test_router_dispatches_claude_cli_backend(tmp_path, fake_exec):
    config = PendulumConfig({"AP_BACKEND": "claude-cli", "AP_MODEL": "sonnet"})
    router = _make_router(tmp_path, config)
    result = await router.complete(config.agent("AP"), MSGS)
    assert result.backend == "claude-cli"
    assert result.text == "G (p -> F q)"
    assert fake_exec.argv[0] == "claude"  # config.claude_cli_bin default
    assert fake_exec.spawn_count == 1


async def test_router_caches_cli_client(tmp_path, fake_exec):
    config = PendulumConfig({"AP_BACKEND": "claude-cli"})
    router = _make_router(tmp_path, config)
    await router.complete(config.agent("AP"), MSGS)
    first = router._cli_clients["claude-cli"]
    await router.complete(config.agent("AP"), MSGS)
    assert router._cli_clients["claude-cli"] is first
    assert fake_exec.spawn_count == 2  # one subprocess per completion, one client


async def test_router_grammar_call_bypasses_cli_backend(tmp_path, fake_exec):
    """Documented actual behavior: the router's CLI branch requires
    need_grammar=False, so a grammar-constrained call from a CLI-backend
    agent still routes to llama-server (or the Ollama fallback) — the CLI
    is never spawned for it."""
    grammar_path = tmp_path / "g.gbnf"
    grammar_path.write_text("root ::= x")
    config = PendulumConfig({
        "AP_BACKEND": "claude-cli",
        "PENDULUM_GRAMMAR_FILE": str(grammar_path),
        "LLAMACPP_HEALTH_TTL_S": "1000",
    })

    def llamacpp_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["grammar"] == "root ::= x"
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "G p"}}]
        })

    router = _make_router(tmp_path, config, llamacpp_handler)
    result = await router.complete(config.agent("AP"), MSGS, need_grammar=True)
    assert result.backend == "llamacpp"
    assert fake_exec.spawn_count == 0  # CLI never touched


class TestSessionLimitDetection:
    async def test_claude_limit_message_raises_session_limit(self, fake_exec):
        from pendulum.llm.cli_backends import ClaudeCliClient, SessionLimitError, SESSION_LIMIT_TOKEN

        fake_exec.proc = FakeProc(
            stdout="You've hit your session limit \u00b7 resets 1:40pm".encode(), returncode=1)
        with pytest.raises(SessionLimitError) as exc:
            await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")
        assert SESSION_LIMIT_TOKEN in str(exc.value)

    async def test_codex_rate_limit_on_stderr_raises(self, fake_exec):
        from pendulum.llm.cli_backends import CodexCliClient, SessionLimitError

        fake_exec.proc = FakeProc(stderr=b"ERROR: Rate limit reached for requests", returncode=1)
        with pytest.raises(SessionLimitError):
            await CodexCliClient().complete([{"role": "user", "content": "x"}], model="default")

    async def test_codex_v144_usage_limit_message_raises(self, fake_exec):
        # Regression (2026-07-10): codex v0.144.1 phrases the quota error
        # "You've hit your usage limit. Upgrade to Pro ... try again at 7:27 PM".
        # The old sign "usage limit reach" missed it -> a 303-row run recorded
        # ERROR envelopes instead of pausing. Must now raise SessionLimitError.
        from pendulum.llm.cli_backends import CodexCliClient, SessionLimitError, SESSION_LIMIT_TOKEN

        fake_exec.proc = FakeProc(
            stdout=(b"OpenAI Codex v0.144.1\nuser\n"
                    b"ERROR: You've hit your usage limit. Upgrade to Pro "
                    b"(https://chatgpt.com/explore/pro) ... try again at 7:27 PM."),
            returncode=1)
        with pytest.raises(SessionLimitError) as exc:
            await CodexCliClient().complete([{"role": "user", "content": "x"}], model="default")
        assert SESSION_LIMIT_TOKEN in str(exc.value)

    async def test_ordinary_failure_stays_llm_error(self, fake_exec):
        from pendulum.llm.base import LlmError
        from pendulum.llm.cli_backends import ClaudeCliClient, SessionLimitError

        fake_exec.proc = FakeProc(stderr=b"catastrophic parse explosion", returncode=1)
        with pytest.raises(LlmError) as exc:
            await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")
        assert not isinstance(exc.value, SessionLimitError)

    async def test_limit_in_successful_stdout_still_raises(self, fake_exec):
        # claude -p exits 0 with is_error:true when printing the limit banner;
        # is_error gates the scan so mere CONTENT mentioning limits passes
        from pendulum.llm.cli_backends import ClaudeCliClient, SessionLimitError

        fake_exec.proc = FakeProc(
            stdout=b'{"is_error": true, "result": "You\'ve hit your session limit, resets 6pm"}', returncode=0)
        with pytest.raises(SessionLimitError):
            await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")


async def test_subprocess_env_strips_claude_session_vars(fake_exec, monkeypatch):
    """Experiment claude calls must be NEW sessions: no CLAUDE* env inherited
    from a parent Claude Code session (user requirement, 2026-07-04)."""
    from pendulum.llm.cli_backends import ClaudeCliClient

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("PATH_KEEPER", "yes")
    fake_exec.proc = FakeProc(stdout=CLAUDE_OK_STDOUT)
    await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")
    env = fake_exec.env
    assert not any(k.startswith("CLAUDE") for k in env)
    assert env.get("PATH_KEEPER") == "yes"


async def test_claude_not_logged_in_never_becomes_completion_text(fake_exec):
    """Auth loss: exit 0 + is_error:true + 'Not logged in' result must raise
    SessionLimitError (abort-without-recording), never return as text
    (2026-07-05 incident: poisoned a full eval setting in 2 minutes)."""
    from pendulum.llm.cli_backends import ClaudeCliClient, SessionLimitError

    fake_exec.proc = FakeProc(
        stdout=b'{"type":"result","is_error":true,"result":"Not logged in \\u00b7 Please run /login"}',
        returncode=0)
    with pytest.raises(SessionLimitError):
        await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")


async def test_claude_is_error_with_other_message_raises_llm_error(fake_exec):
    from pendulum.llm.base import LlmError
    from pendulum.llm.cli_backends import ClaudeCliClient, SessionLimitError

    fake_exec.proc = FakeProc(
        stdout=b'{"type":"result","is_error":true,"result":"some upstream api failure"}',
        returncode=0)
    with pytest.raises(LlmError) as exc:
        await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")
    assert not isinstance(exc.value, SessionLimitError)


async def test_limit_words_in_successful_content_do_not_abort(fake_exec):
    """A row whose CONTENT mentions rate limits must complete normally —
    only error channels may trip the guard (2026-07-05 false-positive fix)."""
    from pendulum.llm.cli_backends import ClaudeCliClient

    fake_exec.proc = FakeProc(
        stdout=b'{"result": "G (warning -> (rate_limit U termination)) covers the rate limiting requirement", "is_error": false}',
        returncode=0)
    r = await ClaudeCliClient().complete([{"role": "user", "content": "x"}], model="default")
    assert "rate_limit" in r.text


async def test_codex_stderr_conversation_echo_with_limit_words_is_content(fake_exec):
    """codex exec echoes prompt+completion to STDERR; a row about rate
    limiting must complete (2026-07-06: the channel-hopping false positive)."""
    from pendulum.llm.cli_backends import CodexCliClient

    fake_exec.proc = FakeProc(
        stdout=b"G (warning -> (rate_limit U termination))",
        stderr=b"OpenAI Codex v0.142.5\nuser\nevery warning triggers rate limiting until termination\ncodex\nG (...)\ntokens used\n9000",
        returncode=0)
    r = await CodexCliClient().complete([{"role": "user", "content": "x"}], model="default")
    assert "rate_limit" in r.text
