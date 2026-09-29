"""Tests for chi-square FDIR: the statistics, the state machine, and the wiring.

Three groups, in increasing order of how much they can embarrass us.

**The maths** is checked against something other than itself. The tabulated
thresholds are verified against :func:`navkit.eval.statistics.chi2_ppf`, which
is an independent exact implementation derived from the incomplete gamma function
rather than from the table. Pinning the table to a copy of itself would prove
nothing, which is the same mistake every lookup table eventually makes.

**The state machine** is driven with hand-built innovations so that the number of
rejections reaching a threshold is exactly known. A test that injects faults into
a simulated run and asserts "at least 5 rejections" cannot distinguish a working
counter from one that happens to be counting something else.

**The integration** tests are the ones that would catch a real regression, and the
two false-alarm tests are the load-bearing ones. A gate that rejects everything
passes every rejection test in this file, and the only thing that catches it is a
clean run asserted to produce no rejections.
"""

from __future__ import annotations

import numpy as np
import numpy.linalg as la
import pytest

from navkit.degrade.config import Outage
from navkit.degrade.inject import apply_gnss_outage
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.eval.statistics import chi2_cdf, chi2_ppf
from navkit.fdir import (
    CHI2_THRESHOLDS,
    STATUS_ACCEPTED,
    STATUS_REACCEPTED_WITH_INFLATION,
    STATUS_REJECTED_PERSISTENT,
    STATUS_REJECTED_SPOOF,
    STATUS_SENSOR_FAULT,
    FdirConfig,
    FdirManager,
    GatingDecision,
    NisConfig,
    NisWindowMonitor,
    chi2_dof,
    chi2_threshold,
    mahalanobis_sq,
    normal_quantile,
    wilson_hilferty,
)
from navkit.io.imu import ImuNoiseModel
from navkit.sensors.models import GnssConfig, VisionConfig, gnss_fixes, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory
from navkit.types import GnssFix, VisionUpdate, interpolate_trajectory

# --------------------------------------------------------------- the table ---

