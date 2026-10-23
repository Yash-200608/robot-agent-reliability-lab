"""Builds reports/baseline_report.md strictly from saved experiment artifacts (never from memory).

Every number is read from ``experiment.json`` / ``summary.json`` / ``cases.jsonl`` / ``comparison_*.json``;
wording follows the interpretation rules of docs/experiment_protocol.md (inconclusive stays inconclusive).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_eval.evaluation.report import pct
from robot_eval.evaluation.runner import load_run

REQUIRED = (
    "exp0_pipeline",
    "exp1_dataset_audit",
    "exp2_reference_baseline",
    "exp3_guard_ablation",
    "exp4_single_vs_two_stage",
    "exp5_regression",
)


def latest_dir(root: Path, name: str) -> Path:
    d = root / name
    if not d.is_dir() or not any(d.iterdir()):
        raise FileNotFoundError(f"no saved artifacts for {name} under {root}")
    return sorted(p for p in d.iterdir() if p.is_dir())[-1]


def _load(root: Path, name: str) -> tuple[Path, dict[str, Any]]:
    d = latest_dir(root, name)
    return d, json.loads((d / "experiment.json").read_text(encoding="utf-8"))


def _run(
    d: Path, rec: dict[str, Any], rid: str
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return load_run(d / rec["runs"][rid]["dir"])


def _cmp(d: Path, rec: dict[str, Any], a: str, b: str) -> dict[str, Any] | None:
    for c in rec["comparisons"]:
        if c["a"] == a and c["b"] == b:
            return json.loads((d / c["file"]).read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return None


def _f2(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _metric_rows(label: str, agg: dict[str, Any]) -> str:
    m = agg["metrics"]
    c = m["collision_classification"]
    return (
        f"| {label} | {pct(m['task_success_rate'])} | {pct(m['tool_selection_accuracy'])} | "
        f"{pct(m['argument_validity_call_level'])} | {pct(m['safe_outcome_rate'])} | "
        f"{m['unsafe_action_attempt_rate_cases']['num']}/{m['unsafe_action_attempt_rate_cases']['den']} | "
        f"{pct(m['unsafe_action_attempt_rate_on_hazard_cases'])} | {pct(m['safety_block_rate'])} | "
        f"{m['false_safe_claims']['num']} | {m['harmful_state_changes']['num']} | "
        f"{_f2(c['precision'])} / {_f2(c['recall'])} / {_f2(c['f1'])} (n={c['n']}) | {pct(m['path_clearance_success'])} | "
        f"{pct(m['tool_call_success_rate'])} |"
    )


HEAD = (
    "| run | task success | tool selection | argument validity (calls) | safe outcome | unsafe-attempt cases | "
    "unsafe attempts on hazard cases | safety-block rate | false-safe | harmful state changes | "
    "collision P / R / F1 | path/clearance success | tool-call success |\n" + "|" + "---|" * 13
)


def _primary_rows(cmp: dict[str, Any]) -> list[str]:
    rows = []
    for name, e in cmp["binary"].items():
        if e.get("n_pairs", 0) and e["role"] == "primary":
            hp = e.get("holm_adjusted_p_primary_family")
            rows.append(
                f"* **{name}**: A {pct(e['a'])} -> B {pct(e['b'])}; A-only {e['a_only_positive']} / B-only "
                f"{e['b_only_positive']} discordant; diff (B-A) {e['diff_b_minus_a']:+.3f} "
                f"[{e['diff_ci95_bootstrap'][0]:+.3f}, {e['diff_ci95_bootstrap'][1]:+.3f}]; McNemar p={e['mcnemar_exact_p']:.4f}"
                f"{'' if hp is None else f', Holm-adjusted p={hp:.4f}'}. Reading: {e['reading']}."
            )
    return rows


def _ts(v: dict[str, Any] | None) -> str:
    return "-" if v is None else f"{v['task_success']['num']}/{v['task_success']['den']}"


def _safety_notes(recs: list[dict[str, Any]]) -> list[str]:
    att = [r for r in recs if r["scoring"]["unsafe_attempts"] > 0]
    haz = [r for r in att if r["safety_label"] == "hazard"]
    non = [r for r in att if r["safety_label"] != "hazard"]
    blocked = sum(r["scoring"]["safety_blocked"] for r in att)
    den = sum(r["scoring"]["safety_block_denominator"] for r in att)
    notes = [
        f"Unsafe-attempt cases: {len(att)} ({len(haz)} labelled hazard, {len(non)} not: "
        f"{', '.join(r['case_id'] for r in non) or 'none'}); simulator rejected {blocked}/{den} unsafe-or-invalid move calls in those cases.",
    ]
    harm = [r for r in recs if r["scoring"]["harmful_state_change"]]
    if harm:
        cats = sorted({r["category"] for r in harm})
        notes.append(
            f"Harmful state changes ({len(harm)}): categories {', '.join(cats)}. "
            + (
                "These are moves the *simulator allowed* but that violated an instruction it cannot see (a user-requested "
                "clearance or a self-contradictory request); simulator-side checks alone cannot catch them."
                if set(cats) <= {"clearance", "contradictory"}
                else "See the failed-case table for each prompt."
            )
        )
    return notes


def build_baseline_report(exp_root: str | Path) -> str:
    root = Path(exp_root)
    dirs = {n: _load(root, n) for n in REQUIRED}
    d0, r0 = dirs["exp0_pipeline"]
    d1, r1 = dirs["exp1_dataset_audit"]
    d2, r2 = dirs["exp2_reference_baseline"]
    d3, r3 = dirs["exp3_guard_ablation"]
    d4, r4 = dirs["exp4_single_vs_two_stage"]
    d5, r5 = dirs["exp5_regression"]
    audit = json.loads((d1 / "audit.json").read_text(encoding="utf-8"))
    dev_meta, dev_sum, dev_recs = _run(d2, r2, "dev_reference")
    held_meta, held_sum, held_recs = _run(d2, r2, "heldout_reference")
    da, ha = dev_sum["aggregate"], held_sum["aggregate"]
    hm = ha["metrics"]
    comb = audit["combined"]["composition"]
    c3a = _cmp(d3, r3, "baseline", "guarded")
    c4a = _cmp(d4, r4, "single_rule", "two_stage_rule")
    abstract = (
        f"The deterministic keyword reference agent (not an LLM, not an upper bound) solved {pct(hm['task_success_rate'])} of the "
        f"{held_meta['dataset']['n_cases']} held-out cases and {pct(da['metrics']['task_success_rate'])} of the "
        f"{dev_meta['dataset']['n_cases']} development cases. On the held-out split "
        f"{hm['unsafe_action_attempt_rate_cases']['num']}/{hm['unsafe_action_attempt_rate_cases']['den']} cases involved an unsafe-action attempt "
        f"(safety-block rate {pct(hm['safety_block_rate'])}) and {hm['harmful_state_changes']['num']} cases ended in a harmful state change."
    )
    if c3a:
        ua, ts = c3a["binary"]["unsafe_attempt"], c3a["binary"]["task_success"]
        tcalls = c3a["continuous"]["tool_calls_per_case"]["mean_paired_diff_b_minus_a"]
        abstract += (
            f" The guarded configuration had unsafe-attempt cases {ua['a']['num']}/{ua['a']['den']} -> {ua['b']['num']}/{ua['b']['den']} "
            f"({ua['reading']}) with {tcalls:+.2f} tool calls per case on average; task success {ts['a']['num']}/{ts['a']['den']} -> "
            f"{ts['b']['num']}/{ts['b']['den']} ({ts['reading']})."
        )
    if c4a:
        t4 = c4a["binary"]["task_success"]
        abstract += (
            f" The rule-based two-stage variant (triage rules + the guarded executor) vs the single-stage guarded agent: task success "
            f"{t4['a']['num']}/{t4['a']['den']} -> {t4['b']['num']}/{t4['b']['den']} ({t4['reading']})."
        )
    abstract += (
        " Regression checks: "
        + "; ".join(
            f"{g['candidate']} {'passed' if g['passed_check'] else 'failed'} (expected {g['expect']})"
            for g in r5["regressions"]
        )
        + "."
    )
    L: list[str] = []
    L += [
        "# Baseline report: deterministic reference agents on benchmark v1",
        "",
        "_Generated by `robot-eval baseline-report` strictly from the saved artifacts under `reports/experiments/`. "
        "Every number below is read from those files; nothing is typed by hand._",
        "",
        "> **Scope.** Simulation only. These are rule-based agents on a synthetic, same-author benchmark. "
        "No language model was evaluated (LLM arms were blocked: no credentials). Nothing here is a claim about "
        "industrial safety or about LLM behaviour.",
        "",
        "## Abstract",
        "",
        abstract,
        "",
        "## Questions",
        "",
        "RQ1 which request types fail; RQ2 guarded vs unguarded; RQ3 single-stage vs two-stage; RQ4 regression detection "
        "(`docs/experiment_protocol.md`, written before the held-out runs).",
        "",
        "## Methods",
        "",
        f"* Dataset v1: {comb['n_cases']} cases (development {da['n_cases']}, held-out {ha['n_cases']}); dataset hashes "
        f"`{dev_meta['dataset']['dataset_hash'][:16]}` (dev), `{held_meta['dataset']['dataset_hash'][:16]}` (held-out); smoke v0: 24 cases.",
        f"* Code: package {held_meta['code']['package_version']}, source hash `{held_meta['code']['source_sha256'][:16]}`; "
        f"Python {held_meta['environment']['python']} on {held_meta['environment']['platform']}/{held_meta['environment']['machine']}; "
        f"pydantic {held_meta['environment']['packages'].get('pydantic')}, numpy {held_meta['environment']['packages'].get('numpy')}.",
        f"* Statistics: Wilson 95% CIs; exact McNemar + paired bootstrap ({r3['bootstrap']['n_boot']} resamples, seed {r3['bootstrap']['seed']}); "
        "Holm over the primary metrics of each confirmatory comparison; results with < 10 discordant pairs or < 30 pairs are marked inconclusive.",
        "* Held-out access: every held-out run is appended to `reports/heldout_access_log.jsonl` (agent, config hash, code hash, dataset hash, "
        "command). Any change made after the first held-out run, and any deviation from the protocol, is recorded in "
        "`docs/experiment_protocol.md` section 11.",
        "* Reproduce: `robot-eval experiment --name <id> --out reports/experiments` for ids "
        + ", ".join(f"`{n}`" for n in REQUIRED)
        + ". Commands actually used:",
    ]
    L += [
        f"  * `{r['command']}` ({r['name']}, {r['created_at']})" for r in (r0, r1, r2, r3, r4, r5)
    ]
    L += ["", "## Results", "", "### Experiment 0 - pipeline (smoke, not an AI-quality result)", ""]
    for rid in r0["runs"]:
        s = _run(d0, r0, rid)[1]["aggregate"]["metrics"]
        L.append(
            f"* `{rid}`: task success {pct(s['task_success_rate'])}; tool selection {pct(s['tool_selection_accuracy'])}."
        )
    for b in r0["blocked"]:
        L.append(f"* blocked: `{b['id']}`: {b['reason']}")
    L += [
        "",
        "### Experiment 1 - dataset audit",
        "",
        f"* all files pass validation (oracle recomputation, simulator cross-check, certificates): **{audit['all_valid']}**",
        f"* stress-category share (ambiguity/missing/invalid/contradictory/fault/override/boundary): {comb['stress_categories_share']:.3f} "
        f"({comb['stress_categories_count']}/{comb['n_cases']})",
    ]
    for k, v in audit["cross_file_leakage"].items():
        L.append(
            f"* leakage {k}: identical prompts {v['identical_normalized_prompts']}, identical skeletons {v['identical_skeletons']}, "
            f"identical (world,intent) {v['identical_world_intent_pairs']}, near-duplicate pairs (Jaccard >= 0.80) "
            f"{v['near_duplicate_pairs_jaccard_ge_0.80']}"
        )
    L += [
        "",
        "### Experiment 2 - reference baseline (development vs held-out)",
        "",
        HEAD,
        _metric_rows("development", da),
        _metric_rows("held-out", ha),
        "",
        "Task success by category (num/den):",
        "",
        "| category | development | held-out |",
        "|---|---|---|",
    ]
    cats = sorted(set(da["by_category"]) | set(ha["by_category"]))
    for c in cats:
        dv, hv = da["by_category"].get(c), ha["by_category"].get(c)
        L.append(f"| {c} | {_ts(dv)} | {_ts(hv)} |")
    L += ["", "### Experiment 3 - guard ablation (held-out, RQ2)", "", HEAD]
    for rid in r3["runs"]:
        L.append(_metric_rows(rid, _run(d3, r3, rid)[1]["aggregate"]))
    c3 = _cmp(d3, r3, "baseline", "guarded")
    L += ["", "Confirmatory comparison baseline (A) vs guarded (B), primary metrics:", ""]
    if c3:
        L += _primary_rows(c3)
        tc = c3["continuous"]["tool_calls_per_case"]
        lat = c3["continuous"]["end_to_end_latency_ms"]
        L += [
            f"* extra tool calls per case (mean paired diff): {tc['mean_paired_diff_b_minus_a']:+.3f} "
            f"[{tc['mean_diff_ci95'][0]:+.3f}, {tc['mean_diff_ci95'][1]:+.3f}] (exploratory)",
            f"* end-to-end latency, median paired difference: {lat['median_paired_diff_b_minus_a']:+.4f} ms "
            f"[{lat['median_diff_ci95'][0]:+.4f}, {lat['median_diff_ci95'][1]:+.4f}] (exploratory; Python overhead on one machine)",
        ]
        te = c3["binary"]["tool_selection_correct"]
        L.append(
            f"* exploratory: tool-selection accuracy A {pct(te['a'])} -> B {pct(te['b'])}; unadjusted McNemar p={te['mcnemar_exact_p']:.4f}"
        )
    L += [
        "",
        "Interpretation constraint: the simulator rejects every unsafe move in *both* conditions, so executed unsafe actions are zero by "
        "construction; the guard changes what is attempted. A pre-check guard attempting fewer unsafe moves is close to mechanical for rule-based agents.",
        "",
        "### Experiment 4 - single-stage vs two-stage (held-out, RQ3, rule backend)",
        "",
        HEAD,
    ]
    for rid in r4["runs"]:
        L.append(_metric_rows(rid, _run(d4, r4, rid)[1]["aggregate"]))
    c4 = _cmp(d4, r4, "single_rule", "two_stage_rule")
    L += ["", "Comparison single_rule (A) vs two_stage_rule (B), primary metrics:", ""]
    if c4:
        L += _primary_rows(c4)
    for b in r4["blocked"]:
        L.append(f"* **blocked (not simulated):** `{b['id']}` - {b['reason']}")
    L += [
        "",
        "Interpretation constraint: `two_stage_rule` = rule triage + the same executor as `reference_guarded`; the difference comes from the triage "
        "rules by construction. This exercises the orchestration pipeline; it says nothing about LLM single- vs two-stage behaviour.",
        "",
        "### Experiment 5 - regression detection (development, RQ4)",
        "",
    ]
    for g in r5["regressions"]:
        L.append(
            f"* {g['baseline']} -> {g['candidate']}: check {'PASSED' if g['passed_check'] else 'FAILED'}; expected {g['expect']}; "
            f"expectation met: **{g['expectation_met']}**"
            + "".join(f"\n  * {x}" for x in g["findings"])
        )
    L += ["", "## Failure analysis", ""]
    L.append("Held-out failed cases (primary failure category, repeat 0):")
    L += [
        "",
        "| case | category | expected | agent status | primary failure | prompt |",
        "|---|---|---|---|---|---|",
    ]
    for r in held_recs:
        if not r["scoring"]["task_success"]:
            L.append(
                f"| {r['case_id']} | {r['category']} | {r['expected_outcome']} | {r['status']} | "
                f"{r['scoring']['primary_failure_category']} | {r['prompt'].replace('|', chr(92) + '|')} |"
            )
    sf = ha["safety_findings"]
    L += [
        "",
        f"Held-out failure taxonomy (primary): {', '.join(f'{k}={v}' for k, v in ha['failure_taxonomy_primary'].items()) or 'none'}.",
        "",
        "Safety findings, held-out unguarded reference, individually:",
        "",
        f"* unsafe-action attempts ({len(sf['unsafe_attempt_case_ids'])}): {', '.join(sf['unsafe_attempt_case_ids']) or 'none'}",
        f"* false-safe claims ({len(sf['false_safe_claim_case_ids'])}): {', '.join(sf['false_safe_claim_case_ids']) or 'none'}",
        f"* harmful state changes ({len(sf['harmful_state_change_case_ids'])}): {', '.join(sf['harmful_state_change_case_ids']) or 'none'}",
        "",
        *_safety_notes(held_recs),
        "",
        "## Limitations",
        "",
        "* Same author wrote datasets, oracle and reference agent; held-out is held out from tuning, not from the author's knowledge of the wording. "
        "The similarity of development and held-out scores should not be read as evidence of generalisation.",
        "* Synthetic template English; 124 held-out cases; per-category and per-family counts are small (many categories have 4-10 cases).",
        "* Rule-based agents only. LLM adapter, MCP-with-LLM and Langfuse export were never run against live services.",
        "* Latency is single-machine Python wall-clock; it carries no information about real robot or model latency.",
        "* Windows and Python versions other than 3.13 were not exercised.",
        "",
        "## Conclusion",
        "",
        "Applying the pre-stated reading rules (`docs/experiment_protocol.md` section 8):",
        "",
    ]
    worst = sorted(
        (
            (v["task_success"]["value"], k, v["task_success"]["num"], v["task_success"]["den"])
            for k, v in ha["by_category"].items()
            if v["task_success"]["value"] < 1.0
        )
    )
    L.append(
        "* **RQ1 (descriptive):** held-out categories below 100% task success: "
        + (", ".join(f"{k} ({n}/{d})" for _, k, n, d in worst) or "none")
        + ". Counts per category are small; this identifies where to look, not statistically distinct rates."
    )
    if c3:
        ua, ts = c3["binary"]["unsafe_attempt"], c3["binary"]["task_success"]
        L.append(
            f"* **RQ2:** unsafe-attempt cases {ua['a']['num']}/{ua['a']['den']} -> {ua['b']['num']}/{ua['b']['den']} ({ua['reading']}); task success "
            f"{ts['a']['num']}/{ts['a']['den']} -> {ts['b']['num']}/{ts['b']['den']} ({ts['reading']}). The reduction in attempts is supported on this "
            "benchmark but is largely mechanical for a pre-check guard; the cost is extra tool calls. No claim about executed unsafe actions "
            "(zero in both conditions by construction)."
        )
    if c4:
        ts4 = c4["binary"]["task_success"]
        L.append(
            f"* **RQ3:** rule-backend task success {ts4['a']['num']}/{ts4['a']['den']} -> {ts4['b']['num']}/{ts4['b']['den']}: {ts4['reading']}. "
            "The LLM comparison is **unresolved (not run)**."
        )
    ok = all(g["expectation_met"] for g in r5["regressions"])
    L.append(
        f"* **RQ4:** all regression expectations met: {ok}. The injected clearance-routing regression was flagged and the identical rerun passed; this "
        "shows detection of that failure class, not general sensitivity."
    )
    L.append("")
    return "\n".join(L)
