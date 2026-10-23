"""Two-stage ``triage -> execution`` orchestration policy (Agent D).

Stage 1 (triage) decides whether a request is sufficiently specified, which task family it is, and
whether to proceed, ask for clarification, or refuse. Stage 2 (execution) selects and calls tools
only when triage allows. Both stages are timed and logged separately.

Backends are pluggable: ``RuleTriage`` + ``RuleExecutor`` are deterministic (offline); LLM-backed
stages live in ``agents/llm.py``. Results from the rule backends characterise *the orchestration
structure under hand-written rules* and must not be read as evidence about language models.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from robot_eval.agents import parsing as P
from robot_eval.agents.base import RunContext
from robot_eval.agents.reference import OVERRIDE_RE, GuardConfig, ReferencePolicy, classify
from robot_eval.domain.errors import AgentStatus
from robot_eval.domain.models import AgentOutput, Usage
from robot_eval.tools.client import ToolClient

CONTRADICTION_RE = re.compile(
    r"at least .{0,40}but no more than|at least .{0,40}and at most|keep it exactly where it is|"
    r"(?:don'?t|do not) change its position|(?:both )?reachable and (?:not reachable|unreachable)|"
    r"and not reachable|reachable and not",
    re.IGNORECASE,
)


@dataclass
class TriageDecision:
    action: Literal["proceed", "clarify", "refuse"]
    family: str | None = None
    reason: str = ""
    usage: Usage = field(default_factory=Usage)
    model_id: str | None = None


class Triage(Protocol):
    def decide(self, prompt: str, ctx: RunContext) -> TriageDecision: ...


class Executor(Protocol):
    def execute(
        self, prompt: str, decision: TriageDecision, tools: ToolClient, ctx: RunContext
    ) -> AgentOutput: ...


class RuleTriage:
    """Deterministic triage: override refusal, contradiction detection, missing-information check."""

    def decide(self, prompt: str, ctx: RunContext) -> TriageDecision:
        fam = classify(prompt)
        if fam is None:
            return TriageDecision("clarify", None, "request family not recognised")
        if fam == "move" and OVERRIDE_RE.search(prompt):
            return TriageDecision("refuse", fam, "asks to bypass safety validation")
        if CONTRADICTION_RE.search(prompt):
            return TriageDecision("clarify", fam, "contradictory constraints")
        needs_point = {
            "query_reach",
            "query_collision",
            "query_clearance",
            "feasibility",
            "move",
            "diagnose_check",
        }
        if fam in needs_point and P.parse_point(prompt).point is None:
            return TriageDecision("clarify", fam, "missing or non-numeric coordinates")
        if fam in {"plan_path", "validate_path"} and len(P.parse_points(prompt)) < 2:
            return TriageDecision("clarify", fam, "fewer than two points given")
        if fam == "query_joints" and not P.parse_joints(prompt):
            return TriageDecision("clarify", fam, "no joint values given")
        return TriageDecision("proceed", fam, "sufficiently specified")


class RuleExecutor:
    def __init__(self, guards: GuardConfig, max_retries: int = 1) -> None:
        self.policy = ReferencePolicy(guards, max_retries)

    def execute(
        self, prompt: str, decision: TriageDecision, tools: ToolClient, ctx: RunContext
    ) -> AgentOutput:
        return self.policy.run(prompt, tools, decision.family)


class TwoStageAgent:
    is_fixture = False

    def __init__(
        self,
        name: str,
        triage: Triage,
        executor: Executor,
        *,
        kind: str,
        model_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.triage = triage
        self.executor = executor
        self.kind = kind
        self.model_id = model_id
        self.version = "1.0"
        self._extra = extra or {}

    def describe(self) -> dict[str, Any]:
        return {"type": self.kind, "stages": ["triage", "execution"], **self._extra}

    def run(self, prompt: str, tools: ToolClient, ctx: RunContext) -> AgentOutput:
        stages: list[dict[str, Any]] = []
        tools.set_stage("triage")
        t0 = time.perf_counter()
        decision = self.triage.decide(prompt, ctx)
        stages.append(
            {
                "stage": "triage",
                "latency_ms": (time.perf_counter() - t0) * 1000.0,
                "action": decision.action,
                "family": decision.family,
                "reason": decision.reason,
                "input_tokens": decision.usage.input_tokens,
                "output_tokens": decision.usage.output_tokens,
            }
        )
        if decision.action == "clarify":
            return AgentOutput(
                status=AgentStatus.CLARIFICATION,
                message=decision.reason,
                stages=stages,
                usage=decision.usage,
            )
        if decision.action == "refuse":
            return AgentOutput(
                status=AgentStatus.REFUSED,
                message=decision.reason,
                stages=stages,
                usage=decision.usage,
            )
        tools.set_stage("execution")
        t1 = time.perf_counter()
        out = self.executor.execute(prompt, decision, tools, ctx)
        tools.set_stage(None)
        stages.append({"stage": "execution", "latency_ms": (time.perf_counter() - t1) * 1000.0})
        out.stages = stages + [s for s in out.stages if s.get("stage") not in {"single"}]
        out.usage = _merge_usage(decision.usage, out.usage)
        return out


def _merge_usage(a: Usage, b: Usage) -> Usage:
    def add(x: int | None, y: int | None) -> int | None:
        return None if x is None and y is None else (x or 0) + (y or 0)

    cost = (
        None
        if a.cost_usd is None and b.cost_usd is None
        else (a.cost_usd or 0.0) + (b.cost_usd or 0.0)
    )
    return Usage(
        input_tokens=add(a.input_tokens, b.input_tokens),
        output_tokens=add(a.output_tokens, b.output_tokens),
        cost_usd=cost,
        request_ids=[*a.request_ids, *b.request_ids],
    )
