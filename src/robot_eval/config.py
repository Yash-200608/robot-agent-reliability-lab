"""Environment/.env handling. Secrets come only from the process environment or a local, git-ignored
``.env`` file; they are never written to logs, reports, datasets or snapshots."""

from __future__ import annotations

import os
from pathlib import Path

TRUTHY = {"1", "true", "yes", "on"}


def load_dotenv(path: str | Path | None = None) -> list[str]:
    """Load KEY=VALUE lines from ``.env`` into ``os.environ`` without overriding existing values.
    Returns the names (never values) of the variables that were set."""
    from robot_eval.agents.factory import repo_root

    p = Path(path) if path else repo_root() / ".env"
    if not p.is_file():
        return []
    set_names: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip().removeprefix("export ").strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        if key and val and key not in os.environ:
            os.environ[key] = val
            set_names.append(key)
    return set_names


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUTHY
