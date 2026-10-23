from __future__ import annotations

import math

import pytest

from robot_eval.agents import parsing as P
from robot_eval.agents.reference import classify


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Can the arm reach the point (1.5, 2.0)?", (1.5, 2.0)),
        ("Is x = -0.5, y = 0.25 within reach?", (-0.5, 0.25)),
        ("Is x of 1.5 m and y of 2.0 m reachable?", (1.5, 2.0)),
        ("Go to x=1.5 m, y=-2.0 m.", (1.5, -2.0)),
        ("Move to (2, 3).", (2.0, 3.0)),
        ("Is y = 0.9, x = 0.8 reachable?", (0.8, 0.9)),
        ("Is x = 0.8 and y = 1.", (0.8, 1.0)),
    ],
)
def test_parse_point(text: str, expected: tuple[float, float]) -> None:
    assert P.parse_point(text).point == expected


def test_parse_point_non_finite_tokens() -> None:
    pt = P.parse_point("Check reachability of x = NaN, y = 1.0.").point
    assert pt is not None and math.isnan(pt[0]) and pt[1] == 1.0
    assert P.parse_point("Does x = inf, y = 0.2 collide?").point == (math.inf, 0.2)
    assert P.parse_point("Is (1e6, 2) reachable?").point == (1e6, 2.0)


@pytest.mark.parametrize(
    "text", ["Move to x = 1.0.", "Can the arm reach y = 0.9?", "Move the tool tip."]
)
def test_missing_coordinate_gives_no_point(text: str) -> None:
    pp = P.parse_point(text)
    assert pp.point is None and not pp.unparsable


@pytest.mark.parametrize(
    "text",
    ["Is x = banana, y = 2.0 reachable?", "Move to (0.6, ??).", "Is (abc, 0.4) within reach?"],
)
def test_non_numeric_coordinate_flagged(text: str) -> None:
    pp = P.parse_point(text)
    assert pp.point is None and pp.unparsable


def test_parse_points_and_margin() -> None:
    assert P.parse_points("Validate (0, 1) -> (2, 3), (4, 5)") == [
        (0.0, 1.0),
        (2.0, 3.0),
        (4.0, 5.0),
    ]
    assert P.parse_margin("Is x = 1.0, y = 2.0 m at least 0.35 m away from every obstacle?") == 0.35
    assert P.parse_margin("Does x=1.5 m, y=2.0 m keep the standard clearance?") is None


def test_parse_joints() -> None:
    assert P.parse_joints("shoulder 35, elbow 9.5, wrist 106 degrees") == {
        "shoulder": 35.0,
        "elbow": 9.5,
        "wrist": 106.0,
    }
    assert P.parse_joints("Check the joint limits for the tentacle at 30 degrees.") == {
        "tentacle": 30.0
    }
    assert P.parse_joints("Is an elbow angle of -9000 degrees allowed?") == {"elbow": -9000.0}


@pytest.mark.parametrize(
    "text,fam",
    [
        ("Can the robot arm reach the point (1, 1)?", "query_reach"),
        ("Does the point (1, 1) collide with any obstacle?", "query_collision"),
        ("Is there enough clearance around (1, 1)?", "query_clearance"),
        ("Move the end effector to (1, 1).", "move"),
        ("Plan a path from (0, 1) to (1, 1).", "plan_path"),
        ("Validate this path: (0, 1) -> (1, 1).", "validate_path"),
        ("Is it feasible to weld at (1, 1)?", "feasibility"),
        ("How many obstacles does the workcell contain?", "describe_state"),
        ("Which arguments are required by the check_clearance tool?", "schema_lookup"),
        ("Are shoulder 10 and elbow 20 degrees within the limits?", "query_joints"),
        ("Do something sensible.", None),
    ],
)
def test_classify(text: str, fam: str | None) -> None:
    assert classify(text) == fam
