# Pendulum

A **fixed multi-agent workflow** for translating natural language into LTL
formulas, built on the `pltl-mcp` tool server (`../mcp/`, `../rust/`). Control
flow is a LangGraph state machine, not an LLM deciding what to call next —
each LLM has one narrow job.

```
NL sentence
  → ATOMIC_PROPOSITION_EXTRACTOR            (tense-neutral atoms, LNLL confidence)
      ↳ orchestrator fallback on error / low confidence
      ↳ skipped entirely when preset atoms are supplied (evals)
  → SYNTHESIS fan-out (parallel)
      PYTHON_TO_LTL     — coding model, Python AST completion trick
      SALT_TO_LTL       — RAG over SALT manual → SALT spec → compiler (fix loop)
      DWYERS_APPROACH   — RAG over Dwyer patterns (flat + recursive) [opt-in]
      (every candidate gated by parse_and_canonicalize; parse errors fed back)
  → orchestrator filter (fuzzy-verdict based; optional compare_candidates lattice)
  → VERIFICATION per candidate
      FUZZY             — ltl_to_nl paraphrases vs original NL (LLM judge)
      DETERMINISTIC     — BLACK solver tools [opt-in]
  → feedback loop: all candidates refuted → one resynthesis round with evidence
  → orchestrator final ranking
      + all surviving candidates appended        [default on]
      + scope variants (p / G p) for each output [default on]
  → 1..N ranked LTL formulas (every one parser-validated)
```

## Requirements

**Python** ≥ 3.12 (developed on 3.14). Dependencies (`requirements.txt`,
exact tested set in `requirements.lock.txt`):

| Package | Why |
|---|---|
| `pydantic-ai-slim[openai,mcp]` | agents, MCP stdio client, OpenAI-compat models |
| `langgraph` | the fixed-workflow graph runtime (Send fan-out, reducers) |
| `httpx` | direct LLM HTTP (grammar + logprobs), embeddings |
| `numpy` | RAG vector math |
| `python-dotenv` | `.env` loading |
| `pypdf` | SALT manual PDF extraction (RAG build only) |
| `pytest`, `pytest-asyncio` | tests |

**Services and binaries** (see the repo-root `README.md` for installs):

