"""Tool clients: the interface agents use to call tools, plus the recording wrapper.

The evaluator only trusts what ``RecordingToolClient`` observed, never an agent's own account.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from robot_eval.domain.models import ToolCallRecord, ToolResult
from robot_eval.simulator.sim import Simulator
from robot_eval.tools.registry import tool_descriptors


class ToolClient(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def set_stage(self, stage: str | None) -> None: ...


class ToolBudgetExceeded(RuntimeError):
    """Raised by the recording client when an agent exceeds the per-case tool-call budget."""


class SimulatorToolClient:
    """In-process client bound to a :class:`Simulator`."""

    def __init__(self, sim: Simulator) -> None:
        self.sim = sim

    def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        return self.sim.call(tool, arguments)

    def list_tools(self) -> list[dict[str, Any]]:
        return tool_descriptors()

    def set_stage(self, stage: str | None) -> None:
        return None


class RecordingToolClient:
    """Wraps a client + simulator, recording every call with latency and pose before/after."""

    def __init__(self, inner: SimulatorToolClient, max_calls: int = 40) -> None:
        self.inner = inner
        self.records: list[ToolCallRecord] = []
        self.stage: str | None = None
        self.max_calls = max_calls

    def set_stage(self, stage: str | None) -> None:
        self.stage = stage

    def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        if len(self.records) >= self.max_calls:
            raise ToolBudgetExceeded(f"tool-call budget of {self.max_calls} exceeded")
        sim = self.inner.sim
        before = sim.ee
        t0 = time.perf_counter()
        result = self.inner.call(tool, arguments)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self.records.append(
            ToolCallRecord(
                index=len(self.records),
                tool=tool,
                arguments=arguments,
                result=result,
                latency_ms=latency_ms,
                ee_before=before,
                ee_after=sim.ee,
                stage=self.stage,
            )
        )
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        return self.inner.list_tools()
