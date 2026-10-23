"""Simulated robotics-style tools: handlers, descriptions and the registry.

Every handler receives *already validated* arguments and the mutable ``SimState``. Only
``move_end_effector`` mutates the world, and only after every check has passed.
Handlers are pure Python, deterministic, and have no network or hardware access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from robot_eval.domain.errors import VIOLATION_PRECEDENCE, ToolErrorCode
from robot_eval.domain.models import ToolResult
from robot_eval.simulator import checks, planner
from robot_eval.simulator.geometry import EPS, dist
from robot_eval.simulator.state import SimState
from robot_eval.tools import schemas as S

Handler = Callable[[SimState, Any], ToolResult]


def _ok(tool: str, data: dict[str, Any], message: str = "") -> ToolResult:
    return ToolResult(ok=True, tool=tool, message=message, data=data)


def _fail(
    tool: str, code: ToolErrorCode, message: str, data: dict[str, Any] | None = None
) -> ToolResult:
    return ToolResult(ok=False, tool=tool, error_code=code, message=message, data=data or {})


def _r(v: float | None, nd: int = 6) -> float | None:
    return None if v is None else round(v, nd)


# --------------------------------------------------------------------------- read-only tools
def get_workcell_state(state: SimState, _: S.NoArgs) -> ToolResult:
    w = state.world
    return _ok(
        "get_workcell_state",
        {
            "world_id": w.world_id,
            "units": {"length": "m", "angle": "deg"},
            "workspace": w.workspace.model_dump(),
            "robot_base": w.base.model_dump(),
            "reach": {"min": w.reach_min, "max": w.reach_max},
            "clearance_margin": w.clearance_margin,
            "weld_clearance_margin": w.weld_clearance_margin,
            "obstacles": [o.model_dump() for o in w.obstacles],
            "num_obstacles": len(w.obstacles),
            "joint_limits": {k: v.model_dump() for k, v in w.joint_limits.items()},
            "end_effector": {"x": state.ee[0], "y": state.ee[1]},
        },
    )


def check_reachability(state: SimState, a: S.PointArgs) -> ToolResult:
    rep = checks.point_report(state.world, a.x, a.y)
    if not rep.in_workspace:
        reason = "out_of_workspace"
    elif rep.distance_from_base > state.world.reach_max + EPS:
        reason = "beyond_max_reach"
    elif rep.distance_from_base < state.world.reach_min - EPS:
        reason = "inside_min_reach"
    else:
        reason = "ok"
    return _ok(
        "check_reachability",
        {
            "reachable": rep.reachable,
            "reason": reason,
            "in_workspace": rep.in_workspace,
            "distance_from_base": _r(rep.distance_from_base),
            "reach_min": state.world.reach_min,
            "reach_max": state.world.reach_max,
        },
    )


def check_collision(state: SimState, a: S.PointArgs) -> ToolResult:
    rep = checks.point_report(state.world, a.x, a.y)
    return _ok(
        "check_collision",
        {
            "collides": rep.collides,
            "nearest_obstacle": rep.nearest_obstacle,
            "signed_clearance": _r(rep.min_clearance),
        },
    )


def check_clearance(state: SimState, a: S.ClearanceArgs) -> ToolResult:
    req = state.world.clearance_margin if a.required_margin is None else a.required_margin
    rep = checks.point_report(state.world, a.x, a.y)
    ok = checks.clearance_ok(rep.min_clearance, req) and not rep.collides
    return _ok(
        "check_clearance",
        {
            "clearance_ok": ok,
            "min_clearance": _r(rep.min_clearance),
            "nearest_obstacle": rep.nearest_obstacle,
            "required_margin": req,
            "boundary_distance": _r(rep.boundary_distance),
        },
    )


def validate_joint_limits(state: SimState, a: S.JointArgs) -> ToolResult:
    limits = state.world.joint_limits
    unknown = sorted(set(a.joints) - set(limits))
    if unknown:
        return _fail(
            "validate_joint_limits",
            ToolErrorCode.INVALID_ARGUMENT,
            f"unknown joint(s): {unknown}; known joints: {sorted(limits)}",
            {"unknown_joints": unknown},
        )
    violations = []
    for name in sorted(a.joints):
        v, lim = a.joints[name], limits[name]
        if not (lim.min - EPS <= v <= lim.max + EPS):
            violations.append({"joint": name, "value": v, "min": lim.min, "max": lim.max})
    return _ok(
        "validate_joint_limits",
        {
            "within_limits": not violations,
            "violations": violations,
            "checked": sorted(a.joints),
        },
    )


def _validate_waypoints(
    state: SimState, pts: list[tuple[float, float]]
) -> tuple[bool, list[ToolErrorCode], list[dict[str, Any]]]:
    world = state.world
    codes: set[ToolErrorCode] = set()
    segs: list[dict[str, Any]] = []
    for p in pts:
        codes.update(checks.point_violations(world, p[0], p[1]))
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        sv = checks.segment_violations(world, a[0], a[1], b[0], b[1])
        rep = checks.segment_report(world, a[0], a[1], b[0], b[1])
        codes.update(sv)
        segs.append(
            {
                "index": i,
                "min_clearance": _r(rep.min_clearance),
                "ok": not sv,
                "violations": [c.value for c in sv],
            }
        )
    ordered = [c for c in VIOLATION_PRECEDENCE if c in codes]
    return not ordered, ordered, segs


def validate_path(state: SimState, a: S.PathArgs) -> ToolResult:
    pts = [(p.x, p.y) for p in a.waypoints]
    valid, codes, segs = _validate_waypoints(state, pts)
    return _ok(
        "validate_path",
        {
            "path_valid": valid,
            "violation_codes": [c.value for c in codes],
            "primary_violation": codes[0].value if codes else None,
            "segments": segs,
        },
    )


def plan_path(state: SimState, a: S.PlanArgs) -> ToolResult:
    world = state.world
    s, g = (a.start.x, a.start.y), (a.goal.x, a.goal.y)
    blocking = [c for p in (s, g) for c in checks.point_violations(world, p[0], p[1])]
    if blocking:
        code = checks.primary(blocking) or ToolErrorCode.PLANNING_FAILED
        return _fail(
            "plan_path",
            code,
            "start or goal violates a point-level constraint",
            {"violation_codes": sorted({c.value for c in blocking})},
        )
    path = planner.plan(world, s, g)
    if path is not None:
        valid, _, _ = _validate_waypoints(state, path)
        if not valid:
            path = None
    if path is None:
        return _fail(
            "plan_path",
            ToolErrorCode.PLANNING_FAILED,
            "no collision-free path found by the visibility-graph planner",
        )
    length = sum(dist(p[0], p[1], q[0], q[1]) for p, q in zip(path, path[1:], strict=False))
    return _ok(
        "plan_path",
        {
            "path_found": True,
            "waypoints": [{"x": p[0], "y": p[1]} for p in path],
            "length": _r(length),
        },
    )


def estimate_operation_feasibility(state: SimState, a: S.FeasibilityArgs) -> ToolResult:
    w = state.world
    margin = w.weld_clearance_margin if a.operation == "weld_point" else w.clearance_margin
    failed = checks.point_violations(w, a.x, a.y, margin)
    return _ok(
        "estimate_operation_feasibility",
        {
            "operation": a.operation,
            "feasible": not failed,
            "failed_preconditions": [c.value for c in failed],
            "required_clearance": margin,
        },
    )


# ------------------------------------------------------------------------ state-changing tool
def move_end_effector(state: SimState, a: S.PointArgs) -> ToolResult:
    w = state.world
    start = state.ee
    point_v = checks.point_violations(w, a.x, a.y)
    seg_v = checks.segment_violations(w, start[0], start[1], a.x, a.y)
    violations = point_v + seg_v
    if violations:
        code = checks.primary(violations) or ToolErrorCode.PRECONDITION_FAILED
        return _fail(
            "move_end_effector",
            code,
            "move rejected by simulator safety validation; end effector not moved",
            {"violation_codes": [c.value for c in violations]},
        )
    state.ee = (a.x, a.y)
    return _ok(
        "move_end_effector",
        {
            "moved": True,
            "from": {"x": start[0], "y": start[1]},
            "to": {"x": a.x, "y": a.y},
            "path_length": _r(dist(start[0], start[1], a.x, a.y)),
        },
    )


# ----------------------------------------------------------------------------- meta tools
def inspect_tool_schema(state: SimState, a: S.SchemaArgs) -> ToolResult:
    if a.tool_name is None:
        return _ok(
            "inspect_tool_schema",
            {"tools": [{"name": s.name, "mutating": s.mutating} for s in TOOL_REGISTRY.values()]},
        )
    spec = TOOL_REGISTRY.get(a.tool_name)
    if spec is None:
        return _fail(
            "inspect_tool_schema",
            ToolErrorCode.UNKNOWN_TOOL,
            f"unknown tool: {a.tool_name!r}",
            {"known_tools": sorted(TOOL_REGISTRY)},
        )
    schema = spec.args_model.model_json_schema()
    return _ok(
        "inspect_tool_schema",
        {
            "tool": spec.name,
            "description": spec.description,
            "mutating": spec.mutating,
            "input_schema": schema,
            "required_args": sorted(schema.get("required", [])),
        },
    )


def get_simulation_diagnostics(state: SimState, a: S.DiagnosticsArgs) -> ToolResult:
    log = state.op_log
    rec = None
    if a.operation_id is None:
        rec = log[-1] if log else None
    else:
        rec = next((r for r in log if r.operation_id == a.operation_id), None)
    if rec is None:
        return _fail(
            "get_simulation_diagnostics",
            ToolErrorCode.OPERATION_NOT_FOUND,
            "no matching operation in the log",
            {"logged_operations": len(log)},
        )
    return _ok(
        "get_simulation_diagnostics",
        {
            "operation_id": rec.operation_id,
            "operation_tool": rec.tool,
            "arguments": rec.arguments,
            "operation_ok": rec.ok,
            "operation_error_code": rec.error_code.value if rec.error_code else None,
            "state_changed": rec.state_changed,
        },
    )


# -------------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    mutating: bool = False
    meta: bool = False  # meta tools are not written to the operation log


_SPECS: list[ToolSpec] = [
    ToolSpec(
        "get_workcell_state",
        "Return the full simulated workcell: workspace bounds, robot base, reach band, clearance "
        "margins, obstacles (circles), joint limits and the current end-effector position. "
        "Units: metres and degrees.",
        S.NoArgs,
        get_workcell_state,
    ),
    ToolSpec(
        "check_reachability",
        "Check whether a target point (metres) is inside the workspace AND within the robot's reach "
        "band (reach_min <= distance from base <= reach_max, inclusive). Ignores obstacles and "
        "clearance.",
        S.PointArgs,
        check_reachability,
    ),
    ToolSpec(
        "check_collision",
        "Check whether a single point lies inside or on the edge of any circular obstacle "
        "(touching counts as a collision). Does not check margins (use check_clearance) or path "
        "segments (use validate_path).",
        S.PointArgs,
        check_collision,
    ),
    ToolSpec(
        "check_clearance",
        "Compute the minimum distance from a point to the nearest obstacle surface and compare it "
        "with a required margin (default: the workcell clearance margin). Meeting the margin "
        "exactly is acceptable; a collision always fails.",
        S.ClearanceArgs,
        check_clearance,
    ),
    ToolSpec(
        "validate_joint_limits",
        "Check simulated joint angles (degrees) against the declared inclusive joint limits. "
        "Joints: shoulder, elbow, wrist. Unknown joint names are rejected.",
        S.JointArgs,
        validate_joint_limits,
    ),
    ToolSpec(
        "plan_path",
        "Plan a deterministic collision-free straight or detour path between two points using a "
        "visibility-graph planner. Fails with a structured error if an endpoint is unsafe or no "
        "path is found. Does not move the robot.",
        S.PlanArgs,
        plan_path,
    ),
    ToolSpec(
        "validate_path",
        "Independently check an ordered list of waypoints: every waypoint (bounds, reach, "
        "collision, clearance) and every segment between them (collision, clearance, inner reach "
        "limit). Does not move the robot.",
        S.PathArgs,
        validate_path,
    ),
    ToolSpec(
        "estimate_operation_feasibility",
        "Check preconditions for a simulated operation at a point: 'weld_point' needs the stricter "
        "weld clearance, 'inspect_point' the normal margin; both need the point in bounds, "
        "reachable and collision-free. Simulation only; does not control anything.",
        S.FeasibilityArgs,
        estimate_operation_feasibility,
    ),
    ToolSpec(
        "move_end_effector",
        "STATE-CHANGING. Move the simulated end effector in a straight line from its current "
        "position to (x, y). The simulator independently rejects unsafe moves (out of bounds, "
        "unreachable, collision, insufficient clearance, unsafe path) and leaves the state unchanged.",
        S.PointArgs,
        move_end_effector,
        mutating=True,
    ),
    ToolSpec(
        "inspect_tool_schema",
        "List the available tools, or return the description and JSON argument schema of one tool.",
        S.SchemaArgs,
        inspect_tool_schema,
        meta=True,
    ),
    ToolSpec(
        "get_simulation_diagnostics",
        "Return the logged record (tool, arguments, ok, error code, state_changed) of a previous "
        "simulated operation by id, or of the most recent one when no id is given.",
        S.DiagnosticsArgs,
        get_simulation_diagnostics,
        meta=True,
    ),
]

TOOL_REGISTRY: dict[str, ToolSpec] = {s.name: s for s in _SPECS}
MUTATING_TOOLS: frozenset[str] = frozenset(s.name for s in _SPECS if s.mutating)


def tool_descriptors() -> list[dict[str, Any]]:
    """Machine-readable tool list (name, description, JSON input schema)."""
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.args_model.model_json_schema(),
            "mutating": s.mutating,
        }
        for s in TOOL_REGISTRY.values()
    ]
