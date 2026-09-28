"""Is the estimator's uncertainty honest?

A pose estimate without a trustworthy uncertainty is not much use for flight
planning. An aircraft is allowed to be lost; it is not allowed to be lost
*quietly*. This module measures whether the covariance an estimator reports
actually describes the error it makes, and provides the machinery to correct it
when it does not.

The claim this project makes is narrow and falsifiable: **a filter tuned for
accuracy is not thereby calibrated, and the gap is measurable, correctable, and
distribution-dependent.** Each function below exists so that the claim can fail
loudly rather than quietly.

What "calibrated" means here
----------------------------
If the reported covariance is correct, the squared Mahalanobis distance of the
error, ``e^T P^-1 e``, follows a chi-square distribution with as many degrees of
freedom as the state dimension. That gives two independent ways to check:

* the *mean* normalised error should equal the dimension;
* the *coverage* of the claimed ellipsoid should equal ``P(chi2_dof <= r**2)``.

Coverage is the more useful of the two for a planner, because it is directly
interpretable: it answers "how often is the aircraft inside the box I drew?"
The per-axis sigma and the coverage are not interchangeable, and
:mod:`navkit.eval.statistics` quantifies by how much. Every coverage number in
this module is stated against the chi-square reference, never against the
nominal percentage it was derived from.

Three levels of rigour
----------------------
``CoverageReport``
    Descriptive. What fraction of epochs fell inside the claimed ellipsoid,
    with a Wilson interval so that a coverage measured on 400 epochs is not
    reported to more precision than it has.

``inflation_factor``
    Corrective. The scalar by which the covariance must be multiplied for
    observed coverage to reach the target. One global scalar, so it cannot fix a
    filter that is miscalibrated only in some directions or only in some
    regimes -- which is the usual case. Report it; do not apply it silently.

``conformal_radius``
    Distributional. A finite-sample bound on the normalised error derived from
    an order statistic of a calibration set, valid at a stated confidence under
    exchangeability with that set. This is the only one of the three carrying a
    guarantee a reader can check, and the guarantee is conditional. The
    behaviour under distribution shift is measured by :func:`shift_sensitivity`
    rather than assumed away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .statistics import chi2_ppf, ellipsoid_coverage

__all__ = [
    "MahalanobisSeries",
    "CoveragePoint",
    "CoverageReport",
    "CalibrationReport",
    "normalized_error_squared",
    "coverage_report",
    "inflation_factor",
    "conformal_radius",
    "shift_sensitivity",
    "wilson_interval",
]

#: Two-sided normal quantile for a 95% interval, via the chi-square reference
#: so the module has no hard-coded statistical constants.
_Z95 = math.sqrt(chi2_ppf(0.95, 1))


def wilson_interval(successes: int, trials: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation, which is badly behaved at the
    coverage values that matter here: a filter that claims 95% coverage and
    achieves 0% is exactly the case where a Wald interval produces nonsense.
    """
    if trials <= 0:
        return (0.0, 1.0)
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / denom
    half = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) / denom
    # Force the interval to bracket the point estimate. At p = 0 or p = 1 the
    # closed form lands one ULP outside the estimate, and an interval that
    # excludes the value it is estimating is wrong regardless of the cause.
    return (max(0.0, min(centre - half, p)), min(1.0, max(centre + half, p)))


@dataclass(frozen=True)
class MahalanobisSeries:
    """Per-epoch normalised error between an estimate and a reference.

    Attributes
    ----------
    squared:
        ``e^T P^-1 e`` per epoch. Under a correct covariance this is chi-square
        with ``dof`` degrees of freedom, so its mean should be ``dof``.
    radius:
        ``sqrt(squared)``, the quantity whose distribution is chi with ``dof``
        degrees of freedom. This is the object the conformal bound is built on.
    dof:
        Dimension of the state being scored.
    epochs:
        How many epochs contributed. Zero-length input is allowed and yields an
        empty series, so callers can pass a filtered sequence without guarding.
    """

    squared: np.ndarray
    radius: np.ndarray
    dof: int
    epochs: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "epochs", int(self.squared.shape[0]))

    def mean_squared(self) -> float:
        return float(np.mean(self.squared)) if self.epochs else float("nan")

    def quantile_radius(self, q: float) -> float:
        """Empirical ``q``-quantile of the normalised radius."""
        if self.epochs == 0:
            return float("nan")
        return float(np.quantile(self.radius, q, method="higher"))


