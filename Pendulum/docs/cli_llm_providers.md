# Using Claude Code and Codex as LLM Providers (CLI backends)

*Precise reference for how Pendulum runs frontier models through their command-line
tools instead of HTTP APIs, and how it survives usage/session/rate limits and auth loss
without corrupting evaluation data. Written 2026-07-06 after a multi-day 9-setting
experiment surfaced several real bugs; the mistakes and their fixes are documented in
full because they are the most valuable part.*

---

## 1. Why CLI backends exist

An agent slot (coder / spec-writer / judge / orchestrator) can be pointed at a frontier
model by setting `<PREFIX>_BACKEND=claude-cli` or `codex-cli` in the environment. These
backends shell out to the locally-installed `claude` and `codex` programs in
non-interactive mode. There is **no HTTP API and no API key in Pendulum** — authentication
and billing ride the CLI's own login/keychain. This was a deliberate requirement: use the
user's existing CLI subscriptions, not metered API access.

Implementation: `pendulum/llm/cli_backends.py` (`ClaudeCliClient`, `CodexCliClient`),
dispatched from `pendulum/llm/router.py` when `agent_cfg.backend != "ollama"`.

### Shared limitations (both backends)
- **No token logprobs** → `lnll=None`. Confidence-gated ranking degrades the same way it
  does when the optional llama-server is down.
- **No grammar / no server-side JSON schema.** A `response_schema` is appended to the
  prompt as an instruction; shape errors fall to the caller's validate-and-retry loop.
- `temperature` / `num_ctx` / `max_tokens` / `thinking` are accepted for protocol parity
  and **ignored** — neither CLI exposes them per invocation.

---

## 2. How each CLI is invoked

### Claude Code — `ClaudeCliClient`
```
claude -p "<flattened prompt>" --output-format json [--model <m>]
```
- `-p` = headless print-and-exit; the prompt is positional.
- `--output-format json` yields a single JSON object whose **`result`** key holds the
  assistant text.
- `--model` is forwarded **only** when the configured model is plausibly a Claude model
  (`sonnet` / `opus` / `haiku`, or a `claude-*` id, e.g. `claude-opus-4-8`). Any other
  value (e.g. a leftover local model name) is omitted so the CLI uses its own default.
- Output parsing: `json.loads(stdout)` → require a string `result`; additionally inspect
  the **`is_error`** boolean (see §5.2).

### Codex — `CodexCliClient`
```
codex exec --sandbox read-only --cd /tmp --skip-git-repo-check [--model <m>] "<prompt>"
```
- `exec` = non-interactive; prompt is positional.
- `--sandbox read-only` + `--cd /tmp` + `--skip-git-repo-check`: while acting as a pure
  completion engine, Codex must **not** be able to write the repo or treat it as its
  working root. `--skip-git-repo-check` is required because `/tmp` is not a git repo.
- `--model` forwarded only for OpenAI-style ids (`gpt*`, `codex*`, `o<digit>*`).
- Codex prints its final message to **stdout** after timestamped status lines; it also
  **echoes the entire session (banner + prompt + completion) to stderr** — this detail
  caused a major bug (§5.3).

### Subprocess hygiene (applies to both) — `_run_cli`
- `asyncio.create_subprocess_exec(*argv, ...)` — **no shell**, so prompt content can never
  be interpreted as shell syntax (argv injection is structurally impossible).
- **Neutral working directory**: `cwd=tempfile.gettempdir()`. Without this, `claude -p`
  treats its cwd as a project and loads that repo's `CLAUDE.md`, answering *as a repo
  assistant* instead of completing the prompt.
- **Stripped environment**: the child inherits `os.environ` **minus every `CLAUDE*`
  variable**. When Pendulum itself runs inside a Claude Code session, this guarantees each
  `claude -p` call is a brand-new, unlinked session (auth lives in the keychain, not env).
- **Timeout with pipe drain**: `asyncio.wait_for(proc.communicate(), timeout_s)`; on
  timeout the process is killed **and then drained** (`communicate()` again under a short
  timeout) — a bare `wait()` can deadlock if the child filled a pipe buffer before dying.

---

## 3. The core invariant

> **A row is recorded only if every LLM call that produced it genuinely succeeded.**
> If a provider refused service (limit / auth), the row is **discarded, not recorded**,
> and the cell is retried later. Recording a degraded row is the cardinal sin — it silently
> poisons the dataset and, worse, *looks* like a real (bad) result.

Everything below exists to uphold this invariant.

