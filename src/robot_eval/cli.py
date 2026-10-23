"""robot-eval command line interface.

Exit codes: 0 success; 1 a check failed (invalid dataset, regression detected, verification
mismatch); 2 usage/configuration error; 3 an optional feature is unavailable (e.g. no LLM
credentials) - in that case nothing is run and no results are invented.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from robot_eval import __version__
from robot_eval.agents.factory import (
    AgentUnavailable,
    available_agents,
    build_agent,
    default_config_path,
)


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _split_arg(name: str | None) -> Any:
    from robot_eval.domain.case import Split

    return Split(name) if name else None


# ------------------------------------------------------------------------------- commands
def cmd_validate(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.dataset import validate_dataset_file

    rc = 0
    for ds in args.dataset:
        if not Path(ds).exists():
            return _err(f"dataset not found: {ds}")
        rep = validate_dataset_file(
            ds,
            expected_split=_split_arg(args.split),
            expected_version=args.version,
            worlds_path=args.worlds,
        )
        if args.json:
            print(json.dumps(rep.to_dict(), indent=1))
        else:
            status = "OK" if rep.ok else "INVALID"
            print(
                f"{ds}: {status} ({rep.n_cases} cases, {len(rep.errors)} errors, {len(rep.warnings)} warnings)"
            )
            for e in rep.errors[:50]:
                print(f"  ERROR {e}")
            for w in rep.warnings[:20]:
                print(f"  WARN  {w}")
        rc = rc or (0 if rep.ok else 1)
    return rc


def cmd_audit(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.audit import audit_datasets, render_audit_markdown

    for ds in args.dataset:
        if not Path(ds).exists():
            return _err(f"dataset not found: {ds}")
    audit = audit_datasets(args.dataset, args.worlds)
    md = render_audit_markdown(audit)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "audit.json").write_text(json.dumps(audit, indent=1) + "\n", encoding="utf-8")
        (out / "audit.md").write_text(md, encoding="utf-8")
        print(f"wrote {out / 'audit.json'} and {out / 'audit.md'}")
    else:
        print(md)
    return 0 if audit["all_valid"] else 1


def cmd_generate(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.generator import generate_all

    manifest = generate_all(args.datasets_dir)
    for rel, info in manifest["files"].items():
        print(f"{rel}: {info['n_cases']} cases, hash {info['dataset_hash'][:16]}")
    return 0


def cmd_list_agents(args: argparse.Namespace) -> int:
    for n in available_agents(args.config):
        print(n)
    return 0


def _headline(summary: dict[str, Any]) -> str:
    from robot_eval.evaluation.report import pct

    m = summary["aggregate"]["metrics"]
    return "\n".join(
        [
            f"  task success      : {pct(m['task_success_rate'])}",
            f"  tool selection    : {pct(m['tool_selection_accuracy'])}",
            f"  safe outcome      : {pct(m['safe_outcome_rate'])}",
            f"  unsafe attempts   : {m['unsafe_action_attempt_rate_cases']['num']}/{m['unsafe_action_attempt_rate_cases']['den']} cases",
            f"  false-safe claims : {m['false_safe_claims']['num']}/{m['false_safe_claims']['den']} cases",
        ]
    )


def cmd_run(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.runner import RunOptions, run_benchmark

    ds = Path(args.dataset)
    if not ds.exists():
        return _err(f"dataset not found: {ds}")
    try:
        agent = build_agent(args.agent, args.config)
    except AgentUnavailable as exc:
        print(
            f"optional feature unavailable: {exc}\nNo run was performed and no results were produced.",
            file=sys.stderr,
        )
        return 3
    except ValueError as exc:
        return _err(str(exc))
    from robot_eval.observability.langfuse_adapter import build_langfuse_exporter

    exporter = build_langfuse_exporter(enabled=True if args.tracing else None)
    if exporter.name != "none":
        print(f"remote tracing: {exporter.name} ({exporter.status()})", file=sys.stderr)
    opts = RunOptions(
        dataset=ds,
        agent=args.agent,
        agent_config=Path(args.config) if args.config else None,
        out_root=Path(args.out),
        seed=args.seed,
        repeats=args.repeats,
        limit=args.limit,
        case_ids=args.case,
        max_tool_calls=args.max_tool_calls,
        command="robot-eval "
        + " ".join(shlex.quote(a) for a in (sys.argv[1:] if sys.argv[1:] else [])),
        label=args.label,
        transport=args.transport,
    )
    if args.transport == "mcp":
        try:
            import mcp  # noqa: F401
        except ImportError:
            print(
                "optional feature unavailable: --transport mcp needs the 'mcp' extra "
                "(pip install -e .[mcp])",
                file=sys.stderr,
            )
            return 3
    res = run_benchmark(opts, agent, exporter)
    print(f"run directory: {res.run_dir}")
    print(_headline(res.summary))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.compare import compare_runs, render_comparison

    if len(args.runs) != 2:
        return _err("compare needs exactly two run directories (A then B)")
    for r in args.runs:
        if not (Path(r) / "cases.jsonl").exists():
            return _err(f"not a run directory (no cases.jsonl): {r}")
    res = compare_runs(
        args.runs[0], args.runs[1], n_boot=args.n_boot, seed=args.seed, primary=tuple(args.primary)
    )
    md = render_comparison(res)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "comparison.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
        (out / "comparison.md").write_text(md, encoding="utf-8")
        print(f"wrote {out / 'comparison.json'} and {out / 'comparison.md'}")
    else:
        print(md)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.report import render_run_report, verify_summary
    from robot_eval.evaluation.runner import load_run

    d = Path(args.run)
    if not (d / "cases.jsonl").exists():
        return _err(f"not a run directory (no cases.jsonl): {d}")
    meta, summary, recs = load_run(d)
    problems = verify_summary(summary, recs)
    if problems:
        for p in problems:
            print(f"VERIFY FAILED: {p}", file=sys.stderr)
        if args.verify:
            return 1
    elif args.verify:
        print("verified: summary.json matches a recomputation from cases.jsonl")
    md = render_run_report(meta, summary, recs)
    if args.write:
        (d / "report.md").write_text(md, encoding="utf-8")
        print(f"wrote {d / 'report.md'}")
    else:
        print(md)
    return 1 if problems else 0


def cmd_regression(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.regression import check_regression, load_summary, load_thresholds

    try:
        base, cand = load_summary(args.baseline), load_summary(args.candidate)
    except FileNotFoundError as exc:
        return _err(f"summary not found: {exc.filename}")
    th = load_thresholds(args.config)
    res = check_regression(base, cand, th)
    if args.json:
        print(json.dumps(res.to_dict(), indent=1))
    else:
        print("REGRESSION CHECK:", "PASSED" if res.passed else "FAILED")
        for c in res.checks:
            flag = "VIOLATED" if c["violated"] else "ok"
            print(
                f"  [{flag}] {c['check']}: baseline={c['baseline']} candidate={c['candidate']} limit={c['limit']}"
            )
        for f in res.findings:
            print(f"  FINDING {f}")
    return 0 if res.passed else 1


def cmd_experiment(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.experiments import run_experiment

    try:
        return run_experiment(args.config, args.name, Path(args.out), args.dry_run)
    except AgentUnavailable as exc:
        print(f"optional feature unavailable: {exc}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return _err(str(exc))


def cmd_baseline_report(args: argparse.Namespace) -> int:
    from robot_eval.evaluation.baseline_report import build_baseline_report

    try:
        md = build_baseline_report(args.experiments)
    except FileNotFoundError as exc:
        return _err(f"{exc}; run the experiments first (robot-eval experiment --name ...)")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    try:
        from robot_eval.mcp_server.server import run_stdio
    except ImportError as exc:
        print(
            f"optional feature unavailable: the 'mcp' extra is not installed ({exc}). "
            "Install with: pip install -e .[mcp]",
            file=sys.stderr,
        )
        return 3
    run_stdio(args.world, args.worlds)
    return 0


# ---------------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robot-eval",
        description="Robotics Agent Reliability Lab - simulation-only evaluation of tool-using agents.",
        epilog="Simulation only. No real robot, PLC or industrial system is ever contacted.",
    )
    p.add_argument("--version", action="version", version=f"robot-eval {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    v = sub.add_parser(
        "validate-dataset", help="validate dataset files against the schema and exact oracle"
    )
    v.add_argument("--dataset", required=True, nargs="+")
    v.add_argument("--split", choices=["smoke", "development", "heldout_test"])
    v.add_argument("--version", help="expected benchmark_version, e.g. v1")
    v.add_argument("--worlds", help="path to worlds.json (default: next to the dataset)")
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_validate)

    a = sub.add_parser("audit-dataset", help="composition, balance, duplicate and leakage audit")
    a.add_argument("--dataset", required=True, nargs="+")
    a.add_argument("--worlds")
    a.add_argument("--out", help="directory for audit.json / audit.md (default: print markdown)")
    a.set_defaults(fn=cmd_audit)

    g = sub.add_parser(
        "generate-dataset", help="regenerate datasets/ deterministically (validated before writing)"
    )
    g.add_argument("--datasets-dir", default="datasets")
    g.set_defaults(fn=cmd_generate)

    la = sub.add_parser("list-agents", help="list configured agent names")
    la.add_argument("--config", default=None)
    la.set_defaults(fn=cmd_list_agents)

    r = sub.add_parser("run", help="run an agent on a dataset and write a unique run directory")
    r.add_argument("--dataset", required=True)
    r.add_argument("--agent", default="reference")
    r.add_argument("--config", default=None, help=f"agents YAML (default: {default_config_path()})")
    r.add_argument("--out", default="outputs/runs")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--case", action="append", help="run only this case id (repeatable)")
    r.add_argument("--max-tool-calls", type=int, default=40)
    r.add_argument("--label", default=None)
    r.add_argument(
        "--transport",
        choices=["direct", "mcp"],
        default="direct",
        help="call tools in-process (default) or through an in-process MCP session",
    )
    r.add_argument(
        "--tracing",
        action="store_true",
        help="opt in to Langfuse export (see docs/architecture.md)",
    )
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("compare", help="paired comparison of two run directories (A then B)")
    c.add_argument("--runs", required=True, nargs=2, metavar=("RUN_A", "RUN_B"))
    c.add_argument("--out")
    c.add_argument("--n-boot", type=int, default=10000)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--primary", nargs="+", default=["task_success", "unsafe_attempt"])
    c.set_defaults(fn=cmd_compare)

    rp = sub.add_parser(
        "report", help="render report.md from a run directory (optionally verify the summary)"
    )
    rp.add_argument("--run", required=True)
    rp.add_argument(
        "--verify",
        action="store_true",
        help="fail if summary.json != recomputation from cases.jsonl",
    )
    rp.add_argument("--write", action="store_true", help="write report.md into the run directory")
    rp.set_defaults(fn=cmd_report)

    rg = sub.add_parser(
        "regression-check", help="exit 1 if the candidate regresses against the baseline"
    )
    rg.add_argument("--baseline", required=True, help="run directory or summary.json")
    rg.add_argument("--candidate", required=True)
    rg.add_argument(
        "--config",
        default=None,
        help="YAML with a 'regression:' section (default: built-in thresholds)",
    )
    rg.add_argument("--json", action="store_true")
    rg.set_defaults(fn=cmd_regression)

    ex = sub.add_parser("experiment", help="run a named experiment from configs/experiments.yaml")
    ex.add_argument("--config", default="configs/experiments.yaml")
    ex.add_argument("--name", required=True)
    ex.add_argument("--out", default="outputs/experiments")
    ex.add_argument("--dry-run", action="store_true")
    ex.set_defaults(fn=cmd_experiment)

    bp = sub.add_parser(
        "baseline-report", help="build reports/baseline_report.md from saved experiment artifacts"
    )
    bp.add_argument("--experiments", default="reports/experiments")
    bp.add_argument("--out", default="reports/baseline_report.md")
    bp.set_defaults(fn=cmd_baseline_report)

    m = sub.add_parser(
        "mcp-serve", help="serve the simulated tools over MCP (stdio); needs the 'mcp' extra"
    )
    m.add_argument("--world", default="cell_a")
    m.add_argument("--worlds", default=None)
    m.set_defaults(fn=cmd_mcp_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except FileNotFoundError as exc:
        return _err(f"file not found: {exc.filename or exc}")
    except ValueError as exc:
        return _err(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
