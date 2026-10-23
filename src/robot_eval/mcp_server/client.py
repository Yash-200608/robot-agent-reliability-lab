"""Synchronous ToolClient that talks to the simulator *through MCP* (in-process transport).

Used to prove that tool results are identical over MCP and to run whole benchmarks with
``robot-eval run --transport mcp``. A background event loop keeps one MCP session open.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any

from mcp import Client

from robot_eval.domain.errors import ToolErrorCode
from robot_eval.domain.models import ToolResult
from robot_eval.mcp_server.server import build_server
from robot_eval.simulator.sim import Simulator


class McpToolClient:
    """Exposes ``.sim`` (the served simulator) so the recording wrapper can read the pose.

    The MCP session is entered and exited inside ONE long-lived task on a private event loop (anyio
    cancel scopes must be exited by the task that entered them); calls are submitted from the
    caller's thread with ``run_coroutine_threadsafe``.
    """

    def __init__(self, sim: Simulator) -> None:
        self.sim = sim
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._client: Client | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._session_future = asyncio.run_coroutine_threadsafe(self._session(), self._loop)
        if not self._ready.wait(30) or self._error is not None:
            raise RuntimeError(f"could not open MCP session: {self._error!r}")

    async def _session(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with Client(build_server(self.sim)) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the constructor / caller
            self._error = exc
            self._ready.set()
            raise

    def _run(self, coro: Any, timeout: float) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        assert self._client is not None
        res = await self._client.call_tool(tool, arguments)
        if res.structured_content is not None:
            return ToolResult.model_validate(res.structured_content)
        text = "".join(getattr(c, "text", "") for c in res.content)
        return ToolResult(
            ok=False, tool=tool, error_code=ToolErrorCode.TOOL_INTERNAL_ERROR, message=text[:300]
        )

    def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        out: ToolResult = self._run(self._call(tool, arguments), 30)
        return out

    def list_tools(self) -> list[dict[str, Any]]:
        async def go() -> list[dict[str, Any]]:
            assert self._client is not None
            r = await self._client.list_tools()
            return [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in r.tools
            ]

        out: list[dict[str, Any]] = self._run(go(), 30)
        return out

    def set_stage(self, stage: str | None) -> None:
        return None

    def close(self) -> None:
        if self._stop is not None and not self._session_future.done():
            self._loop.call_soon_threadsafe(self._stop.set)
            with contextlib.suppress(Exception):  # shutdown errors must not mask results
                self._session_future.result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
