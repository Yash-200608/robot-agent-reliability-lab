"""Dataset audit (Experiment 1): composition, balance, duplicates and split leakage.

Everything is computed from the dataset files; nothing is hand-entered.
"""

from __future__ import annotations

import re
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

from robot_eval.domain.case import STRESS_CATEGORIES, BenchmarkCase, ExpectedOutcome, Family
from robot_eval.evaluation.dataset import (
    dataset_hash,
    default_worlds_path,
    load_cases,
    normalize_prompt,
    prompt_skeleton,
    validate_dataset_file,
)

NEAR_DUP_JACCARD = 0.80


def _display_path(p: Path) -> str:
    """Machine-independent path for reports: relative to the working directory when possible."""
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return p.name


def _tokens(skel: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z#]+", skel))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 1.0


def _counter(cases: list[BenchmarkCase], fn: Any) -> dict[str, int]:
    return dict(sorted(Counter(fn(c) for c in cases).items()))


def _composition(cases: list[BenchmarkCase]) -> dict[str, Any]:
    n = len(cases)
    stress = sum(1 for c in cases if c.category in STRESS_CATEGORIES)
    polarity: dict[str, dict[str, int]] = {}
    for c in cases:
        for k, v in c.expected.answer.items():
            if isinstance(v, bool):
                polarity.setdefault(k, {"true": 0, "false": 0})["true" if v else "false"] += 1
    return {
        "n_cases": n,
        "by_category": _counter(cases, lambda c: c.category.value),
        "by_family": _counter(cases, lambda c: c.intent.family.value),
        "by_difficulty": _counter(cases, lambda c: c.difficulty.value),
        "by_world": _counter(cases, lambda c: c.world_id),
        "by_expected_outcome": _counter(cases, lambda c: c.expected.outcome.value),
        "by_safety_label": _counter(cases, lambda c: c.safety.label),
        "by_source_type": _counter(cases, lambda c: c.source_type),
        "faulted_cases": sum(1 for c in cases if c.fault is not None),
        "stress_categories_count": stress,
        "stress_categories_share": round(stress / n, 4) if n else None,
        "boolean_answer_polarity": polarity,
        "unsafe_move_cases": sum(1 for c in cases if c.expected.unsafe_move),
        "hard_share": round(sum(1 for c in cases if c.difficulty.value == "hard") / n, 4)
        if n
        else None,
    }


def _dup_report(cases: list[BenchmarkCase]) -> dict[str, Any]:
    skels = [prompt_skeleton(c.prompt) for c in cases]
    norm = [normalize_prompt(c.prompt) for c in cases]
    toks = [_tokens(s) for s in skels]
    pairs = []
    for i, j in combinations(range(len(cases)), 2):
        if skels[i] != skels[j]:
            sim = _jaccard(toks[i], toks[j])
            if sim >= NEAR_DUP_JACCARD:
                pairs.append((round(sim, 3), cases[i].case_id, cases[j].case_id))
    pairs.sort(reverse=True)
    return {
        "n_unique_normalized_prompts": len(set(norm)),
        "n_unique_skeletons": len(set(skels)),
        "skeleton_reuse": "templated cases share a skeleton and differ in numbers",
        "near_duplicate_skeleton_pairs_ge_0.80": len(pairs),
        "examples": [list(p) for p in pairs[:8]],
    }


def audit_datasets(
    paths: list[str | Path], worlds_path: str | Path | None = None
) -> dict[str, Any]:
    wp = Path(worlds_path) if worlds_path else default_worlds_path(paths[0])
    per_file: dict[str, Any] = {}
    all_cases: dict[str, list[BenchmarkCase]] = {}
    for p in paths:
        rep = validate_dataset_file(p, worlds_path=wp)
        cases = load_cases(p)
        all_cases[str(p)] = cases
        splits = sorted({c.split.value for c in cases})
        versions = sorted({c.benchmark_version for c in cases})
        per_file[str(p)] = {
            "dataset_hash": dataset_hash(p, wp),
            "splits": splits,
            "benchmark_versions": versions,
            "validation": rep.to_dict(),
            "composition": _composition(cases),
            "duplicates_within_file": _dup_report(cases),
        }
    out: dict[str, Any] = {"worlds_file": _display_path(wp), "files": per_file}

    # combined v1 view and cross-split leakage
    if len(paths) > 1:
        names = list(all_cases)
        combined = [c for cs in all_cases.values() for c in cs]
        ids = [c.case_id for c in combined]
        out["combined"] = {
            "n_cases": len(combined),
            "case_ids_unique_across_files": len(ids) == len(set(ids)),
            "composition": _composition(combined),
        }
        leaks: dict[str, Any] = {}
        for a, b in combinations(names, 2):
            sa = {prompt_skeleton(c.prompt) for c in all_cases[a]}
            sb = {prompt_skeleton(c.prompt) for c in all_cases[b]}
            na = {normalize_prompt(c.prompt) for c in all_cases[a]}
            nb = {normalize_prompt(c.prompt) for c in all_cases[b]}
            ta = [(c.case_id, _tokens(prompt_skeleton(c.prompt))) for c in all_cases[a]]
            tb = [(c.case_id, _tokens(prompt_skeleton(c.prompt))) for c in all_cases[b]]
            close = []
            for ia, xa in ta:
                for ib, xb in tb:
                    sim = _jaccard(xa, xb)
                    if sim >= NEAR_DUP_JACCARD:
                        close.append((round(sim, 3), ia, ib))
            close.sort(reverse=True)
            ka = {(c.world_id, c.intent.model_dump_json()) for c in all_cases[a]}
            kb = {(c.world_id, c.intent.model_dump_json()) for c in all_cases[b]}
            leaks[f"{Path(a).name} vs {Path(b).name}"] = {
                "identical_normalized_prompts": len(na & nb),
                "identical_skeletons": len(sa & sb),
                "identical_world_intent_pairs": len(ka & kb),
                "near_duplicate_pairs_jaccard_ge_0.80": len(close),
                "near_duplicate_examples": [list(x) for x in close[:8]],
            }
        out["cross_file_leakage"] = leaks
    out["all_valid"] = all(f["validation"]["ok"] for f in per_file.values())
    return out


def render_audit_markdown(audit: dict[str, Any]) -> str:
    L: list[str] = [
        "# Dataset audit",
        "",
        "_Generated by `robot-eval audit-dataset`; do not edit by hand._",
        "",
    ]
    L.append(f"Worlds file: `{audit['worlds_file']}`  ")
    L.append(f"All files pass validation: **{audit['all_valid']}**")
    for name, f in audit["files"].items():
        comp, dup = f["composition"], f["duplicates_within_file"]
        L += [
            "",
            f"## `{name}`",
            "",
            f"* cases: **{comp['n_cases']}**, splits: {f['splits']}, versions: {f['benchmark_versions']}",
            f"* dataset hash (file + worlds): `{f['dataset_hash']}`",
            f"* validation: ok={f['validation']['ok']}, errors={len(f['validation']['errors'])}, "
            f"warnings={len(f['validation']['warnings'])}",
            f"* stress categories (ambiguity/missing/invalid/contradictory/fault/override/boundary): "
            f"{comp['stress_categories_count']} / {comp['n_cases']} = {comp['stress_categories_share']}",
            f"* hard-difficulty share: {comp['hard_share']}; faulted cases: {comp['faulted_cases']}; "
            f"oracle-unsafe move requests: {comp['unsafe_move_cases']}",
            f"* unique normalised prompts: {dup['n_unique_normalized_prompts']}; "
            f"unique skeletons (numbers masked): {dup['n_unique_skeletons']}; "
            f"near-duplicate skeleton pairs (Jaccard >= {NEAR_DUP_JACCARD}): "
            f"{dup['near_duplicate_skeleton_pairs_ge_0.80']}",
            "",
        ]
        for title, key in (
            ("Category", "by_category"),
            ("Family", "by_family"),
            ("Difficulty", "by_difficulty"),
            ("World", "by_world"),
            ("Expected outcome", "by_expected_outcome"),
            ("Safety label", "by_safety_label"),
            ("Source type", "by_source_type"),
        ):
            L += [f"**{title}**", "", "| value | cases |", "|---|---|"]
            L += [f"| {k} | {v} |" for k, v in comp[key].items()]
            L.append("")
        if comp["boolean_answer_polarity"]:
            L += [
                "**Boolean answer polarity** (class balance of expected answers)",
                "",
                "| answer key | true | false |",
                "|---|---|---|",
            ]
            L += [
                f"| {k} | {v['true']} | {v['false']} |"
                for k, v in sorted(comp["boolean_answer_polarity"].items())
            ]
            L.append("")
        if f["validation"]["errors"]:
            L += (
                ["**Validation errors**", ""]
                + [f"* {e}" for e in f["validation"]["errors"][:20]]
                + [""]
            )
    if "combined" in audit:
        c = audit["combined"]
        comp = c["composition"]
        L += [
            "",
            "## Combined",
            "",
            f"* cases: **{c['n_cases']}**; case IDs unique across files: {c['case_ids_unique_across_files']}",
            f"* stress-category share: {comp['stress_categories_share']} "
            f"({comp['stress_categories_count']} / {comp['n_cases']})",
            "",
        ]
        L += [
            "## Cross-file leakage",
            "",
            "| pair | identical prompts | identical skeletons | identical (world,intent) | near-dup pairs (J>=0.80) |",
            "|---|---|---|---|---|",
        ]
        for k, v in audit["cross_file_leakage"].items():
            L.append(
                f"| {k} | {v['identical_normalized_prompts']} | {v['identical_skeletons']} | "
                f"{v['identical_world_intent_pairs']} | {v['near_duplicate_pairs_jaccard_ge_0.80']} |"
            )
        for k, v in audit["cross_file_leakage"].items():
            if v["near_duplicate_examples"]:
                L += ["", f"Closest cross-file pairs for {k} (Jaccard, id, id):", ""]
                L += [f"* {x[0]}: `{x[1]}` / `{x[2]}`" for x in v["near_duplicate_examples"]]
    L += [
        "",
        "## How to read this",
        "",
        "* Templated cases deliberately share skeletons within a split (same wording, different numbers).",
        "* Development and held-out use **disjoint template pools**; identical skeletons across files should be 0.",
        "* Near-duplicate pairs use token-set Jaccard on number-masked prompts; they flag very similar "
        "wording, not identical cases.",
        "* This audit does not prove the dataset is representative of real user requests (see "
        "`docs/limitations_and_safety.md`).",
        "",
    ]
    return "\n".join(L)


def families_in(path: str | Path) -> set[Family]:
    return {c.intent.family for c in load_cases(path)}


def outcome_counts(path: str | Path) -> dict[ExpectedOutcome, int]:
    return dict(Counter(c.expected.outcome for c in load_cases(path)))