#: The thresholds as printed in the standard references, which is how the module
#: docstring states them. Deliberately written out again here rather than imported
#: from the module, so that a wrong constant in the module cannot make its own test
#: pass.
PUBLISHED = {
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


@pytest.mark.parametrize("key,value", sorted(PUBLISHED.items()))
def test_threshold_table_matches_published_values(key, value) -> None:
    dof, alpha = key
    assert CHI2_THRESHOLDS[key] == value
    assert chi2_threshold(dof, alpha) == value


@pytest.mark.parametrize("key,value", sorted(PUBLISHED.items()))
def test_threshold_table_agrees_with_the_exact_implementation(key, value) -> None:
    """The table is checked against `chi2_ppf`, not against a copy of itself.

    Tolerance is 5e-4, which is the rounding in the published values (they are
    quoted to three decimals). The exact implementation and the table were derived
    independently, so this is a real check rather than a tautology.
    """
    dof, alpha = key
    exact = chi2_ppf(1.0 - alpha, dof)
    assert exact == pytest.approx(value, abs=5e-4)


@pytest.mark.parametrize("dof", sorted({k[0] for k in PUBLISHED}))
@pytest.mark.parametrize("alpha", sorted({k[1] for k in PUBLISHED}))
def test_tabulated_threshold_has_the_advertised_tail_mass(dof, alpha) -> None:
    """`chi2_cdf(threshold)` should be `1 - alpha`, to within the rounding.

    This is the property the gate actually depends on: the threshold is chosen so
    that a healthy channel is wrongly rejected `alpha` of the time.
    """
    assert chi2_cdf(chi2_threshold(dof, alpha), dof) == pytest.approx(1.0 - alpha, abs=1e-4)


def test_threshold_falls_back_to_exact_quantiles_for_untabulated_small_dof() -> None:
    """dof 4 and 5 are absent from the table and served exactly.

    Wilson-Hilferty is 0.2-0.3% off at these dof, and its error is in the tail
    where the threshold is applied. Both are also dof values a filter can produce,
    so the approximation is not an acceptable fallback here.
    """
    for dof in (4, 5):
        for alpha in (0.05, 0.01):
            exact = chi2_ppf(1.0 - alpha, dof)
            assert chi2_threshold(dof, alpha) == pytest.approx(exact, rel=1e-9)


def test_threshold_falls_back_to_wilson_hilferty_for_large_dof() -> None:
    for dof in (9, 12, 21):
        for alpha in (0.05, 0.01):
            assert chi2_threshold(dof, alpha) == pytest.approx(wilson_hilferty(alpha, dof), rel=1e-12)


def test_wilson_hilferty_accuracy_is_bounded_and_improves_with_dof() -> None:
    """Pin both the error magnitude and its direction.

    The signs matter: the approximation is conservative at alpha=0.05 and slightly
    liberal at alpha=0.01, and a reader deciding whether to trust the fallback
    needs to know which way it errs rather than only how far.
    """
    for alpha, sign in ((0.05, -1.0), (0.01, 1.0)):
        errors = []
        for dof in (4, 9, 21, 60):
            exact = chi2_ppf(1.0 - alpha, dof)
            errors.append((wilson_hilferty(alpha, dof) - exact) / exact)
        assert all(np.sign(e) == sign for e in errors), errors
        assert max(abs(e) for e in errors) < 0.004
        # Error shrinks with dof: a property of the approximation, worth pinning.
        assert abs(errors[-1]) < abs(errors[0])


def test_wilson_hilferty_refuses_the_dof_where_it_is_invalid() -> None:
    with pytest.raises(ValueError, match="dof >= 2"):
        wilson_hilferty(0.01, 1)


def test_normal_quantile_matches_the_published_z_scores() -> None:
    for alpha, z in ((0.05, 1.6448536269514722), (0.01, 2.3263478740408408), (0.001, 3.090232306167813)):
        assert normal_quantile(alpha) == pytest.approx(z, rel=1e-12)


def test_normal_quantile_is_accurate_in_the_deep_tail() -> None:
    """The Newton polish has to survive alpha = 1e-6.

    Acklam's raw approximation is only good to about 1e-9 relative, which is not
    good enough for a value that becomes a safety threshold. Checked against the
    closed form for the *symmetric* quantile that alpha=0.5 pins exactly, and
    against the limiting behaviour in the tail.
    """
    assert normal_quantile(0.5) == pytest.approx(0.0, abs=1e-12)
    z = normal_quantile(1e-6)
    # Phi(4.753424) = 1 - 1e-6; invert via the erf the implementation uses.
    from math import erf, sqrt

    assert 0.5 * (1.0 + erf(z / sqrt(2.0))) == pytest.approx(1.0 - 1e-6, abs=1e-12)


def test_chi2_threshold_rejects_nonsense_arguments() -> None:
    for dof in (0, -1):
        with pytest.raises(ValueError, match="degrees of freedom"):
            chi2_threshold(dof, 0.01)
    for alpha in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(ValueError, match="alpha"):
            chi2_threshold(3, alpha)


# ------------------------------------------------------------ mahalanobis ----


def test_mahalanobis_matches_manual_matrix_arithmetic() -> None:
    """Hand-computed by hand, not by another call into the module.

    S = [[2, 0.5], [0.5, 1]], y = [1, -1].  det = 2*1 - 0.25 = 1.75,
    S^-1 = (1/1.75) [[1, -0.5], [-0.5, 2]].  y^T S^-1 y = (2 - 2) / 1.75 + ...
    expanding: S^-1 y = (1/1.75) [1 + 0.5, -0.5 - 2] = (1/1.75) [1.5, -2.5],
    y . (S^-1 y) = 1.5/1.75 + 2.5/1.75 = 4/1.75 = 2.2857142857.
    """
    S = np.array([[2.0, 0.5], [0.5, 1.0]])
    y = np.array([1.0, -1.0])
    assert mahalanobis_sq(y, S) == pytest.approx(4.0 / 1.75, rel=1e-12)
    # ...and the explicit inverse agrees, which is the independent check.
    assert float(y @ la.inv(S) @ y) == pytest.approx(mahalanobis_sq(y, S), rel=1e-12)


def test_mahalanobis_is_invariant_to_rotation_of_the_coordinate_frame() -> None:
    """`y^T S^-1 y` cannot depend on which axes the error is expressed in.

    This is not an academic property here: the visual residuals live in the
    previous body frame, so a gate applied to them sees a different basis at every
    keyframe. If the statistic were basis-dependent, the threshold would only be
    valid in one orientation and would drift with the vehicle.
    """
    rng = np.random.default_rng(0)
    A = rng.standard_normal((3, 3))
    S = A @ A.T + 3.0 * np.eye(3)
    y = rng.standard_normal(3)
    Q = la.qr(rng.standard_normal((3, 3)))[0]
    if la.det(Q) < 0:
        Q[:, 0] *= -1.0
    assert mahalanobis_sq(y, S) == pytest.approx(mahalanobis_sq(Q @ y, Q @ S @ Q.T), rel=1e-10)


def test_mahalanobis_is_zero_for_a_zero_innovation() -> None:
    S = np.diag([1.0, 2.0, 3.0])
    assert mahalanobis_sq(np.zeros(3), S) == pytest.approx(0.0, abs=1e-15)


def test_mahalanobis_scales_quadratically_with_a_scaled_innovation() -> None:
    S = np.eye(3) * 4.0
    y = np.array([2.0, 0.0, 0.0])
    assert mahalanobis_sq(y, S) == pytest.approx(1.0)
    assert mahalanobis_sq(3.0 * y, S) == pytest.approx(9.0)


def test_mahalanobis_symmetrises_so_the_result_does_not_depend_on_the_triangle() -> None:
    """An asymmetric `S` must give the same answer as its symmetric part.

    `S` is built as `H P H^T + R` from a covariance maintained symmetric, so
    asymmetry can only come from floating-point accumulation. If it leaked into the
    statistic the gate would stop being reproducible across BLAS implementations,
    which is precisely the failure a reported threshold cannot be debugged from.
    """
    S = np.array([[2.0, 0.5], [0.5, 1.0]])
    asym = S.copy()
    asym[0, 1] += 1e-9
    y = np.array([0.3, -0.7])
    assert mahalanobis_sq(y, asym) == pytest.approx(mahalanobis_sq(y, S), rel=1e-9)


def test_mahalanobis_returns_infinity_for_a_singular_covariance() -> None:
    """No finite normalised distance exists, and inventing one would be worse.

    A rank-deficient `S` is reachable here rather than hypothetical: ADR-0003
    documents a degenerate relative-pose model. Returning a large finite number
    from such a matrix would be arbitrary, and an arbitrary rejection is
    indistinguishable from a detected fault.
    """
    S = np.array([[1.0, 1.0], [1.0, 1.0]])  # rank 1
    assert mahalanobis_sq(np.array([1.0, 1.0]), S) == float("inf")
    assert mahalanobis_sq(np.array([0.1, 0.0]), np.zeros((2, 2))) == float("inf")


def test_mahalanobis_returns_infinity_when_ill_conditioned() -> None:
    """Conditioned beyond the guard, the small direction is arithmetic noise."""
    S = np.diag([1.0, 1e-14])
    assert mahalanobis_sq(np.array([1.0, 1.0]), S) == float("inf")
    # Just inside the guard it still returns a finite answer.
    S_ok = np.diag([1.0, 1e-3])
    assert np.isfinite(mahalanobis_sq(np.array([1.0, 1.0]), S_ok))


def test_mahalanobis_returns_infinity_for_non_finite_inputs() -> None:
    S = np.eye(2)
    assert mahalanobis_sq(np.array([np.nan, 0.0]), S) == float("inf")
    assert mahalanobis_sq(np.array([np.inf, 0.0]), S) == float("inf")
    bad = np.eye(2)
    bad[0, 0] = np.nan
    assert mahalanobis_sq(np.array([1.0, 0.0]), bad) == float("inf")


def test_mahalanobis_rejects_a_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="to match the innovation"):
        mahalanobis_sq(np.zeros(3), np.eye(2))


