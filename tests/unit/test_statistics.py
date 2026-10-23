from __future__ import annotations

import math

import pytest

from robot_eval.evaluation.statistics import (
    bootstrap_ci,
    holm,
    mcnemar_exact,
    paired_bootstrap_diff,
    percentile_summary,
    wilson_interval,
)


def test_wilson_known_values() -> None:
    lo, hi = wilson_interval(0, 10)  # type: ignore[misc]
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson_interval(8, 10)  # type: ignore[misc]
    assert (lo, hi) == (pytest.approx(0.4902, abs=1e-3), pytest.approx(0.9433, abs=1e-3))
    lo, hi = wilson_interval(10, 10)  # type: ignore[misc]
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)


def test_wilson_empty_is_none() -> None:
    assert wilson_interval(0, 0) is None


def test_mcnemar_exact_known() -> None:
    assert mcnemar_exact(1, 7) == pytest.approx(0.0703125)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)


def test_holm_adjustment() -> None:
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)  # monotone: not smaller than previous


def test_paired_bootstrap_is_seeded_and_covers_truth() -> None:
    a = [0] * 20 + [1] * 20
    b = [1] * 20 + [1] * 20
    r1 = paired_bootstrap_diff(a, b, n_boot=2000, seed=3)
    r2 = paired_bootstrap_diff(a, b, n_boot=2000, seed=3)
    assert r1 == r2
    point, lo, hi = r1
    assert point == pytest.approx(0.5) and lo < 0.5 < hi


def test_paired_bootstrap_validates_lengths() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap_diff([1], [1, 2])


def test_bootstrap_median_ci() -> None:
    r = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 100.0], n_boot=1000, seed=1)
    assert r is not None and r[0] == 3.0 and r[1] <= 3.0 <= r[2]
    assert bootstrap_ci([]) is None


def test_percentiles() -> None:
    s = percentile_summary([1, 2, 3, 4, 5])
    assert s["n"] == 5 and s["p50"] == 3.0 and s["max"] == 5.0 and not math.isnan(s["mean"])  # type: ignore[arg-type]
    assert percentile_summary([])["p50"] is None
