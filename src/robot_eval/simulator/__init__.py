"""Deterministic 2-D workcell simulator.

``Simulator`` lives in :mod:`robot_eval.simulator.sim` and is re-exported lazily to avoid an
import cycle with :mod:`robot_eval.tools.registry`.
"""

from __future__ import annotations

from typing import Any

from robot_eval.simulator.world import FaultSpec, Obstacle, WorldSpec, load_worlds

__all__ = ["FaultSpec", "Obstacle", "Simulator", "WorldSpec", "load_worlds"]


def __getattr__(name: str) -> Any:
    if name == "Simulator":
        from robot_eval.simulator.sim import Simulator

        return Simulator
    raise AttributeError(name)