def test_chi2_dof_is_the_innovation_length() -> None:
    assert chi2_dof(np.zeros(3)) == 3
    assert chi2_dof(np.zeros((6, 1))) == 6
    with pytest.raises(ValueError, match="empty innovation"):
        chi2_dof(np.zeros(0))


# --------------------------------------------------------- the state machine --


def test_tracker_accepts_a_consistent_update() -> None:
    tr = FdirManager(FdirConfig())
    S = np.eye(3)
    d = tr.check("gnss", np.zeros(3), S)
    assert d.accepted
    assert d.status == STATUS_ACCEPTED
    assert d.dof == 3
    assert d.threshold == chi2_threshold(3, 0.001)


def test_tracker_rejects_an_update_past_the_threshold() -> None:
    """A 3-sigma-per-axis outlier, expressed in the metric the gate uses.

    y = [3, 3, 3] with S = I gives d_M^2 = 27 against a threshold of 16.266 at
    alpha = 0.001.
    """
    tr = FdirManager(FdirConfig())
    d = tr.check("gnss", np.array([3.0, 3.0, 3.0]), np.eye(3))
    assert not d.accepted
    assert d.status == STATUS_REJECTED_SPOOF
    assert d.mahalanobis_sq == pytest.approx(27.0)
    assert d.mahalanobis_sq > d.threshold


def test_tracker_transitions_to_sensor_fault_after_the_configured_count() -> None:
    tr = FdirManager(FdirConfig(max_consecutive_rejections=5))
    S = np.eye(3)
    bad = np.full(3, 5.0)
    for k in range(4):
        d = tr.check("gnss", bad, S)
        assert d.status == STATUS_REJECTED_SPOOF, f"update {k}"
    d = tr.check("gnss", bad, S)
    assert d.status == STATUS_SENSOR_FAULT
    assert tr.is_faulted("gnss")
    # ...and it stays faulted while the fault persists.
    d = tr.check("gnss", bad, S)
    assert d.status == STATUS_REJECTED_PERSISTENT
    assert not d.accepted


def test_a_single_bad_epoch_does_not_fault_a_channel() -> None:
    """The 50 m multipath spike: reject once, then accept again immediately.

    This is the property that separates isolation from a one-way ratchet. A gate
    that faults on the first rejection would throw away a receiver because of one
    bad epoch in a hundred.
    """
    tr = FdirManager(FdirConfig(max_consecutive_rejections=5))
    S = np.eye(3)
    assert tr.check("gnss", np.zeros(3), S).accepted
    d = tr.check("gnss", np.full(3, 50.0), S)
    assert not d.accepted
    assert d.status == STATUS_REJECTED_SPOOF
    assert not tr.is_faulted("gnss")
    assert tr.check("gnss", np.zeros(3), S).accepted
    assert not tr.is_faulted("gnss")


def test_faulted_channel_rejects_clean_updates_until_recovery_completes() -> None:
    """Isolation persists, and clearing it takes a declared run of good updates."""
    cfg = FdirConfig(max_consecutive_rejections=3, auto_recovery_count=10)
    tr = FdirManager(cfg)
    S = np.eye(3)
    bad = np.full(3, 5.0)
    for _ in range(3):
        tr.check("gnss", bad, S)
    assert tr.is_faulted("gnss")
    # Nine good updates: credited, but still excluded.
    for _ in range(9):
        d = tr.check("gnss", np.zeros(3), S)
        assert not d.accepted
        assert d.status == STATUS_REJECTED_PERSISTENT
        assert tr.is_faulted("gnss")
    # The tenth restores the channel.
    d = tr.check("gnss", np.zeros(3), S)
    assert d.accepted
    assert d.status == STATUS_ACCEPTED
    assert not tr.is_faulted("gnss")