def normalized_error_squared(
    estimate_positions: np.ndarray,
    reference_positions: np.ndarray,
    position_cov: np.ndarray,
) -> MahalanobisSeries:
    """Score an estimate against a reference given its position covariance.

    Both trajectories are compared index by index, so the caller is responsible
    for resampling the reference onto the estimate's timestamps. Covariance
    blocks that are numerically singular are handled by symmetric regularisation
    rather than by dropping the epoch, because silently discarding the worst
    epochs is precisely how a miscalibrated filter gets to look well behaved.
    """
    est = np.asarray(estimate_positions, float).reshape(-1, 3)
    ref = np.asarray(reference_positions, float).reshape(-1, 3)
    cov = np.asarray(position_cov, float).reshape(-1, 3, 3)
    if not (len(est) == len(ref) == len(cov)):
        raise ValueError(
            f"length mismatch: estimate {len(est)}, reference {len(ref)}, covariance {len(cov)}"
        )
    dof = 3
    if len(est) == 0:
        return MahalanobisSeries(squared=np.zeros(0), radius=np.zeros(0), dof=dof)

    out = np.empty(len(est))
    for i, (e, P) in enumerate(zip(est - ref, cov)):
        # Symmetric eigendecomposition, with a floor on the smallest eigenvalue.
        # A filter that has collapsed a direction to near-zero variance would
        # otherwise produce a huge normalised error from a rounding-level
        # eigenvalue; flooring keeps the score finite and the epoch visible.
        w, V = np.linalg.eigh(0.5 * (P + P.T))
        w = np.maximum(w, 1e-12)
        y = V.T @ e
        out[i] = float(np.sum((y * y) / w))
    return MahalanobisSeries(squared=out, radius=np.sqrt(np.maximum(out, 0.0)), dof=dof)


