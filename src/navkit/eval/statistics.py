"""Exact chi-square distribution functions for integer degrees of freedom.

Navigation metrics need the chi-square distribution in two places: to know what
coverage a claimed ellipsoid *should* have, and to invert that relation when
calibrating. Both are needed only at integer degrees of freedom (one per scalar
axis, three for a position vector, four for a pose), and at integer degrees of
freedom the distribution has a closed form.

For a chi-square variate with ``n`` degrees of freedom, ``X / 2`` follows a
gamma variate of shape ``n / 2``, and the regularised lower incomplete gamma
function ``P(a, t)`` satisfies the half-step recurrence

    P(a + 1, t) = P(a, t) - t**a * exp(-t) / Gamma(a + 1)

So every integer ``n`` is reached from one of two exact seeds,

    P(1/2, t) = erf(sqrt(t))            P(1, t) = 1 - exp(-t)

by applying the recurrence. That makes the coverage reference exact rather than
tabulated, with no SciPy dependency and no interpolation error near the tails
where the numbers actually matter.

The quantile function is obtained by bisection on the CDF. It is slower than a
specialised implementation and completely unambiguous, which is the right
trade for a function called a few thousand times per report.
"""

from __future__ import annotations

import math

__all__ = [
    "chi2_cdf",
    "chi2_ppf",
    "ellipsoid_coverage",
    "ellipsoid_sigma",
]


def _lower_gamma_p(a: float, t: float) -> float:
    """Regularised lower incomplete gamma ``P(a, t)`` for ``a, t > 0``.

    Two regimes, chosen by where the series is better conditioned:

    * ``t < a + 1`` -- the Maclaurin series for ``P``, which converges quickly
      and never suffers cancellation.
    * otherwise -- Lentz's continued fraction for ``Q``, with ``P = 1 - Q``.

    The power is kept in log space throughout (``exp(-t + a log t - lgamma(a))``)
    rather than formed as ``t**a``. The naive form overflows for the large
    degrees of freedom a NEES test uses: scoring a 3000-epoch run asks for
    ``chi2_ppf(0.975, 9000)``, where ``t**a`` is ``4500**4500`` and raises
    ``OverflowError`` before the series can sum. A NEES test over a long
    sequence is the ordinary case here, not an edge case, so the large-dof path
    has to work.
    """
    if t <= 0.0:
        return 0.0
    log_prefactor = -t + a * math.log(t) - math.lgamma(a)

    if t < a + 1.0:
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(2000):
            ap += 1.0
            term *= t / ap
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return min(max(total * math.exp(log_prefactor), 0.0), 1.0)

    tiny = 1e-300
    b = t + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b if b != 0.0 else 1.0 / tiny
    h = d
    for i in range(1, 2000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return min(max(1.0 - math.exp(log_prefactor) * h, 0.0), 1.0)


def chi2_cdf(x: float, dof: int) -> float:
    """``P(X <= x)`` for a chi-square variate with ``dof`` degrees of freedom."""
    if dof < 1:
        raise ValueError(f"degrees of freedom must be positive, got {dof}")
    if x <= 0.0:
        return 0.0
    return _lower_gamma_p(dof / 2.0, x / 2.0)


def chi2_ppf(q: float, dof: int) -> float:
    """Inverse of :func:`chi2_cdf` by bisection.

    ``q`` is a probability in ``[0, 1]``. Bisection is used rather than a
    Newton iteration because the CDF is monotone and cheap to evaluate here, so
    there is no convergence or bracketing failure mode to guard against.
    """
    if not 0.0 < q < 1.0:
        raise ValueError(f"q must lie strictly inside (0, 1), got {q}")
    if dof < 1:
        raise ValueError(f"degrees of freedom must be positive, got {dof}")
    lo, hi = 0.0, max(4.0 * dof, 1.0)
    while chi2_cdf(hi, dof) < q:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if chi2_cdf(mid, dof) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def ellipsoid_coverage(sigma_per_axis: float, dof: int) -> float:
    """Coverage of an isotropic ``k``-sigma-per-axis ellipsoid in ``dof`` dims.

    This is where the usual shorthand breaks down. The familiar "3-sigma means
    99.7%" is a statement about a *one-dimensional* Gaussian. Applied per axis
    to a three-dimensional position ellipsoid, the same 3-sigma threshold gives
    a squared Mahalanobis radius of ``3 * 3**2 = 27``, and a coverage of
    ``P(chi2_3 <= 27)`` -- a little over 0.999, not 0.997. Worse, the habit
    usually applied is "2 sigma means 95% per axis", which for three axes means
    ``P(chi2_3 <= 12) = 0.9841`` of samples fall inside, while a reader who
    expects 95% is being told something twice as strict as they think.

    Quoting the coverage instead of the per-axis sigma removes the ambiguity.
    """
    if sigma_per_axis <= 0.0:
        return 0.0
    return float(chi2_cdf(sigma_per_axis**2 * dof, dof))


def ellipsoid_sigma(coverage: float, dof: int) -> float:
    """Per-axis sigma whose isotropic ellipsoid achieves ``coverage``.

    The inverse of :func:`ellipsoid_coverage`, and the form in which a
    calibrated bound should be stated.
    """
    return float(math.sqrt(chi2_ppf(coverage, dof) / dof))
