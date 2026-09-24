#!/usr/bin/env bash
# Builds the toolchain from a fresh checkout. Idempotent. Each step is
# guarded: if an optional tool (Docker, Ollama) is missing it warns and
# continues. Ends by running ./doctor.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

say()  { printf '\n\033[1m>> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

say "1/7  Building the OCaml surface parser (ocaml/ -> main.exe)"
if command -v dune >/dev/null 2>&1; then
  ( cd ocaml && dune build main.exe )
  echo "   built: ocaml/_build/default/main.exe"
else
  warn "dune not found — install OCaml + dune (e.g. 'brew install opam && opam install dune'), then re-run."
fi

say "2/7  Building the Rust tools and MCP server (cargo build --release)"
if command -v cargo >/dev/null 2>&1; then
  cargo build --release --workspace
  echo "   built: target/release/pltl-mcp (+ pltl_rust)"
else
  warn "cargo not found — install Rust (https://rustup.rs), then re-run."
fi

say "3/7  Setting up the Python environment (Pendulum/.venv)"
if [[ ! -d Pendulum/.venv ]]; then
  python3 -m venv Pendulum/.venv
fi
Pendulum/.venv/bin/pip install --quiet --upgrade pip
if [[ -f Pendulum/requirements.lock.txt ]]; then
  Pendulum/.venv/bin/pip install --quiet -r Pendulum/requirements.lock.txt
else
  Pendulum/.venv/bin/pip install --quiet -r Pendulum/requirements.txt
fi
echo "   Python deps installed into Pendulum/.venv"

say "4/7  Building the SALT compiler Docker image (optional)"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -t salt-compiler:latest vendor/salt/
  echo "   built image: salt-compiler:latest"
else
  warn "Docker not available — the SALT synthesis path will be skipped. Everything else works."
fi

say "5/7  Pulling local models via Ollama (optional)"
if command -v ollama >/dev/null 2>&1; then
  ollama pull gemma4:31b-mlx || warn "could not pull gemma4:31b-mlx (~28 GB — the default model in every seat)"
  ollama pull all-minilm     || warn "could not pull all-minilm (RAG embeddings)"
  echo "   models ready (gemma4:31b-mlx, all-minilm)"
else
  warn "Ollama not found — install from https://ollama.com to run the local demo."
fi

say "6/7  Building the RAG vector indexes (Dwyer patterns + SALT reference)"
export PYTHONPATH="$REPO/Pendulum"
export PLTL_PARSER_BIN="$REPO/ocaml/_build/default/main.exe"
export PENDULUM_MCP_BIN="$REPO/target/release/pltl-mcp"
if Pendulum/.venv/bin/python -m pendulum init-rag; then
  echo "   indexes built under Pendulum/data/rag/"
else
  warn "init-rag failed (usually Ollama/all-minilm not ready) — re-run after step 5 succeeds."
fi

say "7/7  Running the health check"
"$HERE/doctor.sh" || warn "doctor reported missing pieces — see the checklist above."

say "Setup complete. Try:   ./run_demo.sh"
