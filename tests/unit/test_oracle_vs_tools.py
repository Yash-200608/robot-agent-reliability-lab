"""The float tools must agree with the independent exact oracle (fuzz + hand boundaries)."""

from __future__ import annotations

import random

import pytest

from robot_eval.evaluation import oracle as O
from robot_eval.simulator.checks import point_violations, segment_violations
from robot_eval.simulator.world import WorldSpec


def test_fr_is_exact_decimal() -> None:
    assert O.fr(0.1) == O.Fr(1, 10)
    assert O.fr(0.6) ** 2 == O.Fr(36, 100)


@pytest.mark.parametrize("name", ["cell_a", "cell_b", "cell_c", "cell_open", "cell_walled"])
def test_point_codes_agree_on_grid_fuzz(worlds: dict[str, WorldSpec], name: str) -> None:
    w = worlds[name]
    ew = O.exact_world(w)
    rng = random.Random(1234)
    n_boundary = 0
    for _ in range(4000):
        x = round(rng.randint(-340, 340) / 100, 2)
        y = round(rng.randint(-340, 340) / 100, 2)
        f = [c for c in point_violations(w, x, y)]
        e = O.point_codes(ew, O.pt(x, y))
        assert [c.value for c in f] == [c.value for c in e], (name, x, y)
        n_boundary += 1
    assert n_boundary == 4000


@pytest.mark.parametrize("name", ["cell_a", "cell_b", "cell_c", "cell_walled"])
def test_segment_codes_agree_on_fuzz(worlds: dict[str, WorldSpec], name: str) -> None:
    w = worlds[name]
    ew = O.exact_world(w)
    rng = random.Random(99)
    for _ in range(2000):
        a = (round(rng.randint(-250, 250) / 100, 2), round(rng.randint(-250, 250) / 100, 2))
        b = (round(rng.randint(-250, 250) / 100, 2), round(rng.randint(-250, 250) / 100, 2))
        f = segment_violations(w, a[0], a[1], b[0], b[1])
        e = O.segment_codes(ew, O.pt(*a), O.pt(*b))
        assert [c.value for c in f] == [c.value for c in e], (name, a, b)


def test_exact_boundary_cases_cell_a(worlds: dict[str, WorldSpec]) -> None:
    ew = O.exact_world(worlds["cell_a"])
    # touching o1 (3-4-5): collision
    assert O.collides(ew, O.pt(1.5, 1.3))
    # exactly margin away: safe; one micron inside: not
    assert O.clearance_met(ew, O.pt(1.56, 1.38), ew.margin)
    assert not O.clearance_met(ew, O.pt(1.559999, 1.38), ew.margin)
    # reach boundary exact
    assert O.in_reach_band(ew, O.pt(1.5, 2.0))
    assert not O.in_reach_band(ew, O.pt(1.5, 2.000001))


def test_joint_exactness(worlds: dict[str, WorldSpec]) -> None:
    ew = O.exact_world(worlds["cell_a"])
    assert O.joints_within(ew, {"shoulder": 90.0, "elbow": 150.0, "wrist": -180.0})
    assert not O.joints_within(ew, {"elbow": 150.0000001})