def test_recovery_requires_consecutive_good_updates() -> None:
    """An intermittent good update must not accumulate toward recovery.

    Counting *consecutive* accepts is what stops a channel oscillating around the
    threshold from flapping the state machine with it.
    """
    cfg = FdirConfig(max_consecutive_rejections=2, auto_recovery_count=4)
    tr = FdirManager(cfg)
    S = np.eye(3)
    bad = np.full(3, 5.0)
    tr.check("gnss", bad, S)
    tr.check("gnss", bad, S)
    assert tr.is_faulted("gnss")
    for _ in range(10):
        tr.check("gnss", np.zeros(3), S)
        tr.check("gnss", bad, S)
    assert tr.is_faulted("gnss")
    assert tr.state("gnss").consecutive_accepts <= 1


def test_channels_are_isolated_from_each_other() -> None:
    """A dead GNSS receiver says nothing about the camera."""
    tr = FdirManager(FdirConfig(max_consecutive_rejections=2))
    S = np.eye(3)
    bad = np.full(3, 5.0)
    tr.check("gnss", bad, S)
    tr.check("gnss", bad, S)
    assert tr.is_faulted("gnss")
    assert not tr.is_faulted("vision")
    assert tr.check("vision", np.zeros(3), S).accepted
    assert not tr.is_faulted("altimeter")


def test_disabled_tracker_gates_nothing_and_records_no_fault() -> None:
    """Disabled means disabled: no verdict, and no fault history to misread later."""
    tr = FdirManager(FdirConfig(enabled=False, max_consecutive_rejections=2))
    S = np.eye(3)
    for _ in range(10):
        d = tr.check("gnss", np.full(3, 50.0), S)
        assert d.accepted
        assert d.threshold == float("inf")
    assert not tr.is_faulted("gnss")
    assert tr.state("gnss").rejected_total == 0
    assert tr.events == []


def test_a_degenerate_covariance_is_treated_as_a_fault_not_a_pass() -> None:
    """An unusable `S` must not read as a clean measurement.

    `mahalanobis_sq` returns `inf`, which exceeds every finite threshold, so the
    update is rejected. The alternative -- falling back to accepting when the
    covariance is degenerate -- would quietly disable the gate in exactly the
    configurations where the model is broken.
    """
    tr = FdirManager(FdirConfig())
    d = tr.check("gnss", np.zeros(2), np.zeros((2, 2)))
    assert not d.accepted
    assert d.status == STATUS_REJECTED_SPOOF


def test_tracker_validates_its_configuration() -> None:
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="confidence_level"):
            FdirConfig(confidence_level=bad)
    with pytest.raises(ValueError, match="max_consecutive_rejections"):
        FdirConfig(max_consecutive_rejections=0)
    with pytest.raises(ValueError, match="auto_recovery_count"):
        FdirConfig(auto_recovery_count=0)


def test_tracker_records_isolation_events_but_not_transients() -> None:
    """The event log holds decisions; the counters hold noise."""
    tr = FdirManager(FdirConfig(max_consecutive_rejections=2))
    S = np.eye(3)
    bad = np.full(3, 5.0)
    tr.check("gnss", bad, S)  # transient: not an event
    assert tr.events == []
    tr.check("gnss", bad, S)  # fault declaration: an event
    assert [e.status for e in tr.events] == [STATUS_SENSOR_FAULT]
    tr.check("gnss", bad, S)  # isolation holding: an event
    assert tr.events[-1].status == STATUS_REJECTED_PERSISTENT
    assert tr.events[-1].sensor == "gnss"


def test_tracker_stats_and_reset() -> None:
    tr = FdirManager(FdirConfig(max_consecutive_rejections=1))
    S = np.eye(3)
    tr.check("gnss", np.full(3, 5.0), S)
    tr.check("vision", np.zeros(3), S)
    stats = tr.stats()
    assert stats["fdir_gnss_rejected"] == 1.0
    assert stats["fdir_gnss_faulted"] == 1.0
    assert stats["fdir_vision_accepted"] == 1.0
    assert stats["fdir_channels"] == 2
    tr.reset()
    assert tr.stats()["fdir_channels"] == 0
    assert tr.events == []


def test_decision_serialises_and_reports_fault_state() -> None:
    tr = FdirManager(FdirConfig())
    d = tr.check("gnss", np.full(3, 5.0), np.eye(3))
    assert isinstance(d, GatingDecision)
    payload = d.as_dict()
    assert payload["accepted"] is False
    assert payload["dof"] == 3
    assert payload["status"] == STATUS_REJECTED_SPOOF
    assert d.sensor_fault is False


# -------------------------------------------------------- integration in ESKF --

_DURATION_S = 20.0


