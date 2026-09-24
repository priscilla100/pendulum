#!/usr/bin/env bash
# Translates one NL sentence to LTL using an all-local model configuration
# (gemma-31b via Ollama in every seat — no cloud accounts or billing needed).
#
#   ./run_demo.sh                      # translates a built-in example sentence
#   ./run_demo.sh "your requirement"   # translates your own sentence
#
# If this fails, run ./doctor.sh first to find the missing prerequisite.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

SENTENCE="${1:-every request is eventually acknowledged}"
# Further args are forwarded to `pendulum translate` — e.g. repeatable
# --ap "atom=meaning" to supply atomic propositions and skip extraction.
shift || true
EXTRA_ARGS=("$@")

export PYTHONPATH="$REPO/Pendulum"
export PLTL_PARSER_BIN="$REPO/ocaml/_build/default/main.exe"
export PENDULUM_MCP_BIN="$REPO/target/release/pltl-mcp"
if [[ -z "${BLACK_BIN:-}" ]]; then
  if command -v brew >/dev/null 2>&1 && [[ -x "$(brew --prefix)/bin/black" ]]; then
    export BLACK_BIN="$(brew --prefix)/bin/black"
  fi
fi

export PENDULUM_DEFAULT_MODEL="gemma4:31b-mlx"
export PYTHON_BACKEND="ollama"  PYTHON_MODEL="gemma4:31b-mlx"
export SALT_BACKEND="ollama"    SALT_MODEL="gemma4:31b-mlx"
export AP_MODEL="gemma4:31b-mlx"   ORCH_MODEL="gemma4:31b-mlx"
export FUZZY_MODEL="gemma4:31b-mlx" DET_MODEL="gemma4:31b-mlx"
export PENDULUM_LOG_LEVEL="error"
export PENDULUM_ORCH_DETERMINISTIC="true"

echo ">> Translating:  \"$SENTENCE\""
echo ">> (all-local gemma-31b config; first run also builds the RAG index — may take a minute)"
echo

"$REPO/Pendulum/.venv/bin/python" -m pendulum translate "$SENTENCE" "${EXTRA_ARGS[@]}"

echo
echo ">> Done. The 'formulas' array above is the ranked LTL translation."
echo ">> Full step-by-step transcript: $REPO/Pendulum/logs/<run_id>.jsonl"
