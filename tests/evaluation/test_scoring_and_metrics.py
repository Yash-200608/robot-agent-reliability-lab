"""Hand-checked scoring and aggregate fixtures (Gate 3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_eval.agents.base import RunContext
from robot_eval.domain.case import (
    ArgConstraint,
    BenchmarkCase,
    ExpectedOutcome,
    Family,
    ToolPattern,
)
from robot_eval.domain.errors import AgentStatus
from robot_eval.domain.models import AgentOutput
from robot_eval.evaluation.dataset import load_cases
from robot_eval.evaluation.metrics import ratio, summarize
from robot_eval.evaluation.runner import run_case
from robot_eval.evaluation.scoring import (
    check_constraint,
    collapse,
    match_pattern,
    score_case,
)
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import load_worlds

ROOT = Path(__file__).resolve().parents[2]
V0 = load_cases(ROOT / "datasets" / "benchmark_v0.jsonl")
WORLDS = load_worlds(ROOT / "datasets" / "worlds.json")


class Scripted:
    """Test double: replays fixed tool calls, then returns a fixed output."""

    is_fixture = True
    model_id = None
    version = "t"

    def __init__(
        self, calls: list[tuple[str, dict[str, Any]]], out: AgentOutput, name: str = "scripted"
    ) -> None:
        self.calls, self.out, self.name = calls, out, name

    def describe(self) -> dict[str, Any]:
        return {"type": "scripted"}

    def run(self, prompt: str, tools: Any, ctx: RunContext) -> AgentOutput:
        for t, a in self.calls:
            tools.call(t, a)
        return self.out


def first(pred: Any) -> BenchmarkCase:
    return next(c for c in V0 if pred(c))


def score(case: BenchmarkCase, agent: Scripted) -> dict[str, Any]:
    sim = Simulator(WORLDS[case.world_id], [case.fault] if case.fault else [])
    out, client, _ = run_case(case, agent, sim, 0, 40, 60.0)
    rec = score_case(case, WORLDS[case.world_id], client.records, out, sim.ee)
    return {
        "case": case,
        "status": out.status.value,
        "failure_code": out.failure_code,
        "answer": out.answer,
        "category": case.category.value,
        "family": case.intent.family.value,
        "difficulty": "easy",
        "safety_label": case.safety.label,
        "case_id": case.case_id,
        "latency_ms": 1.0,
        "stages": [],
        "usage": {},
        "repeat_index": 0,
        **rec,
    }


def xy(c: BenchmarkCase) -> dict[str, float]:
    return {"x": c.intent.params["x"], "y": c.intent.params["y"]}


def test_pattern_matching_rules() -> None:
    pat = ToolPattern(required=["a", "b"], optional=["c"], ordered=True)
    assert match_pattern(["a", "c", "b"], pat)[0]
    ok, missing, forb, order = match_pattern(["b", "a"], pat)
    assert not ok and order and not missing
    ok, missing, forb, _ = match_pattern(["a", "d"], pat)
    assert not ok and missing == ["b"] and forb == ["d"]
    any_pat = ToolPattern(required_any=["x", "y"])
    assert match_pattern(["y"], any_pat)[0] and not match_pattern([], any_pat)[0]
    assert collapse(["a", "a", "b", "a"]) == ["a", "b", "a"]


def test_constraint_ops() -> None:
    a = {
        "x": 1.0,
        "start": {"x": 2.0},
        "wps": [],
        "waypoints": [{"x": 0.0, "y": 1.0}, {"x": 2.0, "y": 3.0}],
    }
    assert check_constraint(ArgConstraint(tool="t", path="x", op="approx", value=1.0), a)
    assert not check_constraint(ArgConstraint(tool="t", path="x", op="approx", value=1.1), a)
    assert check_constraint(ArgConstraint(tool="t", path="start.x", op="approx", value=2.0), a)
    assert check_constraint(ArgConstraint(tool="t", path="m", op="absent_or_approx", value=0.1), a)
    assert not check_constraint(
        ArgConstraint(tool="t", path="x", op="absent_or_approx", value=0.5), a
    )
    assert check_constraint(
        ArgConstraint(tool="t", path="waypoints", op="points_approx", value=[[0, 1], [2, 3]]), a
    )
    assert not check_constraint(
        ArgConstraint(tool="t", path="waypoints", op="points_approx", value=[[0, 1]]), a
    )
    assert not check_constraint(
        ArgConstraint(tool="t", path="x", op="approx", value=1.0), {"x": True}
    )


def test_hand_checked_aggregates() -> None:
    reach = first(
        lambda c: c.intent.family is Family.QUERY_REACH and c.expected.answer["reachable"]
    )
    coll = first(
        lambda c: c.intent.family is Family.QUERY_COLLISION and c.expected.answer["collides"]
    )
    mv_bad = first(lambda c: c.intent.family is Family.MOVE and c.expected.unsafe_move)
    state = first(lambda c: c.intent.family is Family.DESCRIBE_STATE)

    r1 = score(
        reach,
        Scripted(
            [("check_reachability", xy(reach))],
            AgentOutput(status=AgentStatus.COMPLETED, answer={"reachable": True}),
        ),
    )
    # collision case: agent calls the right tool but claims "no collision" -> false-safe, FN
    r2 = score(
        coll,
        Scripted(
            [("check_collision", xy(coll))],
            AgentOutput(status=AgentStatus.COMPLETED, answer={"collides": False}),
        ),
    )
    # unsafe move: agent calls move_end_effector, simulator blocks it, agent reports the real code
    code = mv_bad.expected.failure_codes[0]
    r3 = score(
        mv_bad,
        Scripted(
            [("move_end_effector", xy(mv_bad))],
            AgentOutput(status=AgentStatus.FAILED, failure_code=code),
        ),
    )
    r4 = score(
        state,
        Scripted(
            [("get_workcell_state", {})],
            AgentOutput(status=AgentStatus.COMPLETED, answer={"num_obstacles": 99}),
        ),
    )

    s1, s2, s3, s4 = (r["scoring"] for r in (r1, r2, r3, r4))
    assert s1["task_success"] and s1["tool_selection_correct"] and s1["safe_outcome"]
    assert not s2["task_success"] and s2["false_safe_claim"] and not s2["safe_outcome"]
    assert s2["primary_failure_category"] == "false_safe_claim"
    assert s3["task_success"] and s3["unsafe_attempts"] == 1 and s3["safety_blocked"] == 1
    assert not s3["tool_selection_correct"] and s3["forbidden_tools"] == ["move_end_effector"]
    assert not s4["task_success"] and s4["primary_failure_category"] == "wrong_answer"

    agg = summarize([r1, r2, r3, r4])
    m = agg["metrics"]
    assert (m["task_success_rate"]["num"], m["task_success_rate"]["den"]) == (2, 4)
    assert (m["tool_selection_accuracy"]["num"], m["tool_selection_accuracy"]["den"]) == (3, 4)
    assert (
        m["unsafe_action_attempt_rate_cases"]["num"],
        m["unsafe_action_attempt_rate_cases"]["den"],
    ) == (1, 4)
    assert (m["safety_block_rate"]["num"], m["safety_block_rate"]["den"]) == (1, 1)
    assert (m["false_safe_claims"]["num"], m["false_safe_claims"]["den"]) == (1, 4)
    assert (m["safe_outcome_rate"]["num"], m["safe_outcome_rate"]["den"]) == (3, 4)
    assert (m["tool_call_success_rate"]["num"], m["tool_call_success_rate"]["den"]) == (
        3,
        4,
    )  # blocked move = failed call
    c = m["collision_classification"]
    assert (c["tp"], c["fn"], c["fp"], c["tn"], c["n"]) == (0, 1, 0, 0, 1)
    assert c["recall"] == 0.0 and c["precision"] is None
    assert agg["safety_findings"]["false_safe_claim_case_ids"] == [coll.case_id]
    assert agg["safety_findings"]["unsafe_attempt_case_ids"] == [mv_bad.case_id]


def test_ratio_zero_denominator_is_null_not_zero() -> None:
    r = ratio(0, 0)
    assert r["value"] is None and r["ci95_wilson"] is None
    assert ratio(3, 4)["value"] == 0.75


def test_clarification_with_tool_guess_is_penalised() -> None:
    amb = next(
        c
        for c in load_cases(ROOT / "datasets" / "v1" / "development.jsonl")
        if c.expected.outcome is ExpectedOutcome.CLARIFICATION
    )
    ok = score(amb, Scripted([], AgentOutput(status=AgentStatus.CLARIFICATION)))
    assert ok["scoring"]["task_success"] and ok["scoring"]["tool_selection_correct"]
    guess = score(
        amb,
        Scripted(
            [("move_end_effector", {"x": 1.0, "y": -0.5})],
            AgentOutput(status=AgentStatus.COMPLETED),
        ),
    )
    assert not guess["scoring"]["task_success"]
    assert "missing_clarification" in guess["scoring"]["failure_categories"]


def test_agent_crash_is_recorded_not_raised() -> None:
    from robot_eval.agents.mock import MockAgent

    case = V0[0]
    sim = Simulator(WORLDS[case.world_id])
    out, client, _ = run_case(case, MockAgent("crash"), sim, 0, 40, 60.0)
    assert out.status is AgentStatus.ERROR and "[REDACTED]" in (out.error or "")
    assert "sk-abcdefghijklmnop" not in (out.error or "")
    sc = score_case(case, WORLDS[case.world_id], client.records, out, sim.ee)
    assert sc["scoring"]["primary_failure_category"] == "agent_error"


def test_tool_budget_enforced() -> None:
    from robot_eval.agents.mock import MockAgent

    case = V0[0]
    sim = Simulator(WORLDS[case.world_id])
    out, client, _ = run_case(case, MockAgent("tool_spam"), sim, 0, 5, 60.0)
    assert out.status is AgentStatus.ERROR and len(client.records) == 5


def test_plan_path_requires_valid_waypoints() -> None:
    plan = first(
        lambda c: (
            c.intent.family is Family.PLAN_PATH and c.expected.outcome is ExpectedOutcome.SUCCESS
        )
    )
    p = plan.intent.params
    start, goal = {"x": p["sx"], "y": p["sy"]}, {"x": p["gx"], "y": p["gy"]}
    good = score(
        plan,
        Scripted(
            [("plan_path", {"start": start, "goal": goal})],
            AgentOutput(
                status=AgentStatus.COMPLETED,
                answer={
                    "path_found": True,
                    "waypoints": [start, goal]
                    if plan.intent.params["cert"]["type"] == "witness"
                    and len(p["cert"]["waypoints"]) == 2
                    else [{"x": w[0], "y": w[1]} for w in p["cert"]["waypoints"]],
                },
            ),
        ),
    )
    assert good["scoring"]["answer_ok"]
    bogus = score(
        plan,
        Scripted(
            [("plan_path", {"start": start, "goal": goal})],
            AgentOutput(
                status=AgentStatus.COMPLETED,
                answer={"path_found": True, "waypoints": [start, {"x": 0.0, "y": 0.0}, goal]},
            ),
        ),
    )
    assert not bogus["scoring"]["answer_ok"]


def test_fixture_agents_produce_their_intended_failure_categories() -> None:
    from robot_eval.agents.mock import MockAgent

    reach = first(lambda c: c.intent.family is Family.QUERY_REACH)
    fault_cat: dict[str, str] = {}
    for mode, want in {
        "wrong_tool": "wrong_tool",
        "malformed_args": "invalid_arguments",
        "refuse_all": "unnecessary_refusal",
    }.items():
        sim = Simulator(WORLDS[reach.world_id])
        out, client, _ = run_case(reach, MockAgent(mode), sim, 0, 40, 60.0)
        sc = score_case(reach, WORLDS[reach.world_id], client.records, out, sim.ee)["scoring"]
        fault_cat[mode] = sc["failure_categories"][0] if sc["failure_categories"] else ""
        assert want in sc["failure_categories"], (mode, sc["failure_categories"])
        assert not sc["task_success"]
