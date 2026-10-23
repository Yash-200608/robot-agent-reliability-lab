"""Runner behaviour: artifacts, reproducibility, recomputation, redaction, regression (Gate 3/4/7)."""

from __future__ import annotations

import json
from pathlib import Path

from robot_eval.agents.factory import build_agent
from robot_eval.evaluation.compare import compare_records
from robot_eval.evaluation.metrics import summarize
from robot_eval.evaluation.regression import DEFAULT_THRESHOLDS, check_regression, load_summary
from robot_eval.evaluation.report import verify_summary
from robot_eval.evaluation.runner import RunOptions, canonical_record, load_run, run_benchmark

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs" / "agents.yaml"
V0 = ROOT / "datasets" / "benchmark_v0.jsonl"
DEV = ROOT / "datasets" / "v1" / "development.jsonl"


def run(tmp: Path, agent: str = "reference", ds: Path = V0, **kw: object):  # type: ignore[no-untyped-def]
    return run_benchmark(RunOptions(dataset=ds, agent=agent, agent_config=CFG, out_root=tmp, **kw))  # type: ignore[arg-type]


def test_run_directory_artifacts(tmp_path: Path) -> None:
    res = run(tmp_path)
    for f in ("metadata.json", "cases.jsonl", "events.jsonl", "summary.json", "report.md"):
        assert (res.run_dir / f).exists(), f
    meta, summary, recs = load_run(res.run_dir)
    assert meta["status"] == "completed" and len(recs) == 24
    assert meta["dataset"]["dataset_hash"] == recs[0]["dataset_hash"] == summary["dataset_hash"]
    assert meta["agent"]["name"] == "reference" and meta["code"]["source_sha256"]
    for key in (
        "run_id",
        "case_id",
        "timestamp",
        "benchmark_version",
        "dataset_hash",
        "agent_name",
        "seed",
        "status",
    ):
        assert recs[0][key] is not None
    assert recs[0]["usage"]["input_tokens"] is None  # absent token data is null, never 0
    events = [json.loads(line) for line in (res.run_dir / "events.jsonl").read_text().splitlines()]
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "run_finished"
    assert {"case_started", "tool_call", "case_finished"} <= {e["event"] for e in events}


def test_run_dirs_are_unique_never_overwritten(tmp_path: Path) -> None:
    d1 = run(tmp_path, limit=2).run_dir
    d2 = run(tmp_path, limit=2).run_dir
    assert d1 != d2 and d1.exists() and d2.exists()


def test_summary_is_recomputable_from_raw_records(tmp_path: Path) -> None:
    res = run(tmp_path)
    meta, summary, recs = load_run(res.run_dir)
    assert verify_summary(summary, recs) == []
    assert summarize(recs) == summary["aggregate"]
    # tampering with raw results is detected
    recs[0]["scoring"]["task_success"] = not recs[0]["scoring"]["task_success"]
    assert verify_summary(summary, recs)


def test_repeated_deterministic_runs_are_identical_apart_from_volatile_fields(
    tmp_path: Path,
) -> None:
    a = run(tmp_path, ds=DEV, limit=60).records
    b = run(tmp_path, ds=DEV, limit=60).records
    assert [canonical_record(r) for r in a] == [canonical_record(r) for r in b]
    assert summarize_without_latency(a) == summarize_without_latency(b)


def summarize_without_latency(recs):  # type: ignore[no-untyped-def]
    s = summarize(recs)
    s.pop("latency_ms")
    return s


def test_repeats_and_seeds_recorded(tmp_path: Path) -> None:
    res = run(tmp_path, limit=3, repeats=2, seed=10)
    assert [(r["repeat_index"], r["seed"]) for r in res.records] == [(0, 10)] * 3 + [(1, 11)] * 3
    rep = res.summary["aggregate"]["repeatability"]
    assert rep["cases_with_repeats"] == 3 and rep["unstable_cases"]["num"] == 0


def test_crash_secrets_never_reach_disk(tmp_path: Path) -> None:
    res = run(tmp_path, agent="mock_crash", limit=2)
    blob = "".join(p.read_text() for p in res.run_dir.iterdir() if p.is_file())
    assert "sk-abcdefghijklmnop" not in blob and "[REDACTED]" in blob
    assert res.summary["aggregate"]["safety_findings"]["agent_error_case_ids"]


def test_fixture_run_is_labelled_in_report(tmp_path: Path) -> None:
    res = run(tmp_path, agent="mock_refuse_all", limit=3)
    assert "TEST FIXTURE" in (res.run_dir / "report.md").read_text()
    smoke = run(tmp_path, limit=3)
    assert "Pipeline smoke check" in (smoke.run_dir / "report.md").read_text()


def test_tracing_disabled_by_default_and_recorded(tmp_path: Path) -> None:
    res = run(tmp_path, limit=2)
    t = res.metadata["tracing"]
    assert (t["exporter"], t["status"], t["flush"]) == ("none", "disabled", "ok")
    assert all(r["export_status"] == "disabled" for r in res.records)


def test_exporter_failure_does_not_break_run(tmp_path: Path) -> None:
    class Boom:
        name = "boom"

        def status(self) -> str:
            return "enabled"

        def export_case(self, record: dict) -> str:  # type: ignore[type-arg]
            raise ConnectionError("network down api_key=sk-secretsecretsecret1234")

        def flush(self) -> None:
            raise RuntimeError("flush failed")

    res = run_benchmark(
        RunOptions(dataset=V0, agent="reference", agent_config=CFG, out_root=tmp_path, limit=2),
        exporter=Boom(),
    )  # type: ignore[arg-type]
    assert all(
        r["export_status"].startswith("error:") and "secretsecret" not in r["export_status"]
        for r in res.records
    )


# ---------------------------------------------------------- regression detection (Experiment 5 fixture)
def test_identical_runs_pass_regression_check(tmp_path: Path) -> None:
    a = run(tmp_path, ds=DEV, limit=80)
    b = run(tmp_path, ds=DEV, limit=80)
    res = check_regression(load_summary(a.run_dir), load_summary(b.run_dir), DEFAULT_THRESHOLDS)
    assert res.passed and not res.findings


def test_injected_regression_is_detected(tmp_path: Path) -> None:
    base = run(tmp_path, ds=DEV)
    bad = run(tmp_path, agent="reference_regressed", ds=DEV)
    res = check_regression(
        load_summary(base.run_dir), load_summary(bad.run_dir), DEFAULT_THRESHOLDS
    )
    assert not res.passed
    assert any("clearance" in f for f in res.findings)  # category-level drop in the injected area
    # the paired comparison independently shows the regression direction on the same cases
    cmp = compare_records(base.records, bad.records, n_boot=500, seed=1)
    assert (
        cmp["binary"]["task_success"]["a_only_positive"]
        > cmp["binary"]["task_success"]["b_only_positive"]
    )


def test_regression_check_refuses_different_datasets(tmp_path: Path) -> None:
    a = run(tmp_path, limit=5)
    b = run(tmp_path, ds=DEV, limit=5)
    res = check_regression(load_summary(a.run_dir), load_summary(b.run_dir), DEFAULT_THRESHOLDS)
    assert not res.passed and "dataset hashes differ" in res.findings[0]


def test_guards_add_calls_but_never_disable_simulator(tmp_path: Path) -> None:
    g = run(tmp_path, agent="reference_guarded", ds=DEV)
    assert g.summary["aggregate"]["metrics"]["simulator_false_blocks"] == 0
    assert build_agent("reference_guarded", CFG).describe()["guards"] == {
        "validate_args": True,
        "verify": True,
        "refuse_overrides": True,
    }
