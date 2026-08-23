"""Statistical conventions. Implemented once, reused everywhere.

Wilson score intervals for single rates, exact McNemar for paired same-corpus
comparisons. Both are chosen because they behave correctly at the small
denominators this project actually has - a normal-approximation interval on 12
observations is not merely imprecise, it can extend below zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Rate", "mcnemar_exact", "smallest_k_satisfying", "wilson_interval"]


@dataclass(frozen=True, slots=True)
class Rate:
    """A proportion with its denominator and interval. Never a bare percentage."""

    successes: int
    total: int
    lower: float
    upper: float

    @property
    def value(self) -> float:
        return self.successes / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.value:.4f} [{self.lower:.4f}, {self.upper:.4f}] n={self.total}"


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> Rate:
    """Wilson score interval.

    Preferred over the normal approximation because it stays inside [0, 1] and
    remains sensible at the denominators in the tens that this evaluation has.
    """
    if total <= 0:
        return Rate(successes, 0, 0.0, 0.0)
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    z = _z_for(confidence)
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = proportion + z**2 / (2 * total)
    spread = z * math.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2))
    return Rate(
        successes=successes,
        total=total,
        lower=max(0.0, (centre - spread) / denominator),
        upper=min(1.0, (centre + spread) / denominator),
    )


def _z_for(confidence: float) -> float:
    """Inverse normal CDF at (1 + confidence) / 2, via the standard rational
    approximation. Avoids a scipy dependency for one number."""
    p = (1 + confidence) / 2
    a = [
        -39.69683028665376,
        220.9460984245205,
        -275.9285104469687,
        138.3577518672690,
        -30.66479806614716,
        2.506628277459239,
    ]
    b = [
        -54.47609879822406,
        161.5858368580409,
        -155.6989798598866,
        66.80131188771972,
        -13.28068155288572,
    ]
    c = [
        -0.007784894002430293,
        -0.3223964580411365,
        -2.400758277161838,
        -2.549732539343734,
        4.374664141464968,
        2.938163982698783,
    ]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416]
    low, high = 0.02425, 1 - 0.02425

    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Exact McNemar two-sided p-value for paired same-corpus comparisons.

    Only the discordant pairs carry information: cases both configurations got
    right, or both got wrong, say nothing about which is better.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    smaller = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(smaller + 1)) / 2**n
    return min(1.0, 2 * tail)


def smallest_k_satisfying(candidates: list[float], predicate: object) -> float | None:
    """Smallest candidate satisfying ``predicate``.

    Iterates **upward** and returns the first hit. Computing this by scanning
    downward returns the endpoint rather than the first qualifying value - a bug
    that has occurred three times in the sibling project. A unit test asserts the
    direction.
    """
    test = predicate
    for candidate in sorted(candidates):
        if test(candidate):  # type: ignore[operator]
            return candidate
    return None
