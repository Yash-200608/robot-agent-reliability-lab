"""Independent exact-arithmetic geometry oracle.

This module deliberately does **not** import ``robot_eval.simulator.geometry`` or
``robot_eval.simulator.checks``. All decisions are made with :class:`fractions.Fraction` on
*squared* distances (no square roots, no tolerances), so boundary equalities are decided exactly.
Decimal inputs are interpreted as written (``0.1`` means 1/10).

Semantics mirrored from the documented contract:
  * obstacle = closed disc; clearance == 0 is a collision;
  * required margin met when distance >= radius + margin (equality is safe);
  * reach band, workspace and joint limits are closed intervals.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Fr

from robot_eval.domain.errors import VIOLATION_PRECEDENCE, ToolErrorCode
from robot_eval.simulator.world import WorldSpec

Pt = tuple[Fr, Fr]


def fr(v: float | int) -> Fr:
    """Exact decimal interpretation of a float literal (via its shortest repr)."""
    return Fr(repr(float(v)))


def pt(x: float, y: float) -> Pt:
    return (fr(x), fr(y))


@dataclass(frozen=True)
class ExactWorld:
    base: Pt
    reach_min: Fr
    reach_max: Fr
    margin: Fr
    weld_margin: Fr
    ws: tuple[Fr, Fr, Fr, Fr]  # x_min, x_max, y_min, y_max
    obstacles: tuple[tuple[Pt, Fr], ...]
    joints: dict[str, tuple[Fr, Fr]]
    home: Pt


def exact_world(w: WorldSpec) -> ExactWorld:
    s = w.workspace
    return ExactWorld(
        base=pt(w.base.x, w.base.y),
        reach_min=fr(w.reach_min),
        reach_max=fr(w.reach_max),
        margin=fr(w.clearance_margin),
        weld_margin=fr(w.weld_clearance_margin),
        ws=(fr(s.x_min), fr(s.x_max), fr(s.y_min), fr(s.y_max)),
        obstacles=tuple((pt(o.x, o.y), fr(o.radius)) for o in w.obstacles),
        joints={k: (fr(v.min), fr(v.max)) for k, v in w.joint_limits.items()},
        home=pt(w.home.x, w.home.y),
    )


def _d2(a: Pt, b: Pt) -> Fr:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _seg_d2(p: Pt, a: Pt, b: Pt) -> Fr:
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return _d2(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2
    t = max(Fr(0), min(Fr(1), t))
    return _d2(p, (a[0] + t * dx, a[1] + t * dy))


def in_workspace(ew: ExactWorld, p: Pt) -> bool:
    x0, x1, y0, y1 = ew.ws
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def in_reach_band(ew: ExactWorld, p: Pt) -> bool:
    d2 = _d2(p, ew.base)
    return ew.reach_min**2 <= d2 <= ew.reach_max**2


def collides(ew: ExactWorld, p: Pt) -> bool:
    return any(_d2(p, c) <= r * r for c, r in ew.obstacles)


def clearance_met(ew: ExactWorld, p: Pt, margin: Fr) -> bool:
    return all(_d2(p, c) >= (r + margin) ** 2 for c, r in ew.obstacles)


def point_codes(ew: ExactWorld, p: Pt, margin: Fr | None = None) -> list[ToolErrorCode]:
    m = ew.margin if margin is None else margin
    out: list[ToolErrorCode] = []
    if not in_workspace(ew, p):
        out.append(ToolErrorCode.OUT_OF_BOUNDS)
    if not in_reach_band(ew, p):
        out.append(ToolErrorCode.TARGET_UNREACHABLE)
    if collides(ew, p):
        out.append(ToolErrorCode.COLLISION)
    elif not clearance_met(ew, p, m):
        out.append(ToolErrorCode.INSUFFICIENT_CLEARANCE)
    return out


def segment_codes(ew: ExactWorld, a: Pt, b: Pt, margin: Fr | None = None) -> list[ToolErrorCode]:
    m = ew.margin if margin is None else margin
    out: list[ToolErrorCode] = []
    if _seg_d2(ew.base, a, b) < ew.reach_min**2:
        out.append(ToolErrorCode.PATH_UNREACHABLE)
    if any(_seg_d2(c, a, b) <= r * r for c, r in ew.obstacles):
        out.append(ToolErrorCode.PATH_COLLISION)
    elif any(_seg_d2(c, a, b) < (r + m) ** 2 for c, r in ew.obstacles):
        out.append(ToolErrorCode.PATH_CLEARANCE)
    return out


def ordered(codes: list[ToolErrorCode]) -> list[ToolErrorCode]:
    s = set(codes)
    return [c for c in VIOLATION_PRECEDENCE if c in s]


def reachable(ew: ExactWorld, p: Pt) -> bool:
    return in_workspace(ew, p) and in_reach_band(ew, p)


def move_codes(ew: ExactWorld, ee: Pt, target: Pt) -> list[ToolErrorCode]:
    """All violated codes for a straight-line move from ``ee`` to ``target`` (precedence order)."""
    return ordered(point_codes(ew, target) + segment_codes(ew, ee, target))


def path_codes(ew: ExactWorld, pts: list[Pt]) -> list[ToolErrorCode]:
    codes: list[ToolErrorCode] = []
    for p in pts:
        codes += point_codes(ew, p)
    for a, b in zip(pts, pts[1:], strict=False):
        codes += segment_codes(ew, a, b)
    return ordered(codes)


def feasibility_codes(ew: ExactWorld, operation: str, p: Pt) -> list[ToolErrorCode]:
    margin = ew.weld_margin if operation == "weld_point" else ew.margin
    return point_codes(ew, p, margin)


def joints_within(ew: ExactWorld, joints: dict[str, float]) -> bool:
    for name, v in joints.items():
        lo, hi = ew.joints[name]
        if not (lo <= fr(v) <= hi):
            return False
    return True
