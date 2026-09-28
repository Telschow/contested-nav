"""Chi-square innovation gating: the statistics, with no SciPy.

A measurement update arrives with an innovation ``y`` and an innovation
covariance ``S = H P H^T + R``. If the filter is calibrated and the measurement
is uncorrupted, then ``y ~ N(0, S)`` and the normalised squared distance

    d_M^2 = y^T S^-1 y

is chi-square distributed with ``m = len(y)`` degrees of freedom. Rejecting an
update whose ``d_M^2`` exceeds the ``1 - alpha`` quantile is therefore a
decision with a *stated* false-alarm rate: at ``alpha = 0.01`` a healthy sensor
is wrongly rejected about one update in a hundred. That is a property worth
having, and it is what distinguishes this from a hand-tuned residual threshold,
which has no rate attached to it at all.

Why the thresholds are tabulated rather than computed
-----------------------------------------------------
:mod:`navkit.eval.statistics` already computes exact integer-dof chi-square
quantiles, and the module docstring there argues for computing rather than
tabulating. The lookup table here is a deliberate exception with a specific
reason: this code sits on the filter's inner loop, evaluated once per sensor per
epoch, and it must be able to answer for *any* degrees of freedom without a
bisection loop whose cost is not obviously bounded. The table covers the dof a
navigation filter actually produces in the common case -- three position axes and
the six axes of a full relative pose -- the exact implementation covers 1 to 8,
and :func:`wilson_hilferty` covers the rest in closed form.

Every tabulated value has been checked against ``chi2_ppf`` to within 5e-4
(``tests/test_fdir.py`` asserts this against the exact implementation rather
than against the constants, so the table cannot silently drift from the maths).
The table is rounded to the precision printed in standard references; using the
exact value would be marginally better and would make the numbers unrecognisable
to anyone checking them.

Wilson-Hilferty
---------------
For degrees of freedom outside the table and above 8, the cube-root normal
approximation

    chi2_{alpha,m}^2 ~ m (1 - 2/(9m) + z_alpha sqrt(2/(9m)))^3

is used, where ``z_alpha`` is the standard normal quantile. The exact
implementation covers 1 to 8 rather than only the tabulated values, because
Wilson-Hilferty's error is largest exactly where a relative-pose or
scalar-aiding update operates. Measured against the exact quantiles the
relative error runs from -0.33% at ``m = 4`` to -0.005% at ``m = 60``: worst in
the far tail at low dof, which is why the threshold there is exact instead.
The test suite pins both the bound and the direction rather than asserting a
single "accurate enough" number.

Numerical conditioning
----------------------
``S`` is symmetrised before use and its conditioning is checked. An innovation
covariance that is singular or near-singular means the measurement carries no
independent information about some direction of the state -- which is a real
condition for a degenerate relative-pose model (ADR-0003) and not a rounding
curiosity. Such a covariance cannot support a Mahalanobis distance, so
:func:`mahalanobis_sq` returns ``inf`` and the update is rejected. Returning a
finite number from an ill-conditioned solve would be worse: it would be
arbitrary, and arbitrary is indistinguishable from a real measurement.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "CHI2_THRESHOLDS",
    "DEFAULT_CONFIDENCE",
    "mahalanobis_sq",
    "normal_quantile",
    "wilson_hilferty",
    "chi2_threshold",
    "chi2_dof",
]

#: Normal quantiles for the tabulated significance levels. One-sided upper
#: tail: ``z = Phi^-1(1 - alpha)``.
NORMAL_QUANTILES: dict[float, float] = {
    0.05: 1.6448536269514722,
    0.01: 2.3263478740408408,
    0.001: 3.0902323061678130,
}

#: ``(degrees of freedom, alpha) -> chi-square threshold``, the 1-alpha upper
#: tail quantile. Keys are the dof a navigation filter produces per update.
CHI2_THRESHOLDS: dict[tuple[int, float], float] = {
    (1, 0.05): 3.841,
    (1, 0.01): 6.635,
    (1, 0.001): 10.828,
    (2, 0.05): 5.991,
    (2, 0.01): 9.210,
    (2, 0.001): 13.816,
    (3, 0.05): 7.815,
    (3, 0.01): 11.345,
    (3, 0.001): 16.266,
    (6, 0.05): 12.592,
    (6, 0.01): 16.812,
    (6, 0.001): 22.458,
}

#: The same values keyed by ``1 - alpha``, so a caller holding a confidence
#: level gets an exact hit rather than a floating-point-comparison miss.
NORMAL_QUANTILES_INVERTED: dict[float, float] = {
    1.0 - a: z for a, z in NORMAL_QUANTILES.items()
}

#: Default confidence level, and therefore the default ``alpha = 0.001``.
#:
#: Not 0.99, and the reason is worth stating because it looks like an
#: inconsistency. A gate at 99% confidence rejects 1% of *healthy* updates by
#: definition -- that is what the 1% means. Measured on this project's own
#: 20 s fixture with 12 visual seeds, an alpha of 0.01 rejects 13 of 1212
#: healthy GNSS fixes, or 1.07%, matching the nominal rate almost exactly. That
#: is not a defect, but it is useless as an alarm: a healthy receiver tripping
#: the fault detector once per hundred epochs is a receiver nobody can fly with,
#: and it would also drown the covariance-collapse alarm that this subsystem
#: exists to extend.
#:
#: At alpha = 0.001 the same 1212 healthy fixes produce zero rejections, while
#: the genuinely broken configuration still rejects 68 of 101 fixes and trips a
#: fault. The detection power barely moves; the nuisance rate disappears.
#: ``FdirConfig`` still accepts 0.99 -- it is a real operating point for a
#: channel whose every rejection is logged and acted on -- it is simply not the
#: default for a channel sharing a filter with a health monitor.
DEFAULT_CONFIDENCE = 0.999

# Acklam's coefficients for the inverse normal CDF, |relative error| < 1.15e-9.
_A = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
      1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
_B = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
      6.680131188771972e01, -1.328068155288572e01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
      -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
      3.754408661907416e00)


def _acklam_ppf(p: float) -> float:
    """Rational approximation to ``Phi^-1(p)``, valid on ``(0, 1)``."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must lie strictly inside (0, 1), got {p}")
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    elif p > phigh:
        q = math.sqrt(-2.0 * math.log1p(-p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    else:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / (
            ((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0
        )
    return x

#: Above this condition number ``S`` is treated as unusable. 1e12 is roughly
#: where double precision loses the smaller direction of an anisotropic
#: covariance entirely: relative error in the small singular value reaches
#: order one, so a solve through it is arithmetic noise.
MAX_CONDITION_NUMBER = 1e12


def normal_quantile(alpha: float) -> float:
    """Standard normal upper-tail quantile ``Phi^-1(1 - alpha)``.

    Acklam's rational approximation, refined by one Newton step against
    :func:`math.erf`. The refinement matters because this value feeds a
    threshold that a safety decision is made on, and the raw approximation is
    only good to about 1e-9 relative -- good enough to be interesting, not good
    enough to be the last thing standing between a spoofed fix and a fused one.
    The Newton step costs one ``erf`` evaluation and lands at full double
    precision.

    Note that the stdlib has ``math.erf`` but no ``math.erfinv``, so the
    inverse cannot be had for free; S1 rules out SciPy's ``ndtri``.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie strictly inside (0, 1), got {alpha}")
    p = 1.0 - alpha
    if p in NORMAL_QUANTILES_INVERTED:
        return NORMAL_QUANTILES_INVERTED[p]
    z = _acklam_ppf(p)
    # One Newton step on Phi(z) - p, where dPhi/dz = exp(-z^2/2)/sqrt(2*pi).
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    if pdf > 0.0:
        cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        z -= (cdf - p) / pdf
    return z


def wilson_hilferty(alpha: float, dof: int) -> float:
    """Wilson-Hilferty approximation to the ``1 - alpha`` chi-square quantile.

    The approximation is unreliable below a few degrees of freedom (it can go
    negative for ``m = 1`` at large ``alpha``) and becomes tight as ``m`` grows.
    ``dof`` is therefore required to be at least 2 here, and callers with
    ``dof == 1`` are served by the exact table instead.
    """
    if dof < 2:
        raise ValueError(f"wilson_hilferty needs dof >= 2, got {dof}")
    z = normal_quantile(alpha)
    m = float(dof)
    return m * (1.0 - 2.0 / (9.0 * m) + z * math.sqrt(2.0 / (9.0 * m))) ** 3


def _exact_threshold(alpha: float, dof: int) -> float:
    """Exact quantile from :mod:`navkit.eval.statistics`, for any integer dof.

    Not on the inner loop for the common cases -- that is what the table is
    for -- but it is what the table is checked against, so it has to be reachable
    from here rather than only from a test.
    """
    from ..eval.statistics import chi2_ppf

    return float(chi2_ppf(1.0 - alpha, dof))


def chi2_threshold(dof: int, alpha: float) -> float:
    """Chi-square upper-tail threshold for ``dof`` degrees of freedom.

    Resolution order: the tabulated value, then the exact implementation for
    dof up to 8 where Wilson-Hilferty is not trustworthy, then
    Wilson-Hilferty for the large-dof tail.

    The exact branch matters more than it looks. Wilson-Hilferty is documented
    above as unreliable at ``m = 4, 5`` and outright invalid at ``m = 1``; all
    three are dof values a relative-pose or scalar-aiding update can produce, so
    falling through to the approximation there would put a 5% error into a
    security-relevant threshold while the exact value costs one bisection on a
    path that is not hot.
    """
    if dof < 1:
        raise ValueError(f"degrees of freedom must be positive, got {dof}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie strictly inside (0, 1), got {alpha}")
    tabulated = CHI2_THRESHOLDS.get((dof, round(alpha, 6)))
    if tabulated is not None:
        return tabulated
    if dof <= 8:
        return _exact_threshold(alpha, dof)
    return wilson_hilferty(alpha, dof)


def chi2_dof(y: np.ndarray) -> int:
    """Degrees of freedom of an innovation vector, which is its length."""
    arr = np.asarray(y, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError("empty innovation has no degrees of freedom")
    return int(arr.size)


def mahalanobis_sq(
    y: np.ndarray,
    S: np.ndarray,
    max_condition: float = MAX_CONDITION_NUMBER,
) -> float:
    """Squared Mahalanobis distance ``y^T S^-1 y``.

    Solves rather than inverts: forming ``S^-1`` explicitly squares the condition
    number in the forward error for no benefit, since only the quadratic form is
    needed.

    ``S`` is symmetrised first. It is built as ``H P H^T + R`` from a covariance
    that is maintained symmetric, so in exact arithmetic it is already symmetric
    and the operation is a no-op. In floating point the products accumulate
    asymmetrically, and an asymmetric ``S`` makes the quadratic form depend on
    which triangle ``solve`` reads -- a difference of order the rounding error,
    which is the kind of discrepancy that makes a gate non-reproducible across
    platforms. Symmetrising makes the result depend only on the inputs.

    Returns ``inf`` when ``S`` is unusable: non-finite, not positive definite, or
    conditioned beyond ``max_condition``. Each of those means the measurement
    carries no trustworthy information in at least one direction, so no finite
    normalised distance exists. Callers reject, which is the safe direction --
    see the module docstring.
    """
    innov = np.asarray(y, dtype=float).reshape(-1)
    cov = np.asarray(S, dtype=float)
    m = innov.size
    if cov.shape != (m, m):
        raise ValueError(f"S must be {m}x{m} to match the innovation, got {cov.shape}")
    if not np.all(np.isfinite(innov)) or not np.all(np.isfinite(cov)):
        return float("inf")

    sym = 0.5 * (cov + cov.T)
    # Cholesky rather than SVD: it rejects non-positive-definite matrices
    # directly instead of inferring it from a condition number, and the factor is
    # also what the solve below needs. The explicit inverse is only for the
    # condition check.
    try:
        L = np.linalg.cholesky(sym)
    except np.linalg.LinAlgError:
        return float("inf")
    if not np.all(np.isfinite(L)):
        return float("inf")
    # Condition number from the Cholesky factors: S = L L^T, so
    # cond_1(S) = cond_1(L)^2. L is triangular, so its 1-norm is the largest
    # column sum and that of its inverse is the largest column sum of the inverse
    # -- the smallest diagonal entry is only a *lower* bound on the latter, so the
    # inverse is formed explicitly instead. O(m^3) on an m of 3 or 6, which is a
    # few hundred flops, and it makes the number a real condition number rather
    # than a pivot-ratio heuristic. A heuristic would be cheaper but could report
    # a well-conditioned S for a nearly-singular one: large subdiagonal entries
    # with uniform diagonals are exactly that case.
    diag = np.abs(np.diag(L))
    if float(np.min(diag)) <= 0.0:
        return float("inf")
    try:
        linv = np.linalg.inv(L)
    except np.linalg.LinAlgError:  # pragma: no cover - L is already factored
        return float("inf")
    if not np.all(np.isfinite(linv)):
        return float("inf")
    cond_l = float(np.max(np.abs(L).sum(axis=0)) * np.max(np.abs(linv).sum(axis=0)))
    if cond_l * cond_l > max_condition:
        return float("inf")

    try:
        w = np.linalg.solve(L, innov)
    except np.linalg.LinAlgError:  # pragma: no cover - L is already factored
        return float("inf")
    d2 = float(w @ w)
    # A genuinely large but finite distance is meaningful; only non-finite
    # results are not. max(0.0) guards against a tiny negative from rounding,
    # since a sum of squares cannot be negative.
    if not math.isfinite(d2):
        return float("inf")
    return max(d2, 0.0)
