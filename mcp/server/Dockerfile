# Multi-stage build for the parameterized `pltl-mcp` server.
#
# Build context = repo root. Example:
#
#   docker build -f mcp/server/Dockerfile -t pltl-mcp:latest .
#
# One image; the `--tools` flag chooses what is exposed at runtime.
# The OCaml parser is baked in once.  The BLACK satisfiability solver
# is built from source in its own stage and copied into the final
# image.

# ---- Stage: OCaml parser --------------------------------------------------
FROM ocaml/opam:debian-12-ocaml-5.2 AS ocaml
USER root
RUN apt-get update && apt-get install -y --no-install-recommends m4 pkg-config \
 && rm -rf /var/lib/apt/lists/*
USER opam
# Local ocaml/dune declares menhirLib + yojson under `(libraries ...)`,
# plus menhir as a build tool. All three must be installed by opam.
RUN opam install -y dune menhir yojson
WORKDIR /build
COPY --chown=opam:opam ocaml ./ocaml
WORKDIR /build/ocaml
RUN eval $(opam env) && dune build main.exe

# ---- Stage: BLACK solver (built from source) ------------------------------
#
# BLACK isn't in Debian's apt; we build from source with the Z3
# backend (apt's libz3-dev is the simplest backend choice).
# nlohmann/json's bookworm package is too old, so we clone the
# header-only release tag.  Total layer size ~400 MB in the builder
# (build-essential + cmake + dev headers); the runtime copy is just
# the single `black` binary + libz3 runtime, ~30 MB.
FROM debian:bookworm AS black-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates \
      libtsl-hopscotch-map-dev libfmt-dev libz3-dev \
 && rm -rf /var/lib/apt/lists/*

# nlohmann/json header-only library (BLACK build dependency).
RUN git clone --depth 1 --branch v3.11.3 https://github.com/nlohmann/json.git /tmp/json \
 && cmake -S /tmp/json -B /tmp/json/build \
        -DJSON_BuildTests=OFF -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /tmp/json/build --target install -j"$(nproc)" \
 && rm -rf /tmp/json

# BLACK itself. The CalVer tag below is pinned; bump as new stable
# releases land. Verify with `git ls-remote --tags --refs https://github.com/black-sat/black.git | tail`.
ARG BLACK_REF=v0.10.8
RUN git clone --depth 1 --branch ${BLACK_REF} https://github.com/black-sat/black.git /tmp/black \
 && cmake -S /tmp/black -B /tmp/black/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DENABLE_Z3=ON \
 && cmake --build /tmp/black/build -j"$(nproc)" \
 && cmake --install /tmp/black/build \
 && ldconfig \
 && rm -rf /tmp/black

# Quick sanity check the binary is present and runs.
# BLACK installs `libblack.so` to /usr/local/lib; ldconfig above
# refreshes the linker cache for the build-time sanity check.
RUN /usr/local/bin/black --version

# ---- Stage: SySLite2 (Python LTL synthesiser) -----------------------------
#
# The Python tool itself is vendored at `vendor/syslite2/` in the repo.
# This stage copies it in, installs the Python deps into a venv, and
# downloads the CVC4 1.8 statically-linked Linux binary that SySLite2
# spawns from `resources/cvc4` (relative to the working directory).
# All of this is bundled into a single image stage so the final
# runtime can COPY the prepared tree wholesale.
FROM debian:bookworm AS syslite2-build
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates python3 python3-pip python3-venv python3-z3 \
 && rm -rf /var/lib/apt/lists/*

COPY vendor/syslite2 /opt/syslite2

# CVC4 1.8 statically-linked Linux x86_64 binary is vendored at
# `vendor/syslite2/resources/cvc4` (committed into the repo for
# reproducible Docker builds — no external download dependency).
# SySLite2 spawns this binary via `resources/cvc4` relative to its
# working directory.
RUN chmod 0755 /opt/syslite2/resources/cvc4 \
 && /opt/syslite2/resources/cvc4 --version | head -1

# Python deps for SySLite2 in a venv at /opt/syslite2/env.  z3 is
# pulled in via the debian python3-z3 package on the runtime stage
# (precompiled .so) rather than the source-built z3-solver pip wheel
# (which won't compile in the slim image).  PySMT will use it lazily
# when an algorithm asks for a Solver; the `bv_sygus` path used by
# the synthesis tool shells out to `resources/cvc4` directly and does
# not touch pysmt's Solver, so the install is decoupled from that
# fallback.
#
# Note: SySLite2's `ScikitCART.py` imports `sklearn.tree.export`
# which was removed in scikit-learn 0.24.  The vendored copy has a
# compat shim (try old / except new import path) so any modern
# sklearn release installs cleanly.
RUN python3 -m venv /opt/syslite2/env --system-site-packages \
 && /opt/syslite2/env/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/syslite2/env/bin/pip install --no-cache-dir \
        -r /opt/syslite2/requirements.txt

# ---- Stage: Rust workspace ------------------------------------------------
# 1.85+ required by rmcp-macros 1.7 (uses Cargo's `edition2024` feature,
# stabilized in 1.85).
FROM rust:1.90-bookworm AS rust-build
ENV CARGO_HOME=/usr/local/cargo
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY rust ./rust
COPY mcp/shared ./mcp/shared
COPY mcp/server ./mcp/server
# `agent` is a workspace member but isn't built by `cargo build -p
# pltl_mcp_server`; copy its manifest tree so the workspace still
# resolves cleanly.
COPY agent ./agent
RUN cargo build --release -p pltl_mcp_server

# ---- Stage: runtime -------------------------------------------------------
FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libz3-4 libfmt9 python3 python3-z3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ocaml /build/ocaml/_build/default/main.exe /usr/local/bin/pltl-parser
COPY --from=black-builder /usr/local/bin/black /usr/local/bin/black
# BLACK is dynamically linked against libblack.so (and helper libraries)
# installed under /usr/local/lib by the cmake install. Bring those over
# and refresh the linker cache so the binary can find them at runtime.
COPY --from=black-builder /usr/local/lib/ /usr/local/lib/
RUN ldconfig
# SySLite2 — Python tool + CVC4 binary + venv with its deps.  The
# Rust wrapper invokes `python3 src/Driver.py` with cwd
# `$SYSLITE2_DIR` so the hardcoded `resources/cvc4` path resolves.
COPY --from=syslite2-build /opt/syslite2 /opt/syslite2
COPY --from=rust-build /build/target/release/pltl-mcp /usr/local/bin/pltl-mcp

ENV PLTL_PARSER_BIN=/usr/local/bin/pltl-parser \
    BLACK_BIN=/usr/local/bin/black \
    SYSLITE2_DIR=/opt/syslite2 \
    PATH="/opt/syslite2/env/bin:${PATH}" \
    MCP_CACHE_CAPACITY=1024 \
    RUST_LOG=info

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/pltl-mcp"]
# Default args: register all tools, stdio transport. Override at run
# time:
#   docker run -i --rm pltl-mcp:latest --tools parse_and_canonicalize
#   docker run -p 8000:8000 pltl-mcp:latest --tools all --transport sse --bind 0.0.0.0:8000
CMD ["--tools", "all"]
