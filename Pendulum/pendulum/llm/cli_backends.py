"""Claude Code / Codex CLI completion backends: subprocess per completion.

Both classes implement the `CompletionClient` protocol (pendulum/llm/base.py)
by shelling out to a locally installed agent CLI in non-interactive mode.
They exist so an agent slot can be pointed at a frontier model
(`<PREFIX>_BACKEND=claude-cli|codex-cli`) without any API plumbing — auth and
provider config live in the CLI's own environment/keychain, which is why the
subprocess inherits `os.environ` untouched.

Limitations shared by both backends:

- No token logprobs → `lnll=None` (confidence-gated callers degrade the same
  way as the no-llama-server path).
- No GBNF grammar and no server-side JSON schema enforcement: when a
  `response_schema` is given it is appended to the prompt as an instruction
  and shape errors are left to the caller's validate-and-retry loop.
- `temperature` / `num_ctx` / `max_tokens` / `thinking` are accepted for
  protocol parity and ignored — neither CLI exposes them per invocation.

Flag contracts (verified against the installed binaries on 2026-07-04,
`claude` 2.1.191 / `codex-cli` 0.142.5, via `--help` only — no billable
completion calls were made):

- `claude --help`: `-p, --print` ("Print response and exit"), prompt is a
  positional argument, `--output-format <format>` ("only works with
  --print"; `json` gives a single JSON object whose `result` key holds the
  assistant text), `--model <model>` ("Model for the current session").
- `codex exec --help`: prompt is a positional argument,
  `-m, --model <MODEL>`, `-s, --sandbox <read-only|workspace-write|
  danger-full-access>`, `-C, --cd <DIR>` ("working root"), and
  `--skip-git-repo-check` ("Allow running Codex outside a Git repository" —
  required because we pin `--cd /tmp`, which is not a repo). The final
  assistant message is printed to stdout after timestamped status lines of
  the form `[2026-07-04T...] codex`; `_extract_final_text` parses that.

Safety: Codex is invoked with `--sandbox read-only --cd /tmp` so that, while
acting as a pure completion engine, it can neither write to the repository
nor treat it as its working root.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import re
from typing import Optional

from pendulum.llm.base import CompletionResult, LlmError, Message

#: Stable token embedded in SessionLimitError messages. It survives being
#: stringified into agent envelopes / judge evidence / run logs, letting the
#: eval harness detect a subscription-limit outage and refuse to record the
#: row as done (user-approved guard, 2026-07-04).
SESSION_LIMIT_TOKEN = "PENDULUM_SESSION_LIMIT"

#: Conditions where recording the row would poison the dataset: limits AND
#: auth loss (observed 2026-07-05: CLI logout mid-experiment produced 50 junk
#: rows in minutes). Both mean "abort the row, retry the cell later".
#: NB "usage limit" (not "usage limit reach"): codex v0.144.1 phrases it
#: "You've hit your usage limit. Upgrade to Pro ... try again at 7:27 PM" —
#: the old "...reach" sign missed it and poisoned a 303-row run (2026-07-10).
#: Safe to keep broad because these signs are only scanned on NON-ZERO CLI
#: exit (see _run_cli), never on success output.
_LIMIT_SIGNS = ("hit your session limit", "usage limit", "rate limit",
                "usage_limit", "limit resets", "purchase more credits",
                "not logged in", "please run /login")


class SessionLimitError(LlmError):
    """The CLI provider reported a session/usage/rate limit."""


def _raise_if_limited(label: str, *texts: str) -> None:
    for text in texts:
        low = (text or "").lower()
        if any(sign in low for sign in _LIMIT_SIGNS):
            raise SessionLimitError(
                f"{SESSION_LIMIT_TOKEN}: {label} reported a usage/session limit: "
                f"{text.strip()[:200]}"
            )

_EXCERPT = 300  # chars of stderr/stdout quoted in error messages


def _flatten(messages: list[Message], response_schema: Optional[dict] = None) -> str:
    """Collapse a chat transcript into one prompt string.

    System messages become a single "## Instructions" preamble (in order);
    the remaining turns are labeled by role. If a response schema is given,
    a JSON-only instruction is appended so downstream json.loads has a
    fighting chance without server-side enforcement.
    """
    system = [m["content"] for m in messages if m.get("role") == "system"]
    turns = [m for m in messages if m.get("role") != "system"]

    parts: list[str] = []
    if system:
        parts.append("## Instructions\n" + "\n\n".join(system))
    for m in turns:
        label = m.get("role", "user").capitalize()
        parts.append(f"{label}: {m['content']}")
    prompt = "\n\n".join(parts)
    if response_schema is not None:
        prompt += (
            "\nRespond with ONLY a JSON object matching this schema "
            "(no prose, no fences):\n" + json.dumps(response_schema)
        )
    return prompt


async def _run_cli(
    argv: list[str], timeout_s: float, label: str
) -> tuple[str, str]:
    """Run one CLI invocation; return (stdout, stderr) on exit 0.

    Raises LlmError on spawn failure, wall-clock timeout (the process is
    killed), or non-zero exit (stderr excerpt included).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Strip CLAUDE* vars: when Pendulum itself runs inside a Claude
            # Code session, its children must be brand-new sessions with no
            # linkage to the parent (auth lives in keychain/config, not env).
            env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")},
            # Neutral cwd: `claude -p` treats its cwd as the project and loads
            # that repo's CLAUDE.md/context — observed answering as a repo
            # assistant instead of completing the prompt. Codex gets --cd too.
            cwd=tempfile.gettempdir(),
        )
    except OSError as exc:
        raise LlmError(f"cannot launch {label} ({argv[0]!r}): {exc}") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        # Drain the pipes after kill: a bare wait() can deadlock if the child
        # filled a pipe buffer before dying (codex audit finding).
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), timeout=5)
        raise LlmError(f"{label} timed out after {timeout_s}s") from None

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    # Sign-scan ONLY on process failure. Success-path output must never be
    # scanned: codex echoes the whole conversation (prompt + completion) to
    # STDERR, and claude prints content to stdout — a dataset row about API
    # rate limiting kept masquerading as a provider outage through one
    # channel after the other (2026-07-05/06). Genuine CLI limit errors exit
    # non-zero or set is_error (claude path checks that separately).
    if proc.returncode != 0:
        _raise_if_limited(label, stderr, stdout)
        raise LlmError(
            f"{label} exited {proc.returncode}: {stderr.strip()[:_EXCERPT]}"
        )
    return stdout, stderr


