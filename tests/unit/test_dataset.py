"""Dataset acceptance criteria (Gate 2) and validator negative tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_eval.domain.case import (
    STRESS_CATEGORIES,
    BenchmarkCase,
    Category,
    ExpectedOutcome,
    Family,
    Split,
)
from robot_eval.evaluation.audit import audit_datasets, render_audit_markdown
from robot_eval.evaluation.dataset import (
    dataset_hash,
    load_cases,
    validate_cases,
    validate_dataset_file,
)
from robot_eval.evaluation.generator import generate_all
from robot_eval.simulator.world import WorldSpec, load_worlds

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "datasets"


@pytest.fixture(scope="module")
def dev() -> list[BenchmarkCase]:
    return load_cases(D / "v1" / "development.jsonl")


@pytest.fixture(scope="module")
def held() -> list[BenchmarkCase]:
    return load_cases(D / "v1" / "heldout_test.jsonl")


@pytest.fixture(scope="module")
def v0() -> list[BenchmarkCase]:
    return load_cases(D / "benchmark_v0.jsonl")


def test_v0_smoke_suite_has_24_cases(v0: list[BenchmarkCase]) -> None:
    assert len(v0) == 24
    assert {c.split for c in v0} == {Split.SMOKE}
    assert {c.benchmark_version for c in v0} == {"v0"}


def test_v1_has_at_least_200_unique_cases(
    dev: list[BenchmarkCase], held: list[BenchmarkCase]
) -> None:
    ids = [c.case_id for c in dev + held]
    assert len(ids) == len(set(ids)) >= 200
    assert {c.split for c in dev} == {Split.DEVELOPMENT}
    assert {c.split for c in held} == {Split.HELDOUT_TEST}


@pytest.mark.parametrize(
    "rel,split,ver",
    [
        ("benchmark_v0.jsonl", Split.SMOKE, "v0"),
        ("v1/development.jsonl", Split.DEVELOPMENT, "v1"),
        ("v1/heldout_test.jsonl", Split.HELDOUT_TEST, "v1"),
    ],
)
def test_committed_files_pass_validation(rel: str, split: Split, ver: str) -> None:
    rep = validate_dataset_file(D / rel, expected_split=split, expected_version=ver)
    assert rep.ok, rep.errors[:5]


def test_stress_share_at_least_20_percent(
    dev: list[BenchmarkCase], held: list[BenchmarkCase]
) -> None:
    for cases in (dev, held, dev + held):
        share = sum(c.category in STRESS_CATEGORIES for c in cases) / len(cases)
        assert share >= 0.20


def test_all_required_categories_present_in_both_splits(
    dev: list[BenchmarkCase], held: list[BenchmarkCase]
) -> None:
    required = set(Category) - {Category.SMOKE}
    assert {c.category for c in dev} == required
    assert {c.category for c in held} == required


def test_every_expected_outcome_type_present(
    dev: list[BenchmarkCase], held: list[BenchmarkCase]
) -> None:
    for cases in (dev, held):
        assert {c.expected.outcome for c in cases} == set(ExpectedOutcome)


def test_no_cross_split_leakage(dev: list[BenchmarkCase], held: list[BenchmarkCase]) -> None:
    a = audit_datasets([D / "v1" / "development.jsonl", D / "v1" / "heldout_test.jsonl"])
    leak = a["cross_file_leakage"]["development.jsonl vs heldout_test.jsonl"]
    assert leak["identical_normalized_prompts"] == 0
    assert leak["identical_skeletons"] == 0
    assert leak["identical_world_intent_pairs"] == 0
    assert a["all_valid"]
    assert "Cross-file leakage" in render_audit_markdown(a)


def test_prompts_do_not_expose_internal_labels(
    dev: list[BenchmarkCase], held: list[BenchmarkCase]
) -> None:
    for c in dev + held:
        if c.intent.family is not Family.SCHEMA_LOOKUP:
            assert "check_" not in c.prompt and "_end_effector" not in c.prompt
        assert c.oracle_notes and c.oracle_notes not in c.prompt


def test_generator_is_reproducible(tmp_path: Path) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "worlds.json").write_bytes((D / "worlds.json").read_bytes())
    generate_all(tmp_path)
    for rel in ("benchmark_v0.jsonl", "v1/development.jsonl", "v1/heldout_test.jsonl"):
        assert (tmp_path / rel).read_bytes() == (D / rel).read_bytes(), rel


def test_dataset_hash_changes_with_content(tmp_path: Path) -> None:
    src = D / "benchmark_v0.jsonl"
    copy = tmp_path / "x.jsonl"
    copy.write_bytes(src.read_bytes())
    h1 = dataset_hash(copy, D / "worlds.json")
    copy.write_bytes(src.read_bytes() + b"\n")
    assert dataset_hash(copy, D / "worlds.json") != h1


# --------------------------------------------------------------- validator negative tests
@pytest.fixture(scope="module")
def worlds() -> dict[str, WorldSpec]:
    return load_worlds(D / "worlds.json")


def _first(
    cases: list[BenchmarkCase], fam: Family, outcome: ExpectedOutcome | None = None
) -> BenchmarkCase:
    return next(
        c
        for c in cases
        if c.intent.family is fam and (outcome is None or c.expected.outcome is outcome)
    )


def _validate(
    c: BenchmarkCase, worlds: dict[str, WorldSpec], extra: list[BenchmarkCase] | None = None
):
    return validate_cases([c, *(extra or [])], worlds)


def test_validator_accepts_untampered(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    assert _validate(_first(dev, Family.QUERY_REACH), worlds).ok


def test_validator_detects_tampered_answer(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    c = _first(dev, Family.QUERY_REACH)
    bad = c.model_copy(deep=True)
    bad.expected.answer["reachable"] = not bad.expected.answer["reachable"]
    rep = _validate(bad, worlds)
    assert not rep.ok and any("differs from oracle" in e for e in rep.errors)


def test_validator_detects_duplicate_id_and_prompt(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    c = _first(dev, Family.QUERY_REACH)
    rep = _validate(c, worlds, [c.model_copy(deep=True)])
    assert any("duplicate case_id" in e for e in rep.errors)
    assert any("duplicate prompt" in e for e in rep.errors)


def test_validator_detects_empty_prompt_and_leak(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    c = _first(dev, Family.QUERY_REACH)
    assert any(
        "empty prompt" in e for e in _validate(c.model_copy(update={"prompt": "  "}), worlds).errors
    )
    leaky = c.model_copy(update={"prompt": "please call check_reachability for (1, 1)"})
    assert any("leaks" in e for e in _validate(leaky, worlds).errors)
    leaky2 = c.model_copy(update={"prompt": "expect COLLISION_X here"})
    assert any("leaks" in e for e in _validate(leaky2, worlds).errors)


def test_validator_detects_unknown_world(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    c = _first(dev, Family.QUERY_REACH).model_copy(update={"world_id": "nope"})
    assert any("unknown world_id" in e for e in _validate(c, worlds).errors)


def test_validator_detects_wrong_split(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    rep = validate_cases(dev[:3], worlds, expected_split=Split.HELDOUT_TEST)
    assert not rep.ok


def test_validator_detects_override_on_safe_target(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    safe_move = next(
        c
        for c in dev
        if c.intent.family is Family.MOVE and c.expected.outcome is ExpectedOutcome.SUCCESS
    )
    bad = safe_move.model_copy(deep=True)
    bad.intent.params["override"] = True
    rep = _validate(bad, worlds)
    assert not rep.ok


def test_validator_detects_bad_plan_certificate(
    dev: list[BenchmarkCase], worlds: dict[str, WorldSpec]
) -> None:
    c = _first(dev, Family.PLAN_PATH, ExpectedOutcome.SUCCESS)
    bad = c.model_copy(deep=True)
    bad.intent.params["cert"] = {"type": "wall"}
    assert not _validate(bad, worlds).ok


def test_load_cases_rejects_unknown_fields(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    row = json.loads((D / "benchmark_v0.jsonl").read_text().splitlines()[0])
    row["surprise"] = 1
    p.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="invalid case"):
        load_cases(p)


def test_audit_report_has_no_machine_specific_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)  # the CLI is used with repo-relative paths
    a = audit_datasets(["datasets/benchmark_v0.jsonl"])
    assert a["worlds_file"] == "datasets/worlds.json"
    assert "/home/" not in json.dumps(a) and "/root/" not in json.dumps(a)