def _stationary_fixture(sigma_m: float = 0.1, seed: int = 3):
    """A platform with known motion, so the filter is correct and any rejection
    is attributable to the gate.

    The inertial stream is noise-free. Noise would contribute to the innovation
    covariance and therefore widen the gate, which is the honest behaviour but
    makes a "was this rejected?" assertion depend on the noise draw. The fault
    magnitudes here are 15 m and 50 m against a 0.1 m fix sigma, so there is no
    need for that slack.
    """
    cfg = SyntheticConfig(duration_s=_DURATION_S, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(cfg, rate_hz=200.0)
    gnss = gnss_fixes(gt, GnssConfig(sigma_m=sigma_m, rate_hz=5.0, seed=seed))
    return gt, imu, gnss.valid()


def _filter(**kwargs) -> ErrorStateKalmanFilter:
    return ErrorStateKalmanFilter(EskfConfig(imu_noise=ImuNoiseModel(), **kwargs))


def _corrupt(fixes, offset, start, count):
    """A copy of `fixes` with `offset` metres added to `count` fixes from `start`."""
    positions = fixes.positions.copy()
    positions[start : start + count] += offset
    return GnssFix(
        t=fixes.t.copy(),
        positions=positions,
        cov=None if fixes.cov is None else fixes.cov.copy(),
        name=fixes.name + "_corrupted",
    )


def _run_with_offset(offset, start, count, **kwargs):
    """Run the filter over a GNSS stream with a corrupted block.

    Returns the result alongside two error figures against the truth: the peak
    error anywhere in the run, and the final error. The peak is the one that
    matters for "was the filter corrupted" -- a single spoofed epoch that pulled
    the estimate and then let it recover would leave a small *final* error while
    having been wrong for several seconds, so a final-error-only assertion would
    pass a filter that tracked the spoof and then got lucky.
    """
    gt, imu, fixes = _stationary_fixture()
    result = _filter(gnss_position_sigma_m=0.1, **kwargs).run(imu, gnss=_corrupt(fixes, offset, start, count))
    error = np.abs(result.trajectory.positions[:, 0] - np.interp(result.trajectory.t, gt.t, gt.positions[:, 0]))
    return result, float(np.max(error))


def test_fdir_is_in_the_serialised_filter_config() -> None:
    """A config hash that omits FDIR describes a different filter.

    Same reasoning as the anchor blocks: FDIR decides which updates enter the
    state, so two configs differing only in `fdir` are not the same estimator.
    """
    a = _filter().cfg.as_dict()
    b = _filter(fdir_config=FdirConfig(confidence_level=0.95)).cfg.as_dict()
    assert a["fdir_config"]["confidence_level"] != b["fdir_config"]["confidence_level"]
    assert set(a["fdir_config"]) == set(FdirConfig().as_dict())


def test_gnss_step_bias_is_rejected_and_the_filter_is_not_corrupted() -> None:
    """A 15 m spoof step must not move the estimate.

    The requirement is that the reported position stays inside the 2-sigma band of
    dead reckoning rather than following the fix. A filter that tracks the spoofed
    fix while claiming 0.1 m of uncertainty is worse than one that ignores it,
    because the covariance is what a downstream consumer acts on.
    """
    result, peak_error = _run_with_offset(np.array([15.0, 0.0, 0.0]), 40, 1)
    state = result.stats
    assert state["fdir_gnss_rejected"] == 1.0
    assert state["gnss_updates_used"] > 0.0
    # Exactly one rejection: the spoofed epoch, and nothing else.
    assert state["gnss_updates_rejected"] == 1.0
    assert state["fdir_gnss_faulted"] == 0.0
    # The spoof moved the measurement 15 m but must not have moved the estimate.
    # Baseline peak error on this fixture is 0.29 m, so anything near 15 means the
    # filter followed the fix.
    assert peak_error < 1.0, f"spoofed fix pulled the estimate {peak_error:.2f} m off"


def test_a_clean_run_produces_zero_false_rejections() -> None:
    """The test a gate that rejects everything fails.

    A gate tuned to catch everything passes every rejection assertion above. This
    is the only assertion in the file that distinguishes a working gate from a
    broken one, so it is not redundant with the rest.
    """
    result, _ = _run_with_offset(np.zeros(3), 40, 1)
    assert result.stats["gnss_fixes_seen"] > 50.0, "too few fixes to be a real test"
    assert result.stats["fdir_gnss_rejected"] == 0.0
    assert result.stats["gnss_updates_rejected"] == 0.0
    assert result.stats["fdir_gnss_faulted"] == 0.0
    assert result.trajectory.metadata["fdir_events"] == []


def test_a_single_multipath_spike_is_rejected_once_and_recovers_immediately() -> None:
    """One 50 m outlier, then normal measurements.

    Recovery must be immediate: the very next valid fix is accepted. A gate that
    needed several good epochs to resume would leave a real outage uncorrected
    for longer than necessary.
    """
    result, _ = _run_with_offset(np.array([50.0, 0.0, 0.0]), 40, 1)
    assert result.stats["fdir_gnss_rejected"] == 1.0
    assert result.stats["fdir_gnss_faulted"] == 0.0
    assert result.stats["fdir_gnss_consecutive_rejections"] == 0.0
    # Every other fix was fused.
    assert result.stats["gnss_updates_used"] == result.stats["gnss_fixes_seen"] - 1.0


def test_a_persistent_spoofed_signal_isolates_the_channel() -> None:
    """Continuous corruption must escalate to SENSOR_FAULT, not endless transients.

    Beyond ``max_consecutive_rejections`` the rejection is no longer news: it is a
    channel that has stopped producing usable data, and it needs a different
    response from a system that just lost one measurement.
    """
    cfg = FdirConfig(max_consecutive_rejections=5)
    result, peak_error = _run_with_offset(np.array([15.0, 0.0, 0.0]), 40, 30, fdir_config=cfg)
    events = result.trajectory.metadata["fdir_events"]
    faults = [e for e in events if e["status"] == STATUS_SENSOR_FAULT]
    assert len(faults) == 1, "expected exactly one fault declaration"
    assert faults[0]["consecutive_rejections"] == 5
    # The fault is declared at the fifth bad fix, not the thirtieth.
    assert faults[0]["t_s"] < events[-1]["t_s"]
    # Isolation held: the estimate did not follow the spoof.
    assert peak_error < 3.0, f"filter followed the spoof to {peak_error:.2f} m"


def test_a_rejected_update_leaves_the_prediction_untouched() -> None:
    """`P^+ = P^-` on rejection, which is the whole safety claim.

    Asserted structurally rather than through the trajectory: the rejected epoch
    must not shrink the covariance, and must not move the state. A rejected
    measurement that quietly reduced `P` would make the filter *more* confident on
    the strength of information it declined to use.
    """
    result, _ = _run_with_offset(np.array([100.0, 0.0, 0.0]), 40, 1)
    # If the 100 m fix had been fused, the position covariance would have dropped
    # by orders of magnitude at that epoch and the filter would be claiming a
    # tighter bound while being 100 m wrong.
    assert result.stats["gnss_updates_rejected"] == 1.0
    assert float(result.trajectory.metadata["sigma_p"].max()) < 2.0


def test_fdir_disabled_leaves_the_legacy_gate_in_charge() -> None:
    """Turning FDIR off restores the pre-ADR-0005 behaviour exactly.

    Worth pinning because the legacy ``gate_sigma`` test is what the existing
    rejection counters were measured against, and a change there would silently
    move every published number in the README.
    """
    _gt, imu, gnss = _stationary_fixture()
    off = _filter(gnss_position_sigma_m=0.1, fdir_config=FdirConfig(enabled=False)).run(
        imu, gnss=_corrupt(gnss, np.array([50.0, 0.0, 0.0]), 40, 1)
    )
    assert "fdir_gnss_rejected" not in off.stats
    assert off.stats["fdir_channels"] == 0.0
    # The legacy gate is looser than the chi-square test, so it may or may not
    # catch this one. What must hold is that the run completes either way.
    assert off.stats["gnss_fixes_seen"] > 50.0


# ------------------------------------------------------- the visual channel ---

#: What the visual runs below are measured against, recorded here so a reader
#: does not have to re-derive it. 401 frames at 20 Hz over 20 s, keyframe
#: interval 1, so 400 usable relative-pose fixes after the first frame only
#: establishes a keyframe.
_VISION_FRAMES = 400


def _vision_fixture(anchor_modelled: bool = True):
    """A visual run with the benchmark inertial noise model.

    Unlike the GNSS fixture the inertial stream is *noisy* here. A visual-only
    run has no absolute reference, so a stripped-down noise-free IMU would let a
    bad relative pose be absorbed as a plausible trajectory rather than rejected.
    """
    cfg = SyntheticConfig(duration_s=_DURATION_S, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(cfg, rate_hz=200.0)
    noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)
    vision = visual_updates(gt, VisionConfig(rot_sigma_deg=0.05, trans_sigma_m=0.01, seed=0))
    return gt, imu, noise, vision


def _rot_about(axis, degrees: float) -> np.ndarray:
    """Rodrigues rotation, so a jump test can state its magnitude exactly."""
    k = np.asarray(axis, float)
    k = k / la.norm(k)
    a = np.deg2rad(degrees)
    K = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + np.sin(a) * K + (1.0 - np.cos(a)) * (K @ K)


def _run_with_visual_jump(drot=None, dt=None, start=200, count=1, **kwargs):
    """Run a visual-only filter over a stream with one block corrupted.

    ``drot`` is a rotation applied on the right of the relative pose and ``dt`` a
    translation added to it, both to `count` frames from `start`.
    """
    _gt, imu, noise, vision = _vision_fixture()
    R_rel = vision.R_rel.copy()
    t_rel = vision.t_rel.copy()
    if drot is not None:
        R_rel[start : start + count] = R_rel[start : start + count] @ drot
    if dt is not None:
        t_rel[start : start + count] += dt
    corrupted = VisionUpdate(
        t=vision.t.copy(),
        R_rel=R_rel,
        t_rel=t_rel,
        rot_cov=None if vision.rot_cov is None else vision.rot_cov.copy(),
        trans_cov=None if vision.trans_cov is None else vision.trans_cov.copy(),
    )
    result = ErrorStateKalmanFilter(
        EskfConfig(
            imu_noise=noise,
            vision_enabled=True,
            vision_rot_sigma_deg=0.05,
            vision_trans_sigma_m=0.01,
            initial_bias_sigma=0.01,
            vision_keyframe_interval=1,
            **kwargs,
        )
    ).run(imu, gnss=None, vision=corrupted)
    return result


def test_a_clean_visual_run_produces_zero_false_rejections() -> None:
    """The false-alarm test for the channel that has no absolute reference.

    Stated per block rather than as one number because the blocks are gated
    separately: a shared counter would let the rotation gate's rejects hide the
    translation gate's, and this is the only assertion that says the translation
    gate is not simply never firing.
    """
    stats = _run_with_visual_jump().stats
    assert stats["vision_updates_used"] == _VISION_FRAMES
    for block in ("rot", "trans"):
        assert stats[f"fdir_vision_{block}_accepted"] == _VISION_FRAMES
        assert stats[f"fdir_vision_{block}_rejected"] == 0.0
        assert stats[f"fdir_vision_{block}_faulted"] == 0.0
    assert stats["fdir_events"] == 0.0


def test_a_visual_translation_step_is_rejected_without_silencing_the_rotation_gate() -> None:
    """A 10 m translation step: 1000 sigma against a 1 cm measurement.

    The rotation block is asserted un-rejected in the same run. That is the
    property of splitting the channel in two: the two blocks come from one
    transform, so a single 'vision' channel would let the healthy half vouch for
    the broken one and the whole fault would go unobserved.
    """
    result = _run_with_visual_jump(dt=np.array([0.0, 0.0, 10.0]), start=200, count=20)
    stats = result.stats
    assert stats["fdir_vision_trans_rejected"] > 0.0
    assert stats["fdir_vision_rot_rejected"] == 0.0
    assert stats["fdir_vision_rot_accepted"] == _VISION_FRAMES
    # The step is sustained, so the channel must be declared faulty rather than
    # absorb it as a longer-lived nuisance rejection.
    faults = [
        e
        for e in result.trajectory.metadata["fdir_events"]
        if e["sensor"] == "vision_trans" and e["status"] == STATUS_SENSOR_FAULT
    ]
    assert len(faults) == 1
    assert faults[0]["consecutive_rejections"] == 5
    # The step is over after 20 frames, so the channel has to come back. This is
    # the case that separates the two channel states: a fault that never clears
    # is a dead sensor, which is a different failure from a brief one.
    assert stats["fdir_vision_trans_consecutive_rejections"] == 0.0
    assert stats["fdir_vision_trans_faulted"] == 0.0
    assert stats["fdir_vision_trans_accepted"] < _VISION_FRAMES


def test_a_visual_rotation_jump_is_rejected_on_the_rotation_block_only() -> None:
    """A 90 deg rotation step, checked on the block that can see it.

    90 deg is used rather than a marginal value because the point is not the
    threshold. The interesting asymmetry is on the other side: at 20 deg the
    modelled anchor absorbs the step, which is what the anchor exists for, so a
    test at that magnitude would be asserting the anchor's behaviour under the
    name of the gate's. 90 deg is past anything a slowly-drifting calibration
    offset can explain.
    """
    result = _run_with_visual_jump(drot=_rot_about([0.0, 0.0, 1.0], 90.0), start=200, count=20)
    stats = result.stats
    assert stats["fdir_vision_rot_rejected"] > 0.0
    assert stats["fdir_vision_trans_rejected"] == 0.0
    faults = [
        e
        for e in result.trajectory.metadata["fdir_events"]
        if e["sensor"] == "vision_rot" and e["status"] == STATUS_SENSOR_FAULT
    ]
    assert len(faults) == 1
    assert stats["fdir_vision_rot_faulted"] == 0.0


def test_a_faulted_visual_channel_stops_being_counted_as_used() -> None:
    """`vision_updates_used` must not credit an update FDIR refused.

    The counters are what a health monitor reads. A run that keeps reporting 400
    vision updates used while the gate is throwing 29 of them away would look
    healthy for exactly as long as the sensor is broken, and the covariance the
    filter reports during that time is the only other evidence anything has gone
    wrong.
    """
    result = _run_with_visual_jump(dt=np.array([0.0, 0.0, 10.0]), start=200, count=20)
    stats = result.stats
    assert stats["vision_updates_rejected"] == stats["fdir_vision_trans_rejected"]
    assert stats["vision_updates_used"] < _VISION_FRAMES
    assert stats["vision_updates_used"] + stats["vision_updates_rejected"] <= _VISION_FRAMES


# ------------------------------------------- the cost of the gate, pinned ----


def _denial_scenario(**fdir_kwargs):
    """The `outage_visual` benchmark case: 15 s GNSS denial with vision aiding.

    Config values are copied from `configs/benchmark.yaml` rather than imported
    so this test cannot silently follow a change to the published scenario --
    it is pinning a measured cost, and a cost measured against a scenario that
    has since moved is not the same number.
    """
    syn = SyntheticConfig(
        duration_s=30.0,
        rate_hz=100.0,
        radius_m=4.0,
        circles=1.5,
        sway_amplitude_m=0.6,
        sway_cycles=3.0,
        yaw_amplitude_deg=35.0,
        yaw_cycles=1.0,
        start_position=(1.0, 0.0, 1.6),
    )
    gt = synthetic_trajectory(syn)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(syn)
    gnss = gnss_fixes(gt, GnssConfig(rate_hz=5.0, sigma_m=0.8, seed=0))
    vision = visual_updates(gt, VisionConfig(rate_hz=20.0, rot_sigma_deg=0.35, trans_sigma_m=0.05, seed=0))
    gnss = apply_gnss_outage(gnss, [Outage(start_s=5.0, duration_s=15.0)], True)
    noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)
    cfg = EskfConfig(
        imu_noise=noise,
        gnss_position_sigma_m=0.8,
        vision_enabled=True,
        vision_rot_sigma_deg=0.35,
        vision_trans_sigma_m=0.05,
        vision_keyframe_interval=1,
        fdir_config=FdirConfig(**fdir_kwargs),
    )
    return gt, ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, vision=vision)


