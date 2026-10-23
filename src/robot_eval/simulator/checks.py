"""Shared geometric checks (float implementation) used by the tools and by ``move``.

Point-level violation codes: OUT_OF_BOUNDS, TARGET_UNREACHABLE, COLLISION, INSUFFICIENT_CLEARANCE.
Segment-level violation codes: PATH_UNREACHABLE, PATH_COLLISION, PATH_CLEARANCE.
"""

from __future__ import annotations

from dataclasses import dataclass

from robot_eval.domain.errors import VIOLATION_PRECEDENCE, ToolErrorCode
from robot_eval.simulator.geometry import (
    EPS,
    dist,
    in_rect,
    point_segment_distance,
    rect_signed_distance,
)
from robot_eval.simulator.world import WorldSpec


@dataclass(frozen=True)
class PointReport:
    in_workspace: bool
    distance_from_base: float
    in_reach_band: bool
    min_clearance: float | None  # to nearest obstacle surface; None when there are no obstacles
    nearest_obstacle: str | None
    boundary_distance: float

    @property
    def reachable(self) -> bool:
        return self.in_workspace and self.in_reach_band

    @property
    def collides(self) -> bool:
        return self.min_clearance is not None and self.min_clearance <= EPS


@dataclass(frozen=True)
class SegmentReport:
    min_clearance: float | None
    nearest_obstacle: str | None
    min_distance_from_base: float


def point_report(world: WorldSpec, x: float, y: float) -> PointReport:
    ws = world.workspace
    d_base = dist(x, y, world.base.x, world.base.y)
    best: float | None = None
    best_id: str | None = None
    for o in world.obstacles:
        c = dist(x, y, o.x, o.y) - o.radius
        if best is None or c < best:
            best, best_id = c, o.id
    return PointReport(
        in_workspace=in_rect(x, y, ws.x_min, ws.x_max, ws.y_min, ws.y_max),
        distance_from_base=d_base,
        in_reach_band=(world.reach_min - EPS) <= d_base <= (world.reach_max + EPS),
        min_clearance=best,
        nearest_obstacle=best_id,
        boundary_distance=rect_signed_distance(x, y, ws.x_min, ws.x_max, ws.y_min, ws.y_max),
    )


def segment_report(world: WorldSpec, ax: float, ay: float, bx: float, by: float) -> SegmentReport:
    best: float | None = None
    best_id: str | None = None
    for o in world.obstacles:
        c = point_segment_distance(o.x, o.y, ax, ay, bx, by) - o.radius
        if best is None or c < best:
            best, best_id = c, o.id
    return SegmentReport(
        min_clearance=best,
        nearest_obstacle=best_id,
        min_distance_from_base=point_segment_distance(world.base.x, world.base.y, ax, ay, bx, by),
    )


def clearance_ok(min_clearance: float | None, required: float) -> bool:
    return min_clearance is None or min_clearance >= required - EPS


def point_violations(
    world: WorldSpec, x: float, y: float, margin: float | None = None
) -> list[ToolErrorCode]:
    """All point-level violations, in precedence order."""
    req = world.clearance_margin if margin is None else margin
    rep = point_report(world, x, y)
    out: list[ToolErrorCode] = []
    if not rep.in_workspace:
        out.append(ToolErrorCode.OUT_OF_BOUNDS)
    if not rep.in_reach_band:
        out.append(ToolErrorCode.TARGET_UNREACHABLE)
    if rep.collides:
        out.append(ToolErrorCode.COLLISION)
    elif not clearance_ok(rep.min_clearance, req):
        out.append(ToolErrorCode.INSUFFICIENT_CLEARANCE)
    return out


def segment_violations(
    world: WorldSpec, ax: float, ay: float, bx: float, by: float, margin: float | None = None
) -> list[ToolErrorCode]:
    """All segment-level violations, in precedence order."""
    req = world.clearance_margin if margin is None else margin
    rep = segment_report(world, ax, ay, bx, by)
    out: list[ToolErrorCode] = []
    if rep.min_distance_from_base < world.reach_min - EPS:
        out.append(ToolErrorCode.PATH_UNREACHABLE)
    if rep.min_clearance is not None and rep.min_clearance <= EPS:
        out.append(ToolErrorCode.PATH_COLLISION)
    elif not clearance_ok(rep.min_clearance, req):
        out.append(ToolErrorCode.PATH_CLEARANCE)
    return out


def primary(codes: list[ToolErrorCode]) -> ToolErrorCode | None:
    for c in VIOLATION_PRECEDENCE:
        if c in codes:
            return c
    return None