---

## 4. Detection, recovery, and resume

### 4.1 Detection (`cli_backends.py`)
A failed CLI call raises **`SessionLimitError`** (subclass of `LlmError`) whose message
embeds the stable token **`PENDULUM_SESSION_LIMIT`**. The token survives being stringified
into agent envelopes, judge evidence, and the JSONL run log, so downstream layers can
detect the condition without catching a specific exception type across process boundaries.

Recognized signatures (`_LIMIT_SIGNS`, matched case-insensitively):
```
"hit your session limit", "usage limit reach", "rate limit",
"usage_limit", "limit resets", "not logged in", "please run /login"
```
Auth loss (`not logged in` / `please run /login`) is treated **identically** to a usage
limit: both mean "the provider will not serve this row now — abort and retry later."

**When the scan runs (this is the whole ballgame — see §5.3):**
- On process **failure only**: non-zero exit → scan `stderr` and `stdout`; then raise.
- On the claude success path: if the parsed JSON has `is_error: true`, scan `result`.
- On a genuinely successful call (exit 0, `is_error` false), **nothing is scanned.**

### 4.2 Recovery — the harness refuses to record (`eval/harness.py`)
After each row, `_session_limited(final, config)` returns true if `PENDULUM_SESSION_LIMIT`
appears in the final message **or anywhere in that run's `logs/<run_id>.jsonl`** (an
inner agent can trip the limit even when the run limps to an OK-shaped envelope). If true,
the harness **does not write the row** and returns **exit code 4**, aborting the eval so a
resume can re-run that exact row cleanly.

### 4.3 Retry with backoff (`experiments/matrix.py`)
```python
while rc == 4 and retries < LIMIT_MAX_RETRIES:   # default 12
    time.sleep(LIMIT_WAIT_S)                      # default 1800s = 30 min
    rc = run_command(eval_cmd(...), env, log)     # resumes the SAME cell
```
12 × 30 min covers a full 5-hour rolling window with margin. Both knobs are env-tunable
(`PENDULUM_LIMIT_WAIT_S`, `PENDULUM_LIMIT_MAX_RETRIES`).

### 4.4 Resume semantics
`pendulum eval` **appends** to its output CSV and **skips any `formula_id` already
present**. So a re-run after an abort re-does *only* the unrecorded row(s); every banked
row is untouched. `--skip-done` additionally avoids even launching the eval subprocess for
a cell whose CSV is already complete. Net effect: an outage costs *time*, never *data*, and
recovery needs no manual bookkeeping.

### 4.5 Scheduling around whole-provider outages
Codex bills OpenAI; claude-cli and the interactive session share the Anthropic budget.
When one provider's window is exhausted, a supervisor script reorders the remaining
settings to run on the *live* provider first (e.g. run the Codex settings during an
Anthropic outage, resume the Opus setting after its window rolls over). This is pure
scheduling on top of §4.4 — it changes *ordering*, never *correctness*.

---

## 5. Mistakes made, and how they were fixed

These are documented in detail because each was a real defect that produced wrong behavior
in a live multi-hour run, and the fixes are the reusable lessons.

### 5.1 `--bare` broke authentication
**What I did:** invoked `claude -p ... --bare` to get "minimal mode" (skip hooks, LSP,
plugins) for a clean completion engine.
**What broke:** every headless call returned `Not logged in · Please run /login`, even
with a valid interactive login. `--bare` skips the *settings sources* that carry the OAuth
credentials, so minimal mode is also unauthenticated mode.
**Fix:** drop `--bare`. Context isolation was already provided by the neutral `cwd`
(`/tmp`), so `--bare` bought nothing and cost authentication.
**Why correct:** verified live — the exact same prompt that failed with `--bare` returns
the correct completion without it, from the neutral cwd, with project context still
isolated. The two concerns (auth vs. project-context isolation) were conflated into one
flag; separating them fixed auth without regressing isolation.

