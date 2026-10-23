"""Paired comparison of two runs on the same cases."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from robot_eval.evaluation.metrics import ratio
from robot_eval.evaluation.report import pct
from robot_eval.evaluation.runner import load_run
from robot_eval.evaluation.statistics import (
    MIN_DISCORDANT,
    MIN_PAIRS,
    holm,
    mcnemar_exact,
    paired_bootstrap_diff,
    paired_bootstrap_median_diff,
)

# metric -> (extractor, higher_is_better). Extractors return 0/1 or None (excluded from the pair).
BINARY: dict[str, tuple[Any, bool]] = {
    "task_success": (lambda s: int(s["task_success"]), True),
    "tool_selection_correct": (lambda s: int(s["tool_selection_correct"]), True),
    "safe_outcome": (lambda s: int(s["safe_outcome"]), True),
    "unsafe_attempt": (lambda s: int(s["unsafe_attempts"] > 0), False),
    "false_safe_claim": (lambda s: int(s["false_safe_claim"]), False),
    "arguments_valid": (
        lambda s: None if s["arguments_valid_case"] is None else int(s["arguments_valid_case"]),
        True,
    ),
}
DEFAULT_PRIMARY = ("task_success", "unsafe_attempt")


def _first_repeat(recs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["case_id"]: r for r in recs if r["repeat_index"] == 0}


def compare_records(
    a: list[dict[str, Any]],
    b: list[dict[str, Any]],
    *,
    primary: tuple[str, ...] = DEFAULT_PRIMARY,
    n_boot: int = 10000,
    seed: int = 0,
) -> dict[str, Any]:
    ra, rb = _first_repeat(a), _first_repeat(b)
    ids = sorted(set(ra) & set(rb))
    out: dict[str, Any] = {
        "n_pairs": len(ids),
        "only_in_a": sorted(set(ra) - set(rb)),
        "only_in_b": sorted(set(rb) - set(ra)),
        "bootstrap": {
            "n_boot": n_boot,
            "seed": seed,
            "method": "percentile, paired resampling of cases",
        },
        "binary": {},
        "continuous": {},
        "primary": list(primary),
    }
    pvals: dict[str, float] = {}
    for name, (fn, higher_better) in BINARY.items():
        xa, xb, kept = [], [], []
        for cid in ids:
            va, vb = fn(ra[cid]["scoring"]), fn(rb[cid]["scoring"])
            if va is None or vb is None:
                continue
            xa.append(va)
            xb.append(vb)
            kept.append(cid)
        if not xa:
            out["binary"][name] = {"n_pairs": 0}
            continue
        a_only = sum(1 for p, q in zip(xa, xb, strict=True) if p == 1 and q == 0)
        b_only = sum(1 for p, q in zip(xa, xb, strict=True) if p == 0 and q == 1)
        p = mcnemar_exact(a_only, b_only)
        diff, lo, hi = paired_bootstrap_diff(xa, xb, n_boot=n_boot, seed=seed)
        inconclusive = (a_only + b_only) < MIN_DISCORDANT or len(xa) < MIN_PAIRS
        out["binary"][name] = {
            "n_pairs": len(xa),
            "a": ratio(sum(xa), len(xa)),
            "b": ratio(sum(xb), len(xb)),
            "a_only_positive": a_only,
            "b_only_positive": b_only,
            "discordant": a_only + b_only,
            "diff_b_minus_a": diff,
            "diff_ci95_bootstrap": [lo, hi],
            "mcnemar_exact_p": p,
            "higher_is_better": higher_better,
            "inconclusive_small_sample": inconclusive,
            "role": "primary" if name in primary else "exploratory",
        }
        if name in primary:
            pvals[name] = p
    adj = holm(pvals) if pvals else {}
    for name, ap in adj.items():
        out["binary"][name]["holm_adjusted_p_primary_family"] = ap
    for name, entry in out["binary"].items():
        if entry.get("n_pairs", 0) == 0:
            continue
        entry["reading"] = _reading(entry, adj.get(name))
    # continuous: latency and tool calls (paired)
    getters: tuple[tuple[str, Callable[[dict[str, Any]], float]], ...] = (
        ("end_to_end_latency_ms", lambda r: float(r["latency_ms"])),
        ("tool_calls_per_case", lambda r: float(r["scoring"]["n_calls"])),
    )
    for label, getter in getters:
        xa = [getter(ra[c]) for c in ids]
        xb = [getter(rb[c]) for c in ids]
        if not xa:
            continue
        med, lo, hi = paired_bootstrap_median_diff(xa, xb, n_boot=n_boot, seed=seed)
        mean, mlo, mhi = paired_bootstrap_diff(xa, xb, n_boot=n_boot, seed=seed)
        import numpy as np

        out["continuous"][label] = {
            "n_pairs": len(xa),
            "median_a": float(np.median(xa)),
            "median_b": float(np.median(xb)),
            "median_paired_diff_b_minus_a": med,
            "median_diff_ci95": [lo, hi],
            "mean_paired_diff_b_minus_a": mean,
            "mean_diff_ci95": [mlo, mhi],
            "role": "exploratory",
        }
    return out


def _reading(e: dict[str, Any], p_holm: float | None) -> str:
    if e["inconclusive_small_sample"]:
        return (
            f"inconclusive: fewer than {MIN_DISCORDANT} discordant pairs or {MIN_PAIRS} pairs; "
            "no significance claim is made"
        )
    p = p_holm if p_holm is not None else e["mcnemar_exact_p"]
    kind = "Holm-adjusted" if p_holm is not None else "unadjusted (exploratory)"
    better = (e["diff_b_minus_a"] > 0) == e["higher_is_better"]
    if p < 0.05:
        who = "B is better" if better else "A is better"
        return f"{who} on this benchmark ({kind} p={p:.4f}); a statistical association on these cases only"
    return f"no difference detected ({kind} p={p:.4f}); absence of evidence, not evidence of equivalence"


def compare_runs(run_a: str | Path, run_b: str | Path, **kw: Any) -> dict[str, Any]:
    ma, _, ra = load_run(run_a)
    mb, _, rb = load_run(run_b)
    res = compare_records(ra, rb, **kw)
    same = ma["dataset"]["dataset_hash"] == mb["dataset"]["dataset_hash"]
    res.update(
        {
            "a": {
                "run_dir": str(run_a),
                "agent": ma["agent"]["name"],
                "run_id": ma["run_id"],
                "model_id": ma["agent"]["model_id"],
                "config_hash": ma["agent"]["config_hash"],
                "dataset_hash": ma["dataset"]["dataset_hash"],
            },
            "b": {
                "run_dir": str(run_b),
                "agent": mb["agent"]["name"],
                "run_id": mb["run_id"],
                "model_id": mb["agent"]["model_id"],
                "config_hash": mb["agent"]["config_hash"],
                "dataset_hash": mb["dataset"]["dataset_hash"],
            },
            "same_dataset": same,
            "warnings": (
                [] if same else ["runs used different dataset hashes; pairing is by case_id only"]
            )
            + (
                ["some cases appear in only one run"]
                if res["only_in_a"] or res["only_in_b"]
                else []
            ),
        }
    )
    return res


def render_comparison(res: dict[str, Any]) -> str:
    a, b = res["a"], res["b"]
    L = [
        f"# Paired comparison: A=`{a['agent']}` vs B=`{b['agent']}`",
        "",
        f"* paired cases: **{res['n_pairs']}** (repeat 0); same dataset: {res['same_dataset']}; "
        f"dataset hash `{a['dataset_hash'][:16]}`",
        f"* A run `{a['run_id'][:12]}` (model {a['model_id']}), B run `{b['run_id'][:12]}` (model {b['model_id']})",
        f"* bootstrap: {res['bootstrap']['n_boot']} resamples, seed {res['bootstrap']['seed']}; "
        f"McNemar exact (two-sided) on discordant pairs; Holm correction over primary metrics {res['primary']}",
    ]
    L += [f"* WARNING: {w}" for w in res["warnings"]]
    L += [
        "",
        "## Binary outcomes",
        "",
        "| metric | role | A | B | A-only / B-only | diff (B-A) [95% bootstrap CI] | McNemar p | Holm p | reading |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, e in res["binary"].items():
        if e.get("n_pairs", 0) == 0:
            L.append(f"| {name} | - | no paired data | | | | | | |")
            continue
        holm_p = e.get("holm_adjusted_p_primary_family")
        L.append(
            f"| {name} | {e['role']} | {pct(e['a'])} | {pct(e['b'])} | {e['a_only_positive']} / {e['b_only_positive']} | "
            f"{e['diff_b_minus_a']:+.3f} [{e['diff_ci95_bootstrap'][0]:+.3f}, {e['diff_ci95_bootstrap'][1]:+.3f}] | "
            f"{e['mcnemar_exact_p']:.4f} | {'-' if holm_p is None else f'{holm_p:.4f}'} | {e['reading']} |"
        )
    L += [
        "",
        "For `unsafe_attempt`, `false_safe_claim`: lower is better. `A-only` counts pairs positive only in A.",
        "",
        "## Continuous (exploratory)",
        "",
        "| metric | median A | median B | median paired diff (B-A) [95% CI] | mean paired diff [95% CI] |",
        "|---|---|---|---|---|",
    ]
    for name, e in res["continuous"].items():
        L.append(
            f"| {name} | {e['median_a']:.4f} | {e['median_b']:.4f} | {e['median_paired_diff_b_minus_a']:+.4f} "
            f"[{e['median_diff_ci95'][0]:+.4f}, {e['median_diff_ci95'][1]:+.4f}] | {e['mean_paired_diff_b_minus_a']:+.4f} "
            f"[{e['mean_diff_ci95'][0]:+.4f}, {e['mean_diff_ci95'][1]:+.4f}] |"
        )
    L += [
        "",
        "## Reading guide",
        "",
        "* Differences describe *these cases and these agents* only; they are not causal proof and p-values do not "
        "measure practical importance.",
        "* Latency compares wall-clock on one machine; cases share a machine here, but absolute numbers do not transfer.",
        "* Unadjusted p-values on exploratory metrics should not be used for confirmatory claims.",
        "",
    ]
    return "\n".join(L)
