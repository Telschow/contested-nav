"""The candidate gate of ADR-0030 as a pure function: conditions (U), (L), (C), (P) in one scenario, and the rule that
a candidate passes only if both scenarios pass.

Nothing here runs a case. The Decision of ADR-0030 is the specification.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.eval import candidate_gate as cg
from navkit.eval import gate as b1
from navkit.eval.candidate_gate import (
    CandidateGateResult,
    ScenarioGateResult,
    evaluate_candidate_gate,
    evaluate_scenario_gate,
)
from navkit.eval.statistics import chi2_ppf

N, K, DOF = 25, 300, 3


def _inputs(seed: int = 3, m: float = 20.0, n: int = N, k: int = K):
    """A consistent filter: per-run means that are chi-square(3m)/m, errors drawn from the claimed sigma."""
    rng = np.random.default_rng(seed)
    y = rng.chisquare(DOF * m, n) / m
    n_eff = np.full(n, m)
    sigma = rng.uniform(0.5, 2.0, (n, k, DOF))
    err = rng.standard_normal((n, k, DOF)) * sigma
    return y, n_eff, err, sigma


def _call(y=None, n_eff=None, err=None, sigma=None, cand=None, ctrl=None, **kw):
    by, bn, be, bs = _inputs()
    cand = np.full(N, 0.5) if cand is None else cand
    ctrl = np.ones(N) if ctrl is None else ctrl
    return evaluate_scenario_gate(
        by if y is None else y,
        bn if n_eff is None else n_eff,
        be if err is None else err,
        bs if sigma is None else sigma,
        cand,
        ctrl,
        **kw,
    )


def _ratios(better: int, bad: float = 1.2, good: float = 0.5) -> np.ndarray:
    return np.array([good] * better + [bad] * (N - better))


# ------------------------------------------------------------------------------------------ known answers


def test_a_consistent_scenario_with_a_useful_vision_passes_every_condition():
    result = _call()
    assert isinstance(result, ScenarioGateResult)
    assert [c.passed for c in result.conditions] == [True] * 6
    assert result.passed
    assert result.n_runs == N


def test_y_four_times_too_high_fails_u_only():
    y, *_ = _inputs()
    result = _call(y=4.0 * y)
    assert not result.upper.passed and not result.passed
    assert result.lower.passed and result.coverage.passed and result.better.passed


def test_y_five_times_too_low_fails_l_only():
    y, *_ = _inputs()
    result = _call(y=0.2 * y)
    assert not result.lower.passed and not result.passed
    assert result.upper.passed and result.coverage.passed


def test_a_claimed_sigma_that_is_too_small_fails_c_only():
    _, _, _, sigma = _inputs()
    result = _call(sigma=0.5 * sigma)
    assert not result.coverage.passed and not result.passed
    assert result.upper.passed and result.lower.passed


# --------------------------------------------------------------------------------------------------- (U)


def test_u_is_the_ninetieth_percentile_with_linear_interpolation():
    y = np.arange(25, dtype=float)  # sorted 0..24, so the linear 90th percentile is at index 21.6
    result = _call(y=y)
    assert result.upper.value == pytest.approx(21.6)
    assert result.upper.value != 22.0 and result.upper.value != 21.0  # not 'higher' or 'lower'
    assert result.upper.value == float(np.percentile(y, 90.0, method="linear"))


def test_u_threshold_is_chi_square_over_m_with_m_the_median_n_eff():
    n_eff = np.concatenate([np.full(13, 10.0), np.full(12, 40.0)])  # median 10
    result = _call(n_eff=n_eff)
    assert result.m == 10.0
    assert result.upper.threshold == chi2_ppf(cg.CANDIDATE_GATE_UPPER_QUANTILE, DOF * 10.0) / 10.0
    assert result.upper.relation == "<="


def test_m_is_at_least_one_and_a_non_integer_degrees_of_freedom_is_not_floored():
    result = _call(n_eff=np.full(N, 0.2))
    assert result.m == 1.0
    assert result.upper.threshold == chi2_ppf(cg.CANDIDATE_GATE_UPPER_QUANTILE, DOF * 1.0) / 1.0
    result = _call(n_eff=np.full(N, 2.5))
    assert result.m == 2.5
    assert result.upper.threshold == chi2_ppf(cg.CANDIDATE_GATE_UPPER_QUANTILE, 7.5) / 2.5  # 7.5, not 7


def test_u_uses_the_quantile_it_is_given_and_a_higher_one_is_a_looser_edge():
    low = _call(upper_quantile=0.975).upper.threshold
    high = _call(upper_quantile=0.995).upper.threshold
    assert high > low


def test_u_boundary_is_inclusive():
    y = np.full(N, 2.0)
    m = 20.0
    edge = chi2_ppf(cg.CANDIDATE_GATE_UPPER_QUANTILE, DOF * m) / m
    assert _call(y=np.full(N, edge)).upper.passed
    assert not _call(y=np.full(N, edge * (1.0 + 1e-9))).upper.passed
    assert _call(y=y).upper.passed


# --------------------------------------------------------------------------------------------------- (L)


def test_l_is_the_median_and_its_boundary_is_inclusive():
    floor = cg.CANDIDATE_GATE_LOWER_PER_DOF * DOF
    assert _call(y=np.full(N, floor)).lower.passed
    assert not _call(y=np.full(N, floor * (1.0 - 1e-9))).lower.passed
    assert _call(y=np.full(N, floor)).lower.threshold == floor


def test_l_is_a_median_so_a_few_low_runs_do_not_decide_it():
    y = np.concatenate([np.full(12, 0.1), np.full(13, 3.0)])  # the mean (1.6) and the median (3.0) differ
    assert _call(y=y).lower.value == 3.0
    y = np.concatenate([np.full(13, 0.1), np.full(12, 3.0)])
    assert _call(y=y).lower.value == 0.1 and not _call(y=y).lower.passed


# --------------------------------------------------------------------------------------------------- (C)


def test_c_counts_triples_and_its_boundary_is_inclusive():
    y, n_eff, err, sigma = _inputs()
    sigma = np.ones_like(sigma)
    err = np.full_like(err, 2.0)
    assert _call(y=y, n_eff=n_eff, err=err, sigma=sigma).coverage.value == 1.0
    err[:, : K // 2, 0] = 2.0 + 1e-9
    assert _call(y=y, n_eff=n_eff, err=err, sigma=sigma).coverage.value == pytest.approx(1.0 - 1.0 / 6.0)
    assert _call(y=y, n_eff=n_eff, err=-err, sigma=sigma).coverage.value == pytest.approx(1.0 - 1.0 / 6.0)


# --------------------------------------------------------------------------------------------------- (P)


@pytest.mark.parametrize(("better", "passes"), [(20, True), (19, False), (25, True), (0, False)])
def test_the_better_count_is_at_least_eighty_percent_of_n(better, passes):
    result = _call(cand=_ratios(better))
    assert result.better.value == better and result.better.threshold == 20
    assert result.better.passed is passes


def test_a_tie_is_not_lower():
    cand = np.array([0.5] * 19 + [1.0] * 6)
    assert _call(cand=cand).better.value == 19


def test_the_median_ratio_boundary():
    at = np.array([0.5] * 7 + [0.8] * 13 + [1.2] * 5)
    over = np.array([0.5] * 7 + [0.81] * 13 + [1.2] * 5)
    assert _call(cand=at).median_ratio.value == 0.8 and _call(cand=at).median_ratio.passed
    assert _call(cand=over).median_ratio.value == 0.81 and not _call(cand=over).median_ratio.passed


def test_the_worst_ratio_boundary():
    at, over = _ratios(20, bad=1.5), _ratios(20, bad=1.51)
    assert _call(cand=at).worst_ratio.value == 1.5 and _call(cand=at).worst_ratio.passed
    assert _call(cand=over).worst_ratio.value == 1.51 and not _call(cand=over).worst_ratio.passed
    assert _call(cand=at).passed and not _call(cand=over).passed


def test_the_ratio_is_candidate_over_control():
    r = _call(cand=np.full(N, 3.0), ctrl=np.full(N, 4.0))
    assert r.median_ratio.value == pytest.approx(0.75) and r.worst_ratio.value == pytest.approx(0.75)


# ----------------------------------------------------------------------------------------- both scenarios


def test_a_candidate_passes_only_if_both_scenarios_pass():
    y, *_ = _inputs()
    good, bad = _call(), _call(y=4.0 * y)
    assert evaluate_candidate_gate(good, good).passed
    assert not evaluate_candidate_gate(good, bad).passed
    assert not evaluate_candidate_gate(bad, good).passed
    assert not evaluate_candidate_gate(bad, bad).passed


def test_the_combined_result_keeps_both_scenarios_and_is_frozen():
    good = _call()
    combined = evaluate_candidate_gate(good, good)
    assert isinstance(combined, CandidateGateResult)
    assert combined.s1 is good and combined.s2 is good
    with pytest.raises(AttributeError):
        combined.passed = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        good.passed = False  # type: ignore[misc]


def test_the_scenario_result_lists_its_six_conditions_in_order():
    assert [c.name for c in _call().conditions] == [
        "upper",
        "lower",
        "coverage",
        "better",
        "median_ratio",
        "worst_ratio",
    ]


# ---------------------------------------------------------------------------------------- the constants


def test_the_thresholds_are_the_adr_constants():
    assert cg.CANDIDATE_GATE_PERCENTILE == 90.0
    assert cg.CANDIDATE_GATE_LOWER_PER_DOF == 0.44
    assert cg.CANDIDATE_GATE_COVERAGE_SIGMA == 2.0 and cg.CANDIDATE_GATE_COVERAGE_MIN == 0.95
    assert cg.CANDIDATE_GATE_BETTER_FRACTION_MIN == 0.8
    assert cg.CANDIDATE_GATE_MEDIAN_RATIO_MAX == 0.8 and cg.CANDIDATE_GATE_WORST_RATIO_MAX == 1.5
    assert cg.CANDIDATE_GATE_RUNS == 25


def test_the_shared_thresholds_equal_those_of_the_first_gate():
    """ADR-0030 replaces conditions (1) and (2) of ADR-0028 and keeps the rest; the numbers must not drift apart."""
    assert cg.CANDIDATE_GATE_LOWER_PER_DOF == b1.B1_LOWER_BOUND_PER_DOF
    assert cg.CANDIDATE_GATE_COVERAGE_SIGMA == b1.B1_COVERAGE_SIGMA
    assert cg.CANDIDATE_GATE_COVERAGE_MIN == b1.B1_COVERAGE_MIN
    assert cg.CANDIDATE_GATE_BETTER_FRACTION_MIN == b1.B1_BETTER_FRACTION_MIN
    assert cg.CANDIDATE_GATE_MEDIAN_RATIO_MAX == b1.B1_MEDIAN_RATIO_MAX
    assert cg.CANDIDATE_GATE_WORST_RATIO_MAX == b1.B1_WORST_RATIO_MAX


def test_the_first_gate_is_unchanged():
    assert callable(b1.evaluate_b1_gate)
    assert b1.B1_BAND_UPPER_QUANTILE == 0.975


# --------------------------------------------------------------------------------------------- inputs


def test_bad_input_is_refused():
    y, n_eff, err, sigma = _inputs(n=3)
    cand, ctrl = np.full(3, 0.5), np.ones(3)
    with pytest.raises(ValueError, match="two runs"):
        evaluate_scenario_gate(y[:1], n_eff[:1], err[:1], sigma[:1], cand[:1], ctrl[:1])
    with pytest.raises(ValueError, match="shape"):
        evaluate_scenario_gate(y, n_eff[:2], err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_scenario_gate(y, n_eff, err[:, :-1], sigma, cand, ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_scenario_gate(y, n_eff, err, sigma[:2], cand, ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_scenario_gate(y, n_eff, err, sigma, cand[:2], ctrl)
    with pytest.raises(ValueError, match="finite"):
        bad = y.copy()
        bad[0] = np.nan
        evaluate_scenario_gate(bad, n_eff, err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="negative"):
        evaluate_scenario_gate(-y, n_eff, err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="positive"):
        evaluate_scenario_gate(y, np.zeros(3), err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="positive"):
        evaluate_scenario_gate(y, n_eff, err, sigma, cand, np.zeros(3))
    with pytest.raises(ValueError, match="quantile"):
        evaluate_scenario_gate(y, n_eff, err, sigma, cand, ctrl, upper_quantile=1.0)