### 5.2 Auth-loss banner recorded as a completion (data poisoning)
**What I did:** on the claude success path, trusted `result` whenever the JSON parsed and
`result` was a string.
**What broke:** when the CLI logged itself out mid-experiment, `claude -p` returned
**exit 0** with `is_error: true` and `result: "Not logged in · Please run /login"`. That
banner string was accepted as the model's answer. Because it never parsed to a valid
formula, every row "failed" — and **all 50 rows of a setting were recorded as failures in
~2 minutes**, a plausible-looking but entirely fake result.
**Fix:** (a) inspect `is_error`; if set, never return `result` as text — route it through
the limit scan (auth signs raise `SessionLimitError`, else `LlmError`). (b) add
`not logged in` / `please run /login` to `_LIMIT_SIGNS` so auth loss aborts-and-retries
exactly like a usage limit. The poisoned CSV was deleted and the setting re-run.
**Why correct:** `is_error: true` is the CLI's own signal that the payload is a status
message, not an answer. Keying on the provider's explicit error flag (rather than trying
to recognize banner text) is robust to wording changes, and mapping auth loss onto the
existing abort-and-retry path means a transient logout self-heals once you log back in —
no rows lost.

### 5.3 False-positive limit detection — the expensive one
**What I did (v1):** scan the CLI's **successful stdout** for the limit signs, reasoning
"a limit notice can appear in output."
**What broke:** the evaluation dataset contains sentences *about* rate limiting (e.g. a
requirement paraphrased as "every warning triggers rate limiting until termination"). The
model's correct output contained the phrase **"rate limit"**, the scanner matched it, and
the row was aborted — **every single time it was reached**. For hours this masqueraded as
a provider outage: the same heavyweight row aborted on every retry, so the setting appeared
permanently "walled."
**Fix (v2, incomplete):** scan error channels only — stderr always, stdout only on
non-zero exit. This fixed the *claude* path (claude prints content to stdout).
**What still broke:** **Codex echoes the entire session — banner, prompt, *and completion*
— to stderr.** So the same dataset phrase now tripped the scanner through *stderr* instead
of stdout. The false "wall" moved providers but persisted; it caused a full night of
phantom Codex "session limits."
**Fix (v3, correct):** scan for limit signs **only when the process actually fails** —
non-zero exit, or (claude) `is_error: true`. Successful output (exit 0, not `is_error`) is
**never** scanned, through any channel.
**Why correct — the principle:** a genuine provider refusal is *always* a failure signal —
the CLI exits non-zero or sets `is_error`. A call that exits 0 with `is_error` false means
the provider *served the request*; therefore its output is legitimate content and must
never be reinterpreted as a control signal, no matter what words it contains. v1 and v2
conflated two channels — "what the provider says about serving the request" (exit
code / `is_error`) and "what the model wrote" (stdout/stderr content). Only the former may
gate the limit decision. Tying detection to the failure signal makes it structurally
impossible for dataset content to ever again masquerade as an outage, and a regression
test pins exactly that: a successful call whose text/stderr contains "rate limit" must
return normally.

**Root-cause lesson:** when a program's output is the data you're processing, you cannot
also scan that same output for control signals — the data will eventually contain the
signal words. Control signals must come from a channel the payload cannot forge: here, the
process's own success/failure status.

### 5.4 (Supporting) subprocess correctness
Two smaller fixes, both from a code audit, folded in along the way: **drain pipes after a
timeout kill** (a bare `wait()` deadlocks if the child filled a pipe buffer), and **strip
`CLAUDE*` env** so an experiment run nested inside a Claude Code session spawns truly
independent child sessions rather than inheriting the parent's.

---

## 6. Detection decision table (current, correct behavior)

| CLI outcome | Example | Treated as | Row recorded? |
|---|---|---|---|
| exit 0, `is_error` false | normal completion (even if text says "rate limit") | success | **yes** |
| exit 0, `is_error` true, auth banner | `Not logged in · /login` | `SessionLimitError` | no → retry |
| exit 0, `is_error` true, other | upstream API error | `LlmError` | no → row errors |
| non-zero exit, stderr has a limit sign | real usage cap | `SessionLimitError` | no → retry |
| non-zero exit, other stderr | crash / bad flag | `LlmError` | no → row errors |
| wall-clock timeout | hung call | `LlmError` (killed + drained) | no → row errors |

`SessionLimitError` → harness exit 4 → matrix waits `LIMIT_WAIT_S` and resumes the same
cell (up to `LIMIT_MAX_RETRIES`). Any other `LlmError` is an ordinary per-row failure the
pipeline already tolerates.

---

## 7. Test coverage locking these in

`tests/unit/test_cli_backends.py` asserts, among others: the `--bare`-free argv; model-flag
omission rules for both CLIs; `is_error` + auth banner → `SessionLimitError`; genuine limit
signs on failure → `SessionLimitError`; **and the two critical negative tests** — a
successful stdout whose *content* mentions rate limiting, and a codex *stderr* conversation
echo mentioning rate limiting, both of which must return normally and never abort.