- `cargo build --release --workspace` in the parent repo → `../target/release/pltl-mcp`
- `(cd ../ocaml && dune build main.exe)` → the PLTL parser
- **Ollama** on `:11434` with the configured models pulled (defaults need
  `qwen3.6:27b`, `qwen2.5-coder:32b-instruct`, `qwen3:14b`, `all-minilm`;
  MLX variants like `gemma4:26b-mlx` run on Ollama ≥ 0.31's MLX engine)
- **BLACK** SAT solver on PATH (Apple Silicon: `brew install black-sat`,
  then `BLACK_BIN=$(brew --prefix)/bin/black`)
- **Docker** + `salt-compiler:latest` image
  (`docker build -t salt-compiler:latest ../vendor/salt/`)
- *Optional:* **llama-server** on `:8080` for grammar-constrained decoding +
  LNLL confidences (needs a GGUF build of the configured model and
  `--grammar-file ../grammars/pltl.gbnf`); without it the pipeline degrades
  to validate-and-retry with null confidences.
- *For external evals:* dataset checkouts at `<repo-parent>/datasets/`
  (`git clone https://github.com/Dubascudes/VLTL-Bench` and
  `https://github.com/dmmendo/synthTL` there, or point `VLTL_BENCH_ROOT` /
  `SYNTHTL_JSON` elsewhere).

## Setup

```bash
cd Pendulum
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then edit — every knob is documented inline
.venv/bin/python -m pendulum doctor     # verifies every prerequisite above
.venv/bin/python -m pendulum init-rag   # builds the Dwyer + SALT indexes
```

`doctor` is the fastest way to find what's missing: it checks Ollama and each
configured model, llama-server, both binaries, BLACK, Docker/SALT image,
prompts, and RAG indexes.

## Configuration

All configuration lives in `.env` (copied from `.env.example`, where every
key carries a comment). Real environment variables override the file.

**Per-agent LLM settings** — eight agents, each with its own prefix: `AP_`
(extractor), `ORCH_` (orchestrator), `PYTHON_`, `DWYER_`, `SALT_`, `ONESHOT_` (synthesis),
`FUZZY_`, `DET_` (verification). Every `<PREFIX>_<FIELD>` falls back to
`PENDULUM_DEFAULT_<FIELD>`: `BASE_URL`, `API_KEY`, `MODEL`, `TEMPERATURE`,
`NUM_CTX`, `MAX_STEPS`, `TIMEOUT_S`, `MAX_RETRIES`, `THINKING`, `STREAMING`.
Example — run one agent against a different server:

```bash
SALT_MODEL=gemma4:31b-mlx
SALT_BASE_URL=http://otherhost:11434/v1
```

**Feature toggles** (defaults reflect measured evidence from eval forensics):

| Key | Default | Effect |
|---|---|---|
| `PENDULUM_DWYER_ENABLED` | false | add the Dwyer agent to synthesis |
| `PENDULUM_DET_VERIFY_ENABLED` | false | BLACK-tool verifier alongside fuzzy |
| `PENDULUM_ORCH_COMPARE_FILTER` | false | compare_candidates lattice for the orchestrator |
| `PENDULUM_OUTPUT_ALL_SURVIVORS` | true | emit every non-refuted candidate |
| `PENDULUM_OUTPUT_SCOPE_VARIANTS` | true | also emit p / G p counterparts |
| `PENDULUM_EMIT_BEST_GUESS` | true | all-refuted → flagged best guess, not empty |
| `PENDULUM_FEEDBACK_LOOP` | true | one resynthesis round on total refusal |

**Other knobs:** `PENDULUM_LOG_LEVEL` (debug|info|warning|error — debug adds
prompts, completions, and every tool call/result), `PENDULUM_MAX_OUTPUT_FORMULAS`
(cap after survivor+variant expansion, default 10), retry budgets
(`SYNTH_PARSE_MAX_RETRIES`, `SALT_FIX_MAX_ATTEMPTS`), llama-server
(`LLAMACPP_*`, `PENDULUM_GRAMMAR_FILE`), MCP server paths (`PENDULUM_MCP_BIN`,
`PLTL_PARSER_BIN`, `PLTL_TOOL_LLM_*`, `BLACK_BIN`), tool cache
(`PENDULUM_TOOL_CACHE*` — deterministic tools only), RAG (`RAG_*`,
`PENDULUM_RAG_DIR`, `PENDULUM_RAG_AUTOBUILD`). See `.env.example`.

## Usage

All commands: `.venv/bin/python -m pendulum <command>` from `Pendulum/`.

### `translate` — one sentence → ranked formulas

```bash
.venv/bin/python -m pendulum translate "every request is eventually acknowledged"
```

Prints one JSON line: `run_id`, `status`, ranked `formulas` (each with
justification), the `ap_mapping` used, and a message. Exit 0 on OK, 3 on
ERROR. Full structured log lands in `logs/<run_id>.jsonl`.

### `eval` — run a dataset through the pipeline

```bash
# internal ground-truth TSV, 20 sampled rows:
.venv/bin/python -m pendulum eval --sample-size 20 --max-depth 5 --seed 42

# external datasets (checkouts under <repo-parent>/datasets/):
.venv/bin/python -m pendulum eval --dataset synthtl --sample-size 10 --seed 42 \
    --out ../eval_results/myrun_synthtl.csv
.venv/bin/python -m pendulum eval --dataset vltl_bench --formula-ids vltl_warehouse_12,...
```

Rows get the dataset's pre-defined atoms injected (extraction skipped), runs
are resumable (already-done rows skipped by `(formula_id, translation_id)`),
and the CSV feeds directly into the `score` command below. `all_formulas`
holds every ranked output as a JSON array.

### `score` — semantic success over ALL outputs

```bash
.venv/bin/python -m pendulum score --in ../eval_results/myrun_synthtl.csv
```

A row **succeeds when the ground truth is BLACK-equivalent to ANY ranked
output** (not just top-1). Appends `any_equivalent`, `equivalent_rank`,
`n_checked`, `gt_parses`; prints the success rate plus the top-1 figure for
comparison.

### `trace` — readable execution trace of a run

```bash
.venv/bin/python -m pendulum trace                    # newest run
.venv/bin/python -m pendulum trace 20260704-101328-547922b9   # by run id
.venv/bin/python -m pendulum trace logs/whatever.jsonl        # by path
```

Renders the run timeline: extracted/preset propositions, retrievals, each
agent's candidates, **every MCP tool call with its arguments and result**
(runs logged at `PENDULUM_LOG_LEVEL=debug`; info-level runs show the
higher-level events), filter decisions with reasoning, verdicts, feedback
rounds, the final ranking, and errors — each line time-offset from run start.

### `init-rag` / `doctor`

`init-rag [--force]` builds/rebuilds both vector indexes (Dwyer patterns from
`data/dwyer_patterns.json`; SALT from the condensed reference + vendor README
+ pypdf-extracted manual, timed content dropped). Indexes rebuild
automatically when the corpus or embedding model changes. `doctor` checks
every prerequisite and exits non-zero if a required one is missing.

## Tests

```bash
.venv/bin/python -m pytest tests/unit                 # hermetic, fake LLM/MCP layers
PENDULUM_E2E=1 .venv/bin/python -m pytest tests/e2e   # needs live services
```

## Layout

```
pendulum/config.py      .env configuration (per-agent inheritance, toggles)
pendulum/schemas.py     shared pydantic models
pendulum/llm/           completion clients (ollama, llamacpp), router, LNLL
pendulum/mcp/           typed wrapper around pltl-mcp (cache, restart, tracing)
pendulum/rag/           vector store + Dwyer/SALT index builders
pendulum/agents/        one file per agent + shared helpers
pendulum/graph/         LangGraph state, nodes, guard, builder
pendulum/eval/          dataset loaders, harness, any-of semantic scorer
pendulum/tracing.py     run-trace renderer (the `trace` command)
prompts/                every LLM prompt, one editable file each
data/                   dwyer_patterns.json (committed), rag/ indexes (generated)
tests/                  unit/ (hermetic) and e2e/ (live)
```
