"""Dataset loading, hashing and validation against the independent oracle."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from robot_eval.domain.case import BenchmarkCase, ExpectedOutcome, Family, Split
from robot_eval.evaluation import oracle as O
from robot_eval.evaluation.groundtruth import build_expected, build_safety
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import WorldSpec, load_worlds
from robot_eval.tools.registry import TOOL_REGISTRY

_TOOL_NAMES = sorted(TOOL_REGISTRY, key=len, reverse=True)
_LABEL_PATTERNS = [r"\b[A-Z]{4,}(?:_[A-Z]+)+\b", r"\boracle\b", r"\bexpected_", r"\bground truth\b"]
_LEAK_RE = re.compile("|".join([re.escape(t) for t in _TOOL_NAMES] + _LABEL_PATTERNS))
_LEAK_NO_TOOLS_RE = re.compile("|".join(_LABEL_PATTERNS))


def default_worlds_path(dataset_path: str | Path) -> Path:
    """``datasets/worlds.json`` next to (or one level above) the dataset file."""
    p = Path(dataset_path).resolve().parent
    for cand in (p / "worlds.json", p.parent / "worlds.json"):
        if cand.exists():
            return cand
    raise FileNotFoundError(f"worlds.json not found near {dataset_path}")


def load_cases(path: str | Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with Path(path).open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                cases.append(BenchmarkCase.model_validate_json(line))
            except ValidationError as exc:
                raise ValueError(
                    f"{path}:{n}: invalid case: {exc.error_count()} error(s): {exc}"
                ) from exc
    return cases


def write_cases(cases: list[BenchmarkCase], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="\n") as fh:
        for c in cases:
            fh.write(json.dumps(c.model_dump(mode="json"), ensure_ascii=False, sort_keys=False))
            fh.write("\n")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dataset_hash(path: str | Path, worlds_path: str | Path | None = None) -> str:
    """sha256 over the dataset file bytes and the worlds file bytes."""
    wp = Path(worlds_path) if worlds_path else default_worlds_path(path)
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    h.update(b"\0")
    h.update(wp.read_bytes())
    return h.hexdigest()


def normalize_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.\-]", " ", text.lower())).strip()


def prompt_skeleton(text: str) -> str:
    """Prompt with all numbers replaced, used for template/near-duplicate analysis."""
    return re.sub(r"\s+", " ", re.sub(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", "#", text.lower())).strip()


# ----------------------------------------------------------------------------- validation
@dataclass
class ValidationReport:
    path: str
    n_cases: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "n_cases": self.n_cases,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _to_float(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def wall_blocks(ew: O.ExactWorld, s: O.Pt, g: O.Pt) -> bool:
    """Exact certificate that obstacles centred on one horizontal line cover the workspace width
    and separate ``s`` from ``g`` (so every in-workspace path between them hits an obstacle)."""
    x0, x1, _, _ = ew.ws
    by_y: dict[Fraction, list[tuple[Fraction, Fraction]]] = {}
    for (cx, cy), r in ew.obstacles:
        by_y.setdefault(cy, []).append((cx - r, cx + r))
    for yc, ivs in by_y.items():
        if not (min(s[1], g[1]) < yc < max(s[1], g[1])):
            continue
        ivs.sort()
        reach = ivs[0][1]
        if ivs[0][0] > x0:
            continue
        for lo, hi in ivs[1:]:
            if lo <= reach:
                reach = max(reach, hi)
        if reach >= x1:
            return True
    return False


def _crosscheck(case: BenchmarkCase, world: WorldSpec) -> list[str]:
    """Run the reference tool call(s) for the hidden intent against the *float simulator* and
    compare with the oracle-derived expectation."""
    errs: list[str] = []
    f, prm = case.intent.family, case.intent.params
    # Faults are not injected here, so compare against the fault-free expectation.
    exp = build_expected(world, case.intent, None)
    sim = Simulator(world)

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    if f is Family.QUERY_REACH:
        r = sim.call("check_reachability", {"x": prm["x"], "y": prm["y"]})
        need(
            r.ok and r.data["reachable"] == exp.answer["reachable"],
            "simulator disagrees with oracle (reachable)",
        )
    elif f is Family.QUERY_COLLISION:
        r = sim.call("check_collision", {"x": prm["x"], "y": prm["y"]})
        need(
            r.ok and r.data["collides"] == exp.answer["collides"],
            "simulator disagrees with oracle (collides)",
        )
    elif f is Family.QUERY_CLEARANCE:
        args: dict[str, Any] = {"x": prm["x"], "y": prm["y"]}
        if prm.get("required_margin") is not None:
            args["required_margin"] = prm["required_margin"]
        r = sim.call("check_clearance", args)
        need(
            r.ok and r.data["clearance_ok"] == exp.answer["clearance_ok"],
            "simulator disagrees with oracle (clearance_ok)",
        )
    elif f is Family.QUERY_JOINTS:
        r = sim.call("validate_joint_limits", {"joints": prm["joints"]})
        need(
            r.ok and r.data["within_limits"] == exp.answer["within_limits"],
            "simulator disagrees with oracle (within_limits)",
        )
    elif f is Family.FEASIBILITY:
        r = sim.call(
            "estimate_operation_feasibility",
            {"operation": prm["operation"], "x": prm["x"], "y": prm["y"]},
        )
        need(
            r.ok and r.data["feasible"] == exp.answer["feasible"],
            "simulator disagrees with oracle (feasible)",
        )
    elif f is Family.VALIDATE_PATH:
        r = sim.call(
            "validate_path", {"waypoints": [{"x": a, "y": b} for a, b in prm["waypoints"]]}
        )
        need(
            r.ok and r.data["path_valid"] == exp.answer["path_valid"],
            "simulator disagrees with oracle (path_valid)",
        )
    elif f is Family.PLAN_PATH:
        r = sim.call(
            "plan_path",
            {"start": {"x": prm["sx"], "y": prm["sy"]}, "goal": {"x": prm["gx"], "y": prm["gy"]}},
        )
        found = bool(prm["expect_found"])
        need(r.ok == found, f"planner result ok={r.ok} but expect_found={found}")
        if r.ok:
            pts = [O.pt(w["x"], w["y"]) for w in r.data["waypoints"]]
            need(
                not O.path_codes(O.exact_world(world), pts),
                "planner returned a path the exact oracle rejects",
            )
        elif r.error_code is not None:
            need(
                r.error_code.value in exp.failure_codes,
                "planner error code not in expected failure codes",
            )
    elif f is Family.MOVE:
        r = sim.call("move_end_effector", {"x": prm["x"], "y": prm["y"]})
        need(
            r.ok == (not exp.unsafe_move),
            f"simulator move ok={r.ok} but unsafe_move={exp.unsafe_move}",
        )
        if not r.ok and r.error_code is not None:
            need(
                r.error_code.value in exp.failure_codes,
                "move error code not in expected failure codes",
            )
    elif f is Family.DESCRIBE_STATE:
        r = sim.call("get_workcell_state", {})
        need(r.data["num_obstacles"] == exp.answer["num_obstacles"], "obstacle count mismatch")
    elif f is Family.SCHEMA_LOOKUP:
        r = sim.call("inspect_tool_schema", {"tool_name": prm["tool_name"]})
        need(
            r.ok and r.data["required_args"] == exp.answer["required_args"],
            "required_args mismatch",
        )
    elif f is Family.DIAGNOSE_CHECK:
        sim.call(prm["check_tool"], {"x": prm["x"], "y": prm["y"]})
        r = sim.call("get_simulation_diagnostics", {})
        need(
            r.ok and r.data["operation_tool"] == exp.answer["operation_tool"],
            "diagnostics tool mismatch",
        )
    elif f is Family.INVALID_VALUE:
        args = json.loads(json.dumps(prm["args"]))
        args = {
            k: (
                _to_float(v) if not isinstance(v, dict) else {a: _to_float(b) for a, b in v.items()}
            )
            for k, v in args.items()
        }
        r = sim.call(prm["tool"], args)
        need(
            (not r.ok) and r.error_code is not None and r.error_code.value == "INVALID_ARGUMENT",
            "invalid_value args were accepted by the simulator",
        )
    return errs


def _check_plan_certificate(case: BenchmarkCase, world: WorldSpec) -> list[str]:
    prm = case.intent.params
    ew = O.exact_world(world)
    s, g = O.pt(prm["sx"], prm["sy"]), O.pt(prm["gx"], prm["gy"])
    cert = prm.get("cert", {})
    kind = cert.get("type")
    if prm["expect_found"]:
        if kind != "witness":
            return ["found plan_path case needs a 'witness' certificate"]
        pts = [O.pt(a, b) for a, b in cert["waypoints"]]
        if pts[0] != s or pts[-1] != g:
            return ["witness must start at start and end at goal"]
        codes = O.path_codes(ew, pts)
        return [f"witness path violates {[c.value for c in codes]}"] if codes else []
    if kind == "endpoint":
        bad = O.point_codes(ew, s) + O.point_codes(ew, g)
        return [] if bad else ["'endpoint' certificate but both endpoints are safe"]
    if kind == "wall":
        return [] if wall_blocks(ew, s, g) else ["'wall' certificate does not hold exactly"]
    return ["not-found plan_path case needs an 'endpoint' or 'wall' certificate"]


def validate_cases(
    cases: list[BenchmarkCase],
    worlds: dict[str, WorldSpec],
    *,
    path: str = "<memory>",
    expected_split: Split | None = None,
    expected_version: str | None = None,
) -> ValidationReport:
    rep = ValidationReport(path=path, n_cases=len(cases))
    seen_ids: set[str] = set()
    seen_prompts: dict[str, str] = {}
    seen_keys: dict[str, str] = {}

    def err(c: BenchmarkCase, msg: str) -> None:
        rep.errors.append(f"{c.case_id}: {msg}")

    if not cases:
        rep.errors.append("dataset is empty")
    for c in cases:
        if c.case_id in seen_ids:
            err(c, "duplicate case_id")
        seen_ids.add(c.case_id)
        if expected_split is not None and c.split != expected_split:
            err(c, f"split {c.split} != file split {expected_split}")
        if expected_version is not None and c.benchmark_version != expected_version:
            err(c, f"benchmark_version {c.benchmark_version} != {expected_version}")
        if not c.prompt.strip():
            err(c, "empty prompt")
            continue
        norm = normalize_prompt(c.prompt)
        if norm in seen_prompts:
            err(c, f"duplicate prompt (normalised) of {seen_prompts[norm]}")
        seen_prompts[norm] = c.case_id
        leak = _LEAK_NO_TOOLS_RE if c.intent.family is Family.SCHEMA_LOOKUP else _LEAK_RE
        if leak.search(c.prompt):
            err(c, "prompt leaks an internal tool/error/oracle label")
        world = worlds.get(c.world_id)
        if world is None:
            err(c, f"unknown world_id {c.world_id!r}")
            continue
        if c.fault is not None and c.fault.tool not in TOOL_REGISTRY:
            err(c, f"fault references unknown tool {c.fault.tool!r}")
        key = json.dumps(
            [
                c.world_id,
                c.fault.model_dump() if c.fault else None,
                c.intent.model_dump(mode="json"),
            ],
            sort_keys=True,
        )
        if key in seen_keys:
            err(c, f"duplicate (world, intent, fault) of {seen_keys[key]}")
        seen_keys[key] = c.case_id
        if any(
            isinstance(v, float) and not math.isfinite(v) for v in _walk_numbers(c.intent.params)
        ):
            err(c, "non-finite number in intent params (store as string)")
        try:
            recomputed = build_expected(world, c.intent, c.fault)
        except Exception as exc:  # noqa: BLE001 - report any oracle failure as a validation error
            err(c, f"oracle failed: {type(exc).__name__}: {exc}")
            continue
        if recomputed != c.expected:
            err(c, "stored expected result differs from oracle recomputation")
        if build_safety(world, c.intent, recomputed) != c.safety:
            err(c, "stored safety label differs from oracle recomputation")
        if c.intent.family is Family.PLAN_PATH:
            for m in _check_plan_certificate(c, world):
                err(c, m)
        if (
            c.intent.family is Family.MOVE
            and c.intent.params.get("override")
            and not recomputed.unsafe_move
        ):
            err(c, "override case must target an oracle-unsafe move")
        if (
            c.expected.outcome is ExpectedOutcome.SUCCESS
            and not c.expected.answer
            and (c.intent.family is not Family.MOVE)
        ):
            err(c, "success case without an expected answer")
        for m in _crosscheck(c, world):
            err(c, m)
    return rep


def _walk_numbers(v: Any) -> list[Any]:
    if isinstance(v, dict):
        return [x for vv in v.values() for x in _walk_numbers(vv)]
    if isinstance(v, list):
        return [x for vv in v for x in _walk_numbers(vv)]
    return [v] if isinstance(v, float) else []


def validate_dataset_file(
    path: str | Path,
    *,
    expected_split: Split | None = None,
    expected_version: str | None = None,
    worlds_path: str | Path | None = None,
) -> ValidationReport:
    try:
        cases = load_cases(path)
    except (ValueError, OSError) as exc:
        r = ValidationReport(path=str(path))
        r.errors.append(str(exc))
        return r
    worlds = load_worlds(worlds_path or default_worlds_path(path))
    return validate_cases(
        cases,
        worlds,
        path=str(path),
        expected_split=expected_split,
        expected_version=expected_version,
    )
