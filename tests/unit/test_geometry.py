from __future__ import annotations

import math

from robot_eval.simulator.geometry import (
    dist,
    in_rect,
    point_segment_distance,
    rect_signed_distance,
)


def test_dist_345() -> None:
    assert dist(0, 0, 3, 4) == 5.0


def test_point_segment_interior_projection() -> None:
    assert point_segment_distance(1, 1, 0, 0, 2, 0) == 1.0


def test_point_segment_clamps_to_endpoints() -> None:
    assert point_segment_distance(-3, 4, 0, 0, 2, 0) == 5.0
    assert point_segment_distance(5, 4, 0, 0, 2, 0) == 5.0


def test_point_segment_degenerate_segment() -> None:
    assert point_segment_distance(3, 4, 0, 0, 0, 0) == 5.0


def test_point_on_segment_is_zero() -> None:
    assert point_segment_distance(1, 0, 0, 0, 2, 0) == 0.0


def test_rect_edges_are_inside() -> None:
    assert in_rect(3.0, 3.0, -3.0, 3.0, -3.0, 3.0)
    assert not in_rect(3.0001, 0.0, -3.0, 3.0, -3.0, 3.0)


def test_rect_signed_distance() -> None:
    assert rect_signed_distance(0, 0, -1, 1, -1, 1) == 1.0
    assert rect_signed_distance(1, 0, -1, 1, -1, 1) == 0.0
    assert rect_signed_distance(4, 5, -1, 1, -1, 1) == -math.hypot(3, 4)
