"""Markdown reports generated strictly from saved run files (metadata, summary, cases)."""

from __future__ import annotations

from typing import Any

from robot_eval.evaluation.metrics import summarize


def pct(r: dict[str, Any]) -> str:
    if r["value"] is None:
        return f"n/a ({r['num']}/{r['den']})"
    lo, hi = r["ci95_wilson"] if r["ci95_wilson"] else (None, None)
    ci = f" [95% CI {lo:.3f}-{hi:.3f}]" if lo is not None else ""
    return f"{100 * r['value']:.1f}% ({r['num']}/{r['den']}){ci}"


def _f(v: float | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def verify_summary(summary: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    """Recompute the aggregate from raw records and diff it against the stored one."""
    fresh = summarize(records)
    stored = summary["aggregate"]
    return (
        [] if fresh == stored else ["stored aggregate differs from recomputation from cases.jsonl"]
    )


def render_run_report(
    meta: dict[str, Any], summary: dict[str, Any], records: list[dict[str, Any]]
) -> str:
    agg = summary["aggregate"]
    m = agg["metrics"]
    ds, ag = meta["dataset"], meta["agent"]
    L: list[str] = [
        f"# Run report: `{ag['name']}` on {'+'.join(ds['benchmark_versions'])}/{'+'.join(ds['splits'])}",
        "",
    ]
    L += [
        "_Generated from `metadata.json`, `summary.json` and `cases.jsonl` in this directory by_ "
        "`robot-eval report`. _Numbers are raw counts first; percentages carry Wilson 95% intervals._",
        "",
    ]
    if ag.get("is_test_fixture"):
        L += [
            "> **TEST FIXTURE.** This agent is a deterministic fault-injection fixture, not a language model. "
            "Its numbers only validate the evaluator.",
            "",
        ]
    if "smoke" in ds["splits"]:
        L += [
            "> **Pipeline smoke check.** The smoke suite verifies that the software pipeline works. It is not "
            "evidence about AI reliability.",
            "",
        ]
    L += [
        "## Provenance",
        "",
        f"* run id: `{meta['run_id']}`; started {meta['started_at']}; status {meta['status']}",
        f"* agent: `{ag['name']}` v{ag['version']}, model: {ag['model_id'] or 'none (rule-based)'}, "
        f"config hash `{ag['config_hash'][:16]}`",
        f"* dataset: `{ds['path']}`, {ds['n_cases']} cases, hash `{ds['dataset_hash'][:16]}`",
        f"* code: package {meta['code']['package_version']}, source hash `{meta['code']['source_sha256'][:16]}`",
        f"* seed {meta['seed']}, repeats {meta['repeats']}; python {meta['environment']['python']} on "
        f"{meta['environment']['platform']}/{meta['environment']['machine']}",
        f"* remote tracing: {meta['tracing']['exporter']} ({meta['tracing']['status']})",
        f"* command: `{meta.get('command')}`",
        "",
    ]
    L += ["## Headline metrics", "", "| metric | value |", "|---|---|"]
    rows = [
        ("Task success rate", m["task_success_rate"]),
        ("Tool-selection accuracy", m["tool_selection_accuracy"]),
        ("Argument validity (call level)", m["argument_validity_call_level"]),
        ("Argument validity (case level, cases with >=1 call)", m["argument_validity_case_level"]),
        ("Safe outcome rate", m["safe_outcome_rate"]),
        ("Unsafe-action attempt rate (cases)", m["unsafe_action_attempt_rate_cases"]),
        (
            "Unsafe-action attempt rate (hazard cases)",
            m["unsafe_action_attempt_rate_on_hazard_cases"],
        ),
        ("Safety-block rate (blocked / unsafe-or-invalid move calls)", m["safety_block_rate"]),
        ("False-safe claims", m["false_safe_claims"]),
        ("Harmful state changes", m["harmful_state_changes"]),
        ("Path/clearance task success", m["path_clearance_success"]),
        ("Tool-call success rate", m["tool_call_success_rate"]),
    ]
    L += [f"| {k} | {pct(v)} |" for k, v in rows]
    c = m["collision_classification"]
    L += [
        f"| Collision classification (P / R / F1; n={c['n']}) | {_f(c['precision'])} / {_f(c['recall'])} / {_f(c['f1'])}"
        f" (TP {c['tp']}, FP {c['fp']}, FN {c['fn']}, TN {c['tn']}, missing {c['missing_predictions']}) |",
        f"| Tool calls total / mean per case | {m['tool_calls_total']} / {_f(m['mean_tool_calls_per_case'], 2)} |",
        f"| Retries (repeated identical calls) | {m['retries_total']} |",
        f"| Simulator false blocks (safe move rejected) | {m['simulator_false_blocks']} |",
        "",
    ]
    sf = agg["safety_findings"]
    L += [
        "## Safety findings (individual cases)",
        "",
        f"* unsafe-action attempts ({len(sf['unsafe_attempt_case_ids'])} cases): {', '.join(sf['unsafe_attempt_case_ids']) or 'none'}",
        f"* false-safe claims ({len(sf['false_safe_claim_case_ids'])}): {', '.join(sf['false_safe_claim_case_ids']) or 'none'}",
        f"* harmful state changes ({len(sf['harmful_state_change_case_ids'])}): {', '.join(sf['harmful_state_change_case_ids']) or 'none'}",
        f"* agent errors ({len(sf['agent_error_case_ids'])}): {', '.join(sf['agent_error_case_ids']) or 'none'}",
        "",
        "Task success does not offset any of the above; each listed case should be inspected individually.",
        "",
    ]
    L += [
        "## Task success by category",
        "",
        "| category | n | task success | tool selection | unsafe-attempt cases |",
        "|---|---|---|---|---|",
    ]
    for k, v in agg["by_category"].items():
        L.append(
            f"| {k} | {v['n_cases']} | {pct(v['task_success'])} | {pct(v['tool_selection_accuracy'])} | "
            f"{v['unsafe_attempt_cases']['num']}/{v['unsafe_attempt_cases']['den']} |"
        )
    L += [
        "",
        "## Failure taxonomy (primary category of failed cases)",
        "",
        "| category | cases |",
        "|---|---|",
    ]
    L += [f"| {k} | {v} |" for k, v in agg["failure_taxonomy_primary"].items()] or [
        "| (none) | 0 |"
    ]
    L += [
        "",
        "Agent final-status counts: "
        + ", ".join(f"{k}={v}" for k, v in agg["agent_status_counts"].items()),
        "",
    ]
    lat = agg["latency_ms"]
    L += [
        "## Latency (ms)",
        "",
        "| scope | n | p50 | p90 | p95 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]

    def lrow(name: str, s: dict[str, Any]) -> str:
        return f"| {name} | {s['n']} | {_f(s['p50'])} | {_f(s['p90'])} | {_f(s['p95'])} | {_f(s['p99'])} | {_f(s['max'])} |"

    L.append(lrow("end-to-end per case", lat["end_to_end"]))
    L.append(lrow("per tool call", lat["tool_call"]))
    L += [lrow(f"stage: {k}", v) for k, v in lat["stages"].items()]
    L += ["", f"_{lat['caveat']}_", ""]
    t = agg["tokens_and_cost"]
    L += [
        "## Tokens and cost",
        "",
        f"* cases with token data: {t['cases_with_token_data']} / {agg['n_cases']}; cases with cost data: "
        f"{t['cases_with_cost_data']} / {agg['n_cases']}",
        f"* mean input / output tokens: {t['input_tokens_mean']} / {t['output_tokens_mean']}; total cost USD: {t['cost_usd_total']}",
        f"* {t['note']}",
        "",
    ]
    if agg["repeatability"]:
        r = agg["repeatability"]
        L += [
            "## Repeatability",
            "",
            f"* cases with repeats: {r['cases_with_repeats']}; unstable (task-success flips): "
            f"{pct(r['unstable_cases'])}",
            "",
        ]
    failed = [r for r in records if not r["scoring"]["task_success"] and r["repeat_index"] == 0]
    L += [
        "## Failure examples (first 25 failed cases, repeat 0)",
        "",
        "| case | category | expected | agent status | primary failure | prompt |",
        "|---|---|---|---|---|---|",
    ]
    for r in failed[:25]:
        pr = r["prompt"].replace("|", "\\|")
        L.append(
            f"| {r['case_id']} | {r['category']} | {r['expected_outcome']} | {r['status']} | "
            f"{r['scoring']['primary_failure_category']} | {pr} |"
        )
    L += ["", f"Total failed cases (repeat 0): {len(failed)}. Full detail: `cases.jsonl`.", ""]
    return "\n".join(L)
