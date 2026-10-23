from __future__ import annotations

from pathlib import Path

import pytest

from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import WorldSpec, load_worlds

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"


@pytest.fixture(autouse=True)
def _isolate_heldout_log(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests must never write to the committed held-out disclosure log."""
    monkeypatch.setenv(
        "ROBOT_EVAL_HELDOUT_LOG", str(tmp_path_factory.mktemp("heldout_log") / "log.jsonl")
    )


@pytest.fixture(scope="session")
def worlds() -> dict[str, WorldSpec]:
    return load_worlds(DATASETS / "worlds.json")


@pytest.fixture()
def sim_a(worlds: dict[str, WorldSpec]) -> Simulator:
    return Simulator(worlds["cell_a"])


@pytest.fixture()
def sim_open(worlds: dict[str, WorldSpec]) -> Simulator:
    return Simulator(worlds["cell_open"])
