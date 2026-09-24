# Pendulum

Pendulum translates a natural-language requirement into a Linear Temporal
Logic (LTL) formula. It separates candidate generation (two neural synthesis
paths) from symbolic semantic analysis (the BLACK SAT solver) and final
selection (an LLM judge plus deterministic ranking), rather than asking one
model to do all three at once.

```
NL requirement
  → pendulum (Python, LangGraph pipeline)
      → spawns pltl-mcp as a stdio MCP child (14 tools)
          → tools shell out to:
              ocaml/_build/default/main.exe   (surface parser → JSON → Formula AST)
              black                            (BLACK SAT solver: equivalence/entailment/traces)
              docker salt-compiler:latest      (SALT → LTL compilation)
              an Ollama/CLI model              (the 3 LLM-backed tools)
  → ranked LTL formula(s) + the atomic-proposition mapping used
```

## Components

| Path | What it is | Language |
|---|---|---|
| `ocaml/` | Surface-syntax parser: lexer, grammar, AST → JSON. The only thing that understands LTL's textual syntax. | OCaml (dune) |
| `rust/` | `pltl_rust` — the typed `Formula` AST and every symbolic analysis (equivalence, entailment, NNF, simplification, temporal class, ...). | Rust |
| `mcp/shared/` | Glue shared by MCP servers: shells out to the OCaml parser, common error type, LRU cache, transport/CLI scaffolding. | Rust |
| `mcp/server/` | `pltl-mcp` — the MCP server binary hosting all 14 tools over stdio or Streamable HTTP. | Rust |
| `vendor/salt/` | The SALT specification-language compiler, built into a Docker image and invoked by the `nl_to_ltl_via_salt` tool. | Docker |
| `grammars/pltl.gbnf` | GBNF grammar for constraining LLM decoding to valid LTL surface syntax (used with an optional llama.cpp server). | — |
| `Pendulum/` | The pipeline itself: a fixed LangGraph state machine (AP extraction → synthesis fan-out → filter → verify → assess → finalize), its prompts, and the CLI. | Python |
| `scripts/` | `setup.sh`, `doctor.sh`, `run_demo.sh` — the three entry points below. | Bash |
| `run_tests.sh`, `tests/` | Parser conformance corpus (well-formed / ill-formed LTL strings). | Bash + Python |

## Prerequisites

| Tool | Needed for | Install |
|---|---|---|
| Rust (`cargo`) | building `pltl-mcp` | <https://rustup.rs> |
| OCaml + `dune` | building the surface parser | `brew install opam && opam init && opam install dune` |
| Python ≥ 3.12 | running the pipeline | — |
| [BLACK](https://www.black-sat.org/) SAT solver | `check_equivalence`/`check_entailment`/trace tools | `brew install black-sat` — **note:** Homebrew's Python formatter package is also named `black`; if you have both, point `BLACK_BIN` at the `black-sat` one explicitly (e.g. `$(brew --cellar black-sat)/*/bin/black`) rather than relying on `brew link`. |
| [Ollama](https://ollama.com) | local models | pull whatever models you configure (see `Pendulum/.env.example`) |
| Docker | the SALT synthesis path | optional — the pipeline degrades gracefully without it |

## Setup

```bash
./scripts/setup.sh   # builds everything, sets up Pendulum/.venv, pulls models, builds RAG indexes
./scripts/doctor.sh   # checks every prerequisite and tells you what's missing
```

`setup.sh` is idempotent — safe to re-run. See `Pendulum/README.md` and
`Pendulum/.env.example` for the full configuration surface (per-agent model
overrides, feature toggles, backend selection).

## Running it

### The fastest path: the demo script

```bash
./scripts/run_demo.sh                                # built-in example sentence
./scripts/run_demo.sh "every request is eventually acknowledged"
```

Uses an all-local model configuration and prints one line of JSON:
`{run_id, status, formulas[], ap_mapping, message}`.

### Directly via the CLI

The demo script is a thin wrapper around `pendulum`'s own CLI, which has six
subcommands. Run any of these from `Pendulum/`, with `PYTHONPATH`,
`PLTL_PARSER_BIN`, and `PENDULUM_MCP_BIN` set (see `.env.example`, or source
what `scripts/run_demo.sh` exports):

```bash
python -m pendulum translate "SENTENCE" [--ap "atom=meaning" ...]  # one sentence -> ranked formulas
python -m pendulum init-rag [--force]                              # build/rebuild the RAG indexes
python -m pendulum eval --sample-size N --seed S [--dataset NAME]  # run a dataset through the pipeline
python -m pendulum score --in results.csv                          # semantic (BLACK) scoring of an eval run
python -m pendulum trace [run_id | path]                           # render a run's JSONL log as a readable trace
python -m pendulum doctor                                          # prerequisite checklist
```

### The MCP tool server standalone

```bash
PLTL_PARSER_BIN=$(pwd)/ocaml/_build/default/main.exe \
  ./target/release/pltl-mcp --tools all           # or --tools a,b,c / --list-available
                                                   # --transport http --bind 0.0.0.0:8000
```

Useful for exercising the symbolic tools directly (e.g. from another agent
or a different orchestrator) without going through the Python pipeline.

### The parser directly

```bash
./ocaml/_build/default/main.exe 'G (p -> F q)' --json
```

## Tests

```bash
./run_tests.sh --light          # quick parser smoke test
./run_tests.sh --deep           # full parser conformance corpus
cargo test --workspace --lib    # Rust unit tests (needs BLACK_BIN for the BLACK-backed ones)
cd Pendulum && .venv/bin/python -m pytest tests/unit           # hermetic Python tests
cd Pendulum && PENDULUM_E2E=1 .venv/bin/python -m pytest tests/e2e  # needs live services
```

## Frozen semantics

Formulas are evaluated over infinite ω-traces. Next (`X`) is strong. Past
operators are strict at `t=0` (`Y p` is false at the first position; there is
no separate weak-yesterday operator). This is implemented once in the shared
Rust AST (`rust/src/ast.rs`) rather than per tool.

See `Pendulum/README.md` for the pipeline's internal architecture and full
configuration reference, and `mcp/server/ARCHITECTURE.md` /
`mcp/shared/ARCHITECTURE.md` for the tool-server internals.
