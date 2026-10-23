from __future__ import annotations

import json
from pathlib import Path

from robot_eval.evaluation.runner import RunOptions, heldout_log_path, run_benchmark

ROOT = Path(__file__).resolve().parents[2]


def test_heldout_runs_are_disclosed_and_dev_runs_are_not(tmp_path: Path) -> None:
    log = heldout_log_path()
    assert not log.exists()
    run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "v1" / "development.jsonl",
            agent="reference",
            out_root=tmp_path,
            limit=2,
        )
    )
    assert not log.exists()
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "v1" / "heldout_test.jsonl",
            agent="reference",
            out_root=tmp_path,
            limit=2,
            command="robot-eval run ...",
        )
    )
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert (
        len(rows) == 1
        and rows[0]["run_id"] == res.metadata["run_id"]
        and rows[0]["agent"] == "reference"
    )
    assert rows[0]["n_cases"] == 2 and "prompt" not in rows[0]
