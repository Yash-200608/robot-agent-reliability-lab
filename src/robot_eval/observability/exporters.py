"""Optional remote trace export (opt-in). The local run never depends on it."""

from __future__ import annotations

from typing import Any, Protocol


class Exporter(Protocol):
    name: str

    def status(self) -> str: ...

    def export_case(self, record: dict[str, Any]) -> str: ...

    def flush(self) -> None: ...


class NullExporter:
    """Default: nothing leaves the machine."""

    name = "none"

    def status(self) -> str:
        return "disabled"

    def export_case(self, record: dict[str, Any]) -> str:
        return "disabled"

    def flush(self) -> None:
        return None
