"""Deterministic fault-injection *test fixtures* (Agent B). These are NOT language models.

Each mode reproduces one failure category so the evaluator, metrics and regression checks can be
tested with known expected outcomes.
"""

from __future__ import annotations

import time
from typing import Any

from robot_eval.agents import parsing as P
from robot_eval.agents.base import RunContext
from robot_eval.agents.reference import classify
from robot_eval.domain.errors import AgentStatus
from robot_eval.domain.models import AgentOutput
from robot_eval.tools.client import ToolClient

MODES = (
    "wrong_tool",
    "malformed_args",
    "missing_args",
    "refuse_all",
    "clarify_all",
    "crash",
    "timeout",
    "fabricate",
    "always_move",
    "blind_retry",
    "tool_spam",
)


class MockAgent:
    is_fixture = True
    model_id: str | None = None

    def __init__(self, mode: str, name: str | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mock mode {mode!r}; choose from {MODES}")
        self.mode = mode
        self.name = name or f"mock_{mode}"
        self.version = "1.0"

    def describe(self) -> dict[str, Any]:
        return {"type": "mock_fixture", "mode": self.mode, "llm": False}

    def run(self, prompt: str, tools: ToolClient, ctx: RunContext) -> AgentOutput:
        m = self.mode
        pt = P.parse_point(prompt).point or (0.0, 0.0)
        if m == "refuse_all":
            return AgentOutput(status=AgentStatus.REFUSED, message="fixture: refuse everything")
        if m == "clarify_all":
            return AgentOutput(status=AgentStatus.CLARIFICATION, message="fixture: always ask")
        if m == "crash":
            # built at runtime so source scanners do not mistake this fake value for a real key
            raise RuntimeError(
                "fixture crash with token=" + "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
            )
        if m == "timeout":
            raise TimeoutError("fixture timeout")
        if m == "fabricate":
            # claims every safety check passed without calling any tool
            return AgentOutput(
                status=AgentStatus.COMPLETED,
                answer={
                    "reachable": True,
                    "collides": False,
                    "clearance_ok": True,
                    "within_limits": True,
                    "path_valid": True,
                    "feasible": True,
                    "path_found": True,
                },
                message="fixture: fabricated answer, no tools used",
            )
        if m == "wrong_tool":
            res = tools.call("check_collision", {"x": pt[0], "y": pt[1]})
            return AgentOutput(
                status=AgentStatus.COMPLETED, answer={"collides": res.data.get("collides")}
            )
        if m == "malformed_args":
            tools.call("check_reachability", {"x": "not-a-number", "y": pt[1]})
            return AgentOutput(status=AgentStatus.FAILED, failure_code="INVALID_ARGUMENT")
        if m == "missing_args":
            tools.call("check_reachability", {})
            return AgentOutput(status=AgentStatus.FAILED, failure_code="INVALID_ARGUMENT")
        if m == "always_move":
            res = tools.call("move_end_effector", {"x": pt[0], "y": pt[1]})
            if res.ok:
                return AgentOutput(status=AgentStatus.COMPLETED, answer={})
            return AgentOutput(
                status=AgentStatus.FAILED,
                failure_code=res.error_code.value if res.error_code else None,
            )
        if m == "blind_retry":
            fam = classify(prompt) or "query_reach"
            tool = {"query_collision": "check_collision", "query_clearance": "check_clearance"}.get(
                fam, "check_reachability"
            )
            res = tools.call(tool, {"x": pt[0], "y": pt[1]})
            for _ in range(7):
                if res.ok:
                    break
                res = tools.call(tool, {"x": pt[0], "y": pt[1]})
            return AgentOutput(
                status=AgentStatus.FAILED,
                failure_code=res.error_code.value if res.error_code else None,
            )
        if m == "tool_spam":
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 5:
                tools.call("get_workcell_state", {})
        return AgentOutput(status=AgentStatus.FAILED, message="fixture: unreachable")