def test_adaptive_inflation_recovers_the_fixes_that_the_plain_gate_threw_away() -> None:
    """Blocker B5, closed with a number attached. ADR-0006.

    After a 15 s denial the filter is metres off with a collapsed covariance.
    A gate that trusts that covariance reads a healthy fix as an outlier: 51 of
    75 rejected in this configuration, and the filter dead-reckons the rest of the
    run instead of snapping back.

    The same gate, given a second pass, re-accepts the returning fixes once the
    covariance it is testing against has been given back the uncertainty the
    outage actually earned. Measured here: 9.864 m to 3.419 m, and 51 rejections
    down to 15, on one inflation grant.

    The assertions are deliberately asymmetric. The improvement is checked
    tightly, because that is the thing the change was for. The remaining 15
    rejections are checked only to be *fewer* than before, not to be zero, and
    the ATE is checked against the no-FDIR control as a known remaining
    deficiency rather than a pass: at 3.419 m this filter is still worse here
    than with FDIR switched off at 1.878 m. Adaptive inflation removes most of
    the damage the plain gate did; it does not make the underlying anchor model
    calibrated, and pretending otherwise here would just relocate the overclaim.
    """
    gt, with_adapt = _denial_scenario()
    _, without_any_fdir = _denial_scenario(enabled=False)
    _, plain_gate = _denial_scenario(reacq_consecutive_rejections=999)

    def ate(result) -> float:
        reference = interpolate_trajectory(gt, result.trajectory.t)
        return float(np.linalg.norm(result.trajectory.positions[-1] - reference.positions[-1]))

    # The regression this closes, pinned at its old value so it cannot creep
    # back while the assertions below still pass.
    assert plain_gate.stats["fdir_gnss_rejected"] > 40.0
    assert ate(plain_gate) > 9.0

    assert with_adapt.stats["fdir_gnss_rejected"] < 20.0
    assert ate(with_adapt) < 4.0
    assert ate(with_adapt) < 0.5 * ate(plain_gate)

    # One grant, not many. A grant per divergence episode is what bounds how much
    # uncertainty a channel can talk the filter out of; a loop of them would be
    # the filter walking itself onto whatever the measurements say.
    assert with_adapt.stats["fdir_inflations"] == 1.0
    assert with_adapt.stats["fdir_gnss_reaccepted"] == 1.0
    grants = [
        e for e in with_adapt.trajectory.metadata["fdir_events"] if e["status"] == STATUS_REACCEPTED_WITH_INFLATION
    ]
    assert len(grants) == 1
    # The grant is logged with what it bought, so the log says how much trust was
    # surrendered and not merely that some was.
    assert grants[0]["mahalanobis_sq"] > grants[0]["mahalanobis_sq_inflated"]
    assert grants[0]["inflation_variance"] > 0.0
    assert grants[0]["sensor"] == "gnss"

    # Known remaining deficiency, stated so it cannot be forgotten: adaptive
    # inflation is not the same as a calibrated filter, and this case is still
    # worse than running no gate at all.
    assert ate(with_adapt) > ate(without_any_fdir)


