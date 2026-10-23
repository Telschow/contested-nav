"""The gate for a new visual-update candidate (ADR-0030) as a pure function.

ADR-0028 judged a candidate by the grand mean NEES against a band built on the effective sample size. The per-run mean
NEES is heavy tailed, so that mean is fragile: a few runs decided the development pass. ADR-0030 uses robust
statistics per run and asks the same unchanged configuration to pass in two scenarios, S1 (independent visual errors)
and S2 (visual errors correlated over time).

In one scenario the candidate and the no-vision control run on the same 25 seeds over the GNSS-outage window. Each
run gives ``y_i``, the time-mean NEES over the window, and ``n_i``, its effective sample size. The scenario passes when
all of these hold:

* (U) the 90th percentile of the ``y_i`` is at most ``chi2_ppf(q, dof * m) / m``, with ``m`` the median of the
  ``n_i`` and at least one. The percentile is numpy's ``"linear"`` method. ``dof * m`` is not rounded:
  :func:`navkit.eval.statistics.chi2_ppf` takes a non-integer number of degrees of freedom, and ADR-0030 gives no
  floor (ADR-0028 floored its ``D``, and this gate does not).
* (L) the median of the ``y_i`` is at least ``0.44 * dof``;
* (C) the pooled share of (run, epoch, axis) triples with ``|error| <= 2 sigma`` on that axis is at least 95%;
* (P) paired by seed against the control: the candidate has the lower ATE in at least 80% of the runs (20 of 25), the
  median ratio of candidate ATE to control ATE is at most 0.8, and no ratio exceeds 1.5.

A candidate passes only if both scenarios pass. ``q`` is :data:`CANDIDATE_GATE_UPPER_QUANTILE`. It is not chosen: it
is the first of 0.975, 0.99 and 0.995 for which (U) and (L) have the properties that ADR-0030 pre-registers on
simulated runs (:func:`select_upper_quantile`), and a test fails if the constant differs from what the rule returns.

Nothing here does I/O or runs a case; :mod:`navkit.candidate_gate` collects the arrays. Passing does not change
``vision_enabled``.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

import numpy as np

from .calibration import wilson_interval
from .gate import Condition
from .statistics import chi2_ppf

# The thresholds. Each is the number in the Decision of ADR-0030, under the ADR's own wording.
CANDIDATE_GATE_RUNS = 25  #: "the same 25 held-out seeds"
CANDIDATE_GATE_PERCENTILE = 90.0  #: "(U) the 90th percentile of the y_i"
CANDIDATE_GATE_LOWER_PER_DOF = 0.44  #: "(L) the median of the y_i is at least 0.44 x 3"
CANDIDATE_GATE_COVERAGE_SIGMA = 2.0  #: "(C) pooled 2-sigma per-axis coverage"
CANDIDATE_GATE_COVERAGE_MIN = 0.95  #: "is at least 95%"
CANDIDATE_GATE_BETTER_FRACTION_MIN = 0.8  #: "(P) the lower ATE in at least 20 of 25 seeds", as 80% of N
CANDIDATE_GATE_MEDIAN_RATIO_MAX = 0.8  #: "the median ratio ... is at most 0.8"
CANDIDATE_GATE_WORST_RATIO_MAX = 1.5  #: "no seed's ratio exceeds 1.5"

#: The confidence levels of (U) that ADR-0030 allows, in the order they are tried.
UPPER_QUANTILE_LEVELS = (0.975, 0.99, 0.995)

#: The pre-registered properties (ADR-0030 "Pre-registered properties").
SIMULATION_RUNS = 25  #: "simulated 25-run sets"
SIMULATION_SETS = 10000  #: the number of simulated sets; the ADR asks for at least this many
SIMULATION_SEED = 0  #: fixed in advance; a different seed is not tried
SIMULATION_FACTOR_CONSISTENT = 1.0  #: "a consistent filter"
SIMULATION_FACTOR_HIGH = 2.0  #: "a filter whose NEES is 2 times too high"
SIMULATION_FACTOR_LOW = 0.3  #: "a filter whose NEES is 0.3 times too low"
PROPERTY_MIN_CONSISTENT = 0.90  #: "passes (U) and (L) together in at least 90% of simulated 25-run sets"
PROPERTY_MIN_HIGH_FAIL = 0.99  #: "fails (U) in at least 99%"
PROPERTY_MIN_LOW_FAIL = 0.99  #: "fails (L) in at least 99%"

#: The confidence level of (U). Set by :func:`select_upper_quantile` on ``docs/data/gate_n_eff_pool.csv``, not by hand.
CANDIDATE_GATE_UPPER_QUANTILE = 0.975


@dataclass(frozen=True)
class ScenarioGateResult:
    """The six conditions of the gate in one scenario, and the outcome."""

    upper: Condition
    lower: Condition
    coverage: Condition
    better: Condition
    median_ratio: Condition
    worst_ratio: Condition
    passed: bool
    n_runs: int
    m: float  # the median effective sample size, at least one, that (U) is built on
    upper_quantile: float
    dof: int

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return (self.upper, self.lower, self.coverage, self.better, self.median_ratio, self.worst_ratio)


@dataclass(frozen=True)
class CandidateGateResult:
    """A candidate passes only if the gate passes in both scenarios."""

    s1: ScenarioGateResult
    s2: ScenarioGateResult
    passed: bool


def _finite(name: str, a: np.ndarray) -> None:
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite")


def evaluate_scenario_gate(
    y: np.ndarray,
    n_eff: np.ndarray,
    err: np.ndarray,
    sigma: np.ndarray,
    cand_ate: np.ndarray,
    ctrl_ate: np.ndarray,
    dof: int = 3,
    upper_quantile: float = CANDIDATE_GATE_UPPER_QUANTILE,
) -> ScenarioGateResult:
    """Apply (U), (L), (C) and (P) to ``N`` paired runs of one scenario.

    ``y`` and ``n_eff`` are ``(N,)``: the time-mean window NEES and its effective sample size per run. ``err`` and
    ``sigma`` are ``(N, K, 3)``: the window position error and the claimed per-axis standard deviation. ``cand_ate``
    and ``ctrl_ate`` are ``(N,)``, the window ATE of the candidate and of the control on the same seed. Any ``N >= 2``
    is accepted so that the function can be tested; the command fixes ``N = 25``.
    """
    y_a = np.asarray(y, dtype=float)
    m_a = np.asarray(n_eff, dtype=float)
    err_a = np.asarray(err, dtype=float)
    sig_a = np.asarray(sigma, dtype=float)
    cand = np.asarray(cand_ate, dtype=float)
    ctrl = np.asarray(ctrl_ate, dtype=float)
    if y_a.ndim != 1:
        raise ValueError(f"y must have shape (N,), got {y_a.shape}")
    n = y_a.shape[0]
    if n < 2:
        raise ValueError(f"the gate needs at least two runs, got {n}")
    if m_a.shape != (n,) or cand.shape != (n,) or ctrl.shape != (n,):
        raise ValueError(
            f"n_eff, cand_ate and ctrl_ate must have shape {(n,)}, got {m_a.shape}, {cand.shape} and {ctrl.shape}"
        )
    if err_a.ndim != 3 or err_a.shape[0] != n or err_a.shape[2] != 3 or sig_a.shape != err_a.shape:
        raise ValueError(f"err and sigma must have the same shape (N, K, 3), got {err_a.shape} and {sig_a.shape}")
    for name, a in (
        ("y", y_a),
        ("n_eff", m_a),
        ("err", err_a),
        ("sigma", sig_a),
        ("cand_ate", cand),
        ("ctrl_ate", ctrl),
    ):
        _finite(name, a)
    if np.any(y_a < 0.0):
        raise ValueError("y has a negative value")
    if np.any(sig_a < 0.0) or np.any(cand < 0.0):
        raise ValueError("sigma and cand_ate must not be negative")
    if np.any(m_a <= 0.0):
        raise ValueError("n_eff must be positive")
    if np.any(ctrl <= 0.0):
        raise ValueError("ctrl_ate must be positive, the ratio is taken against it")
    if not 0.5 < upper_quantile < 1.0:
        raise ValueError(f"upper_quantile must lie in (0.5, 1), got {upper_quantile}")

    m = max(float(np.median(m_a)), 1.0)
    upper_edge = chi2_ppf(upper_quantile, dof * m) / m
    p90 = float(np.percentile(y_a, CANDIDATE_GATE_PERCENTILE, method="linear"))
    median_y = float(np.median(y_a))
    floor = CANDIDATE_GATE_LOWER_PER_DOF * dof
    coverage = float(np.mean(np.abs(err_a) <= CANDIDATE_GATE_COVERAGE_SIGMA * sig_a))

    ratio = cand / ctrl
    better = int(np.sum(cand < ctrl))
    needed = math.ceil(round(CANDIDATE_GATE_BETTER_FRACTION_MIN * n, 9))
    median_ratio = float(np.median(ratio))
    worst_ratio = float(np.max(ratio))

    upper = Condition("upper", p90, upper_edge, "<=", p90 <= upper_edge)
    lower = Condition("lower", median_y, floor, ">=", median_y >= floor)
    cov = Condition("coverage", coverage, CANDIDATE_GATE_COVERAGE_MIN, ">=", coverage >= CANDIDATE_GATE_COVERAGE_MIN)
    b = Condition("better", float(better), float(needed), ">=", better >= needed)
    mr = Condition(
        "median_ratio",
        median_ratio,
        CANDIDATE_GATE_MEDIAN_RATIO_MAX,
        "<=",
        median_ratio <= CANDIDATE_GATE_MEDIAN_RATIO_MAX,
    )
    wr = Condition(
        "worst_ratio", worst_ratio, CANDIDATE_GATE_WORST_RATIO_MAX, "<=", worst_ratio <= CANDIDATE_GATE_WORST_RATIO_MAX
    )
    parts = (upper, lower, cov, b, mr, wr)
    return ScenarioGateResult(
        upper=upper,
        lower=lower,
        coverage=cov,
        better=b,
        median_ratio=mr,
        worst_ratio=wr,
        passed=all(c.passed for c in parts),
        n_runs=n,
        m=m,
        upper_quantile=upper_quantile,
        dof=dof,
    )


def evaluate_candidate_gate(s1: ScenarioGateResult, s2: ScenarioGateResult) -> CandidateGateResult:
    """A candidate passes only if the gate passes in both scenarios."""
    return CandidateGateResult(s1=s1, s2=s2, passed=s1.passed and s2.passed)


# ------------------------------------------------------------------------------ the pre-registered properties


@dataclass(frozen=True)
class GateProperties:
    """The three simulated rates of ADR-0030 at one confidence level of (U), each with its Wilson interval."""

    upper_quantile: float
    n_sets: int
    consistent_rate: float  # a consistent filter passes (U) and (L) together
    high_fail_rate: float  # a filter whose NEES is too high fails (U)
    low_fail_rate: float  # a filter whose NEES is too low fails (L)
    consistent_interval: tuple[float, float]
    high_fail_interval: tuple[float, float]
    low_fail_interval: tuple[float, float]


def simulate_gate_properties(
    n_eff_pool: np.ndarray,
    n_sets: int = SIMULATION_SETS,
    seed: int = SIMULATION_SEED,
    upper_quantile: float = CANDIDATE_GATE_UPPER_QUANTILE,
    n_runs: int = SIMULATION_RUNS,
    dof: int = 3,
) -> GateProperties:
    """Simulate the properties of (U) and (L) that ADR-0030 pre-registers.

    A simulated run has ``y_i = chi-square(dof * n_i) / n_i`` times a factor, with ``n_i`` drawn with replacement from
    ``n_eff_pool``. A set is ``n_runs`` such runs. The three cases share their draws (common random numbers), so a
    difference between them is the factor and not the sample. The rates are shares of ``n_sets`` sets.
    """
    pool = np.asarray(n_eff_pool, dtype=float)
    if pool.ndim != 1 or pool.size == 0:
        raise ValueError("the pool of effective sample sizes must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(pool)) or np.any(pool <= 0.0):
        raise ValueError("every effective sample size in the pool must be positive and finite")
    if n_sets < 1 or n_runs < 2:
        raise ValueError("a simulation needs at least one set of at least two runs")
    rng = np.random.default_rng(seed)
    n = rng.choice(pool, size=(n_sets, n_runs), replace=True)
    base = rng.chisquare(dof * n) / n
    m = np.maximum(np.median(n, axis=1), 1.0)
    edges: dict[float, float] = {}
    for value in np.unique(m):
        edges[float(value)] = chi2_ppf(upper_quantile, dof * float(value)) / float(value)
    edge = np.array([edges[float(v)] for v in m])
    floor = CANDIDATE_GATE_LOWER_PER_DOF * dof

    def u_pass(y: np.ndarray) -> np.ndarray:
        return np.percentile(y, CANDIDATE_GATE_PERCENTILE, axis=1, method="linear") <= edge

    def l_pass(y: np.ndarray) -> np.ndarray:
        return np.median(y, axis=1) >= floor

    consistent = SIMULATION_FACTOR_CONSISTENT * base
    consistent_ok = int(np.sum(u_pass(consistent) & l_pass(consistent)))
    high_ok = int(np.sum(~u_pass(SIMULATION_FACTOR_HIGH * base)))
    low_ok = int(np.sum(~l_pass(SIMULATION_FACTOR_LOW * base)))
    return GateProperties(
        upper_quantile=upper_quantile,
        n_sets=n_sets,
        consistent_rate=consistent_ok / n_sets,
        high_fail_rate=high_ok / n_sets,
        low_fail_rate=low_ok / n_sets,
        consistent_interval=wilson_interval(consistent_ok, n_sets),
        high_fail_interval=wilson_interval(high_ok, n_sets),
        low_fail_interval=wilson_interval(low_ok, n_sets),
    )


def properties_met(props: GateProperties) -> bool:
    """All three pre-registered properties hold at this level."""
    return (
        props.consistent_rate >= PROPERTY_MIN_CONSISTENT
        and props.high_fail_rate >= PROPERTY_MIN_HIGH_FAIL
        and props.low_fail_rate >= PROPERTY_MIN_LOW_FAIL
    )


def select_upper_quantile(
    n_eff_pool: np.ndarray,
    n_sets: int = SIMULATION_SETS,
    seed: int = SIMULATION_SEED,
    levels: tuple[float, ...] = UPPER_QUANTILE_LEVELS,
) -> float:
    """The first of ``levels`` at which all three properties hold; raises when none does.

    This is the only correction ADR-0030 allows. The percentile, the 0.44 tolerance and the other thresholds do not
    change, so when no level works the result is a finding about the gate and not a number to adjust.
    """
    for level in levels:
        props = simulate_gate_properties(n_eff_pool, n_sets=n_sets, seed=seed, upper_quantile=level)
        if properties_met(props):
            return level
    raise ValueError(f"no level of {levels} meets the three pre-registered properties")


def property_table(
    n_eff_pool: np.ndarray, n_sets: int = SIMULATION_SETS, seed: int = SIMULATION_SEED
) -> list[GateProperties]:
    """The three rates at every level, for the record. :func:`select_upper_quantile` stops at the first that works."""
    return [
        simulate_gate_properties(n_eff_pool, n_sets=n_sets, seed=seed, upper_quantile=level)
        for level in UPPER_QUANTILE_LEVELS
    ]


# ------------------------------------------------------------------------------------------- the pool file


def pool_csv_text(rows: list[dict[str, float]]) -> str:
    """``seeds,n_eff`` as CSV text. Floats are written with ``repr``, so the bytes are deterministic."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("seeds", "n_eff"))
    for row in rows:
        writer.writerow((int(row["seeds"]), repr(float(row["n_eff"]))))
    return buffer.getvalue()


def parse_pool_csv(text: str) -> list[dict[str, float]]:
    """The inverse of :func:`pool_csv_text`."""
    return [{"seeds": int(r["seeds"]), "n_eff": float(r["n_eff"])} for r in csv.DictReader(io.StringIO(text))]
