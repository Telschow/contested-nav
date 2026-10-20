"""The B1 gate of ADR-0028 as a pure function.

The gate asks one question of an ensemble of seeded runs over the GNSS-outage window: is the filter honest about how
wrong it is, and does vision help? It passes when all six parts below hold. The thresholds are the ADR's, and the ADR
is the specification. Nothing here does I/O or runs a case; :mod:`navkit.b1_gate` collects the arrays.

1. The grand mean NEES is at or below the upper edge of the 95% chi-square band with ``D`` degrees of freedom, where
   ``D = floor(dof * sum_i n_eff_i)`` and ``n_eff_i`` is the effective sample size of run ``i``'s window NEES series.
   Epochs within a run are strongly autocorrelated, so the raw epoch count would make the band far too narrow.
2. The same grand mean is at least ``0.44 * dof``: the claimed standard deviation is at most 1.5 times the actual error.
3. The pooled share of (run, epoch, axis) triples with ``|error| <= 2 sigma`` on that axis is at least 95%.
4. Against the no-vision control, paired by seed: the candidate has the lower ATE in at least 80% of the runs, the
   median ATE ratio (candidate over control) is at most 0.8, and no ratio exceeds 1.5.

Passing does not by itself change ``vision_enabled``; that is a separate decision (ADR-0028).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .statistics import autocorrelation_estimate, chi2_ppf

# The thresholds. Each is the number in the Decision of ADR-0028, under the ADR's own wording.
B1_BAND_UPPER_QUANTILE = 0.975  #: "the upper edge of the 95% chi-square band"
B1_LOWER_BOUND_PER_DOF = 0.44  #: "at least 0.44 x dof (claimed standard deviation at most 1.5 times the actual error)"
B1_COVERAGE_SIGMA = 2.0  #: "pooled 2-sigma per-axis coverage"
B1_COVERAGE_MIN = 0.95  #: "is at least 95%"
B1_BETTER_FRACTION_MIN = 0.8  #: "the lower ATE in at least 20 of 25 seeds", written as at least 80% of N
B1_MEDIAN_RATIO_MAX = 0.8  #: "the median ATE ratio is 0.8 or lower"
B1_WORST_RATIO_MAX = 1.5  #: "no seed's ratio exceeds 1.5"

#: The least number of epochs per run for which an autocorrelation time can be estimated.
_MIN_EPOCHS = 10


@dataclass(frozen=True)
class Condition:
    """One part of the gate: what was measured, what it was held to, and whether it held."""

    name: str
    value: float
    threshold: float
    relation: str  # "<=" (value must be at most the threshold) or ">=" (at least)
    passed: bool


@dataclass(frozen=True)
class B1GateResult:
    """The six conditions of ADR-0028, the overall outcome, and what the band was built from."""

    nees_upper: Condition
    nees_lower: Condition
    coverage: Condition
    ate_better: Condition
    ate_median: Condition
    ate_worst: Condition
    passed: bool
    n_runs: int
    n_epochs: int
    dof: int
    sum_n_eff: float
    degrees_of_freedom: int  # D, the chi-square degrees of freedom of the band
    n_truncated: int  # runs whose autocorrelation estimate hit its largest window (n_eff is then an upper bound)

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return (self.nees_upper, self.nees_lower, self.coverage, self.ate_better, self.ate_median, self.ate_worst)

    @property
    def any_truncated(self) -> bool:
        return self.n_truncated > 0


def _finite(name: str, a: np.ndarray) -> None:
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite")


def evaluate_b1_gate(
    cand_nees: np.ndarray,
    cand_err: np.ndarray,
    cand_sigma: np.ndarray,
    cand_ate: np.ndarray,
    ctrl_ate: np.ndarray,
    dof: int = 3,
) -> B1GateResult:
    """Apply the gate to ``N`` paired runs.

    ``cand_nees`` is ``(N, K)``: the per-epoch position NEES of the candidate over the window. ``cand_err`` and
    ``cand_sigma`` are ``(N, K, 3)``: the position error and the claimed per-axis standard deviation at the same
    epochs. ``cand_ate`` and ``ctrl_ate`` are ``(N,)``: the RMSE of the 3-D position error over the window for the
    candidate and for its no-vision control, run ``i`` of each on the same seed.

    Any ``N >= 2`` is accepted so that the function can be tested; the command that decides the gate fixes ``N = 25``.
    The count rule of condition 4 is "at least 80% of ``N``", which is 20 for ``N = 25``.
    """
    nees = np.asarray(cand_nees, dtype=float)
    err = np.asarray(cand_err, dtype=float)
    sigma = np.asarray(cand_sigma, dtype=float)
    cand = np.asarray(cand_ate, dtype=float)
    ctrl = np.asarray(ctrl_ate, dtype=float)
    if nees.ndim != 2:
        raise ValueError(f"cand_nees must have shape (N, K), got {nees.shape}")
    n, k = nees.shape
    if n < 2:
        raise ValueError(f"the gate needs at least two runs, got {n}")
    if k < _MIN_EPOCHS:
        raise ValueError(f"the gate needs at least {_MIN_EPOCHS} epochs per run, got {k}")
    if err.shape != (n, k, 3) or sigma.shape != (n, k, 3):
        raise ValueError(f"cand_err and cand_sigma must have shape {(n, k, 3)}, got {err.shape} and {sigma.shape}")
    if cand.shape != (n,) or ctrl.shape != (n,):
        raise ValueError(f"cand_ate and ctrl_ate must have shape {(n,)}, got {cand.shape} and {ctrl.shape}")
    for name, a in (
        ("cand_nees", nees),
        ("cand_err", err),
        ("cand_sigma", sigma),
        ("cand_ate", cand),
        ("ctrl_ate", ctrl),
    ):
        _finite(name, a)
    if np.any(nees < 0.0):
        raise ValueError("cand_nees has a negative value")
    if np.any(sigma < 0.0):
        raise ValueError("cand_sigma has a negative value")
    if np.any(cand < 0.0):
        raise ValueError("cand_ate has a negative value")
    if np.any(ctrl <= 0.0):
        raise ValueError("ctrl_ate must be positive, the ratio is taken against it")

    # (1) and (2): the grand mean against the band built on the effective sample size.
    estimates = [autocorrelation_estimate(row) for row in nees]
    sum_n_eff = float(sum(e.effective_sample_size for e in estimates))
    degrees = math.floor(dof * sum_n_eff)
    upper = chi2_ppf(B1_BAND_UPPER_QUANTILE, degrees) * dof / degrees
    grand_mean = float(nees.mean())
    lower = B1_LOWER_BOUND_PER_DOF * dof

    # (3): pooled over runs, epochs and axes.
    coverage = float(np.mean(np.abs(err) <= B1_COVERAGE_SIGMA * sigma))

    # (4): paired by seed, candidate over control.
    ratio = cand / ctrl
    better = int(np.sum(cand < ctrl))
    needed = math.ceil(round(B1_BETTER_FRACTION_MIN * n, 9))
    median_ratio = float(np.median(ratio))
    worst_ratio = float(np.max(ratio))

    nees_upper = Condition("nees_upper", grand_mean, upper, "<=", grand_mean <= upper)
    nees_lower = Condition("nees_lower", grand_mean, lower, ">=", grand_mean >= lower)
    cov = Condition("coverage", coverage, B1_COVERAGE_MIN, ">=", coverage >= B1_COVERAGE_MIN)
    ate_better = Condition("ate_better", float(better), float(needed), ">=", better >= needed)
    ate_median = Condition("ate_median", median_ratio, B1_MEDIAN_RATIO_MAX, "<=", median_ratio <= B1_MEDIAN_RATIO_MAX)
    ate_worst = Condition("ate_worst", worst_ratio, B1_WORST_RATIO_MAX, "<=", worst_ratio <= B1_WORST_RATIO_MAX)
    parts = (nees_upper, nees_lower, cov, ate_better, ate_median, ate_worst)
    return B1GateResult(
        nees_upper=nees_upper,
        nees_lower=nees_lower,
        coverage=cov,
        ate_better=ate_better,
        ate_median=ate_median,
        ate_worst=ate_worst,
        passed=all(c.passed for c in parts),
        n_runs=n,
        n_epochs=k,
        dof=dof,
        sum_n_eff=sum_n_eff,
        degrees_of_freedom=degrees,
        n_truncated=sum(1 for e in estimates if e.truncated),
    )
