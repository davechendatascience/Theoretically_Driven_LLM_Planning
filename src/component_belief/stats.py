"""Beta-Binomial posterior arithmetic.

Implemented directly rather than pulled from SciPy: the server needs exactly
one special function, and a heavy numerical dependency on an MCP server that
must start fast for every session is a poor trade.

`betainc` is the standard continued-fraction evaluation of the regularised
incomplete beta function; the quantile is a bisection over it, which is slower
than a Newton step and immune to the convergence failures that make Newton
awkward near the boundaries.
"""

from __future__ import annotations

import math

_MAX_ITER = 200
_EPS = 3.0e-12


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) — the Beta CDF."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(a: float, b: float, q: float) -> float:
    """Inverse Beta CDF by bisection."""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2.0


def beta_mean(a: float, b: float) -> float:
    return a / (a + b)


def credible_interval(a: float, b: float, mass: float = 0.94) -> tuple[float, float]:
    """Equal-tailed credible interval carrying `mass` of the posterior."""
    tail = (1.0 - mass) / 2.0
    return beta_ppf(a, b, tail), beta_ppf(a, b, 1.0 - tail)
