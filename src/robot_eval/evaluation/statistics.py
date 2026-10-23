"""Statistics used in reports. Small, dependency-light (numpy + stdlib) and fully seeded.

Methods and assumptions are documented in docs/experiment_protocol.md. Nothing here decides
"significance" on its own: callers must also check sample sizes (see ``MIN_DISCORDANT``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt

Z95 = 1.959963984540054
MIN_DISCORDANT = 10  # below this many discordant pairs a paired binary test is marked inconclusive
MIN_PAIRS = 30


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion; None when n == 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar test (binomial, p0 = 0.5) on discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return float(min(1.0, 2 * tail))


def paired_bootstrap_diff(
    a: Sequence[float], b: Sequence[float], n_boot: int = 10000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Mean of (b - a) over paired items with a percentile bootstrap CI. Items are resampled with
    replacement as pairs. Returns (point, lo, hi)."""
    if len(a) != len(b) or not a:
        raise ValueError("paired samples must have equal, non-zero length")
    d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(d.mean()), float(lo), float(hi)


def bootstrap_ci(
    values: Sequence[float],
    stat: Callable[[npt.NDArray[np.float64]], float] = np.median,
    n_boot: int = 5000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float] | None:
    if not values:
        return None
    x = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    stats = np.apply_along_axis(stat, 1, x[idx])
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    return float(stat(x)), float(lo), float(hi)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (monotone, capped at 1)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def percentile_summary(
    values: Sequence[float], qs: Sequence[float] = (50, 90, 95, 99)
) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, **{f"p{int(q)}": None for q in qs}, "mean": None, "max": None}
    x = np.asarray(values, dtype=float)
    out: dict[str, float | int | None] = {"n": int(x.size)}
    for q in qs:
        out[f"p{int(q)}"] = float(np.percentile(x, q))
    out["mean"] = float(x.mean())
    out["max"] = float(x.max())
    return out


def paired_bootstrap_median_diff(
    a: Sequence[float], b: Sequence[float], n_boot: int = 10000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Median of paired differences (b - a) with a percentile bootstrap CI (for skewed latency)."""
    if len(a) != len(b) or not a:
        raise ValueError("paired samples must have equal, non-zero length")
    d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    meds = np.median(d[idx], axis=1)
    lo, hi = np.quantile(meds, [alpha / 2, 1 - alpha / 2])
    return float(np.median(d)), float(lo), float(hi)