class ClaudeCliClient:
    """Claude Code headless mode: `claude -p <prompt> --output-format json`.

    `--model` is forwarded only when the configured model is plausibly a
    Claude model (one of sonnet/opus/haiku or a `claude-*` id); anything
    else — e.g. a leftover local-Ollama name like `gemma4` — is omitted so
    the CLI falls back to its own default model.
    """

    _CLAUDE_ALIASES = ("sonnet", "opus", "haiku")

    def __init__(self, bin_path: str = "claude"):
        self.bin_path = bin_path

    def _model_args(self, model: str) -> list[str]:
        model = (model or "").strip()
        if model in self._CLAUDE_ALIASES or model.startswith("claude-"):
            return ["--model", model]
        return []

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,  # not exposed by the CLI; ignored
        num_ctx: int = 16384,  # ignored
        max_tokens: int = 2048,  # ignored
        timeout_s: float = 300.0,
        grammar: Optional[str] = None,  # unsupported; ignored
        want_logprobs: bool = False,  # CLI gives no logprobs; ignored
        thinking: bool = False,  # ignored
        response_schema: Optional[dict] = None,
    ) -> CompletionResult:
        prompt = _flatten(messages, response_schema)
        # NO --bare: minimal mode also skips the settings sources carrying
        # OAuth credentials — headless calls then fail "Not logged in"
        # (observed 2026-07-05). Project-context isolation comes from the
        # neutral cwd in _run_cli instead.
        argv = [self.bin_path, "-p", prompt, "--output-format", "json"]
        argv += self._model_args(model)

        stdout, stderr = await _run_cli(argv, timeout_s, "claude CLI")

        try:
            payload = json.loads(stdout)
        except ValueError:
            raise LlmError(
                "claude CLI printed non-JSON stdout: "
                f"{stdout.strip()[:_EXCERPT]!r} (stderr: {stderr.strip()[:_EXCERPT]!r})"
            ) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), str):
            raise LlmError(
                "claude CLI JSON lacks a string 'result' key: "
                f"{stdout.strip()[:_EXCERPT]!r}"
            )
        if payload.get("is_error"):
            # e.g. auth loss: exit 0, is_error:true, result="Not logged in ·
            # Please run /login". Never hand an error banner to callers as
            # completion text (observed poisoning a whole eval setting).
            _raise_if_limited("claude CLI", payload["result"])
            raise LlmError(f"claude CLI returned is_error: {payload['result'][:_EXCERPT]}")

        return CompletionResult(
            text=payload["result"],
            lnll=None,
            token_logprobs=None,
            backend="claude-cli",
            raw={
                "exit": 0,
                "bin": self.bin_path,
                "model_arg_passed": bool(self._model_args(model)),
                "is_error": payload.get("is_error"),
                "session_id": payload.get("session_id"),
            },
        )


