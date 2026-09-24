#!/usr/bin/env bash
# Checks every prerequisite (native binaries, Ollama, BLACK) and wraps
# `pendulum doctor` with paths already wired in.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

export PYTHONPATH="$REPO/Pendulum"
export PLTL_PARSER_BIN="$REPO/ocaml/_build/default/main.exe"
export PENDULUM_MCP_BIN="$REPO/target/release/pltl-mcp"
if [[ -z "${BLACK_BIN:-}" ]]; then
  if command -v brew >/dev/null 2>&1 && [[ -x "$(brew --prefix)/bin/black" ]]; then
    export BLACK_BIN="$(brew --prefix)/bin/black"
  fi
fi
export PENDULUM_DEFAULT_MODEL="gemma4:31b-mlx"
export AP_MODEL="gemma4:31b-mlx"   ORCH_MODEL="gemma4:31b-mlx"
export PYTHON_MODEL="gemma4:31b-mlx" DWYER_MODEL="gemma4:31b-mlx"
export SALT_MODEL="gemma4:31b-mlx" FUZZY_MODEL="gemma4:31b-mlx" DET_MODEL="gemma4:31b-mlx"

echo ">> Checking toolchain prerequisites (paths wired from $REPO)"
echo
"$REPO/Pendulum/.venv/bin/python" -m pendulum doctor
