"""The simulator facade: validation, fault injection, dispatch, operation log."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from robot_eval.domain.errors import ToolErrorCode
from robot_eval.domain.models import ToolResult
from robot_eval.simulator.state import OperationRecord, SimState
from robot_eval.simulator.world import FaultSpec, WorldSpec
from robot_eval.tools.registry import TOOL_REGISTRY

_FAULT_CODES = {
    "timeout": ToolErrorCode.TOOL_TIMEOUT,
    "unavailable": ToolErrorCode.TOOL_UNAVAILABLE,
    "internal_error": ToolErrorCode.TOOL_INTERNAL_ERROR,
}


def _summarize_validation_error(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"loc": ".".join(str(p) for p in e["loc"]), "type": e["type"], "msg": e["msg"]}
        for e in exc.errors(include_url=False, include_input=False, include_context=False)
    ]


class Simulator:
    """Deterministic simulator. The only mutable world state is the end-effector pose.

    Invariants (tested):
      * a call whose arguments fail schema validation changes nothing (not even the log);
      * a rejected ``move_end_effector`` leaves the end-effector pose unchanged;
      * injected faults are checked before validation and also change nothing.
    """

    def __init__(self, world: WorldSpec, faults: Iterable[FaultSpec] = ()) -> None:
        self.state = SimState.initial(world)
        self._faults = tuple(faults)
        self._fault_calls: dict[int, int] = {}

    @property
    def world(self) -> WorldSpec:
        return self.state.world

    @property
    def ee(self) -> tuple[float, float]:
        return self.state.ee

    def world_fingerprint(self) -> str:
        """Hash of the world state proper (end-effector pose)."""
        return hashlib.sha256(json.dumps(self.state.ee).encode()).hexdigest()[:16]

    def full_fingerprint(self) -> str:
        """Hash of pose plus operation-log length."""
        payload = json.dumps([self.state.ee, len(self.state.op_log)])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _maybe_fault(self, tool: str) -> ToolResult | None:
        for i, f in enumerate(self._faults):
            if f.tool != tool:
                continue
            n = self._fault_calls.get(i, 0)
            if n < f.fail_first_n:
                self._fault_calls[i] = n + 1
                code = _FAULT_CODES[f.kind]
                return ToolResult(
                    ok=False,
                    tool=tool,
                    error_code=code,
                    message=f"injected fault: {f.kind}",
                    data={"injected": True, "attempt": n + 1},
                )
        return None

    def call(self, tool: str, arguments: Any) -> ToolResult:
        spec = TOOL_REGISTRY.get(tool)
        if spec is None:
            return ToolResult(
                ok=False,
                tool=tool,
                error_code=ToolErrorCode.UNKNOWN_TOOL,
                message=f"unknown tool {tool!r}",
                data={"known_tools": sorted(TOOL_REGISTRY)},
            )
        fault = self._maybe_fault(tool)
        if fault is not None:
            return fault
        if not isinstance(arguments, dict):
            return ToolResult(
                ok=False,
                tool=tool,
                error_code=ToolErrorCode.INVALID_ARGUMENT,
                message="arguments must be a JSON object",
            )
        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                tool=tool,
                error_code=ToolErrorCode.INVALID_ARGUMENT,
                message="argument validation failed",
                data={"errors": _summarize_validation_error(exc)},
            )
        before = self.state.ee
        result = spec.handler(self.state, args)
        if not spec.meta:
            op_id = f"op-{len(self.state.op_log) + 1:04d}"
            self.state.op_log.append(
                OperationRecord(
                    operation_id=op_id,
                    tool=tool,
                    arguments=args.model_dump(mode="json"),
                    ok=result.ok,
                    error_code=result.error_code,
                    state_changed=self.state.ee != before,
                )
            )
            result = result.model_copy(update={"operation_id": op_id})
        return result
