"""Tool contracts, boundary semantics and simulator invariants (Gate 1)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from robot_eval.domain.errors import ToolErrorCode
from robot_eval.simulator.checks import point_violations
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import FaultSpec, WorldSpec
from robot_eval.tools.registry import MUTATING_TOOLS, TOOL_REGISTRY, tool_descriptors

# cell_a: base (0,0), reach [0.3, 2.5], margin 0.1, weld 0.25, workspace +-3,
# o1 = (1.2, 0.9, r=0.5), o2 = (-1.0, 1.5, r=0.4), o3 = (0.5, -1.6, r=0.3), home (1.0, -0.5)


def test_tool_count_and_descriptors() -> None:
    assert 8 <= len(TOOL_REGISTRY) <= 12
    desc = tool_descriptors()
    assert {d["name"] for d in desc} == set(TOOL_REGISTRY)
    for d in desc:
        assert d["description"] and d["input_schema"]["type"] == "object"
    assert {"move_end_effector"} == MUTATING_TOOLS


@pytest.mark.parametrize("name", ["cell_a", "cell_b", "cell_c", "cell_open", "cell_walled"])
def test_home_pose_is_safe_in_every_world(worlds: dict[str, WorldSpec], name: str) -> None:
    w = worlds[name]
    assert point_violations(w, w.home.x, w.home.y) == []


def test_get_workcell_state(sim_a: Simulator) -> None:
    r = sim_a.call("get_workcell_state", {})
    assert r.ok and r.data["num_obstacles"] == 3
    assert r.data["end_effector"] == {"x": 1.0, "y": -0.5}
    assert r.data["units"] == {"length": "m", "angle": "deg"}


# ---------------------------------------------------------------- boundary semantics
def test_reach_boundary_is_inclusive(sim_a: Simulator) -> None:
    # (1.5, 2.0) is exactly 2.5 m from the base (3-4-5)
    assert sim_a.call("check_reachability", {"x": 1.5, "y": 2.0}).data["reachable"] is True
    r = sim_a.call("check_reachability", {"x": 1.5, "y": 2.0001})
    assert r.data["reachable"] is False and r.data["reason"] == "beyond_max_reach"


def test_inner_reach_limit_inclusive(sim_a: Simulator) -> None:
    assert sim_a.call("check_reachability", {"x": 0.3, "y": 0.0}).data["reachable"] is True
    r = sim_a.call("check_reachability", {"x": 0.29, "y": 0.0})
    assert r.data["reachable"] is False and r.data["reason"] == "inside_min_reach"


def test_workspace_edge_inclusive_and_outside(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(worlds["cell_open"])  # workspace +-2, reach_max 1.8
    r = sim.call("check_reachability", {"x": 2.1, "y": 0.0})
    assert r.data["reachable"] is False and r.data["reason"] == "out_of_workspace"


def test_touching_obstacle_is_collision(sim_a: Simulator) -> None:
    # (1.5, 1.3) is exactly 0.5 m from o1's centre (3-4-5) == radius -> touching
    r = sim_a.call("check_collision", {"x": 1.5, "y": 1.3})
    assert r.data["collides"] is True
    assert sim_a.call("check_collision", {"x": 1.56, "y": 1.38}).data["collides"] is False


def test_clearance_margin_equality_is_safe(sim_a: Simulator) -> None:
    # (1.56, 1.38) is 0.6 m from o1's centre: clearance 0.1 == margin
    r = sim_a.call("check_clearance", {"x": 1.56, "y": 1.38})
    assert r.data["clearance_ok"] is True
    r2 = sim_a.call("check_clearance", {"x": 1.559, "y": 1.38})
    assert r2.data["clearance_ok"] is False


def test_clearance_custom_margin(sim_a: Simulator) -> None:
    r = sim_a.call("check_clearance", {"x": 1.56, "y": 1.38, "required_margin": 0.5})
    assert r.data["clearance_ok"] is False and r.data["required_margin"] == 0.5


def test_clearance_without_obstacles_is_ok(sim_open: Simulator) -> None:
    r = sim_open.call("check_clearance", {"x": 0.5, "y": 0.5})
    assert r.data["clearance_ok"] is True and r.data["min_clearance"] is None


def test_joint_limits_inclusive(sim_a: Simulator) -> None:
    assert sim_a.call("validate_joint_limits", {"joints": {"shoulder": 90, "elbow": 0}}).data[
        "within_limits"
    ]
    r = sim_a.call("validate_joint_limits", {"joints": {"shoulder": 90.5, "elbow": 151.0}})
    assert not r.data["within_limits"]
    assert {v["joint"] for v in r.data["violations"]} == {"shoulder", "elbow"}


def test_unknown_joint_is_invalid_argument(sim_a: Simulator) -> None:
    r = sim_a.call("validate_joint_limits", {"joints": {"tentacle": 1.0}})
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGUMENT


# --------------------------------------------------------------------- argument validation
@pytest.mark.parametrize(
    "tool,args",
    [
        ("check_reachability", {"x": 1.0}),  # missing field
        ("check_reachability", {"x": 1.0, "y": 1.0, "z": 0.0}),  # unknown field
        ("check_reachability", {"x": float("nan"), "y": 0.0}),
        ("check_reachability", {"x": float("inf"), "y": 0.0}),
        ("check_reachability", {"x": "1.0", "y": 0.0}),  # no type coercion
        ("check_reachability", {"x": True, "y": 0.0}),
        ("check_reachability", {"x": 5000.0, "y": 0.0}),  # out of schema range
        ("check_clearance", {"x": 0.0, "y": 0.0, "required_margin": -1.0}),
        ("validate_joint_limits", {"joints": {}}),
        ("validate_path", {"waypoints": [{"x": 0.0, "y": 0.0}]}),
        ("plan_path", {"start": {"x": 0.0, "y": 0.0}}),
        ("estimate_operation_feasibility", {"operation": "cut", "x": 0.0, "y": 0.0}),
    ],
)
def test_invalid_arguments_rejected_without_state_change(
    sim_a: Simulator, tool: str, args: dict[str, Any]
) -> None:
    before = (sim_a.full_fingerprint(), sim_a.world_fingerprint())
    r = sim_a.call(tool, args)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGUMENT
    assert r.operation_id is None and r.data["errors"]
    assert (sim_a.full_fingerprint(), sim_a.world_fingerprint()) == before


def test_non_object_arguments_rejected(sim_a: Simulator) -> None:
    r = sim_a.call("check_reachability", [1, 2])
    assert r.error_code == ToolErrorCode.INVALID_ARGUMENT


def test_unknown_tool(sim_a: Simulator) -> None:
    r = sim_a.call("launch_missiles", {})
    assert not r.ok and r.error_code == ToolErrorCode.UNKNOWN_TOOL


def test_integer_coordinates_are_accepted(sim_a: Simulator) -> None:
    assert sim_a.call("check_reachability", {"x": 1, "y": 1}).ok


# ------------------------------------------------------------------------------ move tool
def test_move_success_updates_pose_and_logs(sim_a: Simulator) -> None:
    r = sim_a.call("move_end_effector", {"x": 1.0, "y": 0.0})
    assert r.ok and r.operation_id == "op-0001"
    assert sim_a.ee == (1.0, 0.0)
    assert len(sim_a.state.op_log) == 1 and sim_a.state.op_log[0].state_changed


@pytest.mark.parametrize(
    "target,code",
    [
        ((5.0, 5.0), ToolErrorCode.OUT_OF_BOUNDS),
        ((2.0, 2.0), ToolErrorCode.TARGET_UNREACHABLE),  # 2.83 m > 2.5
        ((0.1, 0.0), ToolErrorCode.TARGET_UNREACHABLE),  # inside min reach
        ((1.2, 0.9), ToolErrorCode.COLLISION),
        ((1.56, 1.37), ToolErrorCode.INSUFFICIENT_CLEARANCE),
    ],
)
def test_unsafe_move_rejected_and_pose_unchanged(
    sim_a: Simulator, target: tuple[float, float], code: ToolErrorCode
) -> None:
    pose, world_fp = sim_a.ee, sim_a.world_fingerprint()
    r = sim_a.call("move_end_effector", {"x": target[0], "y": target[1]})
    assert not r.ok and r.error_code == code
    assert sim_a.ee == pose and sim_a.world_fingerprint() == world_fp
    assert sim_a.state.op_log[-1].state_changed is False


def test_move_through_obstacle_rejected_as_path_collision(sim_a: Simulator) -> None:
    # target (1.0, 1.6) is itself safe (0.73 m from o1's centre, clearance 0.23) and reachable,
    # but the straight line from home (1.0, -0.5) passes through o1 at (1.2, 0.9) r=0.5.
    assert point_violations(sim_a.world, 1.0, 1.6) == []
    r = sim_a.call("move_end_effector", {"x": 1.0, "y": 1.6})
    assert not r.ok and r.error_code == ToolErrorCode.PATH_COLLISION
    assert sim_a.ee == (1.0, -0.5)


def test_precedence_clearance_before_path_collision(sim_a: Simulator) -> None:
    # target too close to o1 (clearance 0.04 < 0.1): point-level code wins, path code also listed
    r = sim_a.call("move_end_effector", {"x": 1.0, "y": 1.4})
    assert r.error_code == ToolErrorCode.INSUFFICIENT_CLEARANCE
    assert "PATH_COLLISION" in r.data["violation_codes"]


def test_path_collision_when_target_itself_is_safe(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(worlds["cell_c"])  # home (-1,1); c1 at origin r=0.8
    r = sim.call("move_end_effector", {"x": 1.0, "y": -1.0})
    # target (1,-1): clearance to c1 = 1.414-0.8 = 0.61 (safe); to c2 (1.5,-1): 0.5-0.4=0.1 (==margin)
    assert not r.ok and r.error_code == ToolErrorCode.PATH_COLLISION
    assert sim.ee == (-1.0, 1.0)


def test_failed_moves_never_change_pose_property(sim_a: Simulator) -> None:
    import random

    rng = random.Random(7)
    for _ in range(300):
        pose = sim_a.ee
        r = sim_a.call("move_end_effector", {"x": rng.uniform(-4, 4), "y": rng.uniform(-4, 4)})
        if not r.ok:
            assert sim_a.ee == pose
        else:
            # whatever the simulator accepted must satisfy every point-level check
            assert point_violations(sim_a.world, *sim_a.ee) == []


# ---------------------------------------------------------------------- planning / paths
def test_plan_straight_path(sim_open: Simulator) -> None:
    r = sim_open.call("plan_path", {"start": {"x": 0.5, "y": 0.0}, "goal": {"x": 0.0, "y": 1.0}})
    assert r.ok and len(r.data["waypoints"]) == 2


def test_plan_detour_is_valid_and_deterministic(worlds: dict[str, WorldSpec]) -> None:
    args = {"start": {"x": -1.0, "y": 0.0}, "goal": {"x": 1.0, "y": 0.0}}
    a = Simulator(worlds["cell_c"]).call("plan_path", args)
    b = Simulator(worlds["cell_c"]).call("plan_path", args)
    assert a.ok and len(a.data["waypoints"]) >= 3
    assert a.data == b.data
    v = Simulator(worlds["cell_c"]).call("validate_path", {"waypoints": a.data["waypoints"]})
    assert v.data["path_valid"] is True


def test_plan_fails_when_goal_unsafe(sim_a: Simulator) -> None:
    r = sim_a.call("plan_path", {"start": {"x": 1.0, "y": -0.5}, "goal": {"x": 1.2, "y": 0.9}})
    assert not r.ok and r.error_code == ToolErrorCode.COLLISION


def test_plan_fails_through_wall(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(worlds["cell_walled"])
    r = sim.call("plan_path", {"start": {"x": -1.0, "y": -1.5}, "goal": {"x": 1.0, "y": 1.5}})
    assert not r.ok and r.error_code == ToolErrorCode.PLANNING_FAILED


def test_validate_path_reports_collision_segment(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(worlds["cell_c"])
    r = sim.call("validate_path", {"waypoints": [{"x": -1.0, "y": 0.0}, {"x": 1.0, "y": 0.0}]})
    assert r.ok and r.data["path_valid"] is False
    assert r.data["primary_violation"] == "PATH_COLLISION"
    assert r.data["segments"][0]["ok"] is False


def test_validate_path_inner_reach_violation(sim_a: Simulator) -> None:
    # segment passes within 0.1 m of the base (reach_min 0.3) although both ends are fine
    r = sim_a.call("validate_path", {"waypoints": [{"x": -1.0, "y": 0.1}, {"x": 1.0, "y": 0.1}]})
    assert "PATH_UNREACHABLE" in r.data["violation_codes"]


def test_feasibility_weld_is_stricter_than_inspect(sim_a: Simulator) -> None:
    # clearance 0.1 to o1: ok for inspect (margin 0.1), not for weld (0.25)
    p = {"x": 1.56, "y": 1.38}
    assert sim_a.call("estimate_operation_feasibility", {"operation": "inspect_point", **p}).data[
        "feasible"
    ]
    w = sim_a.call("estimate_operation_feasibility", {"operation": "weld_point", **p})
    assert not w.data["feasible"] and w.data["failed_preconditions"] == ["INSUFFICIENT_CLEARANCE"]


# ------------------------------------------------------------------- meta tools / faults
def test_inspect_tool_schema(sim_a: Simulator) -> None:
    allr = sim_a.call("inspect_tool_schema", {})
    assert len(allr.data["tools"]) == len(TOOL_REGISTRY)
    one = sim_a.call("inspect_tool_schema", {"tool_name": "check_clearance"})
    assert one.data["required_args"] == ["x", "y"]
    assert sim_a.call("inspect_tool_schema", {"tool_name": "nope"}).error_code == (
        ToolErrorCode.UNKNOWN_TOOL
    )


def test_diagnostics_last_and_by_id(sim_a: Simulator) -> None:
    assert sim_a.call("get_simulation_diagnostics", {}).error_code == (
        ToolErrorCode.OPERATION_NOT_FOUND
    )
    r1 = sim_a.call("check_reachability", {"x": 1.0, "y": 1.0})
    sim_a.call("check_collision", {"x": 0.0, "y": 0.5})
    last = sim_a.call("get_simulation_diagnostics", {})
    assert last.data["operation_tool"] == "check_collision"
    by_id = sim_a.call("get_simulation_diagnostics", {"operation_id": r1.operation_id})
    assert by_id.data["operation_tool"] == "check_reachability"
    # diagnostics/schema calls are meta and are not themselves logged
    assert len(sim_a.state.op_log) == 2


def test_fault_injection_transient_then_ok(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(
        worlds["cell_a"], faults=[FaultSpec(tool="check_collision", kind="timeout", fail_first_n=1)]
    )
    a = sim.call("check_collision", {"x": 0.0, "y": 0.5})
    assert not a.ok and a.error_code == ToolErrorCode.TOOL_TIMEOUT and a.data["injected"]
    assert sim.state.op_log == []
    assert sim.call("check_collision", {"x": 0.0, "y": 0.5}).ok


def test_fault_injection_persistent(worlds: dict[str, WorldSpec]) -> None:
    sim = Simulator(
        worlds["cell_a"],
        faults=[FaultSpec(tool="check_reachability", kind="unavailable", fail_first_n=99)],
    )
    for _ in range(5):
        assert sim.call("check_reachability", {"x": 1.0, "y": 1.0}).error_code == (
            ToolErrorCode.TOOL_UNAVAILABLE
        )
    assert sim.call("check_collision", {"x": 1.0, "y": 1.0}).ok  # other tools unaffected


def test_results_are_json_serialisable(sim_a: Simulator) -> None:
    import json

    for tool, args in [
        ("get_workcell_state", {}),
        ("check_clearance", {"x": 0.0, "y": 0.5}),
        ("plan_path", {"start": {"x": 1.0, "y": -0.5}, "goal": {"x": -1.0, "y": -0.5}}),
    ]:
        json.dumps(sim_a.call(tool, args).model_dump(mode="json"), allow_nan=False)


def test_float_robustness_no_nan_in_outputs(sim_a: Simulator) -> None:
    r = sim_a.call("check_clearance", {"x": 1.2, "y": 0.9})  # centre of o1
    assert not math.isnan(r.data["min_clearance"]) and r.data["clearance_ok"] is False
