"""Benchmark execution: one simulator per case, a recording tool client, a scored record per case."""

from __future__ import annotations

import hashlib
import importlib.metadata as im
import json
import platform
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import robot_eval
from robot_eval.agents.base import Agent, RunContext
from robot_eval.agents.factory import build_agent
from robot_eval.domain.case import BenchmarkCase
from robot_eval.domain.errors import AgentStatus
from robot_eval.domain.models import AgentOutput
from robot_eval.evaluation.dataset import dataset_hash, default_worlds_path, file_sha256, load_cases
from robot_eval.evaluation.metrics import summarize
from robot_eval.evaluation.scoring import score_case
from robot_eval.observability.events import EventLog, new_span_id, new_trace_id, utc_now
from robot_eval.observability.exporters import Exporter, NullExporter
from robot_eval.observability.sanitize import json_safe, safe_error, sanitize, sanitize_text
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import load_worlds
from robot_eval.tools.client import RecordingToolClient, SimulatorToolClient, ToolBudgetExceeded

RESULT_SCHEMA = "robot_eval.case_result/1"
# fields that legitimately differ between otherwise identical deterministic runs
VOLATILE_KEYS = {"run_id", "timestamp", "latency_ms", "trace_id", "export_status", "stages"}


def code_hash() -> str:
    """sha256 over all package source files (identifies the exact code that produced a run)."""
    h = hashlib.sha256()
    root = Path(robot_eval.__file__).resolve().parent
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def canonical_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Record minus volatile fields (ids, timestamps, wall-clock latencies)."""
    out = {k: v for k, v in rec.items() if k not in VOLATILE_KEYS}
    out["calls"] = [{k: v for k, v in c.items() if k != "latency_ms"} for c in rec["calls"]]
    return out


def environment_info() -> dict[str, Any]:
    pk: dict[str, str | None] = {}
    for name in ("pydantic", "numpy", "PyYAML", "mcp", "anthropic", "langfuse"):
        try:
            pk[name] = im.version(name)
        except im.PackageNotFoundError:
            pk[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "machine": platform.machine(),
        "packages": pk,
    }


@dataclass
class RunOptions:
    dataset: Path
    agent: str = "reference"
    agent_config: Path | None = None
    out_root: Path = Path("outputs/runs")
    seed: int = 0
    repeats: int = 1
    limit: int | None = None
    case_ids: list[str] | None = None
    max_tool_calls: int = 40
    max_case_seconds: float = 120.0
    command: str | None = None
    label: str | None = None
    transport: str = "direct"  # "direct" (in-process) or "mcp" (through an in-process MCP session)


@dataclass
class RunResult:
    run_dir: Path
    records: list[dict[str, Any]]
    summary: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", s).strip("-")


def make_run_dir(root: Path, agent: str, version: str, split: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{_slug(agent)}_{_slug(version)}_{_slug(split)}"
    for n in range(1, 1000):
        d = root / (base if n == 1 else f"{base}-{n}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique run directory")


def run_case(
    case: BenchmarkCase,
    agent: Agent,
    sim: Simulator,
    seed: int,
    max_calls: int,
    max_seconds: float,
    transport: str = "direct",
) -> tuple[AgentOutput, RecordingToolClient, float]:
    closer: Any = None
    if transport == "mcp":
        from robot_eval.mcp_server.client import McpToolClient

        mcp_client = McpToolClient(sim)
        closer = mcp_client.close
        client = RecordingToolClient(mcp_client, max_calls=max_calls)  # type: ignore[arg-type]
    elif transport == "direct":
        client = RecordingToolClient(SimulatorToolClient(sim), max_calls=max_calls)
    else:
        raise ValueError(f"unknown transport {transport!r}")
    try:
        return _run_case_inner(case, agent, sim, seed, max_seconds, client)
    finally:
        if closer is not None:
            closer()


def _run_case_inner(
    case: BenchmarkCase,
    agent: Agent,
    sim: Simulator,
    seed: int,
    max_seconds: float,
    client: RecordingToolClient,
) -> tuple[AgentOutput, RecordingToolClient, float]:
    t0 = time.perf_counter()
    try:
        out = agent.run(case.prompt, client, RunContext(seed=seed, case_id=case.case_id))
    except ToolBudgetExceeded as exc:
        out = AgentOutput(status=AgentStatus.ERROR, error=safe_error(exc))
    except Exception as exc:  # noqa: BLE001 - any agent crash must be recorded, not propagated
        out = AgentOutput(status=AgentStatus.ERROR, error=safe_error(exc))
    elapsed = (time.perf_counter() - t0) * 1000.0
    if elapsed > max_seconds * 1000.0 and out.status is not AgentStatus.ERROR:
        out = AgentOutput(
            status=AgentStatus.ERROR,
            error=f"TimeoutError: case exceeded {max_seconds}s wall-clock budget ({elapsed / 1000:.1f}s)",
        )
    return out, client, elapsed


def run_benchmark(
    opts: RunOptions, agent: Agent | None = None, exporter: Exporter | None = None
) -> RunResult:
    cases = load_cases(opts.dataset)
    if opts.case_ids:
        wanted = set(opts.case_ids)
        cases = [c for c in cases if c.case_id in wanted]
    if opts.limit is not None:
        cases = cases[: opts.limit]
    if not cases:
        raise ValueError("no cases selected")
    worlds_path = default_worlds_path(opts.dataset)
    worlds = load_worlds(worlds_path)
    ds_hash = dataset_hash(opts.dataset, worlds_path)
    ag = agent or build_agent(opts.agent, opts.agent_config)
    exporter = exporter or NullExporter()
    versions = sorted({c.benchmark_version for c in cases})
    splits = sorted({c.split.value for c in cases})
    run_dir = make_run_dir(opts.out_root, ag.name, "+".join(versions), "+".join(splits))
    run_id = uuid.uuid4().hex
    started = utc_now()
    desc = ag.describe()
    meta: dict[str, Any] = {
        "schema": "robot_eval.run_metadata/1",
        "run_id": run_id,
        "status": "running",
        "started_at": started,
        "command": opts.command,
        "label": opts.label,
        "agent": {
            "name": ag.name,
            "version": ag.version,
            "model_id": ag.model_id,
            "is_test_fixture": ag.is_fixture,
            "config": sanitize(desc),
            "config_hash": hashlib.sha256(
                json.dumps(desc, sort_keys=True, default=str).encode()
            ).hexdigest(),
        },
        "dataset": {
            "path": str(opts.dataset),
            "benchmark_versions": versions,
            "splits": splits,
            "n_cases": len(cases),
            "dataset_hash": ds_hash,
            "file_sha256": file_sha256(opts.dataset),
            "worlds_sha256": file_sha256(worlds_path),
        },
        "code": {"package_version": robot_eval.__version__, "source_sha256": code_hash()},
        "environment": environment_info(),
        "transport": opts.transport,
        "seed": opts.seed,
        "repeats": opts.repeats,
        "limits": {
            "max_tool_calls": opts.max_tool_calls,
            "max_case_seconds": opts.max_case_seconds,
        },
        "tracing": {"exporter": exporter.name, "status": exporter.status()},
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    _log_heldout_access(meta, run_dir)
    records: list[dict[str, Any]] = []
    cases_path = run_dir / "cases.jsonl"
    with (
        EventLog(run_dir / "events.jsonl", run_id) as ev,
        cases_path.open("w", encoding="utf-8", newline="\n") as out_fh,
    ):
        ev.emit(
            "run_started",
            agent=ag.name,
            dataset_hash=ds_hash,
            n_cases=len(cases),
            repeats=opts.repeats,
        )
        for rep in range(opts.repeats):
            for case in cases:
                seed = opts.seed + rep
                trace_id = new_trace_id()
                world = worlds[case.world_id]
                sim = Simulator(world, [case.fault] if case.fault else [])
                ev.emit(
                    "case_started",
                    case_id=case.case_id,
                    repeat_index=rep,
                    trace_id=trace_id,
                    span_id=new_span_id(),
                )
                out, client, elapsed = run_case(
                    case, ag, sim, seed, opts.max_tool_calls, opts.max_case_seconds, opts.transport
                )
                sc = score_case(case, world, client.records, out, sim.ee)
                rec: dict[str, Any] = {
                    "schema": RESULT_SCHEMA,
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "repeat_index": rep,
                    "seed": seed,
                    "timestamp": utc_now(),
                    "benchmark_version": case.benchmark_version,
                    "split": case.split.value,
                    "category": case.category.value,
                    "family": case.intent.family.value,
                    "difficulty": case.difficulty.value,
                    "safety_label": case.safety.label,
                    "safety_severity": case.safety.severity,
                    "dataset_hash": ds_hash,
                    "agent_name": ag.name,
                    "agent_version": ag.version,
                    "model_id": out.model_id or ag.model_id,
                    "world_id": case.world_id,
                    "fault": case.fault.model_dump() if case.fault else None,
                    "prompt": case.prompt,
                    "expected_outcome": case.expected.outcome.value,
                    "status": out.status.value,
                    "failure_code": out.failure_code,
                    "answer": sanitize(out.answer),
                    "message": sanitize_text(out.message, 500),
                    "error": out.error,
                    "final_ee": list(sim.ee),
                    "calls": sanitize(sc["calls"]),
                    "scoring": sc["scoring"],
                    "latency_ms": round(elapsed, 4),
                    "stages": sanitize(out.stages),
                    "usage": out.usage.model_dump(),
                    "trace_id": trace_id,
                }
                rec = json_safe(rec)
                try:
                    rec["export_status"] = exporter.export_case(rec)
                except Exception as exc:  # noqa: BLE001 - tracing must never break a run
                    rec["export_status"] = f"error: {safe_error(exc)}"
                for c in rec["calls"]:
                    ev.emit(
                        "tool_call",
                        case_id=case.case_id,
                        trace_id=trace_id,
                        span_id=new_span_id(),
                        tool=c["tool"],
                        ok=c["ok"],
                        error_code=c["error_code"],
                        stage=c["stage"],
                        latency_ms=c["latency_ms"],
                    )
                for st in rec["stages"]:
                    ev.emit(
                        "stage",
                        case_id=case.case_id,
                        trace_id=trace_id,
                        span_id=new_span_id(),
                        **st,
                    )
                ev.emit(
                    "case_finished",
                    case_id=case.case_id,
                    trace_id=trace_id,
                    status=rec["status"],
                    task_success=rec["scoring"]["task_success"],
                    latency_ms=rec["latency_ms"],
                )
                out_fh.write(json.dumps(rec, ensure_ascii=False, allow_nan=False) + "\n")
                out_fh.flush()
                records.append(rec)
        flush_status = "ok"
        try:
            exporter.flush()
        except Exception as exc:  # noqa: BLE001 - tracing must never break a run
            flush_status = f"error: {safe_error(exc)}"
        agg = summarize(records)
        summary = {
            "schema": "robot_eval.run_summary/1",
            "run_id": run_id,
            "agent": ag.name,
            "dataset_hash": ds_hash,
            "benchmark_versions": versions,
            "splits": splits,
            "aggregate": agg,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(json_safe(summary), indent=1, allow_nan=False) + "\n", encoding="utf-8"
        )
        meta.update(
            {
                "status": "completed",
                "completed_at": utc_now(),
                "tracing": {
                    "exporter": exporter.name,
                    "status": exporter.status(),
                    "flush": flush_status,
                },
            }
        )
        (run_dir / "metadata.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
        ev.emit("run_finished", n_records=len(records))
    from robot_eval.evaluation.report import render_run_report

    (run_dir / "report.md").write_text(render_run_report(meta, summary, records), encoding="utf-8")
    return RunResult(run_dir, records, summary, meta)


def heldout_log_path() -> Path:
    """Append-only disclosure log of every run that touched the held-out split."""
    import os

    from robot_eval.agents.factory import repo_root

    env = os.environ.get("ROBOT_EVAL_HELDOUT_LOG")
    return Path(env) if env else repo_root() / "reports" / "heldout_access_log.jsonl"


def _log_heldout_access(meta: dict[str, Any], run_dir: Path) -> None:
    if "heldout_test" not in meta["dataset"]["splits"]:
        return
    entry = {
        "timestamp": meta["started_at"],
        "run_id": meta["run_id"],
        "run_dir": run_dir.name,
        "agent": meta["agent"]["name"],
        "agent_config_hash": meta["agent"]["config_hash"][:16],
        "dataset_hash": meta["dataset"]["dataset_hash"][:16],
        "n_cases": meta["dataset"]["n_cases"],
        "code_source_sha256": meta["code"]["source_sha256"][:16],
        "command": meta.get("command"),
    }
    p = heldout_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_run(run_dir: str | Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    d = Path(run_dir)
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    recs = [
        json.loads(line)
        for line in (d / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return meta, summary, recs
