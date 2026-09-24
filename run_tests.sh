#!/usr/bin/env bash
# Builds the OCaml parser and Rust binary, then runs tests/run_tests.py.
#
#   ./run_tests.sh                # deep mode (default)
#   ./run_tests.sh --light        # quick smoke set
#   ./run_tests.sh --deep         # explicit deep mode
#   ./run_tests.sh --light -v     # verbose
#
# Exit code 0 if all tests pass, non-zero otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Building OCaml parser ==="
(cd "$SCRIPT_DIR/ocaml" && dune build main.exe)

echo "=== Building Rust binary ==="
(cd "$SCRIPT_DIR/rust" && cargo build 2>&1 | tail -1)

export PLTL_PARSER_BIN="$SCRIPT_DIR/ocaml/_build/default/main.exe"

echo ""
exec python3 "$SCRIPT_DIR/tests/run_tests.py" "$@"
