"""Small statistics helpers: Wilson intervals, bootstrap intervals, percentiles."""

import math
from collections.abc import Sequence

import numpy as np

Z_95 = 1.959964


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval of a proportion. With no observations it is (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= successes <= n:
        raise ValueError(f"successes={successes} outside 0..{n}")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)  # exact at the edges
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return lo, hi


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval of the mean. Needs at least one value."""
    if len(values) == 0:
        raise ValueError("bootstrap of an empty sample")
    data = np.asarray(values, dtype=float)
    if len(data) == 1:
        return float(data[0]), float(data[0])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(data), size=(n_boot, len(data)))
    means = data[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def percentile(values: Sequence[float], q: float) -> float | None:
    """The q-th percentile (0-100) with linear interpolation; None for an empty sample."""
    if len(values) == 0:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), q))


def mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if len(values) else None