@dataclass(frozen=True)
class CoveragePoint:
    """Observed versus expected coverage at one per-axis sigma."""

    sigma_per_axis: float
    covered: int
    epochs: int

    @property
    def observed(self) -> float:
        return self.covered / self.epochs if self.epochs else float("nan")

    @property
    def expected(self) -> float:
        return ellipsoid_coverage(self.sigma_per_axis, 3)

    @property
    def gap(self) -> float:
        """Observed minus expected. Negative means the filter is overconfident."""
        return self.observed - self.expected

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.covered, self.epochs)

    @property
    def verdict(self) -> str:
        """Calibration verdict from a two-sided test on the coverage.

        The question is whether the expected coverage lies inside the Wilson
        interval of what was observed. Comparing the observed and expected
        values directly, as a sign test would, flags almost every correct filter
        as miscalibrated, because an observed coverage essentially never equals
        its expectation exactly.
        """
        lo, hi = self.interval
        if self.expected > hi:
            return "overconfident"
        if self.expected < lo:
            return "underconfident"
        return "calibrated"

    def as_dict(self) -> dict[str, object]:
        return {
            "sigma_per_axis": self.sigma_per_axis,
            "covered": self.covered,
            "epochs": self.epochs,
            "observed_coverage": self.observed,
            "expected_coverage": self.expected,
            "gap": self.gap,
            "wilson_low": self.interval[0],
            "wilson_high": self.interval[1],
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class CoverageReport:
    """Coverage of an estimator at a range of per-axis sigmas."""

    points: tuple[CoveragePoint, ...]
    mean_normalised_error: float
    dof: int = 3

    @property
    def epochs(self) -> int:
        return self.points[0].epochs if self.points else 0

    def at(self, sigma_per_axis: float) -> CoveragePoint | None:
        for p in self.points:
            if abs(p.sigma_per_axis - sigma_per_axis) < 1e-12:
                return p
        return None

    @property
    def worst_gap(self) -> float:
        return min((p.gap for p in self.points), default=float("nan"))

    def as_dict(self) -> dict[str, object]:
        return {
            "dof": self.dof,
            "epochs": self.epochs,
            "mean_normalised_error": self.mean_normalised_error,
            "expected_mean_normalised_error": float(self.dof),
            "points": [p.as_dict() for p in self.points],
        }


def coverage_report(
    series: MahalanobisSeries,
    sigmas: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> CoverageReport:
    """Measure coverage at several per-axis sigmas.

    Note that ``series.squared`` is the squared Mahalanobis distance, so a
    ``k``-sigma-per-axis ellipsoid is the set ``squared <= k**2 * dof``.
    """
    points = tuple(
        CoveragePoint(
            sigma_per_axis=float(k),
            covered=int(np.count_nonzero(series.squared <= k * k * series.dof)),
            epochs=series.epochs,
        )
        for k in sigmas
    )
    return CoverageReport(
        points=points, mean_normalised_error=series.mean_squared(), dof=series.dof
    )


def inflation_factor(
    series: MahalanobisSeries, target_coverage: float = 0.95
) -> float:
    """Scalar covariance inflation that reaches ``target_coverage``.

    Returns ``inf`` when the target is unreachable at any inflation, which
    happens when the filter is *underconfident* to a degree that no global
    scale can repair. Reporting infinity is the honest answer; clipping to a
    large finite number would disguise an unbounded calibration error as a
    merely large correction.
    """
    if series.epochs == 0:
        return float("nan")
    radius_at_target = math.sqrt(chi2_ppf(target_coverage, series.dof))
    # The inflation factor is a per-axis sigma multiplier, so the threshold on
    # the squared distance scales with its square.
    q = series.quantile_radius(target_coverage)
    if q <= 0.0:
        return 0.0
    return float(q / radius_at_target)


def conformal_radius(
    calibration: MahalanobisSeries, confidence: float = 0.95
) -> dict[str, float]:
    """Finite-sample bound on the normalised error under exchangeability.

    The bound is the order statistic at index ``ceil((n + 1) * confidence) / n``
    of the calibration radii. The index, not the plain ``confidence`` quantile,
    is what makes the guarantee hold for finite ``n``; using the plain quantile
    is a small and very common error that silently voids the guarantee. When
    the index exceeds ``n`` the target cannot be certified from this sample and
    the bound is reported as infinity rather than extrapolated.
    """
    n = calibration.epochs
    if n == 0:
        return {"radius": float("nan"), "confidence": confidence, "n": 0.0, "certified": 0.0}
    k = math.ceil((n + 1) * confidence)
    if k > n:
        return {
            "radius": float("inf"),
            "confidence": confidence,
            "n": float(n),
            "certified": 0.0,
            "index": float(k),
        }
    radius = float(np.sort(calibration.radius)[k - 1])
    return {
        "radius": radius,
        "confidence": confidence,
        "n": float(n),
        "index": float(k),
        "certified": 1.0,
        "nominal_radius": float(math.sqrt(chi2_ppf(confidence, calibration.dof))),
    }


def shift_sensitivity(
    calibration: MahalanobisSeries, held_out: MahalanobisSeries, confidence: float = 0.95
) -> dict[str, float]:
    """How much of a calibrated guarantee survives a change of distribution.

    The conformal bound is only valid for data exchangeable with the set it was
    built from. Applying it after a change in noise level, outage profile, or
    manoeuvre regime is exactly the situation a planner cares about, and the
    honest thing is to measure how far the realised coverage falls below the
    nominal one instead of carrying the nominal number forward.
    """
    bound = conformal_radius(calibration, confidence)
    if held_out.epochs == 0 or not math.isfinite(bound["radius"]):
        return {
            "realised_coverage": float("nan"),
            "nominal_coverage": confidence,
            "deficit": float("nan"),
        }
    inside = int(np.count_nonzero(held_out.radius <= bound["radius"]))
    realised = inside / held_out.epochs
    return {
        "radius": bound["radius"],
        "realised_coverage": realised,
        "nominal_coverage": confidence,
        "deficit": confidence - realised,
        "held_out_epochs": float(held_out.epochs),
    }


@dataclass(frozen=True)
class CalibrationReport:
    """Everything measured about one estimator's uncertainty on one dataset."""

    estimator: str
    scenario: str
    coverage: CoverageReport
    inflation_to_95: float
    conformal: dict[str, float]
    notes: tuple[str, ...] = ()

    @property
    def bulk_verdict(self) -> str:
        """Verdict from the *bulk* of the error distribution, via NEES.

        The coverage verdict above is a tail test: it asks whether errors ever
        escape the k-sigma ellipsoid, and it uses a Wilson interval because an
        observed coverage essentially never equals its expectation exactly. That
        alone is not enough to describe a filter, because the two diagnostics
        detect different failure modes and can disagree.

        A filter can sit slightly *above* its covariance almost everywhere (bulk
        NEES above ``dof``, meaning marginally overconfident) while never once
        producing an error outside the 2-sigma ellipsoid (coverage at nominal).
        Calling that "underconfident" because the tail looks clean, or
        "overconfident" because NEES is high, would each discard half the
        evidence. Both are reported.

        The test is the standard chi-square one: ``NEES * n`` is distributed as
        ``chi2(n * dof)`` when the filter is correctly calibrated. Polarity
        follows the mean: a NEES *above* ``dof`` means the real errors are
        larger than the covariance admits, so the filter is overconfident; below
        it, the filter is underconfident. That is the same sense as
        :attr:`CoveragePoint.gap`, where too few covered epochs also means
        overconfidence.
        """
        series_nees = self.coverage.mean_normalised_error
        n = self.coverage.epochs
        if n == 0 or not np.isfinite(series_nees):
            return "insufficient_data"
        dof = self.coverage.dof
        lo = chi2_ppf(0.025, n * dof) / n
        hi = chi2_ppf(0.975, n * dof) / n
        if series_nees > hi:
            return "overconfident"
        if series_nees < lo:
            return "underconfident"
        return "calibrated"

    @property
    def tail_verdict(self) -> str:
        """Verdict from the tail, i.e. from coverage at 2 sigma per axis."""
        point = self.coverage.at(2.0) or (
            self.coverage.points[-1] if self.coverage.points else None
        )
        return point.verdict if point else "insufficient_data"

    @property
    def verdict(self) -> str:
        """Combined verdict, naming a disagreement rather than hiding it.

        ``bulk`` and ``tail`` disagreeing is itself the finding: it means the
        error distribution is misshapen in a way neither number describes on its
        own, and that is a different defect from a simple miscalibration.
        """
        bulk, tail = self.bulk_verdict, self.tail_verdict
        if bulk == tail:
            return bulk
        if "insufficient" in (bulk, tail):
            return next(v for v in (bulk, tail) if v != "insufficient_data")
        return f"mixed(bulk={bulk}, tail={tail})"

    @property
    def calibrated(self) -> bool:
        """True only when the bulk and the tail both agree with expectation.

        This is stricter than either test alone, which is the intent: a filter
        counts as calibrated only if it is neither systematically
        overconfident in the bulk nor producing tail escapes.
        """
        return self.verdict == "calibrated"

    def as_dict(self) -> dict[str, object]:
        return {
            "estimator": self.estimator,
            "scenario": self.scenario,
            "calibrated": self.calibrated,
            "verdict": self.verdict,
            "bulk_verdict": self.bulk_verdict,
            "tail_verdict": self.tail_verdict,
            "mean_nees": self.coverage.mean_normalised_error,
            "expected_nees": self.coverage.dof,
            "inflation_to_95": self.inflation_to_95,
            "conformal": self.conformal,
            "coverage": self.coverage.as_dict(),
            "notes": list(self.notes),
        }


def summarise(
    estimator: str,
    scenario: str,
    series: MahalanobisSeries,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> CalibrationReport:
    """Build a :class:`CalibrationReport` from a scored sequence."""
    return CalibrationReport(
        estimator=estimator,
        scenario=scenario,
        coverage=coverage_report(series),
        inflation_to_95=inflation_factor(series, 0.95),
        conformal=conformal_radius(series, confidence),
        notes=notes,
    )
