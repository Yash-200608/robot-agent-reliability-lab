"""Local-first JSONL event log. Always on; independent of any remote tracing."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from robot_eval.observability.sanitize import json_safe, sanitize


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self._fh = path.open("a", encoding="utf-8", newline="\n")

    def emit(self, event: str, **payload: Any) -> None:
        rec = {
            "ts": utc_now(),
            "run_id": self.run_id,
            "event": event,
            **json_safe(sanitize(payload)),
        }
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str, allow_nan=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> EventLog:
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
