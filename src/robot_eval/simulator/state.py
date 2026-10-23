"""Mutable simulator state: end-effector pose and an append-only operation log."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from robot_eval.domain.errors import ToolErrorCode
from robot_eval.simulator.world import WorldSpec


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    error_code: ToolErrorCode | None
    state_changed: bool


@dataclass
class SimState:
    world: WorldSpec
    ee: tuple[float, float]
    op_log: list[OperationRecord] = field(default_factory=list)

    @classmethod
    def initial(cls, world: WorldSpec) -> SimState:
        return cls(world=world, ee=(world.home.x, world.home.y))
