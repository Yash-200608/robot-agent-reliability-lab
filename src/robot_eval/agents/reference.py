"""Deterministic keyword/regex reference agent (Agent A).

A transparent *baseline*, not an intelligent agent and not an upper bound. It never sees held-out
labels or oracle notes. Optional guard components (RQ2) are switched by ``GuardConfig``:

* ``validate_args``    - validate every tool call's arguments client-side before sending;
* ``verify``           - deterministic pre-flight checks before a move and post-verification of
                         planned paths / executed moves (costs extra tool calls);
* ``refuse_overrides`` - refuse requests that tell the agent to ignore or bypass safety checks.

The simulator's own hard constraints are active in every configuration.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from robot_eval.agents import parsing as P
from robot_eval.agents.base import RunContext
from robot_eval.domain.errors import TRANSIENT_FAULT_CODES, AgentStatus, ToolErrorCode
from robot_eval.domain.models import AgentOutput, ToolResult
from robot_eval.tools.client import ToolClient
from robot_eval.tools.registry import TOOL_REGISTRY

OVERRIDE_RE = re.compile(
    r"\b(even if|ignore|ignoring|anyway|regardless|override|bypass|skip|disregard|despite|no matter|"
    r"don'?t care|without (?:checking|validation|validating)|never mind the (?:check|warning))\b",
    re.IGNORECASE,
)
_MOVE_START_RE = re.compile(
    r"^\s*(?:please\s+)?(?:move|go to|go|position|send|drive|bring|take|put|shift|override|ignore|"
    r"proceed|bypass|skip)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuardConfig:
    validate_args: bool = False
    verify: bool = False
    refuse_overrides: bool = False

    @property
    def any(self) -> bool:
        return self.validate_args or self.verify or self.refuse_overrides


def classify(text: str) -> str | None:
    """Ordered keyword rules -> task family name (a Family value) or None."""
    t = text.lower()
    n_pts = len(P.parse_points(text))
    if re.search(r"\b(arguments?|parameters?|schema|inputs?)\b", t) and P.find_tool_name(text):
        return "schema_lookup"
    if "diagnostic" in t:
        return "diagnose_check"
    if re.search(r"how many obstacles|number of obstacles|obstacle count|count the obstacles", t):
        return "describe_state"
    if re.search(
        r"\b(plan|find|generate|compute|come up with)\b.*\b(path|route)\b|\bpath (?:from|between)\b|"
        r"motion path|route the end effector|how can the tool tip travel",
        t,
    ):
        return "plan_path"
    if n_pts >= 2 and re.search(
        r"validate|verify|waypoint|trajectory|route through|collision-free|follows?|pass through|safe",
        t,
    ):
        return "validate_path"
    if re.search(r"\b(shoulder|elbow|wrist|joint)\b", t) and re.search(
        r"deg|°|angle|joint|limit", t
    ):
        return "query_joints"
    if re.search(r"\bweld|\binspect", t):
        return "feasibility"
    if _MOVE_START_RE.search(text):
        return "move"
    if re.search(
        r"clearance|margin|spacing|free space|room around|distance-to-obstacle|buffer|clear of|"
        r"away from|from the obstacles|space to the obstacles|how close",
        t,
    ):
        return "query_clearance"
    if re.search(
        r"collid|collision|\bhit\b|\btouch|intersect|blocked|occupied|inside an obstacle", t
    ):
        return "query_collision"
    if re.search(r"reach|range|extend|get to|able to get", t):
        return "query_reach"
    if re.search(r"\b(move|go to|position|send|drive|bring|shift|put|place|take)\b", t):
        return "move"
    return None


class ReferencePolicy:
    """The shared single-pass policy; also used as the executor of the rule-based two-stage agent."""

    def __init__(self, guards: GuardConfig, max_retries: int = 1) -> None:
        self.guards = guards
        self.max_retries = max_retries

    # ------------------------------------------------------------------ tool plumbing
    def _call(self, tools: ToolClient, tool: str, args: dict[str, Any]) -> ToolResult:
        """Call with optional client-side validation and bounded retry of transient faults."""
        if self.guards.validate_args:
            try:
                TOOL_REGISTRY[tool].args_model.model_validate(args)
            except ValidationError:
                return ToolResult(
                    ok=False,
                    tool=tool,
                    error_code=ToolErrorCode.INVALID_ARGUMENT,
                    message="rejected by client-side argument validation (call not sent)",
                    data={"client_side": True},
                )
        res = tools.call(tool, args)
        retries = 0
        while not res.ok and res.error_code in TRANSIENT_FAULT_CODES and retries < self.max_retries:
            retries += 1
            res = tools.call(tool, args)
        return res

    @staticmethod
    def _fail(res: ToolResult, msg: str = "") -> AgentOutput:
        code = res.error_code.value if res.error_code else None
        return AgentOutput(
            status=AgentStatus.FAILED,
            failure_code=code,
            message=msg or f"{res.tool} failed: {res.message}",
        )

    @staticmethod
    def _clarify(msg: str) -> AgentOutput:
        return AgentOutput(status=AgentStatus.CLARIFICATION, message=msg)

    @staticmethod
    def _done(answer: dict[str, Any], msg: str = "") -> AgentOutput:
        return AgentOutput(status=AgentStatus.COMPLETED, answer=answer, message=msg)

    # ----------------------------------------------------------------------- entry
    def run(self, prompt: str, tools: ToolClient, family: str | None = None) -> AgentOutput:
        fam = family or classify(prompt)
        if fam is None:
            return self._clarify("I could not tell which operation you want. Could you rephrase?")
        if self.guards.refuse_overrides and fam == "move" and OVERRIDE_RE.search(prompt):
            return AgentOutput(
                status=AgentStatus.REFUSED,
                message="I will not skip or override the safety validation for a move.",
            )
        handler = getattr(self, f"_do_{fam}", None)
        if handler is None:
            return self._clarify(f"Unsupported request family {fam!r}.")
        out: AgentOutput = handler(prompt, tools)
        return out

    # ------------------------------------------------------------------- families
    def _need_point(self, prompt: str) -> tuple[tuple[float, float] | None, AgentOutput | None]:
        pp = P.parse_point(prompt)
        if pp.point is None:
            what = (
                "one of the coordinates is not a number"
                if pp.unparsable
                else "no complete x/y target given"
            )
            return None, self._clarify(
                f"I need a numeric x and y position ({what}). Please specify it."
            )
        return pp.point, None

    def _query_point(
        self,
        prompt: str,
        tools: ToolClient,
        tool: str,
        key: str,
        extra: dict[str, Any] | None = None,
    ) -> AgentOutput:
        pt, ask = self._need_point(prompt)
        if ask:
            return ask
        assert pt is not None
        res = self._call(tools, tool, {"x": pt[0], "y": pt[1], **(extra or {})})
        if not res.ok:
            return self._fail(res)
        return self._done({key: res.data[key]})

    def _do_query_reach(self, prompt: str, tools: ToolClient) -> AgentOutput:
        return self._query_point(prompt, tools, "check_reachability", "reachable")

    def _do_query_collision(self, prompt: str, tools: ToolClient) -> AgentOutput:
        return self._query_point(prompt, tools, "check_collision", "collides")

    def _do_query_clearance(self, prompt: str, tools: ToolClient) -> AgentOutput:
        margin = P.parse_margin(prompt)
        extra = {"required_margin": margin} if margin is not None else None
        return self._query_point(prompt, tools, "check_clearance", "clearance_ok", extra)

    def _do_feasibility(self, prompt: str, tools: ToolClient) -> AgentOutput:
        op = "weld_point" if re.search(r"\bweld", prompt, re.IGNORECASE) else "inspect_point"
        pt, ask = self._need_point(prompt)
        if ask:
            return ask
        assert pt is not None
        res = self._call(
            tools, "estimate_operation_feasibility", {"operation": op, "x": pt[0], "y": pt[1]}
        )
        return self._fail(res) if not res.ok else self._done({"feasible": res.data["feasible"]})

    def _do_query_joints(self, prompt: str, tools: ToolClient) -> AgentOutput:
        joints = P.parse_joints(prompt)
        if not joints:
            return self._clarify("Which joint angles (in degrees) should I check?")
        res = self._call(tools, "validate_joint_limits", {"joints": joints})
        return (
            self._fail(res)
            if not res.ok
            else self._done({"within_limits": res.data["within_limits"]})
        )

    def _do_validate_path(self, prompt: str, tools: ToolClient) -> AgentOutput:
        pts = P.parse_points(prompt)
        if len(pts) < 2:
            return self._clarify("A path needs at least two waypoints. Please list them.")
        res = self._call(tools, "validate_path", {"waypoints": [{"x": a, "y": b} for a, b in pts]})
        return self._fail(res) if not res.ok else self._done({"path_valid": res.data["path_valid"]})

    def _do_plan_path(self, prompt: str, tools: ToolClient) -> AgentOutput:
        pts = P.parse_points(prompt)
        if len(pts) < 2:
            return self._clarify("I need both a start and a goal position for planning.")
        res = self._call(
            tools,
            "plan_path",
            {"start": {"x": pts[0][0], "y": pts[0][1]}, "goal": {"x": pts[-1][0], "y": pts[-1][1]}},
        )
        if not res.ok:
            return self._fail(res)
        wps = res.data["waypoints"]
        answer: dict[str, Any] = {"path_found": True, "waypoints": wps}
        wants_check = bool(
            re.search(
                r"validate|verify|double-check|check (?:that|the) (?:route|path)|check that route|afterwards",
                prompt,
                re.IGNORECASE,
            )
        )
        if wants_check or self.guards.verify:
            vr = self._call(tools, "validate_path", {"waypoints": wps})
            if not vr.ok:
                return self._fail(vr)
            if self.guards.verify and not vr.data["path_valid"]:
                return AgentOutput(
                    status=AgentStatus.FAILED,
                    failure_code=ToolErrorCode.PLANNING_FAILED.value,
                    message="planned path failed independent validation",
                )
            if wants_check:
                answer["path_valid"] = vr.data["path_valid"]
        return self._done(answer)

    def _do_describe_state(self, prompt: str, tools: ToolClient) -> AgentOutput:
        res = self._call(tools, "get_workcell_state", {})
        return (
            self._fail(res)
            if not res.ok
            else self._done({"num_obstacles": res.data["num_obstacles"]})
        )

    def _do_schema_lookup(self, prompt: str, tools: ToolClient) -> AgentOutput:
        name = P.find_tool_name(prompt)
        res = self._call(tools, "inspect_tool_schema", {"tool_name": name})
        return (
            self._fail(res)
            if not res.ok
            else self._done({"required_args": res.data["required_args"]})
        )

    def _do_diagnose_check(self, prompt: str, tools: ToolClient) -> AgentOutput:
        t = prompt.lower()
        tool = "check_reachability" if "reach" in t else "check_collision"
        pt, ask = self._need_point(prompt)
        if ask:
            return ask
        assert pt is not None
        res = self._call(tools, tool, {"x": pt[0], "y": pt[1]})
        if not res.ok:
            return self._fail(res)
        dr = self._call(
            tools,
            "get_simulation_diagnostics",
            {"operation_id": res.operation_id} if res.operation_id else {},
        )
        if not dr.ok:
            return self._fail(dr)
        return self._done({"operation_tool": dr.data["operation_tool"]})

    def _do_move(self, prompt: str, tools: ToolClient) -> AgentOutput:
        pt, ask = self._need_point(prompt)
        if ask:
            return ask
        assert pt is not None
        x, y = pt
        if self.guards.verify:
            pre = self._preflight(prompt, tools, x, y)
            if pre is not None:
                return pre
        res = self._call(tools, "move_end_effector", {"x": x, "y": y})
        if not res.ok:
            return self._fail(res)
        if self.guards.verify:
            st = self._call(tools, "get_workcell_state", {})
            if not st.ok:
                return self._fail(st)
            ee = st.data["end_effector"]
            if abs(ee["x"] - x) > 1e-6 or abs(ee["y"] - y) > 1e-6:
                return AgentOutput(
                    status=AgentStatus.FAILED,
                    failure_code=ToolErrorCode.PRECONDITION_FAILED.value,
                    message="post-move verification found the end effector away from the target",
                )
        return self._done({}, f"Moved the end effector to ({x}, {y}).")

    def _preflight(self, prompt: str, tools: ToolClient, x: float, y: float) -> AgentOutput | None:
        """Deterministic pre-move verification. Returns a failure output, or None if all clear."""
        st = self._call(tools, "get_workcell_state", {})
        if not st.ok:
            return self._fail(st)
        ee = st.data["end_effector"]
        fe = self._call(
            tools, "estimate_operation_feasibility", {"operation": "inspect_point", "x": x, "y": y}
        )
        if not fe.ok:
            return self._fail(fe)
        if not fe.data["feasible"]:
            code = (fe.data["failed_preconditions"] or ["PRECONDITION_FAILED"])[0]
            return AgentOutput(
                status=AgentStatus.FAILED,
                failure_code=code,
                message="target failed pre-flight checks",
            )
        margin = P.parse_margin(prompt)
        if margin is not None:
            cl = self._call(tools, "check_clearance", {"x": x, "y": y, "required_margin": margin})
            if not cl.ok:
                return self._fail(cl)
            if not cl.data["clearance_ok"]:
                return AgentOutput(
                    status=AgentStatus.FAILED,
                    failure_code=ToolErrorCode.INSUFFICIENT_CLEARANCE.value,
                    message="requested clearance is not available at the target",
                )
        vp = self._call(
            tools, "validate_path", {"waypoints": [{"x": ee["x"], "y": ee["y"]}, {"x": x, "y": y}]}
        )
        if not vp.ok:
            return self._fail(vp)
        if not vp.data["path_valid"]:
            return AgentOutput(
                status=AgentStatus.FAILED,
                failure_code=vp.data["primary_violation"],
                message="straight-line path to the target failed pre-flight validation",
            )
        return None


class ReferenceAgent:
    """Single-stage rule-based agent: classify -> extract -> call -> report."""

    is_fixture = False
    model_id: str | None = None

    def __init__(
        self,
        name: str = "reference",
        guards: GuardConfig | None = None,
        max_retries: int = 1,
        regress: str | None = None,
    ) -> None:
        self.name = name
        self.guards = guards or GuardConfig()
        self.policy = ReferencePolicy(self.guards, max_retries)
        self.regress = regress  # test-only knob used by the regression experiment (see below)
        self.version = "1.0"

    def describe(self) -> dict[str, Any]:
        return {
            "type": "reference",
            "guards": self.guards.__dict__,
            "max_retries": self.policy.max_retries,
            "regress": self.regress,
            "llm": False,
        }

    def run(self, prompt: str, tools: ToolClient, ctx: RunContext) -> AgentOutput:
        t0 = time.perf_counter()
        family = classify(prompt)
        if self.regress == "clearance_as_collision" and family == "query_clearance":
            family = "query_collision"  # injected, documented regression (Experiment 5)
        out = self.policy.run(prompt, tools, family)
        out.stages = [{"stage": "single", "latency_ms": (time.perf_counter() - t0) * 1000.0}]
        return out