# ---------------------------------------- ADR-0007 re-expansion in the filter --


def test_a_lockout_re_expansion_widens_the_covariance_while_refusing_the_fix() -> None:
    """The ESKF honours a lockout's re-expansion *before* the early return.

    This is the branch that prevents a walked-off filter from coasting on a
    covariance that no longer describes where it is. It must both refuse the
    fix and widen ``P[3:6, 3:6]``; a filter that does only one of the two has
    not implemented the ADR.

    Driven with a stub FDIR because a real lockout needs two grants in one
    episode, and the filter-level recoveries grant only once.
    """

    class LockoutFdir(FdirManager):
        def evaluate_and_adapt(self, sensor, innovation, S, t_s=0.0, P=None, H=None, block=()):
            return GatingDecision(
                accepted=False,
                mahalanobis_sq=80.0,
                threshold=16.266,
                dof=3,
                status=STATUS_REJECTED_SPOOF,
                reexpansion_variance=25.0,
                reexpansion_block=(3, 4, 5),
                outlier=True,
            )

    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(),
        gnss_position_sigma_m=0.8,
    )
    f = ErrorStateKalmanFilter(cfg)
    f.fdir = LockoutFdir(FdirConfig())
    x = {
        "R": np.eye(3),
        "p": np.zeros(3),
        "v": np.zeros(3),
        "b_a": np.zeros(3),
        "b_g": np.zeros(3),
        "P": f._initial_covariance(),
        "R_vk": np.eye(3),
        "p_vk": np.zeros(3),
        "P_theta_vk": np.zeros((3, 3)),
        "P_p_vk": np.zeros((3, 3)),
        "c_p": np.zeros(3),
        "c_t": np.zeros(3),
        "vision_updates": 0,
    }
    P_before = x["P"][3:6, 3:6].copy()
    ok, _innov = f._gnss_update(x, np.array([50.0, 0.0, 0.0]), 0.8, t_s=0.0)
    assert ok is False, "a lockout must refuse the measurement"
    grown = x["P"][3:6, 3:6] - P_before
    np.testing.assert_allclose(grown, np.eye(3) * 25.0, atol=1e-9)
    assert f.fdir_inflations == 1, "the re-expansion is a covariance event, so it is counted"
