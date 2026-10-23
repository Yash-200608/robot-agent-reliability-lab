"""Deterministic visibility-graph path planner (documented, intentionally simple).

Candidate nodes: start, goal, and 8 ring points around each obstacle (radius + margin + 0.02 m)
and around the robot base (reach_min + 0.02 m). Edges are straight segments that pass all
segment-level checks. Dijkstra with index tie-breaking makes the result deterministic. The planner
is *incomplete*: failure to find a path does not prove none exists (see docs/benchmark_design.md).
"""

from __future__ import annotations

import heapq
import math

from robot_eval.simulator.checks import point_violations, segment_violations
from robot_eval.simulator.world import WorldSpec

RING_POINTS = 8
RING_OFFSET = 0.02


def _ring(cx: float, cy: float, radius: float) -> list[tuple[float, float]]:
    pts = []
    for k in range(RING_POINTS):
        ang = 2 * math.pi * k / RING_POINTS
        pts.append((round(cx + radius * math.cos(ang), 6), round(cy + radius * math.sin(ang), 6)))
    return pts


def plan(
    world: WorldSpec, start: tuple[float, float], goal: tuple[float, float]
) -> list[tuple[float, float]] | None:
    nodes: list[tuple[float, float]] = [start, goal]
    for o in world.obstacles:
        nodes.extend(_ring(o.x, o.y, o.radius + world.clearance_margin + RING_OFFSET))
    if world.reach_min > 0:
        nodes.extend(_ring(world.base.x, world.base.y, world.reach_min + RING_OFFSET))
    usable = [i for i, n in enumerate(nodes) if i < 2 or not point_violations(world, n[0], n[1])]

    def edge_ok(a: int, b: int) -> bool:
        return not segment_violations(world, nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1])

    best: dict[int, float] = {0: 0.0}
    prev: dict[int, int] = {}
    heap: list[tuple[float, int]] = [(0.0, 0)]
    done: set[int] = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == 1:
            break
        for v in usable:
            if v == u or v in done or not edge_ok(u, v):
                continue
            nd = d + math.hypot(nodes[u][0] - nodes[v][0], nodes[u][1] - nodes[v][1])
            if nd < best.get(v, math.inf) - 1e-12:
                best[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    if 1 not in done:
        return None
    path = [1]
    while path[-1] != 0:
        path.append(prev[path[-1]])
    return [nodes[i] for i in reversed(path)]
