"""Unit tests for experiments/matrix.py (the 9-setting model-matrix runner).

Pure parts only — settings table, env building, selection parsing, dry-run
plan rendering, scored-CSV aggregation — plus ONE orchestration test with
subprocess execution monkeypatched out (no real evals, no CLI calls).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "experiments"))

import matrix  # noqa: E402  (needs the sys.path insert above)

# ---------------------------------------------------------------------------
# settings table
# ---------------------------------------------------------------------------

EXPECTED_NAMES = [
    "baseline", "code-qwen", "code-codex", "code-claude",
    "salt-codex", "salt-claude", "judge-codex", "judge-claude", "all-frontier",
    "orch-opus",
]


def test_settings_table_shape():
    assert len(matrix.SETTINGS) == 10
    assert [s.name for s in matrix.SETTINGS] == EXPECTED_NAMES
    assert len({s.name for s in matrix.SETTINGS}) == 10  # unique
    assert [s.number for s in matrix.SETTINGS] == list(range(1, 11))
    # phases: 1-2 all-local, 3-9 touch a paid CLI
    assert [s.phase for s in matrix.SETTINGS] == ["local"] * 2 + ["cli"] * 8
    six = {
        "PYTHON_BACKEND", "PYTHON_MODEL",
        "SALT_BACKEND", "SALT_MODEL",
        "FUZZY_BACKEND", "FUZZY_MODEL",
    }
    for s in matrix.SETTINGS:
        # every setting pins the three varied seats; orch-opus adds the two
        # ORCH override keys on top.
        assert six <= set(s.env) <= six | {"ORCH_BACKEND", "ORCH_MODEL"}
        for k, v in s.env.items():
            assert isinstance(k, str) and isinstance(v, str) and v


def test_settings_table_matches_approved_matrix():
    by_name = {s.name: s.env for s in matrix.SETTINGS}
    base = ("ollama", matrix.BASELINE_MODEL)
    cli_default = matrix.CLI_DEFAULT_MODEL
    opus = "claude-opus-4-8"  # user-pinned 2026-07-05

    def cell(env, prefix):
        return (env[f"{prefix}_BACKEND"], env[f"{prefix}_MODEL"])

    assert cell(by_name["baseline"], "PYTHON") == base
    assert cell(by_name["baseline"], "SALT") == base
    assert cell(by_name["baseline"], "FUZZY") == base

    assert cell(by_name["code-qwen"], "PYTHON") == ("ollama", "qwen2.5-coder:32b-instruct")
    assert cell(by_name["code-qwen"], "SALT") == base

    assert cell(by_name["code-codex"], "PYTHON") == ("codex-cli", cli_default)
    assert cell(by_name["code-claude"], "PYTHON") == ("claude-cli", opus)
    assert cell(by_name["salt-codex"], "SALT") == ("codex-cli", cli_default)
    assert cell(by_name["salt-claude"], "SALT") == ("claude-cli", opus)
    assert cell(by_name["judge-codex"], "FUZZY") == ("codex-cli", cli_default)
    assert cell(by_name["judge-claude"], "FUZZY") == ("claude-cli", opus)
    for prefix in ("PYTHON", "SALT", "FUZZY"):
        assert cell(by_name["all-frontier"], prefix) == ("claude-cli", opus)
    # non-varied slots stay baseline in single-swap settings
    assert cell(by_name["judge-codex"], "PYTHON") == base
    assert cell(by_name["salt-claude"], "FUZZY") == base


def test_shared_env_pins_the_approved_constants():
    backend_pins = {f"{p}_BACKEND": "ollama"
                    for p in ("AP", "ORCH", "PYTHON", "DWYER", "SALT", "FUZZY", "DET")}
    assert matrix.SHARED_ENV == {
        "ORCH_MODEL": "gemma4:12b-mlx",
        "PENDULUM_DEFAULT_MODEL": "gemma4:12b-mlx",
        "PLTL_TOOL_LLM_MODEL": "gemma4:12b-mlx",
        "PENDULUM_DEFAULT_NUM_CTX": "65536",
        "PENDULUM_LOG_LEVEL": "debug",
        "PENDULUM_DEFAULT_BACKEND": "ollama",
        **backend_pins,
    }


def test_cli_default_model_is_omitted_by_both_cli_clients():
    """The load-bearing decision: MODEL='default' must make both CLI clients
    drop the --model flag entirely (checked against the real classes)."""
    from pendulum.llm.cli_backends import ClaudeCliClient, CodexCliClient

    assert ClaudeCliClient()._model_args(matrix.CLI_DEFAULT_MODEL) == []
    assert CodexCliClient()._model_args(matrix.CLI_DEFAULT_MODEL) == []
    # sanity: the rule still forwards genuine provider models
    assert ClaudeCliClient()._model_args("sonnet") == ["--model", "sonnet"]
    assert CodexCliClient()._model_args("gpt-5") == ["--model", "gpt-5"]


# ---------------------------------------------------------------------------
# env building
# ---------------------------------------------------------------------------


def test_build_env_layering_and_no_mutation():
    base = {"PATH": "/usr/bin", "PENDULUM_LOG_LEVEL": "info", "SALT_MODEL": "leftover"}
    overrides = {"SALT_MODEL": "default", "SALT_BACKEND": "claude-cli"}
    env = matrix.build_env(base, overrides)

    assert env["PATH"] == "/usr/bin"  # base preserved
    assert env["PENDULUM_LOG_LEVEL"] == "debug"  # shared beats base
    assert env["SALT_MODEL"] == "default"  # override beats shared and base
    assert env["SALT_BACKEND"] == "claude-cli"
    assert env["PENDULUM_DEFAULT_NUM_CTX"] == "65536"  # shared applied
    # inputs untouched
    assert base == {"PATH": "/usr/bin", "PENDULUM_LOG_LEVEL": "info",
                    "SALT_MODEL": "leftover"}


def test_build_env_for_baseline_pins_all_varied_slots():
    baseline = matrix.SETTINGS[0]
    env = matrix.build_env({"SALT_MODEL": "junk-from-dotenv"}, baseline.env)
    assert env["SALT_MODEL"] == matrix.BASELINE_MODEL
    assert env["PYTHON_BACKEND"] == "ollama"
    assert env["FUZZY_BACKEND"] == "ollama"


# ---------------------------------------------------------------------------
# --settings parsing
# ---------------------------------------------------------------------------


def test_parse_settings_numbers():
    picked = matrix.parse_settings_arg("1,3,7")
    assert [s.name for s in picked] == ["baseline", "code-codex", "judge-codex"]


def test_parse_settings_names_mixed_and_deduped():
    picked = matrix.parse_settings_arg("all-frontier, 2, code-qwen")
    # dedup + table order
    assert [s.name for s in picked] == ["code-qwen", "all-frontier"]


def test_parse_settings_rejects_unknown_and_empty():
    with pytest.raises(ValueError, match="unknown setting 'nope'"):
        matrix.parse_settings_arg("1,nope")
    with pytest.raises(ValueError, match="selected nothing"):
        matrix.parse_settings_arg(" , ,")


# ---------------------------------------------------------------------------
# --phase filtering
# ---------------------------------------------------------------------------


def test_filter_by_phase():
    local = matrix.filter_by_phase(list(matrix.SETTINGS), "local")
    assert [s.name for s in local] == ["baseline", "code-qwen"]
    cli = matrix.filter_by_phase(list(matrix.SETTINGS), "cli")
    assert [s.name for s in cli] == EXPECTED_NAMES[2:]
    assert matrix.filter_by_phase(list(matrix.SETTINGS), "all") == list(matrix.SETTINGS)
    with pytest.raises(ValueError, match="unknown phase"):
        matrix.filter_by_phase(list(matrix.SETTINGS), "billing-please")


def test_main_defaults_to_local_phase(monkeypatch):
    """The billing guardrail: without flags, only settings 1-2 reach run_matrix."""
    captured: dict = {}

    def fake_run(settings, **kwargs):
        captured["settings"] = settings
        return 0

    monkeypatch.setattr(matrix, "run_matrix", fake_run)
    assert matrix.main([]) == 0
    assert [s.name for s in captured["settings"]] == ["baseline", "code-qwen"]

    assert matrix.main(["--phase", "cli"]) == 0
    assert [s.name for s in captured["settings"]] == EXPECTED_NAMES[2:]

    assert matrix.main(["--phase", "all"]) == 0
    assert [s.name for s in captured["settings"]] == EXPECTED_NAMES


def test_main_refuses_cli_settings_under_default_phase(monkeypatch, capsys):
    def fake_run(settings, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("run_matrix must not run for a phase-empty selection")

    monkeypatch.setattr(matrix, "run_matrix", fake_run)
    rc = matrix.main(["--settings", "all-frontier"])  # cli setting, default phase local
    assert rc == 2
    err = capsys.readouterr().err
    assert "excluded by --phase local" in err
    assert "--phase cli" in err  # tells the user how to opt in


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

SCORED_FIELDS = ["formula_id", "domain", "elapsed_sec", "any_equivalent", "equivalent_rank"]


def _write_scored(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _scored_row(fid, tier, elapsed, equivalent, rank=""):
    return {"formula_id": fid, "domain": tier, "elapsed_sec": elapsed,
            "any_equivalent": equivalent, "equivalent_rank": rank}


def test_parse_scored_name():
    p = matrix.parse_scored_name
    assert p(Path("matrix_code-qwen_unambiguous50_scored.csv")) == ("code-qwen", "unambiguous50")
    assert p(Path("matrix_all-frontier_unambiguous50_scored.csv")) == ("all-frontier", "unambiguous50")
    assert p(Path("matrix_code-qwen_unambiguous50.csv")) is None  # raw, not scored
    assert p(Path("pendulum_gt_scored.csv")) is None  # not a matrix file
    assert p(Path("matrix_x_synthtl_scored.csv")) is None  # retired dataset
    assert p(Path("matrix_x_unknownds_scored.csv")) is None  # unknown dataset


def test_aggregate_counts_median_and_tiers(tmp_path):
    _write_scored(tmp_path / "matrix_code-qwen_unambiguous50_scored.csv", [
        _scored_row("u50_very_easy_01", "very_easy", "10", "true", "1"),
        _scored_row("u50_very_easy_02", "very_easy", "30", "true", "2"),
        _scored_row("u50_hard_01", "hard", "20", "false"),
        _scored_row("u50_impossible_01", "impossible", "40", "false"),
    ])
    _write_scored(tmp_path / "matrix_baseline_unambiguous50_scored.csv", [
        _scored_row("u50_easy_01", "easy", "5.5", "false"),
    ])
    (tmp_path / "matrix_baseline_unambiguous50.csv").write_text("raw,not,scored\n")  # ignored
    (tmp_path / "other_scored.csv").write_text("x\n")  # ignored

    rows = matrix.aggregate(tmp_path)
    assert [(r["setting"], r["dataset"]) for r in rows] == [
        ("baseline", "unambiguous50"),  # settings-table order, not alphabetical
        ("code-qwen", "unambiguous50"),
    ]
    qwen = rows[1]
    assert qwen["n"] == 4
    assert qwen["any_equivalent_count"] == 2
    assert qwen["top1_count"] == 1
    assert qwen["median_elapsed"] == 25.0
    # per-tier breakdown, read from the domain column
    assert (qwen["n_very_easy"], qwen["any_equivalent_very_easy"]) == (2, 2)
    assert (qwen["n_hard"], qwen["any_equivalent_hard"]) == (1, 0)
    assert (qwen["n_impossible"], qwen["any_equivalent_impossible"]) == (1, 0)
    assert (qwen["n_easy"], qwen["any_equivalent_easy"]) == (0, 0)
    assert (qwen["n_medium"], qwen["any_equivalent_medium"]) == (0, 0)
    assert rows[0]["median_elapsed"] == 5.5
    assert (rows[0]["n_easy"], rows[0]["any_equivalent_easy"]) == (1, 0)


def test_write_summary_and_markdown(tmp_path):
    _write_scored(tmp_path / "matrix_judge-codex_unambiguous50_scored.csv", [
        _scored_row("u50_medium_01", "medium", "7", "true", "1"),
    ])
    rows = matrix.aggregate(tmp_path)
    out = tmp_path / "summary.csv"
    matrix.write_summary(rows, out)
    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == matrix.SUMMARY_FIELDS  # incl. per-tier columns
        written = list(reader)
    expected = {
        "setting": "judge-codex", "dataset": "unambiguous50", "n": "1",
        "any_equivalent_count": "1", "top1_count": "1", "median_elapsed": "7.0",
    }
    for tier in matrix.TIERS:
        expected[f"n_{tier}"] = "1" if tier == "medium" else "0"
        expected[f"any_equivalent_{tier}"] = "1" if tier == "medium" else "0"
    assert written == [expected]
    md = matrix.render_markdown(rows)
    assert "| very_easy | easy | medium | hard | impossible |" in md
    assert "| judge-codex | unambiguous50 | 1 | 1 | 1 | 7.0 | 0/0 | 0/0 | 1/1 | 0/0 | 0/0 |" in md
    assert matrix.render_markdown([]).startswith("(no matrix_")


# ---------------------------------------------------------------------------
# dry-run plan
# ---------------------------------------------------------------------------


def test_dry_run_renders_plan_without_running(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):  # pragma: no cover - should never fire
        raise AssertionError("dry-run must not spawn subprocesses")

    monkeypatch.setattr(matrix, "run_command", boom)
    picked = matrix.parse_settings_arg("baseline,judge-claude")
    rc = matrix.run_matrix(
        picked, dry_run=True, base_env={},
        eval_results_dir=tmp_path / "evals", logs_dir=tmp_path / "logs",
        summary_path=tmp_path / "summary.csv", check_prereqs=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "matrix_baseline_unambiguous50.csv" in out
    assert "matrix_judge-claude_unambiguous50.csv" in out
    assert "baseline (phase local)" in out
    assert "judge-claude (phase cli)" in out
    assert "FUZZY_BACKEND=claude-cli" in out
    assert "FUZZY_MODEL=claude-opus-4-8" in out
    assert "PENDULUM_DEFAULT_NUM_CTX=65536" in out  # shared env shown
    assert "--seed 42" in out and "--sample-size 50" in out  # full 50-row set
    assert str(tmp_path / "logs" / "baseline_unambiguous50.log") in out


# ---------------------------------------------------------------------------
# orchestration (monkeypatched subprocess layer)
# ---------------------------------------------------------------------------


def test_orchestration_sequential_resilient_and_scores(tmp_path, monkeypatch):
    """Settings run one after another; a failing eval is recorded but does not
    abort the matrix; score runs after each setting's evals."""
    calls: list[dict] = []

    def fake_run(cmd, env, log_path):
        record = {"cmd": list(cmd), "env": dict(env), "log": Path(log_path)}
        calls.append(record)
        if "eval" in cmd:
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("header\n")  # exists -> score step is attempted
            if "matrix_baseline_unambiguous50" in out.name:
                return 3  # first setting's eval fails
        return 0

    monkeypatch.setattr(matrix, "run_command", fake_run)
    picked = matrix.parse_settings_arg("baseline,code-qwen")
    rc = matrix.run_matrix(
        picked, base_env={"PATH": "/usr/bin"},
        eval_results_dir=tmp_path / "evals", logs_dir=tmp_path / "logs",
        summary_path=tmp_path / "summary.csv", check_prereqs=False,
    )
    assert rc == 1  # failure recorded, but ...

    def phase(c):
        cmd = c["cmd"]
        kind = "eval" if "eval" in cmd else "score"
        target = cmd[cmd.index("--out") + 1] if kind == "eval" else cmd[cmd.index("--in") + 1]
        return (kind, Path(target).name)

    phases = [phase(c) for c in calls]
    # ... the whole matrix still ran, sequentially, evals before scores per setting
    assert phases == [
        ("eval", "matrix_baseline_unambiguous50.csv"),   # fails (exit 3)
        ("score", "matrix_baseline_unambiguous50.csv"),  # CSV exists -> still scored
        ("eval", "matrix_code-qwen_unambiguous50.csv"),  # next setting still runs
        ("score", "matrix_code-qwen_unambiguous50.csv"),
    ]
    # env plumbing: shared + per-setting overrides reached the subprocess
    qwen_eval_env = calls[2]["env"]
    assert qwen_eval_env["PYTHON_MODEL"] == "qwen2.5-coder:32b-instruct"
    assert qwen_eval_env["PENDULUM_LOG_LEVEL"] == "debug"
    assert qwen_eval_env["PATH"] == "/usr/bin"
    # summary written even though a cell failed (no scored CSVs -> header only)
    assert (tmp_path / "summary.csv").exists()


