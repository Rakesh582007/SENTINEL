"""Small statistics helpers (no numpy needed)."""
from __future__ import annotations

import math
import statistics


def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> float:
    """Lower end of the Wilson score interval for k successes out of n.

    Small samples get pulled toward 0, so 2 bad aircraft out of 3 (0.21)
    counts for less than 20 out of 30 (0.49). Returns 0 when n == 0.
    """
    if n <= 0:
        return 0.0
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def median_mad(values: list[float]) -> tuple[float, float]:
    """Median and median absolute deviation (unscaled). Empty input -> (nan, nan)."""
    if not values:
        return math.nan, math.nan
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return med, mad


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile, pct in [0, 100]. Empty input -> nan."""
    if not values:
        return math.nan
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
