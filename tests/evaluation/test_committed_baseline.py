"""The committed CI regression baseline must match what the current code produces on the dev set."""

from __future__ import annotations

from pathlib import Path

from robot_eval.evaluation.regression import check_regression, load_summary, load_thresholds
from robot_eval.evaluation.runner import RunOptions, run_benchmark

ROOT = Path(__file__).resolve().parents[2]


def test_committed_baseline_is_current(tmp_path: Path) -> None:
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "v1" / "development.jsonl",
            agent="reference",
            out_root=tmp_path,
        )
    )
    base = load_summary(ROOT / "reports" / "baselines" / "reference_development.summary.json")
    cand = load_summary(res.run_dir)
    out = check_regression(base, cand, load_thresholds(ROOT / "configs" / "benchmark.yaml"))
    assert out.passed, out.findings
    assert base["aggregate"]["metrics"] == cand["aggregate"]["metrics"], (
        "regenerate reports/baselines/*.json (dataset or agent changed)"
    )
