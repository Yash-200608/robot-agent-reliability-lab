"""Optional Langfuse export (opt-in; local JSONL logging never depends on it).

Written against the installed ``langfuse`` 5.0.4 API (``Langfuse``, ``propagate_attributes``,
``start_as_current_observation``, ``create_trace_id``, ``create_score``, ``flush``) as documented by the
package's own docstrings; langfuse.com was unreachable from the build sandbox, so the online docs were
not consulted and live export has NOT been exercised (see docs/limitations_and_safety.md).

WHAT IS TRANSMITTED when enabled: the user prompt text, tool names/arguments/results summaries (ok,
error code), the agent's final status/message/answer, model id, token counts and latencies, and
boolean scores. NOT transmitted: expected outcomes/answers, oracle notes, dataset files, API keys.
Everything passes through ``sanitize`` first.

Enable with ``robot-eval run --tracing`` or ``ROBOT_EVAL_LANGFUSE=1`` plus LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY (and LANGFUSE_HOST / LANGFUSE_BASE_URL for non-default regions).
"""

from __future__ import annotations

import os
from typing import Any

from robot_eval.config import env_flag, load_dotenv
from robot_eval.observability.exporters import NullExporter
from robot_eval.observability.sanitize import safe_error, sanitize

SCORES = ("task_success", "tool_selection_correct", "safe_outcome", "false_safe_claim")


class UnavailableExporter(NullExporter):
    """Requested but not usable: the run proceeds locally and records why."""

    name = "langfuse"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def status(self) -> str:
        return self.reason

    def export_case(self, record: dict[str, Any]) -> str:
        return self.reason


class LangfuseExporter:
    name = "langfuse"

    def __init__(self, client: Any, propagate: Any) -> None:
        self.client = client
        self._propagate = propagate
        self._errors = 0

    def status(self) -> str:
        return "enabled" if not self._errors else f"enabled ({self._errors} export errors)"

    def export_case(self, record: dict[str, Any]) -> str:
        rec = sanitize(record)
        sc = rec["scoring"]
        try:
            trace_id = self.client.create_trace_id(
                seed=f"{rec['run_id']}:{rec['case_id']}:{rec['repeat_index']}"
            )
            with (
                self._propagate(
                    session_id=rec["run_id"],
                    trace_name=f"{rec['agent_name']}/{rec['case_id']}",
                    tags=[
                        rec["agent_name"],
                        rec["benchmark_version"],
                        rec["split"],
                        rec["category"],
                    ],
                    metadata={
                        "dataset_hash": rec["dataset_hash"][:16],
                        "seed": str(rec["seed"]),
                        "agent_version": str(rec["agent_version"]),
                        "family": rec["family"],
                    },
                ),
                self.client.start_as_current_observation(
                    name=f"case:{rec['case_id']}",
                    as_type="agent",
                    trace_context={"trace_id": trace_id},
                    input={"prompt": rec["prompt"]},
                    output={
                        "status": rec["status"],
                        "answer": rec["answer"],
                        "failure_code": rec["failure_code"],
                        "message": rec["message"],
                    },
                    metadata={"latency_ms": rec["latency_ms"], "n_calls": sc["n_calls"]},
                    level="ERROR" if rec["status"] == "error" else "DEFAULT",
                    status_message=rec["error"],
                ),
            ):
                for call in rec["calls"]:
                    with self.client.start_as_current_observation(
                        name=call["tool"],
                        as_type="tool",
                        input=call["arguments"],
                        output={"ok": call["ok"], "error_code": call["error_code"]},
                        metadata={"latency_ms": call["latency_ms"], "stage": call["stage"]},
                        level="DEFAULT" if call["ok"] else "WARNING",
                    ):
                        pass
                usage = rec.get("usage") or {}
                if rec.get("model_id") and usage.get("input_tokens") is not None:
                    with self.client.start_as_current_observation(
                        name="llm",
                        as_type="generation",
                        model=rec["model_id"],
                        usage_details={
                            "input": usage["input_tokens"],
                            "output": usage.get("output_tokens") or 0,
                        },
                    ):
                        pass
            for s in SCORES:
                self.client.create_score(
                    name=s, value=float(bool(sc[s])), trace_id=trace_id, data_type="BOOLEAN"
                )
            return f"exported trace {trace_id[:8]}"
        except Exception as exc:  # noqa: BLE001 - tracing must never break a run
            self._errors += 1
            return f"error: {safe_error(exc)}"

    def flush(self) -> None:
        self.client.flush()


def build_langfuse_exporter(enabled: bool | None = None) -> Any:
    """Return an exporter. ``enabled=None`` reads ROBOT_EVAL_LANGFUSE; False/unset -> NullExporter."""
    load_dotenv()
    if enabled is None:
        enabled = env_flag("ROBOT_EVAL_LANGFUSE")
    if not enabled:
        return NullExporter()
    try:
        import langfuse
    except ImportError:
        return UnavailableExporter("package_not_installed (pip install -e .[tracing])")
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return UnavailableExporter(
            "missing_credentials (set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)"
        )
    try:
        client = langfuse.Langfuse()
    except Exception as exc:  # noqa: BLE001
        return UnavailableExporter(f"client_init_failed: {safe_error(exc)}")
    return LangfuseExporter(client, langfuse.propagate_attributes)
