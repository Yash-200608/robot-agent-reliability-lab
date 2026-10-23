"""Error taxonomies shared by the simulator, agents and evaluator."""

from __future__ import annotations

from enum import StrEnum


class ToolErrorCode(StrEnum):
    """Structured error codes returned by simulated tools.

    Codes double as the vocabulary an agent may use when it reports a ``failed`` task.
    """

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    COLLISION = "COLLISION"
    INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
    PATH_UNREACHABLE = "PATH_UNREACHABLE"
    PATH_COLLISION = "PATH_COLLISION"
    PATH_CLEARANCE = "PATH_CLEARANCE"
    JOINT_LIMIT_VIOLATION = "JOINT_LIMIT_VIOLATION"
    PLANNING_FAILED = "PLANNING_FAILED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    OPERATION_NOT_FOUND = "OPERATION_NOT_FOUND"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_INTERNAL_ERROR = "TOOL_INTERNAL_ERROR"


# Fixed precedence used when several geometric constraints are violated at once: the first
# code in this tuple that applies is the "primary" code reported by the simulator.
VIOLATION_PRECEDENCE: tuple[ToolErrorCode, ...] = (
    ToolErrorCode.OUT_OF_BOUNDS,
    ToolErrorCode.TARGET_UNREACHABLE,
    ToolErrorCode.COLLISION,
    ToolErrorCode.INSUFFICIENT_CLEARANCE,
    ToolErrorCode.PATH_UNREACHABLE,
    ToolErrorCode.PATH_COLLISION,
    ToolErrorCode.PATH_CLEARANCE,
)

TRANSIENT_FAULT_CODES: frozenset[ToolErrorCode] = frozenset(
    {
        ToolErrorCode.TOOL_TIMEOUT,
        ToolErrorCode.TOOL_UNAVAILABLE,
        ToolErrorCode.TOOL_INTERNAL_ERROR,
    }
)


class AgentStatus(StrEnum):
    """Final status an agent reports for a request."""

    COMPLETED = "completed"
    CLARIFICATION = "clarification"
    REFUSED = "refused"
    FAILED = "failed"
    ERROR = "error"  # harness-assigned when the agent crashed or exceeded a budget


class FailureCategory(StrEnum):
    """Evaluator-assigned failure taxonomy (a failed case may carry several)."""

    AGENT_ERROR = "agent_error"
    WRONG_STATUS = "wrong_status"
    WRONG_ANSWER = "wrong_answer"
    WRONG_TOOL = "wrong_tool"
    MISSING_TOOL = "missing_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNSAFE_ATTEMPT = "unsafe_attempt"
    FALSE_SAFE_CLAIM = "false_safe_claim"
    MISSING_CLARIFICATION = "missing_clarification"
    SPURIOUS_CLARIFICATION = "spurious_clarification"
    MISSED_REFUSAL = "missed_refusal"
    UNNECESSARY_REFUSAL = "unnecessary_refusal"
    UNHANDLED_TOOL_FAILURE = "unhandled_tool_failure"
    WRONG_FAILURE_CODE = "wrong_failure_code"
    UNEXPECTED_STATE_CHANGE = "unexpected_state_change"
    WRONG_FINAL_STATE = "wrong_final_state"
