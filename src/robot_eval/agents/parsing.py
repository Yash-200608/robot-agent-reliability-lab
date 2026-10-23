"""Small, transparent prompt parser used by the rule-based reference agents.

This is intentionally simple (regular expressions, no unit conversion, no coreference). It is a
baseline, not an upper bound.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?(?:nan|inf(?:inity)?)"
_NUM_RE = re.compile(NUM, re.IGNORECASE)
_TUPLE_RE = re.compile(rf"\(\s*({NUM})\s*,\s*({NUM})\s*\)", re.IGNORECASE)
_BAD_TUPLE_RE = re.compile(r"\(\s*[^()]*?(?:\?\?|[a-z]{2,}|n/a|~)[^()]*?\)", re.IGNORECASE)
_LABEL_RE = {
    ax: re.compile(rf"\b{ax}\b\s*(?:=|:|of|at|is)?\s*({NUM})(?!\w)", re.IGNORECASE) for ax in "xy"
}
_LABEL_ANY_RE = {
    ax: re.compile(rf"\b{ax}\b\s*(?:=|:|of|at|is)\s*(\S+)", re.IGNORECASE) for ax in "xy"
}
_JOINT_RE = re.compile(
    rf"\b(shoulder|elbow|wrist)\b\s*(?:angle\s*)?(?:of|=|:|at|is|/)?\s*({NUM})", re.IGNORECASE
)
_GENERIC_JOINT_RE = re.compile(
    rf"\bthe\s+([a-z_]+)(?:\s+joint)?\s+(?:at|=|of)\s+({NUM})\s*(?:°|deg)", re.IGNORECASE
)
TOOL_NAMES_RE = re.compile(
    r"\b(get_workcell_state|check_reachability|check_collision|check_clearance|validate_joint_limits|"
    r"plan_path|validate_path|estimate_operation_feasibility|move_end_effector|inspect_tool_schema|"
    r"get_simulation_diagnostics)\b"
)


def to_float(tok: str) -> float:
    return float(tok.lower().replace("infinity", "inf"))


@dataclass
class PointParse:
    point: tuple[float, float] | None
    unparsable: bool = False  # a coordinate label was present but its value was not numeric


def parse_points(text: str) -> list[tuple[float, float]]:
    return [(to_float(a), to_float(b)) for a, b in _TUPLE_RE.findall(text)]


def parse_point(text: str) -> PointParse:
    pts = parse_points(text)
    if pts:
        return PointParse(pts[0])
    vals: dict[str, float] = {}
    for ax in "xy":
        m = _LABEL_RE[ax].search(text)
        if m:
            vals[ax] = to_float(m.group(1))
    if len(vals) == 2:
        return PointParse((vals["x"], vals["y"]))
    # labelled coordinate present but not a number ("x = banana")?
    bad = False
    for ax in "xy":
        if ax not in vals:
            m2 = _LABEL_ANY_RE[ax].search(text)
            if m2 and not _NUM_RE.fullmatch(m2.group(1).strip(".,;?")):
                bad = True
    if _BAD_TUPLE_RE.search(text) and not pts:
        bad = True
    return PointParse(None, unparsable=bad)


def strip_points(text: str) -> str:
    """Remove coordinate expressions so remaining numbers (e.g. margins) can be found."""
    t = _TUPLE_RE.sub(" ", text)
    for ax in "xy":
        t = re.sub(
            rf"\b{ax}\b\s*(?:=|:|of|at|is)?\s*({NUM})\s*(?:m\b)?", " ", t, flags=re.IGNORECASE
        )
    return t


def parse_margin(text: str) -> float | None:
    """A clearance margin such as '0.35 m' left after coordinates are removed."""
    rest = strip_points(text)
    m = re.search(rf"({NUM})\s*m\b(?!m)", rest, flags=re.IGNORECASE)
    if m:
        v = to_float(m.group(1))
        return v if v == v and abs(v) != float("inf") else None
    return None


def parse_joints(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, val in _JOINT_RE.findall(text):
        out[name.lower()] = to_float(val)
    if not out:
        for name, val in _GENERIC_JOINT_RE.findall(text):
            out[name.lower()] = to_float(val)
    return out


def find_tool_name(text: str) -> str | None:
    m = TOOL_NAMES_RE.search(text)
    return m.group(1) if m else None