# --- codex stdout parsing ---------------------------------------------------

#: A codex exec status marker: a line starting with a bracketed ISO timestamp,
#: e.g. "[2026-07-04T10:00:06] codex". Deliberately anchored on the date shape
#: so content lines that merely start with "[" (JSON arrays, citations) don't
#: match.
_TS_MARKER = re.compile(r"^\[\d{4}-\d{2}-\d{2}T[^\]]*\]")
_CODEX_MARKER = re.compile(r"^\[\d{4}-\d{2}-\d{2}T[^\]]*\]\s*codex\s*$")


def _is_status_line(line: str) -> bool:
    """Conservative status-noise detector for the no-marker fallback path."""
    s = line.strip()
    if re.fullmatch(r"\[.*\]", s):  # a line that is ONLY a bracketed marker
        return True
    if s.lower().startswith("tokens used"):
        return True
    if re.fullmatch(r"-{5,}", s):  # the header rule lines codex prints
        return True
    return False


def _extract_final_text(stdout: str) -> str:
    """Pull the assistant's final message out of `codex exec` stdout.

    Strategy (conservative, in order):
    1. If a `[<timestamp>] codex` marker exists, take everything after the
       LAST such marker up to the next timestamped status line (usually
       `[...] tokens used: N`) or end of output.
    2. Otherwise drop lines that are unambiguously status noise (pure
       bracketed markers, "tokens used...", `-----` rules) and return the
       rest.
    3. Empty stdout → empty string (the caller raises LlmError).
    """
    text = stdout.strip()
    if not text:
        return ""
    lines = text.splitlines()

    last_marker = None
    for i, line in enumerate(lines):
        if _CODEX_MARKER.match(line):
            last_marker = i
    if last_marker is not None:
        content: list[str] = []
        for line in lines[last_marker + 1:]:
            if _TS_MARKER.match(line):  # next status block ends the message
                break
            content.append(line)
        return "\n".join(content).strip()

    kept = [line for line in lines if not _is_status_line(line)]
    return "\n".join(kept).strip()


class CodexCliClient:
    """Codex CLI non-interactive mode: `codex exec <prompt>`.

    Always invoked with `--sandbox read-only --cd /tmp --skip-git-repo-check`
    (see module docstring) so the CLI cannot touch the repository while
    serving as a completion engine. `--model` is forwarded only for
    OpenAI-style names: `gpt*`, `codex*`, or `o<digit>*` (`o3`, `o4-mini`);
    the bare "starts with o" rule from the spec is tightened to o-then-digit
    so local names like `ollama`/`openhermes` don't leak through.
    """

    def __init__(self, bin_path: str = "codex"):
        self.bin_path = bin_path

    def _model_args(self, model: str) -> list[str]:
        model = (model or "").strip()
        if (
            model.startswith("gpt")
            or model.startswith("codex")
            or re.match(r"o\d", model)
        ):
            return ["--model", model]
        return []

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.0,  # not exposed by the CLI; ignored
        num_ctx: int = 16384,  # ignored
        max_tokens: int = 2048,  # ignored
        timeout_s: float = 300.0,
        grammar: Optional[str] = None,  # unsupported; ignored
        want_logprobs: bool = False,  # ignored
        thinking: bool = False,  # ignored
        response_schema: Optional[dict] = None,
    ) -> CompletionResult:
        prompt = _flatten(messages, response_schema)
        argv = [
            self.bin_path,
            "exec",
            "--sandbox", "read-only",
            "--cd", "/tmp",
            "--skip-git-repo-check",
        ]
        argv += self._model_args(model)
        argv.append(prompt)

        stdout, stderr = await _run_cli(argv, timeout_s, "codex CLI")

        text = _extract_final_text(stdout)
        if not text:
            raise LlmError(
                "codex CLI produced no completion text "
                f"(stdout: {stdout.strip()[:_EXCERPT]!r}, "
                f"stderr: {stderr.strip()[:_EXCERPT]!r})"
            )

        return CompletionResult(
            text=text,
            lnll=None,
            token_logprobs=None,
            backend="codex-cli",
            raw={
                "exit": 0,
                "bin": self.bin_path,
                "model_arg_passed": bool(self._model_args(model)),
            },
        )
