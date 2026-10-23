"""Benchmark case schema (versioned, strict)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from robot_eval.simulator.world import FaultSpec


class Split(StrEnum):
    SMOKE = "smoke"
    DEVELOPMENT = "development"
    HELDOUT_TEST = "heldout_test"


class Category(StrEnum):
    SMOKE = "smoke"
    VALID_SIMPLE = "valid_simple"
    PARAPHRASE = "paraphrase_variation"
    TOOL_CONFUSION = "tool_confusion"
    AMBIGUOUS = "ambiguous"
    MISSING_PARAMS = "missing_params"
    INVALID_ARGS = "invalid_args"
    REACHABILITY = "reachability"
    COLLISION_DIRECT = "collision_direct"
    COLLISION_PATH = "collision_path"
    CLEARANCE = "clearance"
    JOINT_LIMITS = "joint_limits"
    CONTRADICTORY = "contradictory"
    TOOL_FAULT = "tool_fault"
    SAFETY_OVERRIDE = "safety_override"
    BOUNDARY_NUMERIC = "boundary_numeric"
    PLANNING = "planning"
    MULTI_STEP = "multi_step"


# Categories counted towards the "invalid input / ambiguity / tool failure / safety / boundary"
# share required by the plan (>= 20% of the dataset).
STRESS_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.AMBIGUOUS,
        Category.MISSING_PARAMS,
        Category.INVALID_ARGS,
        Category.CONTRADICTORY,
        Category.TOOL_FAULT,
        Category.SAFETY_OVERRIDE,
        Category.BOUNDARY_NUMERIC,
    }
)


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Family(StrEnum):
    """Hidden task family of a case (never shown to the agent)."""

    QUERY_REACH = "query_reach"
    QUERY_COLLISION = "query_collision"
    QUERY_CLEARANCE = "query_clearance"
    QUERY_JOINTS = "query_joints"
    PLAN_PATH = "plan_path"
    VALIDATE_PATH = "validate_path"
    FEASIBILITY = "feasibility"
    MOVE = "move"
    DESCRIBE_STATE = "describe_state"
    SCHEMA_LOOKUP = "schema_lookup"
    DIAGNOSE_CHECK = "diagnose_check"
    UNDERSPECIFIED = "underspecified"
    UNPARSABLE = "unparsable"
    INVALID_VALUE = "invalid_value"
    CONTRADICTORY = "contradictory"


class ExpectedOutcome(StrEnum):
    SUCCESS = "success"
    SAFE_REFUSAL = "safe_refusal"
    CLARIFICATION = "clarification_required"
    TASK_FAILURE = "task_failure"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Intent(_Strict):
    family: Family
    params: dict[str, Any] = Field(default_factory=dict)


class ToolPattern(_Strict):
    """Acceptable tool usage: the collapsed call sequence must contain every ``required`` tool
    (in order when ``ordered``), at least one ``required_any`` tool if given, and no tool outside
    ``required + required_any + optional``."""

    required: list[str] = Field(default_factory=list)
    required_any: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    ordered: bool = True


class ArgConstraint(_Strict):
    """Constraint on one argument of every call to ``tool``.

    ops: ``approx`` (|a-v| <= tol), ``eq`` (exact), ``absent_or_approx`` (missing or approx),
    ``points_approx`` (list of {x,y} matching a list of [x,y] within tol)."""

    tool: str
    path: str
    op: Literal["approx", "eq", "absent_or_approx", "points_approx"]
    value: Any
    tol: float = 1e-6


class SafeAnswer(_Strict):
    """Which answer key carries a safety verdict, and which value means 'safe'."""

    key: str
    safe_value: bool
    expected_is_safe: bool


class Expected(_Strict):
    outcome: ExpectedOutcome
    failure_codes: list[str] = Field(default_factory=list)
    answer: dict[str, Any] = Field(default_factory=dict)
    final_ee: tuple[float, float]
    tool_patterns: list[ToolPattern] = Field(default_factory=list)
    argument_constraints: list[ArgConstraint] = Field(default_factory=list)
    unsafe_move: bool = False
    collision_label: bool | None = None
    safe_answer: SafeAnswer | None = None


class Safety(_Strict):
    label: Literal["none", "safety_query", "hazard"] = "none"
    severity: Literal["none", "low", "medium", "high"] = "none"


class BenchmarkCase(_Strict):
    case_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    benchmark_version: str
    split: Split
    category: Category
    difficulty: Difficulty
    prompt: str
    world_id: str
    fault: FaultSpec | None = None
    intent: Intent
    expected: Expected
    safety: Safety = Field(default_factory=Safety)
    oracle_notes: str = ""
    source_type: Literal["authored", "templated", "derived"]
    provenance: str = ""
    tags: list[str] = Field(default_factory=list)
