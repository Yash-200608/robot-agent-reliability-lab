"""Floating-point 2-D geometry primitives used by the simulator tools.

Conventions (see docs/architecture.md): metres, x right, y up, angles in degrees.

Equality semantics are fixed here and mirrored *independently* with exact rational arithmetic in
``robot_eval.evaluation.oracle``:

* an obstacle is a closed disc: touching it (clearance == 0) is a **collision**;
* a required clearance margin is **met** when clearance >= margin (equality is safe);
* reach, workspace and joint limits are closed intervals (equality is inside).

Comparisons tolerate ``EPS`` so that decimal inputs such as 0.6 behave as written.
"""

from __future__ import annotations

import math

EPS = 1e-9


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Minimum distance from point P to the closed segment AB."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return dist(px, py, ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / len2
    t = max(0.0, min(1.0, t))
    return dist(px, py, ax + t * dx, ay + t * dy)


def in_rect(x: float, y: float, x_min: float, x_max: float, y_min: float, y_max: float) -> bool:
    return (x_min - EPS) <= x <= (x_max + EPS) and (y_min - EPS) <= y <= (y_max + EPS)


def rect_signed_distance(
    x: float, y: float, x_min: float, x_max: float, y_min: float, y_max: float
) -> float:
    """Distance to the nearest rectangle edge: positive inside, negative outside."""
    inside = min(x - x_min, x_max - x, y - y_min, y_max - y)
    if inside >= 0:
        return inside
    dx = max(x_min - x, 0.0, x - x_max)
    dy = max(y_min - y, 0.0, y - y_max)
    return -math.hypot(dx, dy)
