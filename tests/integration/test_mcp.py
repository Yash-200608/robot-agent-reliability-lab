"""Gate 5: MCP discovery, valid calls, structured validation/safety errors, equivalence, lifecycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")
pytestmark = pytest.mark.mcp

import anyio  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

from robot_eval.evaluation.runner import RunOptions, canonical_record, run_benchmark  # noqa: E402
from robot_eval.mcp_server.server import build_server  # noqa: E402
from robot_eval.simulator.sim import Simulator  # noqa: E402
from robot_eval.simulator.world import FaultSpec, load_worlds  # noqa: E402
from robot_eval.tools.registry import TOOL_REGISTRY, tool_descriptors  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORLDS = load_worlds(ROOT / "datasets" / "worlds.json")


async def with_client(fn: Any, faults: list[FaultSpec] | None = None) -> Any:
    sim = Simulator(WORLDS["cell_a"], faults or [])
    async with Client(build_server(sim)) as client:
        return await fn(client, sim)


def run(fn: Any, faults: list[FaultSpec] | None = None) -> Any:
    return anyio.run(with_client, fn, faults)


def test_discovery_lists_every_tool_with_schema() -> None:
    async def go(c: Client, sim: Simulator) -> Any:
        return await c.list_tools()

    res = run(go)
    tools = {t.name: t for t in res.tools}
    assert set(tools) == set(TOOL_REGISTRY) and len(tools) == 11
    expected = {d["name"]: d for d in tool_descriptors()}
    for name, t in tools.items():
        assert t.description and t.input_schema["type"] == "object"
        assert (
            t.input_schema == expected[name]["input_schema"]
        )  # exactly the strict pydantic schema
        assert t.annotations is not None and t.annotations.open_world_hint is False
        assert t.annotations.read_only_hint is (name != "move_end_effector")
    assert tools["check_reachability"].input_schema["required"] == ["x", "y"]
    assert tools["check_reachability"].input_schema["additionalProperties"] is False


def test_valid_call_returns_structured_success() -> None:
    async def go(c: Client, sim: Simulator) -> Any:
        return await c.call_tool("check_reachability", {"x": 1.5, "y": 2.0})

    r = run(go)
    assert not r.is_error
    sc = r.structured_content
    assert sc["ok"] is True and sc["data"]["reachable"] is True and sc["error_code"] is None
    assert sc["operation_id"] == "op-0001"


@pytest.mark.parametrize(
    "args",
    [{"x": "abc", "y": 1.0}, {"x": 1.0}, {"x": 1.0, "y": 1.0, "z": 2.0}, {"x": 1e9, "y": 0.0}],
)
def test_invalid_arguments_give_structured_error(args: dict[str, Any]) -> None:
    async def go(c: Client, sim: Simulator) -> Any:
        before = sim.full_fingerprint()
        r = await c.call_tool("check_collision", args)
        return r, before == sim.full_fingerprint()

    r, unchanged = run(go)
    assert r.is_error
    assert (
        r.structured_content["error_code"] == "INVALID_ARGUMENT"
        and r.structured_content["data"]["errors"]
    )
    assert unchanged  # no state mutation on failed validation


def test_nan_is_rejected_over_the_wire() -> None:
    async def go(c: Client, sim: Simulator) -> Any:
        return await c.call_tool("check_collision", {"x": float("nan"), "y": 0.0})

    try:
        r = run(go)
    except Exception:  # noqa: BLE001 - a strict JSON encoder may refuse NaN before sending; also a rejection
        return
    assert r.is_error and r.structured_content["error_code"] == "INVALID_ARGUMENT"


def test_safety_rejection_is_enforced_server_side() -> None:
    async def go(c: Client, sim: Simulator) -> Any:
        bad = await c.call_tool("move_end_effector", {"x": 1.2, "y": 0.9})  # centre of obstacle o1
        state = await c.call_tool("get_workcell_state", {})
        good = await c.call_tool("move_end_effector", {"x": 1.0, "y": 0.0})
        state2 = await c.call_tool("get_workcell_state", {})
        return bad, state, good, state2

    bad, state, good, state2 = run(go)
    assert bad.is_error and bad.structured_content["error_code"] == "COLLISION"
    assert state.structured_content["data"]["end_effector"] == {"x": 1.0, "y": -0.5}
    assert not good.is_error and state2.structured_content["data"]["end_effector"] == {
        "x": 1.0,
        "y": 0.0,
    }


def test_unknown_tool_and_injected_fault_are_structured() -> None:
    faults = [FaultSpec(tool="check_collision", kind="timeout", fail_first_n=1)]

    async def go(c: Client, sim: Simulator) -> Any:
        unk = await c.call_tool("launch_missiles", {})
        f1 = await c.call_tool("check_collision", {"x": 0.0, "y": 0.5})
        f2 = await c.call_tool("check_collision", {"x": 0.0, "y": 0.5})
        return unk, f1, f2

    unk, f1, f2 = run(go, faults)
    assert unk.is_error and unk.structured_content["error_code"] == "UNKNOWN_TOOL"
    assert f1.is_error and f1.structured_content["error_code"] == "TOOL_TIMEOUT"
    assert not f2.is_error


def test_benchmark_results_identical_over_mcp_and_direct(tmp_path: Path) -> None:
    ds = ROOT / "datasets" / "benchmark_v0.jsonl"
    cfg = ROOT / "configs" / "agents.yaml"
    direct = run_benchmark(
        RunOptions(
            dataset=ds, agent="reference_guarded", agent_config=cfg, out_root=tmp_path, limit=12
        )
    )
    via_mcp = run_benchmark(
        RunOptions(
            dataset=ds,
            agent="reference_guarded",
            agent_config=cfg,
            out_root=tmp_path,
            limit=12,
            transport="mcp",
        )
    )
    assert via_mcp.metadata["transport"] == "mcp"
    assert [canonical_record(r) for r in direct.records] == [
        canonical_record(r) for r in via_mcp.records
    ]


def test_stdio_subprocess_lifecycle() -> None:
    """Spawn `robot-eval mcp-serve` as a real stdio subprocess, talk MCP to it, shut it down."""

    async def go() -> Any:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "robot_eval.cli", "mcp-serve", "--world", "cell_open"],
            cwd=str(ROOT),
        )
        async with Client(params) as c:
            tools = await c.list_tools()
            st = await c.call_tool("get_workcell_state", {})
            return len(tools.tools), st.structured_content["data"]["world_id"]

    n, world = anyio.run(go)
    assert n == 11 and world == "cell_open"


def test_core_works_without_mcp_installed() -> None:
    code = (
        "import sys\n"
        "sys.modules['mcp'] = None\n"  # makes `import mcp` raise ImportError
        "from robot_eval.cli import main\n"
        "from robot_eval.evaluation.runner import RunOptions, run_benchmark\n"
        "import tempfile, pathlib\n"
        "r = run_benchmark(RunOptions(dataset=pathlib.Path('datasets/benchmark_v0.jsonl'), agent='reference',"
        " out_root=pathlib.Path(tempfile.mkdtemp()), limit=3))\n"
        "assert len(r.records) == 3\n"
        "rc = main(['mcp-serve'])\n"
        "assert rc == 3, rc\n"
        "assert 'robot_eval.mcp_server.server' not in sys.modules\n"
        "print('core-ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert "core-ok" in out.stdout and "unavailable" in out.stderr
