"""MCP server for the simulated robotics tools (simulation only; no hardware, no network I/O).

Built on the low-level ``mcp.server.lowlevel.Server`` of the official Python SDK (mcp 2.x) so that
the *published* JSON input schemas are exactly the strict pydantic schemas used by the simulator,
and argument validation happens once, in the simulator, not twice with different coercion rules.

Domain logic lives in ``robot_eval.simulator`` / ``robot_eval.tools``; this module is plumbing:
  tools/list -> ``tool_descriptors()``;  tools/call -> ``Simulator.call`` -> structured result.

Result convention: ``structuredContent`` is the ``ToolResult`` JSON (ok, tool, error_code, message,
data, operation_id); ``isError`` is true when ``ok`` is false (invalid arguments, safety rejection,
injected fault). Errors are therefore machine-readable, not only free text.

Local development: ``robot-eval mcp-serve --world cell_a`` speaks MCP over stdio. See
docs/architecture.md for lifecycle and a client example.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from robot_eval import __version__
from robot_eval.agents.factory import repo_root
from robot_eval.simulator.sim import Simulator
from robot_eval.simulator.world import load_worlds
from robot_eval.tools.registry import tool_descriptors

SERVER_NAME = "robot-eval-simulator"
INSTRUCTIONS = (
    "Simulated 2-D robotics workcell tools. SIMULATION ONLY: nothing here controls real robots, PLCs "
    "or industrial equipment. Units: metres and degrees. move_end_effector is the only "
    "state-changing tool; the simulator rejects unsafe moves regardless of the caller's claims."
)


def build_server(sim: Simulator, name: str = SERVER_NAME) -> Server[Any]:
    descriptors = tool_descriptors()

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=d["name"],
                description=d["description"],
                input_schema=d["input_schema"],
                annotations=types.ToolAnnotations(
                    read_only_hint=not d["mutating"],
                    destructive_hint=False,  # simulated state only
                    idempotent_hint=not d["mutating"],
                    open_world_hint=False,
                ),
            )
            for d in descriptors
        ]
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = sim.call(params.name, params.arguments if params.arguments is not None else {})
        payload = result.model_dump(mode="json")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, allow_nan=False))],
            structured_content=payload,
            is_error=not result.ok,
        )

    return Server(
        name,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def _serve_stdio(server: Server[Any]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_stdio(world_id: str = "cell_a", worlds_path: str | Path | None = None) -> None:
    """Serve one simulated workcell over stdio until the client disconnects."""
    wp = Path(worlds_path) if worlds_path else repo_root() / "datasets" / "worlds.json"
    worlds = load_worlds(wp)
    if world_id not in worlds:
        raise SystemExit(f"unknown world {world_id!r}; available: {sorted(worlds)}")
    anyio.run(_serve_stdio, build_server(Simulator(worlds[world_id])))
