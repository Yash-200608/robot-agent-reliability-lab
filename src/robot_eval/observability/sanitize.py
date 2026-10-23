"""Redaction of secrets before anything is logged or exported."""

from __future__ import annotations

import math
import re
from typing import Any

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|authorization|password|bearer|credential)", re.IGNORECASE
)
_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?:pk|sk)-lf-[A-Za-z0-9\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+"),
]
REDACTED = "[REDACTED]"


def sanitize_text(s: str, max_len: int = 500) -> str:
    for pat in _VALUE_PATTERNS:
        s = pat.sub(REDACTED, s)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def sanitize(obj: Any) -> Any:
    """Recursively redact secret-looking keys and values."""
    if isinstance(obj, dict):
        return {
            k: (
                REDACTED
                if isinstance(k, str) and SECRET_KEY_RE.search(k) and v not in (None, "", False)
                else sanitize(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str):
        return sanitize_text(obj, max_len=4000)
    return obj


def json_safe(obj: Any) -> Any:
    """Make a structure strict-JSON serialisable: NaN/inf floats become the strings 'NaN',
    'Infinity', '-Infinity' (so records stay valid JSON and compare equal across runs)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return "NaN" if math.isnan(obj) else ("Infinity" if obj > 0 else "-Infinity")
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {sanitize_text(str(exc))}"
