"""Strict argument schemas for every simulated tool (unknown fields and NaN/inf rejected)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from robot_eval.domain.models import Coord, Point, StrictModel

JointValue = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-3600.0, le=3600.0)]
Margin = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.0, le=100.0)]


class NoArgs(StrictModel):
    pass


class PointArgs(StrictModel):
    x: Coord = Field(description="X coordinate in metres (workcell frame, x to the right).")
    y: Coord = Field(description="Y coordinate in metres (workcell frame, y up).")


class ClearanceArgs(PointArgs):
    required_margin: Margin | None = Field(
        default=None,
        description="Required clearance in metres; defaults to the workcell clearance margin.",
    )


class JointArgs(StrictModel):
    joints: dict[str, JointValue] = Field(
        min_length=1,
        description="Joint name -> angle in degrees. Known joints: shoulder, elbow, wrist.",
    )


class PlanArgs(StrictModel):
    start: Point
    goal: Point


class PathArgs(StrictModel):
    waypoints: list[Point] = Field(
        min_length=2, max_length=50, description="Ordered waypoints (metres), at least two."
    )


class FeasibilityArgs(StrictModel):
    operation: Literal["weld_point", "inspect_point"] = Field(
        description="Simulated operation: weld_point (stricter clearance) or inspect_point."
    )
    x: Coord
    y: Coord


class SchemaArgs(StrictModel):
    tool_name: str | None = Field(
        default=None, max_length=100, description="Tool to describe; omit to list all tools."
    )


class DiagnosticsArgs(StrictModel):
    operation_id: str | None = Field(
        default=None,
        max_length=32,
        description="Operation id such as 'op-0001'; omit for the most recent operation.",
    )
