from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_eval.cli import main

ROOT = Path(__file__).resolve().parents[2]
V0 = str(ROOT / "datasets" / "benchmark_v0.jsonl")
CFG = str(ROOT / "configs" / "agents.yaml")


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "validate-dataset" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e2:
        main(["--version"])
    assert e2.value.code == 0


def test_validate_ok_and_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate-dataset", "--dataset", V0]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["validate-dataset", "--dataset", "nope.jsonl"]) == 2
    assert "dataset not found" in capsys.readouterr().err


def test_validate_invalid_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [json.loads(line) for line in Path(V0).read_text().splitlines()]
    rows[0]["expected"]["answer"] = {
        "reachable": not list(rows[0]["expected"]["answer"].values())[0]
    }
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "worlds.json").write_bytes((ROOT / "datasets" / "worlds.json").read_bytes())
    assert main(["validate-dataset", "--dataset", str(bad)]) == 1
    assert "differs from oracle" in capsys.readouterr().out


def test_run_report_verify_and_unknown_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "run",
                "--dataset",
                V0,
                "--agent",
                "reference",
                "--config",
                CFG,
                "--out",
                str(tmp_path),
                "--limit",
                "4",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    run_dir = next(
        line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("run directory")
    )
    assert main(["report", "--run", run_dir, "--verify"]) == 0
    assert "verified" in capsys.readouterr().out
    assert (
        main(["run", "--dataset", V0, "--agent", "nope", "--config", CFG, "--out", str(tmp_path)])
        == 2
    )
    assert main(["report", "--run", str(tmp_path / "missing")]) == 2


def test_llm_agent_without_credentials_is_exit_3_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ROBOT_EVAL_LLM_MODEL", raising=False)
    rc = main(
        ["run", "--dataset", V0, "--agent", "llm_single", "--config", CFG, "--out", str(tmp_path)]
    )
    assert rc == 3
    assert "unavailable" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())  # no run directory, no invented results


def test_regression_check_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dev = str(ROOT / "datasets" / "v1" / "development.jsonl")
    dirs = []
    for ag in ("reference", "reference_regressed"):
        assert (
            main(["run", "--dataset", dev, "--agent", ag, "--config", CFG, "--out", str(tmp_path)])
            == 0
        )
        dirs.append(
            next(
                line.split(": ", 1)[1]
                for line in capsys.readouterr().out.splitlines()
                if line.startswith("run directory")
            )
        )
    assert main(["regression-check", "--baseline", dirs[0], "--candidate", dirs[0]]) == 0
    assert main(["regression-check", "--baseline", dirs[0], "--candidate", dirs[1]]) == 1
    assert "FAILED" in capsys.readouterr().out
    out = tmp_path / "cmp"
    assert main(["compare", "--runs", dirs[0], dirs[1], "--out", str(out), "--n-boot", "300"]) == 0
    assert (out / "comparison.md").exists()
