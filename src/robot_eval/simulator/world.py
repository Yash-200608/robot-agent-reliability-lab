"""Workcell specification (pure data) and loading of named worlds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robot_eval.domain.models import Coord, Point


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Obstacle(_Frozen):
    """Circular obstacle (closed disc) in metres."""

    id: str
    x: Coord
    y: Coord
    radius: float = Field(gt=0, le=100, allow_inf_nan=False)


class JointLimit(_Frozen):
    min: float = Field(allow_inf_nan=False)
    max: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered(self) -> JointLimit:
        if self.min > self.max:
            raise ValueError("joint limit min must be <= max")
        return self


class Workspace(_Frozen):
    x_min: Coord
    x_max: Coord
    y_min: Coord
    y_max: Coord

    @model_validator(mode="after")
    def _ordered(self) -> Workspace:
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("workspace must have positive extent")
        return self


class WorldSpec(_Frozen):
    """Deterministic 2-D workcell. All lengths in metres, joint values in degrees."""

    world_id: str
    description: str = ""
    workspace: Workspace
    base: Point
    reach_min: float = Field(ge=0, allow_inf_nan=False)
    reach_max: float = Field(gt=0, allow_inf_nan=False)
    clearance_margin: float = Field(ge=0, allow_inf_nan=False)
    weld_clearance_margin: float = Field(ge=0, allow_inf_nan=False)
    home: Point
    obstacles: tuple[Obstacle, ...] = ()
    joint_limits: dict[str, JointLimit]

    @model_validator(mode="after")
    def _consistent(self) -> WorldSpec:
        if self.reach_min >= self.reach_max:
            raise ValueError("reach_min must be < reach_max")
        ids = [o.id for o in self.obstacles]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate obstacle ids")
        return self


class FaultSpec(_Frozen):
    """Controlled tool fault: the first ``fail_first_n`` calls to ``tool`` fail."""

    tool: str
    kind: Literal["timeout", "unavailable", "internal_error"]
    fail_first_n: int = Field(ge=1, le=1000)


def load_worlds(path: str | Path) -> dict[str, WorldSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    worlds = {w["world_id"]: WorldSpec.model_validate(w) for w in raw["worlds"]}
    return worlds
