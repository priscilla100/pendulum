"""Command-line interface: translate, init-rag, eval, doctor.

`translate` prints one line of JSON (mirroring the Rust agent's contract) and
exits 0 on OK / 3 on ERROR, so shell pipelines and the eval harness can treat
Pendulum and the old agent interchangeably.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys

import httpx

from pendulum.config import PendulumConfig
from pendulum.logging_setup import RunLogger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pendulum", description="Fixed multi-agent NL -> LTL workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p_translate = sub.add_parser("translate", help="translate one NL sentence to LTL formula(s)")
    p_translate.add_argument("text", help="the natural-language requirement")
    p_translate.add_argument("--run-id", default=None, help="override the generated run id")
    p_translate.add_argument(
        "--ap", action="append", default=None, metavar="ATOM=MEANING",
        help="provide an atomic proposition (repeatable), e.g. "
             "--ap 'req=a request occurs'. When given, these preset atoms skip the "
             "AP-extraction stage. Atom names must match [a-z][a-z0-9_]*.")

    p_rag = sub.add_parser("init-rag", help="build (or rebuild) the Dwyer + SALT vector indexes")
    p_rag.add_argument("--force", action="store_true", help="rebuild even if indexes are current")

    p_eval = sub.add_parser("eval", help="run the dataset evaluation harness")
    p_eval.add_argument("--dataset", default="gt",
                        choices=["gt", "vltl_bench", "synthtl", "unambiguous50"],
                        help="gt = internal TSV; external checkouts under <repo-parent>/datasets/; "
                             "unambiguous50 = curated tiered set in data/unambiguous50.json")
    p_eval.add_argument("--input", default=None, help="dataset TSV (gt only; default: ../test_inputs_ground_truth.txt)")
    p_eval.add_argument("--sample-size", type=int, default=20)
    p_eval.add_argument("--max-depth", type=int, default=None)
    p_eval.add_argument("--seed", type=int, default=42)
    p_eval.add_argument("--formula-ids", default=None,
                        help="comma-separated formula_ids to run (overrides sampling)")
    p_eval.add_argument("--out", default=None, help="output CSV path")

    p_score = sub.add_parser(
        "score",
        help="semantic scoring: row succeeds when GT is BLACK-equivalent to ANY ranked output",
    )
    p_score.add_argument("--in", dest="in_path", required=True, help="harness output CSV")
    p_score.add_argument("--out", dest="out_path", default=None,
                         help="scored CSV (default: input with _scored before .csv)")

    p_trace = sub.add_parser("trace", help="render a run's JSONL log as a readable execution trace")
    p_trace.add_argument("run", nargs="?", default=None,
                         help="run id or log path (default: the newest run)")

    sub.add_parser("doctor", help="check every service prerequisite")

    args = parser.parse_args(argv)
    if args.command == "translate":
        return _cmd_translate(args)
    if args.command == "init-rag":
        return _cmd_init_rag(args)
    if args.command == "eval":
        return _cmd_eval(args)
    if args.command == "score":
        return _cmd_score(args)
    if args.command == "trace":
        return _cmd_trace(args)
    return _cmd_doctor()


def _cmd_trace(args: argparse.Namespace) -> int:
    from pendulum.tracing import TraceError, render_trace

    try:
        print(render_trace(args.run))
        return 0
    except TraceError as exc:
        print(f"trace failed: {exc}", file=sys.stderr)
        return 1


def _cmd_translate(args: argparse.Namespace) -> int:
    import re

    from pendulum.pipeline import translate
    from pendulum.schemas import APMapping

    preset_aps = None
    if args.ap:
        preset_aps = []
        for item in args.ap:
            atom, sep, meaning = item.partition("=")
            atom, meaning = atom.strip(), meaning.strip()
            if not sep or not meaning:
                print(f"error: --ap must be ATOM=MEANING, got {item!r}", file=sys.stderr)
                return 2
            if not re.fullmatch(r"[a-z][a-z0-9_]*", atom):
                print(f"error: atom {atom!r} must match [a-z][a-z0-9_]* (from --ap {item!r})",
                      file=sys.stderr)
                return 2
            preset_aps.append(APMapping(ap=atom, nl_fragment=meaning))

    final = asyncio.run(translate(args.text, run_id=args.run_id, preset_aps=preset_aps))
    print(json.dumps({
        "run_id": final.run_id,
        "status": final.status,
        "formulas": [
            {"rank": f.rank, "formula": f.canonical, "justification": f.justification}
            for f in final.formulas
        ],
        "ap_mapping": {m.ap: m.nl_fragment for m in final.ap_mapping},
        "message": final.message,
    }, ensure_ascii=False))
    return 0 if final.status == "OK" else 3


def _cmd_init_rag(args: argparse.Namespace) -> int:
    from pendulum.llm.ollama import OllamaClient
    from pendulum.rag.embedder import OllamaEmbedder
    from pendulum.rag.init import ensure_rag_dbs

    config = PendulumConfig.from_env()
    logger = RunLogger(config.log_dir, level=config.log_level)

    async def run() -> int:
        client = OllamaClient(config.rag_embed_base_url)
        try:
            stores = await ensure_rag_dbs(
                config, OllamaEmbedder(client, config.rag_embed_model), logger, force=args.force
            )
            print(f"dwyer index: {len(stores.dwyer)} chunks")
            print(f"salt index:  {len(stores.salt)} chunks")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"init-rag failed: {exc}", file=sys.stderr)
            return 1
        finally:
            await client.aclose()

    return asyncio.run(run())


def _cmd_eval(args: argparse.Namespace) -> int:
    from pendulum.eval.harness import run_eval

    return asyncio.run(run_eval(
        input_path=args.input,
        sample_size=args.sample_size,
        max_depth=args.max_depth,
        seed=args.seed,
        formula_ids=[s.strip() for s in args.formula_ids.split(",")] if args.formula_ids else None,
        out_path=args.out,
        dataset=args.dataset,
    ))


def _cmd_score(args: argparse.Namespace) -> int:
    from pathlib import Path

    from pendulum.eval.semantic_score import default_out_path, score_file

    in_path = Path(args.in_path)
    out_path = Path(args.out_path) if args.out_path else default_out_path(in_path)
    try:
        return asyncio.run(score_file(in_path, out_path, PendulumConfig.from_env()))
    except (FileNotFoundError, ValueError) as exc:
        print(f"score failed: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "ok " if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _cmd_doctor() -> int:
    config = PendulumConfig.from_env()
    good = True

    # Ollama + models
    try:
        tags = httpx.get(f"{config.rag_embed_base_url}/api/tags", timeout=3).json()
        installed = {m["name"].split(":")[0] for m in tags.get("models", [])} | {
            m["name"] for m in tags.get("models", [])
        }
        good &= _check("Ollama server", True, config.rag_embed_base_url)
        for prefix in ("AP", "ORCH", "PYTHON", "DWYER", "SALT", "FUZZY", "DET"):
            model = config.agent(prefix).model
            good &= _check(f"model for {prefix} ({model})", model in installed or model.split(":")[0] in installed)
        embed = config.rag_embed_model
        good &= _check(f"embedding model ({embed})", embed in installed or embed.split(":")[0] in installed)
    except Exception as exc:  # noqa: BLE001
        good = _check("Ollama server", False, str(exc))

    # llama-server (optional)
    if config.llamacpp_enabled:
        try:
            up = httpx.get(f"{config.llamacpp_base_url}/health", timeout=2).status_code == 200
        except Exception:  # noqa: BLE001
            up = False
        _check("llama-server (optional: grammar + logprobs)", up,
               config.llamacpp_base_url + ("" if up else " — pipeline degrades to null confidences"))
    else:
        print("[ok ] llama-server disabled by config")

    # binaries
    good &= _check("pltl-mcp binary", config.mcp_server_bin.exists(), str(config.mcp_server_bin))
    good &= _check("OCaml parser", config.pltl_parser_bin.exists(), str(config.pltl_parser_bin))
    if config.pltl_parser_bin.exists():
        try:
            r = subprocess.run([str(config.pltl_parser_bin), "p U q"], capture_output=True, timeout=10)
            good &= _check("parser accepts 'p U q'", r.returncode == 0)
        except Exception as exc:  # noqa: BLE001
            good = _check("parser accepts 'p U q'", False, str(exc))

    black = config.black_bin or shutil.which("black-sat") or shutil.which("black")
    good &= _check("BLACK solver", bool(black), black or "not on PATH; set BLACK_BIN")

    docker = shutil.which("docker")
    if docker:
        try:
            r = subprocess.run([docker, "image", "inspect", "salt-compiler:latest"],
                               capture_output=True, timeout=10)
            good &= _check("salt-compiler:latest image", r.returncode == 0,
                           "" if r.returncode == 0 else "docker build -t salt-compiler:latest ../vendor/salt/")
        except Exception as exc:  # noqa: BLE001
            good = _check("salt-compiler:latest image", False, str(exc))
    else:
        good = _check("docker", False, "not on PATH (SALT agent will fail)")

    # CLI completion backends (claude-cli / codex-cli), if any agent uses one
    from pendulum.config import AGENT_PREFIXES

    try:
        cli_backends = sorted(
            {config.agent(p).backend for p in AGENT_PREFIXES} - {"ollama"}
        )
    except ValueError as exc:  # invalid <PREFIX>_BACKEND value
        cli_backends = []
        good = _check("agent backend config", False, str(exc))
    if not cli_backends:
        print("[ok ] CLI backends: none configured")
    for backend in cli_backends:
        bin_name = config.claude_cli_bin if backend == "claude-cli" else config.codex_cli_bin
        label = f"{backend} binary ({bin_name})"
        path = shutil.which(bin_name)
        if not path:
            good = _check(label, False, "not on PATH")
            continue
        try:
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            version = (r.stdout or r.stderr).strip().splitlines()
            good &= _check(label, r.returncode == 0, version[0] if version else path)
        except Exception as exc:  # noqa: BLE001
            good = _check(label, False, str(exc))

    # prompts + RAG
    from pendulum.prompt_loader import PROMPTS_DIR

    prompt_count = len(list(PROMPTS_DIR.glob("*.md")))
    good &= _check(f"prompt files ({prompt_count})", prompt_count >= 20, str(PROMPTS_DIR))
    for name in ("dwyer", "salt"):
        exists = (config.rag_dir / name / "meta.json").exists()
        _check(f"RAG index '{name}'", exists,
               "" if exists else "will be built on first run (or: python -m pendulum init-rag)")

    print("\nall required checks passed" if good else "\nsome REQUIRED checks failed")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
