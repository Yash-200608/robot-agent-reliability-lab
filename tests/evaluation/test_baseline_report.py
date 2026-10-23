from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_eval.cli import main
from robot_eval.evaluation.baseline_report import REQUIRED, build_baseline_report, latest_dir
from robot_eval.evaluation.experiments import run_experiment
from robot_eval.evaluation.runner import load_run

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def exp_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    import os

    os.environ["ROBOT_EVAL_HELDOUT_LOG"] = str(tmp_path_factory.mktemp("hl") / "log.jsonl")
    root = tmp_path_factory.mktemp("exps")
    for name in REQUIRED:
        assert run_experiment(ROOT / "configs" / "experiments.yaml", name, root) == 0
    return root


def test_report_numbers_trace_to_saved_files(exp_root: Path) -> None:
    md = build_baseline_report(exp_root)
    d2 = latest_dir(exp_root, "exp2_reference_baseline")
    rec = json.loads((d2 / "experiment.json").read_text())
    _, summ, _ = load_run(d2 / rec["runs"]["heldout_reference"]["dir"])
    m = summ["aggregate"]["metrics"]["task_success_rate"]
    assert f"({m['num']}/{m['den']})" in md
    for section in (
        "## Abstract",
        "## Questions",
        "## Methods",
        "## Results",
        "## Failure analysis",
        "## Limitations",
        "## Conclusion",
    ):
        assert section in md
    assert "blocked (not simulated)" in md and "unresolved (not run)" in md
    assert "{" not in md and "}" not in md  # no unformatted template fragments


def test_cli_writes_report_and_errors_without_artifacts(
    exp_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "r.md"
    assert main(["baseline-report", "--experiments", str(exp_root), "--out", str(out)]) == 0
    assert out.read_text().startswith("# Baseline report")
    assert (
        main(["baseline-report", "--experiments", str(tmp_path / "none"), "--out", str(out)]) == 2
    )