def test_skip_done_skips_complete_cells_but_still_scores(tmp_path, monkeypatch):
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    done = evals_dir / "matrix_baseline_unambiguous50.csv"
    with open(done, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["formula_id"])
        writer.writerows([[str(i)] for i in range(matrix.SAMPLE_SIZE)])  # complete (50 rows)

    calls = []

    def fake_run(cmd, env, log_path):
        calls.append(list(cmd))
        if "eval" in cmd:
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text("header\n")
        return 0

    monkeypatch.setattr(matrix, "run_command", fake_run)
    rc = matrix.run_matrix(
        matrix.parse_settings_arg("baseline,code-qwen"), skip_done=True, base_env={},
        eval_results_dir=evals_dir, logs_dir=tmp_path / "logs",
        summary_path=tmp_path / "summary.csv", check_prereqs=False,
    )
    assert rc == 0
    evals = [c for c in calls if "eval" in c]
    scores = [c for c in calls if "score" in c]
    assert len(evals) == 1  # only code-qwen; the complete baseline cell skipped
    assert "matrix_code-qwen_unambiguous50.csv" in str(evals[0])
    assert len(scores) == 2  # both settings' CSVs still (re)scored


def test_shared_env_forces_all_backends_to_ollama():
    """Codex audit HIGH: ambient *_BACKEND env must never leak CLI billing
    into local-phase settings — SHARED_ENV pins every backend to ollama."""
    from experiments import matrix

    for prefix in ("AP", "ORCH", "PYTHON", "DWYER", "SALT", "FUZZY", "DET"):
        assert matrix.SHARED_ENV.get(f"{prefix}_BACKEND") == "ollama"
    assert matrix.SHARED_ENV.get("PENDULUM_DEFAULT_BACKEND") == "ollama"
    # and a CLI setting still overrides its varied slot
    cli = next(s for s in matrix.SETTINGS if s.name == "judge-claude")
    env = matrix.build_env({}, cli.env)
    assert env["FUZZY_BACKEND"] == "claude-cli"
    assert env["PYTHON_BACKEND"] == "ollama"


def test_orch_opus_setting_overrides_orchestrator_and_is_cli_phase():
    from experiments import matrix

    s = next(x for x in matrix.SETTINGS if x.name == "orch-opus")
    assert s.env["ORCH_BACKEND"] == "claude-cli"
    assert s.env["ORCH_MODEL"] == "claude-opus-4-8"
    # the three synthesis/judge seats stay local
    for prefix in ("PYTHON", "SALT", "FUZZY"):
        assert s.env[f"{prefix}_BACKEND"] == "ollama"
    # ORCH override marks it as a paid (cli) phase setting
    assert s.phase == "cli"
    # and build_env keeps the ORCH override on top of SHARED_ENV's ollama pin
    env = matrix.build_env({}, s.env)
    assert env["ORCH_BACKEND"] == "claude-cli"
    assert env["ORCH_MODEL"] == "claude-opus-4-8"
