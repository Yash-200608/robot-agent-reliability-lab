"""Every agent honours the same contract and runs through the same evaluator code path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_eval.agents.base import Agent
from robot_eval.agents.factory import available_agents, build_agent
from robot_eval.agents.mock import MODES
from robot_eval.domain.errors import AgentStatus
from robot_eval.evaluation.runner import RunOptions, run_benchmark

ROOT = Path(__file__).resolve().parents[2]
OFFLINE = [
    "reference",
    "reference_guarded",
    "reference_validate_only",
    "reference_verify_only",
    "reference_refuse_only",
    "reference_regressed",
    "two_stage_rule",
] + [f"mock_{m}" for m in MODES if m != "tool_spam"]


@pytest.mark.parametrize("name", OFFLINE)
def test_agent_runs_through_common_pipeline(name: str, tmp_path: Path) -> None:
    ag = build_agent(name, ROOT / "configs" / "agents.yaml")
    assert isinstance(ag, Agent)
    assert ag.name == name and isinstance(ag.version, str)
    json.dumps(ag.describe())
    res = run_benchmark(
        RunOptions(
            dataset=ROOT / "datasets" / "benchmark_v0.jsonl",
            agent=name,
            agent_config=ROOT / "configs" / "agents.yaml",
            out_root=tmp_path,
            limit=6,
        ),
        ag,
    )
    assert len(res.records) == 6
    for r in res.records:
        assert r["status"] in {s.value for s in AgentStatus}
        assert "scoring" in r and "calls" in r


def test_listing_includes_all_configured_and_mock_agents() -> None:
    names = available_agents(ROOT / "configs" / "agents.yaml")
    for n in (
        "reference",
        "reference_guarded",
        "two_stage_rule",
        "llm_single",
        "llm_two_stage",
        "mock_crash",
    ):
        assert n in names


def test_unknown_agent_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        build_agent("nope", ROOT / "configs" / "agents.yaml")


def test_fixture_flag_is_set_for_mocks_only() -> None:
    assert build_agent("mock_refuse_all").is_fixture
    assert not build_agent("reference", ROOT / "configs" / "agents.yaml").is_fixture
