"""Tests for uncertainty calibration and the chi-square reference it relies on.

The statistical functions are tested against published quantiles rather than
against their own output, because a self-consistent but wrong distribution
function would pass a round-trip test. The distributional properties (coverage,
conformal validity) are tested with a fixed seed and deliberately loose
tolerances, since they are statements about a sample rather than a value.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from navkit.eval.calibration import (
    MahalanobisSeries,
    conformal_radius,
    coverage_report,
    inflation_factor,
    normalized_error_squared,
    shift_sensitivity,
    wilson_interval,
)
from navkit.eval.statistics import chi2_cdf, chi2_ppf, ellipsoid_coverage, ellipsoid_sigma

# Published 95% chi-square quantiles, scipy.stats.chi2.ppf(0.95, dof).
CHI2_95 = {
    1: 3.841458820694124,
    2: 5.991464547107980,
    3: 7.814727903251179,
    4: 9.487729036781029,
    5: 11.070497693516351,
    10: 18.307038053275146,
    20: 31.410432844230918,
}


@pytest.mark.parametrize(("dof", "expected"), sorted(CHI2_95.items()))
def test_chi2_ppf_matches_published_quantiles(dof: int, expected: float) -> None:
    assert chi2_ppf(0.95, dof) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("dof", sorted(CHI2_95))
def test_chi2_cdf_inverts_its_own_ppf(dof: int) -> None:
    for q in (0.5, 0.9, 0.95, 0.99):
        assert chi2_cdf(chi2_ppf(q, dof), dof) == pytest.approx(q, abs=1e-12)


def test_chi2_cdf_at_zero_and_negative_is_zero() -> None:
    assert chi2_cdf(0.0, 3) == 0.0
    assert chi2_cdf(-1.0, 3) == 0.0


@pytest.mark.parametrize("bad", [0, -1])
def test_chi2_rejects_non_positive_degrees_of_freedom(bad: int) -> None:
    with pytest.raises(ValueError):
        chi2_cdf(1.0, bad)
    with pytest.raises(ValueError):
        chi2_ppf(0.95, bad)


@pytest.mark.parametrize("q", [0.0, 1.0, -0.1, 1.5])
def test_chi2_ppf_rejects_probabilities_outside_the_open_unit_interval(q: float) -> None:
    with pytest.raises(ValueError):
        chi2_ppf(q, 3)


def test_ellipsoid_coverage_quantifies_the_per_axis_shorthand() -> None:
    # The point of the module: per-axis sigma and coverage are not the same
    # number, and the gap is large enough to change a decision.
    assert ellipsoid_coverage(1.0, 3) == pytest.approx(0.608381, abs=1e-5)
    assert ellipsoid_coverage(3.0, 3) > 0.999
    # A one-dimensional 1.96-sigma interval really is about 95%.
    assert ellipsoid_coverage(1.959963985, 1) == pytest.approx(0.95, abs=1e-5)
    assert ellipsoid_coverage(0.0, 3) == 0.0


@pytest.mark.parametrize("coverage", [0.5, 0.9, 0.95, 0.99])
def test_ellipsoid_sigma_inverts_coverage(coverage: float) -> None:
    assert ellipsoid_coverage(ellipsoid_sigma(coverage, 3), 3) == pytest.approx(
        coverage, abs=1e-12
    )


def test_wilson_interval_brackets_the_estimate_and_stays_in_range() -> None:
    for successes, trials in ((0, 400), (380, 400), (200, 400), (400, 400), (7, 10)):
        lo, hi = wilson_interval(successes, trials)
        assert 0.0 <= lo <= successes / trials <= hi <= 1.0
    # The whole point of preferring Wilson over the normal approximation: with no
    # successes out of many trials the upper bound must be small, not ~0.5.
    lo, hi = wilson_interval(0, 400)
    assert hi < 0.02
    assert wilson_interval(0, 0) == (0.0, 1.0)


def _synthetic_gaussian(n: int = 4000, scale: float = 1.0, seed: int = 11) -> MahalanobisSeries:
    """Errors drawn from N(0, scale**2 I) against a covariance of I."""
    rng = np.random.default_rng(seed)
    err = rng.standard_normal((n, 3)) * scale
    return normalized_error_squared(err, np.zeros((n, 3)), np.tile(np.eye(3), (n, 1, 1)))


def test_normalized_error_squared_of_a_correct_gaussian_averages_to_its_dof() -> None:
    series = _synthetic_gaussian()
    assert series.dof == 3
    assert series.epochs == 4000
    # Mean of chi2_3 is 3; 4000 samples put the standard error near 0.05.
    assert series.mean_squared() == pytest.approx(3.0, abs=0.2)


def test_normalized_error_squared_detects_a_tenfold_overconfident_covariance() -> None:
    series = _synthetic_gaussian(scale=10.0)
    assert series.mean_squared() == pytest.approx(300.0, rel=0.1)


def test_normalized_error_squared_handles_a_singular_covariance_block() -> None:
    # A direction collapsed to zero variance must not produce inf or nan, and the
    # epoch must stay visible rather than being silently dropped.
    cov = np.tile(np.eye(3), (3, 1, 1))
    cov[:, 0, 0] = 0.0
    err = np.zeros((3, 3))
    err[0] = (1.0, 0.0, 0.0)
    series = normalized_error_squared(err, np.zeros((3, 3)), cov)
    assert np.all(np.isfinite(series.squared))
    assert series.squared[0] > 1e11
    assert series.squared[1] == pytest.approx(0.0)


def test_normalized_error_squared_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        normalized_error_squared(np.zeros((4, 3)), np.zeros((3, 3)), np.tile(np.eye(3), (4, 1, 1)))


def test_normalized_error_squared_of_an_empty_sequence_is_empty_not_an_error() -> None:
    series = normalized_error_squared(np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3, 3)))
    assert series.epochs == 0
    assert math.isnan(series.mean_squared())


def test_coverage_report_agrees_with_expectation_for_a_correct_filter() -> None:
    report = coverage_report(_synthetic_gaussian())
    assert report.epochs == 4000
    assert report.mean_normalised_error == pytest.approx(3.0, abs=0.2)
    for point in report.points:
        assert point.observed == pytest.approx(point.expected, abs=0.02)
        assert point.verdict == "calibrated"
    assert report.at(1.0) is not None
    assert report.at(1.5) is None


def test_coverage_report_calls_an_overconfident_filter_out() -> None:
    # Covariance claims 1 m; the error is really 4 m in every direction.
    series = _synthetic_gaussian(scale=4.0)
    report = coverage_report(series)
    two_sigma = report.at(2.0)
    assert two_sigma is not None
    # The claimed radius is 2**2 * 3 = 12 in squared Mahalanobis units, but the
    # true error is 4x, so only squared distances below 12 / 16 count. The
    # expectation is a chi-square value, not a number typed in by hand.
    expected = chi2_cdf(12.0 / 16.0, 3)
    assert 0.13 < expected < 0.15
    assert two_sigma.observed == pytest.approx(expected, abs=0.02)
    assert two_sigma.expected == pytest.approx(0.9926, abs=1e-3)
    assert two_sigma.gap < -0.85
    assert two_sigma.verdict == "overconfident"


def test_inflation_factor_recovers_a_known_scale_error() -> None:
    assert inflation_factor(_synthetic_gaussian(scale=1.0), 0.95) == pytest.approx(1.0, abs=0.1)
    assert inflation_factor(_synthetic_gaussian(scale=3.0), 0.95) == pytest.approx(3.0, abs=0.3)
    assert inflation_factor(_synthetic_gaussian(scale=0.5), 0.95) == pytest.approx(0.5, abs=0.1)


def test_inflation_factor_of_an_empty_series_is_not_a_number() -> None:
    empty = MahalanobisSeries(squared=np.zeros(0), radius=np.zeros(0), dof=3)
    assert math.isnan(inflation_factor(empty, 0.95))


def test_conformal_radius_uses_the_finite_sample_order_statistic() -> None:
    n = 100
    calibration = _synthetic_gaussian(n=n, seed=5)
    bound = conformal_radius(calibration, 0.95)
    # ceil((n + 1) * 0.95) = 96, so the bound is the 96th smallest of 100 radii.
    assert bound["index"] == 96
    assert bound["certified"] == 1.0
    assert bound["radius"] == pytest.approx(float(np.sort(calibration.radius)[95]))
    # The plain 0.95 quantile would be the 95th value and would void the guarantee.
    assert bound["radius"] > float(np.quantile(calibration.radius, 0.95, method="higher")) - 1e-12


def test_conformal_radius_refuses_to_certify_an_unreachable_confidence() -> None:
    calibration = _synthetic_gaussian(n=10, seed=5)
    bound = conformal_radius(calibration, 0.999)
    assert bound["index"] == 11
    assert bound["certified"] == 0.0
    assert math.isinf(bound["radius"])


def test_conformal_bound_is_wider_than_the_nominal_gaussian_bound() -> None:
    bound = conformal_radius(_synthetic_gaussian(n=500, seed=9), 0.95)
    assert bound["radius"] > bound["nominal_radius"]


def test_shift_sensitivity_flags_a_bound_that_stops_holding() -> None:
    calibration = _synthetic_gaussian(n=2000, seed=3)
    same = _synthetic_gaussian(n=2000, seed=4)
    worse = _synthetic_gaussian(n=2000, scale=3.0, seed=4)
    held = shift_sensitivity(calibration, same, 0.95)
    shifted = shift_sensitivity(calibration, worse, 0.95)
    assert held["deficit"] == pytest.approx(0.0, abs=0.03)
    # A 3x error inflation shrinks realised coverage to the chi-square mass below
    # (1/3) of the nominal radius, which is a small number, not zero.
    assert shifted["realised_coverage"] == pytest.approx(0.18, abs=0.06)
    assert shifted["deficit"] > 0.75
    assert shifted["realised_coverage"] < 0.30


def test_shift_sensitivity_of_an_uncertifiable_bound_is_not_a_number() -> None:
    tiny = MahalanobisSeries(squared=np.zeros(3), radius=np.zeros(3), dof=3)
    out = shift_sensitivity(tiny, _synthetic_gaussian(n=10), 0.99)
    assert math.isnan(out["realised_coverage"])


# --- large degrees of freedom ------------------------------------------------
#
# A NEES test over a long run asks for chi2 quantiles at n*dof, which for a
# 3000-epoch sequence is 9000. The original implementation formed `t**a`
# directly and raised OverflowError there, so these pin the fix.


@pytest.mark.parametrize("dof", [900, 9000, 30000])
def test_chi2_ppf_survives_large_degrees_of_freedom(dof: int) -> None:
    q = chi2_ppf(0.975, dof)
    assert np.isfinite(q)
    assert chi2_cdf(q, dof) == pytest.approx(0.975, abs=1e-6)


def test_chi2_median_is_close_to_the_degrees_of_freedom() -> None:
    assert chi2_ppf(0.5, 9000) == pytest.approx(9000.0, rel=1e-3)


def test_chi2_tail_stays_flat_for_an_extreme_argument() -> None:
    assert chi2_cdf(1e9, 3) == pytest.approx(1.0)
    assert chi2_cdf(1e-9, 3) == pytest.approx(0.0, abs=1e-9)


def test_chi2_cdf_is_monotone_in_both_arguments() -> None:
    for dof in (1, 3, 50, 9000):
        xs = np.geomspace(1e-3, 1e3, 40)
        vals = [chi2_cdf(x, dof) for x in xs]
        assert all(a <= b + 1e-12 for a, b in zip(vals, vals[1:]))


# --- bulk vs tail verdicts ---------------------------------------------------
#
# A single calibration boolean is not enough: the two diagnostics below detect
# different failure modes and genuinely disagree for a mildly miscalibrated
# filter. Reporting only one of them hides half the evidence.


def _report(mean_nees: float, covered_at_2sigma: float, epochs: int = 3000):
    from navkit.eval.calibration import CoveragePoint, CoverageReport, CalibrationReport

    cov = CoverageReport(
        points=(
            CoveragePoint(sigma_per_axis=2.0, covered=int(covered_at_2sigma * epochs), epochs=epochs),
        ),
        mean_normalised_error=mean_nees,
        dof=3,
    )
    return CalibrationReport(
        estimator="eskf", scenario="s", coverage=cov, inflation_to_95=1.0, conformal={}
    )


def test_high_nees_is_overconfident() -> None:
    """NEES above dof means the errors exceed the claimed covariance."""
    assert _report(1000.0, 0.16).bulk_verdict == "overconfident"


def test_low_nees_is_underconfident() -> None:
    assert _report(0.01, 1.0).bulk_verdict == "underconfident"


def test_nees_at_the_expectation_is_calibrated() -> None:
    assert _report(3.0, 0.992).bulk_verdict == "calibrated"


def test_bulk_and_tail_can_disagree_and_the_report_says_so() -> None:
    """Marginally overconfident everywhere, yet never escapes 2 sigma.

    Collapsing this to one word would either blame the tail, which is clean, or
    the bulk, which is only slightly off, and would lose the actual shape of the
    error distribution.
    """
    rep = _report(3.74, 1.0)
    assert rep.bulk_verdict == "overconfident"
    assert rep.tail_verdict == "underconfident"
    assert rep.verdict == "mixed(bulk=overconfident, tail=underconfident)"
    assert rep.calibrated is False


def test_agreeing_bulk_and_tail_give_a_plain_verdict() -> None:
    rep = _report(3.0, 0.992)
    assert rep.verdict == "calibrated"
    assert rep.calibrated is True


def test_a_firmly_overconfident_filter_is_not_called_mixed() -> None:
    rep = _report(1000.0, 0.16)
    assert rep.verdict == "overconfident"
    assert rep.calibrated is False


def test_calibrated_requires_both_diagnostics_to_pass() -> None:
    """A filter that passes only the tail test is not calibrated."""
    assert _report(3.74, 1.0).calibrated is False
    assert _report(3.0, 0.992).calibrated is True


def test_no_epochs_is_insufficient_data_not_a_verdict() -> None:
    rep = _report(float("nan"), 0.0, epochs=0)
    assert rep.bulk_verdict == "insufficient_data"
    assert rep.calibrated is False


def test_report_dict_exposes_both_verdicts_and_the_nees_pair() -> None:
    d = _report(3.74, 1.0).as_dict()
    assert d["bulk_verdict"] == "overconfident"
    assert d["tail_verdict"] == "underconfident"
    assert d["mean_nees"] == pytest.approx(3.74)
    assert d["expected_nees"] == 3
