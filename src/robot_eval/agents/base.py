"""Common agent contract. The evaluator treats every agent identically through this interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from robot_eval.domain.models import AgentOutput
from robot_eval.tools.client import ToolClient


@dataclass(frozen=True)
class RunContext:
    """Per-case context given to an agent. Deliberately contains no world data, no expected
    result and no oracle information."""

    seed: int = 0
    case_id: str = ""


@runtime_checkable
class Agent(Protocol):
    name: str
    version: str
    model_id: str | None
    is_fixture: bool  # True for test fixtures that are not real agents (mock/fault injection)

    def run(self, prompt: str, tools: ToolClient, ctx: RunContext) -> AgentOutput: ...

    def describe(self) -> dict[str, Any]: ...


# Answer keys the evaluator understands (documented in docs/metric_definitions.md). Agents report
# a structured ``answer`` using these standard keys; they are verified against the oracle.
ANSWER_KEYS: dict[str, str] = {
    "reachable": "bool - target is reachable (check_reachability)",
    "collides": "bool - point collides with an obstacle (check_collision)",
    "clearance_ok": "bool - clearance requirement met (check_clearance)",
    "within_limits": "bool - joint values within limits (validate_joint_limits)",
    "path_found": "bool - a path was planned (plan_path)",
    "waypoints": "list of {x, y} - the planned path",
    "path_valid": "bool - path validated (validate_path)",
    "feasible": "bool - operation feasible (estimate_operation_feasibility)",
    "num_obstacles": "int - number of obstacles (get_workcell_state)",
    "required_args": "list[str] - required argument names (inspect_tool_schema)",
    "operation_tool": "str - tool of a logged operation (get_simulation_diagnostics)",
}
