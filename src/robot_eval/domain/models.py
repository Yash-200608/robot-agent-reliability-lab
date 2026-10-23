"""Core typed models shared across packages."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from robot_eval.domain.errors import AgentStatus, ToolErrorCode

MAX_ABS_COORD = 1000.0

Coord = Annotated[
    float, Field(strict=True, allow_inf_nan=False, ge=-MAX_ABS_COORD, le=MAX_ABS_COORD)
]


class StrictModel(BaseModel):
    """Base for tool-argument models: unknown fields rejected, no type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Point(StrictModel):
    """A 2-D point in metres in the workcell frame (x right, y up)."""

    x: Coord
    y: Coord


class ToolResult(BaseModel):
    """Structured result of any simulated tool call (also the MCP payload)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    tool: str
    error_code: ToolErrorCode | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    operation_id: str | None = None


class Usage(BaseModel):
    """Token usage; ``None`` means the provider did not report it (never coerced to zero)."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    request_ids: list[str] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    """One tool call as observed by the harness (not self-reported by the agent)."""

    index: int
    tool: str
    arguments: dict[str, Any]
    result: ToolResult
    latency_ms: float
    ee_before: tuple[float, float]
    ee_after: tuple[float, float]
    stage: str | None = None


class AgentOutput(BaseModel):
    """What an agent returns. Everything here is *claimed* by the agent and is verified by the
    evaluator against the oracle; it is never trusted as ground truth."""

    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    message: str = ""
    answer: dict[str, Any] = Field(default_factory=dict)
    failure_code: str | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model_id: str | None = None
    error: str | None = None
