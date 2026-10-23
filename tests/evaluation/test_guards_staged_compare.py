"""Gate 4: guarded vs baseline, two-stage logging, fault handling, paired comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from robot_eval.agents.base import RunContext
from robot_eval.agents.factory import build_agent
from robot_eval.domain.case import BenchmarkCase, ExpectedOutcome, Family
from robot_eval.evaluation.compare import compare_records, render_comparison
from robot_eval.evaluation.dataset import load_cases
from robot_eval.evaluation.runner import RunOptions, run_benchmark, run_case
from robot_eval.evaluation.scoring import score_case
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import load_worlds

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs" / "agents.yaml"
DEV = load_cases(ROOT / "datasets" / "v1" / "development.jsonl")
WORLDS = load_worlds(ROOT / "datasets" / "worlds.json")


def exec_case(case: BenchmarkCase, agent_name: str) -> tuple[dict[str, Any], Any, Simulator]:
    ag = build_agent(agent_name, CFG)
    sim = Simulator(WORLDS[case.world_id], [case.fault] if case.fault else [])
    out, client, _ = run_case(case, ag, sim, 0, 40, 60)
    return score_case(case, WORLDS[case.world_id], client.records, out, sim.ee)["scoring"], out, sim


def pick(pred: Any) -> BenchmarkCase:
    return next(c for c in DEV if pred(c))


# ------------------------------------------------------------------------------------- guards
def test_validate_args_guard_prevents_sending_invalid_call() -> None:
    case = pick(
        lambda c: c.intent.family is Family.INVALID_VALUE and c.intent.params["mode"] == "nan"
    )
    base, out_b, _ = exec_case(case, "reference")
    guard, out_g, _ = exec_case(case, "reference_validate_only")
    assert (
        base["n_calls"] == 1 and base["n_calls_schema_valid"] == 0
    )  # baseline sent a NaN to the tool
    assert guard["n_calls"] == 0  # guard never sent it
    assert out_b.failure_code == out_g.failure_code == "INVALID_ARGUMENT"
    assert (
        base["task_success"] and guard["task_success"]
    )  # both end correctly; call hygiene differs


def test_verify_guard_removes_unsafe_attempts_and_costs_extra_calls() -> None:
    case = pick(
        lambda c: (
            c.intent.family is Family.MOVE
            and c.expected.unsafe_move
            and not c.intent.params.get("override")
        )
    )
    base, _, sim_b = exec_case(case, "reference")
    ver, out_v, sim_v = exec_case(case, "reference_verify_only")
    assert base["unsafe_attempts"] == 1 and base["safety_blocked"] == 1
    assert ver["unsafe_attempts"] == 0 and ver["n_calls"] > base["n_calls"]
    assert out_v.failure_code in case.expected.failure_codes and ver["task_success"]
    assert (
        sim_b.ee == sim_v.ee == (WORLDS[case.world_id].home.x, WORLDS[case.world_id].home.y)
    )  # sim protected both


def test_refuse_override_guard() -> None:
    case = pick(lambda c: c.expected.outcome is ExpectedOutcome.SAFE_REFUSAL)
    base, out_b, _ = exec_case(case, "reference")
    ref, out_r, _ = exec_case(case, "reference_refuse_only")
    assert base["unsafe_attempts"] == 1 and out_b.status.value == "failed"
    assert ref["n_calls"] == 0 and out_r.status.value == "refused" and ref["task_success"]


def test_guarded_agent_has_zero_unsafe_attempts_on_development_set(tmp_path: Path) -> None:
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "v1" / "development.jsonl",
            agent="reference_guarded",
            agent_config=CFG,
            out_root=tmp_path,
        )
    )
    m = res.summary["aggregate"]["metrics"]
    assert m["unsafe_action_attempt_rate_cases"]["num"] == 0
    assert m["simulator_false_blocks"] == 0


def test_simulator_hard_constraints_active_in_every_condition() -> None:
    case = pick(lambda c: c.intent.family is Family.MOVE and c.expected.unsafe_move)
    for name in ("reference", "reference_guarded", "two_stage_rule", "mock_always_move"):
        _, _, sim = exec_case(case, name)
        w = WORLDS[case.world_id]
        assert sim.ee == (w.home.x, w.home.y), name


def test_user_margin_constraint_is_verified_only_by_guarded() -> None:
    case = pick(
        lambda c: (
            c.intent.family is Family.MOVE
            and c.intent.params.get("required_margin") is not None
            and c.expected.outcome is ExpectedOutcome.TASK_FAILURE
            and not c.expected.unsafe_move
        )
    )
    base, _, sim_b = exec_case(case, "reference")
    ver, out_v, sim_v = exec_case(case, "reference_verify_only")
    assert (
        base["harmful_state_change"] and not base["task_success"]
    )  # moved although the user's margin was violated
    assert (
        not ver["harmful_state_change"]
        and ver["task_success"]
        and out_v.failure_code == "INSUFFICIENT_CLEARANCE"
    )


# --------------------------------------------------------------------------------- fault handling
def _fault_case(persistent: bool) -> BenchmarkCase:
    return pick(
        lambda c: (
            c.fault is not None
            and (c.fault.fail_first_n > 1) == persistent
            and c.intent.family
            in (Family.QUERY_REACH, Family.QUERY_COLLISION, Family.QUERY_CLEARANCE)
        )
    )


def test_transient_fault_recovered_by_one_retry_only() -> None:
    case = _fault_case(persistent=False)
    s, out, _ = exec_case(case, "reference")
    assert s["task_success"] and s["retry_count"] == 1 and s["n_calls"] == 2
    # a reference agent with retries disabled gives up: classified as unhandled tool failure
    from robot_eval.agents.reference import GuardConfig, ReferenceAgent

    ag = ReferenceAgent("noretry", GuardConfig(), max_retries=0)
    sim = Simulator(WORLDS[case.world_id], [case.fault])  # type: ignore[list-item]
    o, client, _ = run_case(case, ag, sim, 0, 40, 60)
    sc = score_case(case, WORLDS[case.world_id], client.records, o, sim.ee)["scoring"]
    assert not sc["task_success"] and sc["primary_failure_category"] == "unhandled_tool_failure"


def test_persistent_fault_reported_not_fabricated() -> None:
    case = _fault_case(persistent=True)
    s, out, _ = exec_case(case, "reference")
    assert out.status.value == "failed" and out.failure_code == case.expected.failure_codes[0]
    assert s["task_success"] and s["retry_count"] == 1
    fab, out_f, _ = exec_case(case, "mock_fabricate")
    assert not fab["task_success"] and fab["primary_failure_category"] in {
        "unhandled_tool_failure",
        "false_safe_claim",
    }


def test_blind_retry_fixture_shows_excess_retries() -> None:
    case = _fault_case(persistent=True)
    s, _, _ = exec_case(case, "mock_blind_retry")
    assert s["retry_count"] >= 6


# ------------------------------------------------------------------------------------ two-stage
def test_two_stage_logs_stages_distinctly(tmp_path: Path) -> None:
    case = pick(
        lambda c: (
            c.intent.family is Family.QUERY_REACH and c.expected.outcome is ExpectedOutcome.SUCCESS
        )
    )
    ag = build_agent("two_stage_rule", CFG)
    sim = Simulator(WORLDS[case.world_id])
    from robot_eval.tools.client import RecordingToolClient, SimulatorToolClient

    client = RecordingToolClient(SimulatorToolClient(sim))
    out = ag.run(case.prompt, client, RunContext())
    assert [s["stage"] for s in out.stages] == ["triage", "execution"]
    assert out.stages[0]["action"] == "proceed" and all(s["latency_ms"] >= 0 for s in out.stages)
    assert {r.stage for r in client.records} == {"execution"}


def test_two_stage_triage_stops_before_any_tool_call_on_contradiction() -> None:
    case = pick(lambda c: c.intent.family is Family.CONTRADICTORY)
    s, out, _ = exec_case(case, "two_stage_rule")
    assert out.status.value == "clarification" and s["n_calls"] == 0 and s["task_success"]
    assert [st["stage"] for st in out.stages] == ["triage"]
    # the single-stage guarded agent has no triage and acts on the same request
    s1, _, _ = exec_case(case, "reference_guarded")
    assert not s1["task_success"]


def test_stage_latencies_in_summary(tmp_path: Path) -> None:
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent="two_stage_rule",
            agent_config=CFG,
            out_root=tmp_path,
            limit=10,
        )
    )
    st = res.summary["aggregate"]["latency_ms"]["stages"]
    assert "triage" in st and "execution" in st and st["triage"]["n"] == 10


# ------------------------------------------------------------------------------ paired comparison
def _rec(cid: str, ok: int, unsafe: int = 0, lat: float = 1.0) -> dict[str, Any]:
    return {
        "case_id": cid,
        "repeat_index": 0,
        "latency_ms": lat,
        "scoring": {
            "task_success": bool(ok),
            "tool_selection_correct": bool(ok),
            "safe_outcome": True,
            "unsafe_attempts": unsafe,
            "false_safe_claim": False,
            "arguments_valid_case": True,
            "n_calls": 1,
        },
    }


def test_mcnemar_hand_fixture_and_holm() -> None:
    # 40 paired cases: 10 are B-only successes, 2 are A-only, 28 concordant (14 ok / 14 failed)
    a, b = [], []
    for i in range(10):
        a.append(_rec(f"c{i}", 0))
        b.append(_rec(f"c{i}", 1))
    for i in range(10, 12):
        a.append(_rec(f"c{i}", 1))
        b.append(_rec(f"c{i}", 0))
    for i in range(12, 26):
        a.append(_rec(f"c{i}", 1))
        b.append(_rec(f"c{i}", 1))
    for i in range(26, 40):
        a.append(_rec(f"c{i}", 0))
        b.append(_rec(f"c{i}", 0))
    res = compare_records(a, b, n_boot=1000, seed=5)
    ts = res["binary"]["task_success"]
    assert (ts["a_only_positive"], ts["b_only_positive"], ts["discordant"]) == (2, 10, 12)
    assert ts["mcnemar_exact_p"] == pytest.approx(158 / 4096)
    assert ts["diff_b_minus_a"] == pytest.approx(0.2) and ts["role"] == "primary"
    lo, hi = ts["diff_ci95_bootstrap"]
    assert lo < 0.2 < hi
    # Holm over {task_success, unsafe_attempt}: smallest p is multiplied by 2 -> 0.0771 > 0.05
    assert ts["holm_adjusted_p_primary_family"] == pytest.approx(2 * 158 / 4096)
    assert "no difference detected" in ts["reading"]
    assert not ts["inconclusive_small_sample"]
    assert "Holm" in render_comparison(
        {
            **res,
            "a": {"agent": "A", "dataset_hash": "x" * 64, "run_id": "r" * 12, "model_id": None},
            "b": {"agent": "B", "dataset_hash": "x" * 64, "run_id": "s" * 12, "model_id": None},
            "same_dataset": True,
            "warnings": [],
        }
    )


def test_small_samples_are_marked_inconclusive() -> None:
    a = [_rec(f"c{i}", 0) for i in range(8)]
    b = [_rec(f"c{i}", 1) for i in range(8)]
    ts = compare_records(a, b, n_boot=200)["binary"]["task_success"]
    assert ts["inconclusive_small_sample"] and "inconclusive" in ts["reading"]


def test_pairing_ignores_unmatched_cases() -> None:
    a = [_rec("x", 1), _rec("y", 1)]
    b = [_rec("y", 0), _rec("z", 1)]
    res = compare_records(a, b, n_boot=100)
    assert res["n_pairs"] == 1 and res["only_in_a"] == ["x"] and res["only_in_b"] == ["z"]


def test_baseline_vs_guarded_paired_run_is_reproducible(tmp_path: Path) -> None:
    ds = ROOT / "datasets" / "v1" / "development.jsonl"
    runs = {
        n: run_benchmark(RunOptions(dataset=ds, agent=n, agent_config=CFG, out_root=tmp_path))
        for n in ("reference", "reference_guarded")
    }
    r1 = compare_records(
        runs["reference"].records, runs["reference_guarded"].records, n_boot=500, seed=11
    )
    r2 = compare_records(
        runs["reference"].records, runs["reference_guarded"].records, n_boot=500, seed=11
    )
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    ua = r1["binary"]["unsafe_attempt"]
    assert ua["a"]["num"] > 0 and ua["b"]["num"] == 0 and ua["a_only_positive"] == ua["a"]["num"]
    assert r1["n_pairs"] == 164
