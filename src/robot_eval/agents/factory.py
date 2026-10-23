"""Build agents by name from ``configs/agents.yaml`` (the evaluator never branches on class)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from robot_eval.agents.base import Agent
from robot_eval.agents.mock import MODES, MockAgent
from robot_eval.agents.reference import GuardConfig, ReferenceAgent
from robot_eval.agents.staged import RuleExecutor, RuleTriage, TwoStageAgent


class AgentUnavailable(RuntimeError):
    """An optional agent (e.g. LLM) cannot be built, typically for missing credentials/packages."""


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [Path.cwd(), *here.parents]:
        if (p / "configs").is_dir() and (p / "datasets").is_dir():
            return p
    return Path.cwd()


def default_config_path(name: str = "agents.yaml") -> Path:
    env = os.environ.get("ROBOT_EVAL_CONFIG_DIR")
    return (Path(env) if env else repo_root() / "configs") / name


def load_agent_configs(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    p = Path(path) if path else default_config_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        raise ValueError(f"{p}: 'agents' must be a mapping")
    return agents


def available_agents(path: str | Path | None = None) -> list[str]:
    try:
        names = list(load_agent_configs(path))
    except FileNotFoundError:
        names = []
    return names + [f"mock_{m}" for m in MODES if f"mock_{m}" not in names]


def _guards(cfg: dict[str, Any]) -> GuardConfig:
    g = cfg.get("guards", {}) or {}
    unknown = set(g) - {"validate_args", "verify", "refuse_overrides"}
    if unknown:
        raise ValueError(f"unknown guard option(s): {sorted(unknown)}")
    return GuardConfig(**{k: bool(v) for k, v in g.items()})


def build_agent(name: str, config_path: str | Path | None = None) -> Agent:
    if name.startswith("mock_") and name[5:] in MODES:
        return MockAgent(name[5:], name)
    try:
        cfgs = load_agent_configs(config_path)
    except FileNotFoundError as exc:
        raise ValueError(f"agent config file not found: {exc.filename}") from exc
    if name not in cfgs:
        raise ValueError(f"unknown agent {name!r}; available: {available_agents(config_path)}")
    cfg = cfgs[name]
    kind = cfg.get("type")
    if kind == "reference":
        return ReferenceAgent(
            name, _guards(cfg), int(cfg.get("max_retries", 1)), cfg.get("regress")
        )
    if kind == "two_stage_rule":
        g = _guards(cfg)
        retries = int(cfg.get("max_retries", 1))
        return TwoStageAgent(
            name,
            RuleTriage(),
            RuleExecutor(g, retries),
            kind="two_stage_rule",
            extra={"guards": g.__dict__, "max_retries": retries, "llm": False},
        )
    if kind == "mock":
        return MockAgent(str(cfg["mode"]), name)
    if kind == "llm":
        from robot_eval.agents.llm import build_llm_agent

        return build_llm_agent(name, cfg)
    raise ValueError(f"agent {name!r}: unknown type {kind!r}")
