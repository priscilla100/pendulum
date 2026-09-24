#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s "natural language requirement"\n' "${0##*/}" >&2
  printf 'Pass the requirement as exactly one shell-quoted argument.\n' >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

NL_TEXT=$1

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -f "$SCRIPT_DIR/cli.py" ] && [ -f "$SCRIPT_DIR/../requirements.txt" ]; then
  PENDULUM_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
elif [ -f "$SCRIPT_DIR/pendulum/cli.py" ] && [ -f "$SCRIPT_DIR/requirements.txt" ]; then
  PENDULUM_ROOT=$SCRIPT_DIR
else
  printf 'Could not locate the Pendulum project root from %s\n' "$SCRIPT_DIR" >&2
  exit 1
fi

PYTHON_BIN="${PENDULUM_PYTHON:-$PENDULUM_ROOT/.venv/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then
  printf 'Python interpreter not found or not executable: %s\n' "$PYTHON_BIN" >&2
  printf 'Set PENDULUM_PYTHON or create the venv with: python3 -m venv .venv\n' >&2
  exit 1
fi

# Agent model/backend defaults. Real environment variables supplied by the
# caller still win, so one-off overrides remain possible without editing this
# script.
export PENDULUM_DEFAULT_BACKEND="${PENDULUM_DEFAULT_BACKEND:-ollama}"
export PENDULUM_DEFAULT_BASE_URL="${PENDULUM_DEFAULT_BASE_URL:-http://localhost:11434/v1}"
export PENDULUM_DEFAULT_API_KEY="${PENDULUM_DEFAULT_API_KEY:-ollama}"
export PENDULUM_DEFAULT_MODEL="${PENDULUM_DEFAULT_MODEL:-gemma4:12b-mlx}"
export PENDULUM_DEFAULT_TEMPERATURE="${PENDULUM_DEFAULT_TEMPERATURE:-0.0}"
export PENDULUM_DEFAULT_NUM_CTX="${PENDULUM_DEFAULT_NUM_CTX:-65536}"
export PENDULUM_DEFAULT_TIMEOUT_S="${PENDULUM_DEFAULT_TIMEOUT_S:-480}"
export PENDULUM_DEFAULT_MAX_RETRIES="${PENDULUM_DEFAULT_MAX_RETRIES:-2}"
export PENDULUM_DEFAULT_THINKING="${PENDULUM_DEFAULT_THINKING:-false}"
export PENDULUM_DEFAULT_STREAMING="${PENDULUM_DEFAULT_STREAMING:-false}"

export AP_MODEL="${AP_MODEL:-$PENDULUM_DEFAULT_MODEL}"
export ORCH_MODEL="${ORCH_MODEL:-gemma4:12b-mlx}"
export PYTHON_MODEL="${PYTHON_MODEL:-gemma4:12b-mlx}"
export SALT_MODEL="${SALT_MODEL:-gemma4:12b-mlx}"
export FUZZY_MODEL="${FUZZY_MODEL:-$PENDULUM_DEFAULT_MODEL}"
export DET_MODEL="${DET_MODEL:-$PENDULUM_DEFAULT_MODEL}"

# Switch individual agents to claude-cli or codex-cli here when desired.
export AP_BACKEND="${AP_BACKEND:-ollama}"
export ORCH_BACKEND="${ORCH_BACKEND:-ollama}"
export PYTHON_BACKEND="${PYTHON_BACKEND:-ollama}"
export SALT_BACKEND="${SALT_BACKEND:-ollama}"
export FUZZY_BACKEND="${FUZZY_BACKEND:-ollama}"
export DET_BACKEND="${DET_BACKEND:-ollama}"
export CLAUDE_CLI_BIN="${CLAUDE_CLI_BIN:-claude}"
export CODEX_CLI_BIN="${CODEX_CLI_BIN:-codex}"

# Helper services, tools, and runtime toggles.
export PLTL_TOOL_LLM_BASE_URL="${PLTL_TOOL_LLM_BASE_URL:-http://localhost:11434}"
export PLTL_TOOL_LLM_MODEL="${PLTL_TOOL_LLM_MODEL:-gemma4:12b-mlx}"
export RAG_EMBED_BASE_URL="${RAG_EMBED_BASE_URL:-http://localhost:11434}"
export RAG_EMBED_MODEL="${RAG_EMBED_MODEL:-all-minilm}"
export LLAMACPP_ENABLED="${LLAMACPP_ENABLED:-true}"
export LLAMACPP_BASE_URL="${LLAMACPP_BASE_URL:-http://localhost:8080}"
export PENDULUM_LOG_LEVEL="${PENDULUM_LOG_LEVEL:-info}"
export PENDULUM_DWYER_ENABLED="${PENDULUM_DWYER_ENABLED:-false}"
export PENDULUM_DET_VERIFY_ENABLED="${PENDULUM_DET_VERIFY_ENABLED:-false}"
export PENDULUM_CONTRASTIVE_JUDGE="${PENDULUM_CONTRASTIVE_JUDGE:-true}"
export PENDULUM_OUTPUT_ALL_SURVIVORS="${PENDULUM_OUTPUT_ALL_SURVIVORS:-true}"
export PENDULUM_OUTPUT_SCOPE_VARIANTS="${PENDULUM_OUTPUT_SCOPE_VARIANTS:-true}"
export PENDULUM_MAX_OUTPUT_FORMULAS="${PENDULUM_MAX_OUTPUT_FORMULAS:-10}"

cd "$PENDULUM_ROOT"
exec "$PYTHON_BIN" -m pendulum translate -- "$NL_TEXT"
