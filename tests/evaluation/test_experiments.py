from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_eval.evaluation.experiments import run_experiment

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "configs" / "experiments.yaml"


def latest(out: Path, name: str) -> Path:
    return sorted((out / name).iterdir())[-1]


def test_dry_run_lists_plan_without_running(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_experiment(EXP, "exp3_guard_ablation", tmp_path, dry_run=True) == 0
    assert "run baseline" in capsys.readouterr().out and not list(tmp_path.iterdir())


def test_unknown_experiment_is_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown experiment"):
        run_experiment(EXP, "nope", tmp_path)


def test_exp5_detects_regression_and_passes_negative_control(tmp_path: Path) -> None:
    assert run_experiment(EXP, "exp5_regression", tmp_path) == 0
    d = latest(tmp_path, "exp5_regression")
    rec = json.loads((d / "experiment.json").read_text())
    by = {(g["candidate"]): g for g in rec["regressions"]}
    assert by["baseline_repeat"]["passed_check"] and by["baseline_repeat"]["expectation_met"]
    assert not by["regressed"]["passed_check"] and by["regressed"]["expectation_met"]
    assert (d / "experiment_report.md").exists() and (
        d / "comparison_baseline_vs_regressed.json"
    ).exists()
    assert len(list((d / "runs").iterdir())) == 3


def test_llm_arms_are_reported_blocked_not_simulated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ROBOT_EVAL_LLM_MODEL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)  # so no stray .env is found
    cfg = tmp_path / "e.yaml"
    cfg.write_text(f"""
experiments:
  mini:
    description: mini
    runs:
      - {{id: rule, dataset: {ROOT}/datasets/benchmark_v0.jsonl, agent: reference}}
      - {{id: llm, dataset: {ROOT}/datasets/benchmark_v0.jsonl, agent: llm_single, optional: true}}
    comparisons:
      - {{a: rule, b: llm, role: confirmatory, primary: [task_success]}}
""")
    import shutil

    shutil.copy(ROOT / "configs" / "agents.yaml", tmp_path / "agents.yaml")
    assert run_experiment(cfg, "mini", tmp_path / "out") == 0
    d = latest(tmp_path / "out", "mini")
    rec = json.loads((d / "experiment.json").read_text())
    assert [b["id"] for b in rec["blocked"]][0] == "llm" and "llm" not in rec["runs"]
    assert "Blocked / skipped" in (d / "experiment_report.md").read_text()
    assert not (d / "comparison_rule_vs_llm.json").exists()
