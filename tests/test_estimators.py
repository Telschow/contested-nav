"""Estimator tests.

The most important test in this file is
:func:`test_visual_measurements_telescope`: it pins the frame convention of the
relative-pose measurement. A measurement stream whose rotation and translation
blocks come from *different* transforms still looks plausible, still passes a
gating check, and still fuses without raising -- it is just wrong, and the error
shows up only as unexplained multi-metre drift. That bug is recorded here.
"""

from __future__ import annotations

import numpy as np
import numpy.linalg as la
import pytest

from navkit.degrade.config import Outage
from navkit.degrade.inject import apply_gnss_outage
from navkit.estimators.dead_reckoning import DeadReckoning
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.fdir import FdirConfig
from navkit.geometry.rigid import rot_exp, rot_log_batch, rot_right_jacobian
from navkit.io.imu import ImuNoiseModel, apply_imu_noise
from navkit.sensors.models import GnssConfig, VisionConfig, gnss_fixes, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory
from navkit.types import interpolate_trajectory

DURATION_S = 20.0


@pytest.fixture(scope="module")
def truth() -> object:
    cfg = SyntheticConfig(duration_s=DURATION_S, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    # Start at the identity pose so the filter's zero initial state is correct.
    return gt.transformed(la.inv(gt.poses[0]))


@pytest.fixture(scope="module")
def imu(truth):
    return synthetic_imu(SyntheticConfig(duration_s=DURATION_S, rate_hz=100.0), rate_hz=200.0)


def position_error(trajectory, reference) -> np.ndarray:
    ref = interpolate_trajectory(reference, trajectory.t)
    return np.linalg.norm(trajectory.positions - ref.positions, axis=1)


def rotation_error(trajectory, reference) -> np.ndarray:
    ref = interpolate_trajectory(reference, trajectory.t)
    return np.array(
        [
            float(np.linalg.norm(rot_log_batch((trajectory.rotations[i] @ ref.rotations[i].T)[None])[0]))
            for i in range(len(trajectory.t))
        ]
    )


# ------------------------------------------------------------ measurement ---


def test_visual_measurements_telescope(truth) -> None:
    """Chaining the emitted relative poses must reproduce the trajectory.

    This is the regression test for the frame-convention bug. The buggy stream
    emitted ``R_rel = R_i R_{i-1}^T`` (the rotation of ``T_i^-1 T_{i-1}``) next to
    ``t_rel = R_{i-1}^T (p_i - p_{i-1})`` (the translation of ``T_{i-1}^-1 T_i``).
    Each block was individually exact, so per-step checks passed, but the chain
    diverged steadily from the trajectory.
    """
    updates = visual_updates(truth, VisionConfig(rot_sigma_deg=1e-9, trans_sigma_m=1e-9))
    R = truth.rotations[0].copy()
    p = truth.positions[0].copy()
    rot_err = []
    pos_err = []
    for k in range(1, len(updates.t)):
        p = p + R @ updates.t_rel[k]
        R = R @ updates.R_rel[k]
        ref = interpolate_trajectory(truth, np.array([updates.t[k]]))
        rot_err.append(float(np.linalg.norm(rot_log_batch((R @ ref.rotations[0].T)[None])[0])))
        pos_err.append(float(np.linalg.norm(p - ref.positions[0])))
    assert max(rot_err) < 1e-7, f"rotation chain diverges: {max(rot_err):.3e} rad"
    assert max(pos_err) < 1e-7, f"position chain diverges: {max(pos_err):.3e} m"


def test_visual_blocks_belong_to_the_same_transform(truth) -> None:
    """Both blocks must come from ``T_prev_cur = T_prev^-1 T_cur``."""
    updates = visual_updates(truth, VisionConfig(rot_sigma_deg=1e-9, trans_sigma_m=1e-9))
    for k in (1, 5, 17, len(updates.t) - 1):
        prev = interpolate_trajectory(truth, np.array([updates.t[k - 1]]))
        cur = interpolate_trajectory(truth, np.array([updates.t[k]]))
        assert np.allclose(updates.R_rel[k], prev.rotations[0].T @ cur.rotations[0], atol=1e-9)
        assert np.allclose(
            updates.t_rel[k],
            prev.rotations[0].T @ (cur.positions[0] - prev.positions[0]),
            atol=1e-9,
        )


def test_visual_first_frame_is_dropped(truth) -> None:
    """The first entry has no predecessor and must not be fused as a fix."""
    updates = visual_updates(truth, VisionConfig())
    assert updates.dropped is not None
    assert bool(updates.dropped[0])
    assert not bool(updates.dropped[1:].any())


def test_visual_is_deterministic_for_a_fixed_seed(truth) -> None:
    a = visual_updates(truth, VisionConfig(rot_sigma_deg=0.1, trans_sigma_m=0.01, seed=11))
    b = visual_updates(truth, VisionConfig(rot_sigma_deg=0.1, trans_sigma_m=0.01, seed=11))
    c = visual_updates(truth, VisionConfig(rot_sigma_deg=0.1, trans_sigma_m=0.01, seed=12))
    assert np.array_equal(a.R_rel, b.R_rel)
    assert np.array_equal(a.t_rel, b.t_rel)
    assert not np.array_equal(a.t_rel, c.t_rel)


# ------------------------------------------------------------- estimators ---


def test_dead_reckoning_tracks_a_short_horizon(imu, truth) -> None:
    """Un-aided inertial integration must stay centimetre-level over 20 s.

    The synthetic IMU is analytic, so this bounds the propagation path itself:
    if the differencing, the gravity sign, or the bias states were wrong, this
    test would move by orders of magnitude rather than a little.
    """
    result = DeadReckoning().run(imu)
    err = position_error(result.trajectory, truth)
    assert err[-1] < 0.2, f"final dead-reckoning error {err[-1]:.4f} m"
    assert err.max() < 0.5, f"peak dead-reckoning error {err.max():.4f} m"


def test_dead_reckoning_attitude_stays_small(imu, truth) -> None:
    result = DeadReckoning().run(imu)
    assert rotation_error(result.trajectory, truth)[-1] < 1e-3


def test_eskf_gnss_only_beats_dead_reckoning(imu, truth) -> None:
    noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)
    cfg = EskfConfig(imu_noise=noise, gnss_position_sigma_m=0.1, initial_bias_sigma=0.01)
    fused = ErrorStateKalmanFilter(cfg).run(
        imu, gnss=gnss_fixes(truth, GnssConfig(sigma_m=0.1, rate_hz=5.0)), vision=None
    )
    fused_err = position_error(fused.trajectory, truth)[-1]
    unaided_err = position_error(DeadReckoning().run(imu).trajectory, truth)[-1]
    assert fused_err < unaided_err
    assert fused_err < 0.5, f"GNSS-aided error {fused_err:.4f} m"
    assert fused.stats["gnss_updates_used"] > 0


def test_eskf_uses_every_available_gnss_fix(imu, truth) -> None:
    """With consistent noise the gate must not throw away good measurements."""
    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3),
        gnss_position_sigma_m=0.1,
        initial_bias_sigma=0.01,
    )
    result = ErrorStateKalmanFilter(cfg).run(
        imu, gnss=gnss_fixes(truth, GnssConfig(sigma_m=0.1, rate_hz=5.0)), vision=None
    )
    assert result.stats["gnss_updates_rejected"] == 0


def test_single_visual_update_corrects_a_perturbed_state() -> None:
    """A single noiseless visual fix must pull the state onto the measurement.

    This exercises the update in isolation, with an exact keyframe, so a wrong
    sign in either block shows up as the error *growing*.
    """
    R_prev = rot_exp(np.array([0.0, 0.0, 0.3]))
    p_prev = np.array([1.0, 2.0, 0.0])
    R_true = R_prev @ rot_exp(np.array([0.01, -0.02, 0.03]))
    p_true = p_prev + R_prev @ np.array([0.05, 0.0, 0.01])
    R = R_prev @ rot_exp(np.array([0.05, 0.0, 0.0]))
    p = p_prev + np.array([0.10, 0.0, 0.0])

    filt = ErrorStateKalmanFilter(
        EskfConfig(
            imu_noise=ImuNoiseModel(),
            gate_sigma=0.0,
            initial_pos_sigma_m=10.0,
            initial_rot_sigma_deg=30.0,
            initial_vel_sigma_m_s=1.0,
            vision_anchor_modelled=True,
        )
    )
    state = {
        "R": R.copy(),
        "p": p.copy(),
        "v": np.zeros(3),
        "b_a": np.zeros(3),
        "b_g": np.zeros(3),
        "P": filt._initial_covariance(),
        "R_vk": R_prev.copy(),
        "p_vk": p_prev.copy(),
        "P_theta_vk": np.zeros((3, 3)),
        "P_p_vk": np.zeros((3, 3)),
        "c_p": np.zeros(3),
        "c_t": np.zeros(3),
        "vision_updates": 0,
        "vision_keyframe_set": True,
    }

    def error() -> tuple[float, float]:
        rot = float(np.linalg.norm(rot_log_batch((state["R"] @ R_true.T)[None])[0]))
        return rot, float(np.linalg.norm(state["p"] - p_true))

    before = error()
    filt._vision_update(state, R_true @ R_prev.T, R_prev.T @ (p_true - p_prev), 1.0, 1.0)
    after = error()
    # Both blocks must reduce their error. A sign error in either one makes the
    # error grow, which is the failure mode this test exists to catch. The
    # reduction is not exact because the position block also carries attitude
    # information through the propagated cross-covariance, so the second update
    # nudges the attitude slightly.
    assert after[0] < before[0] / 4.0, f"rotation error {before[0]:.4f} -> {after[0]:.4f}"
    assert after[1] < before[1] / 10.0, f"position error {before[1]:.4f} -> {after[1]:.4f}"


def test_visual_translation_jacobian_is_the_measurement_model() -> None:
    """``H`` is ``dh/dp``, not ``d(residual)/dp``; they differ by a sign.

    Pinning this because using the residual derivative pushes the state the
    wrong way, and the resulting error is silent.
    """
    R_prev = rot_exp(np.array([0.0, 0.0, 0.3]))
    p_prev = np.array([1.0, 2.0, 0.0])
    t_rel = np.array([0.05, 0.0, 0.01])
    p = p_prev + np.array([0.10, -0.03, 0.02])

    def residual(pn: np.ndarray) -> np.ndarray:
        return t_rel - R_prev.T @ (pn - p_prev)

    h = 1e-7
    numeric = np.zeros((3, 3))
    for i in range(3):
        step = np.zeros(3)
        step[i] = h
        numeric[:, i] = (residual(p + step) - residual(p)) / h
    # d(residual)/dp is -R_prev^T; the measurement model Jacobian is its negative.
    assert np.allclose(numeric, -R_prev.T, atol=1e-9)
    assert np.allclose(-numeric, R_prev.T, atol=1e-9)


def test_eskf_rejects_inconsistent_measurements(imu, truth) -> None:
    """A badly biased GNSS stream must be gated, not fused blindly."""
    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3),
        gnss_position_sigma_m=0.1,
        gate_sigma=3.0,
        initial_bias_sigma=0.01,
    )
    gnss = gnss_fixes(truth, GnssConfig(sigma_m=0.1, rate_hz=5.0))
    gnss.positions = gnss.positions + np.array([50.0, 0.0, 0.0])
    result = ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, vision=None)
    assert result.stats["gnss_updates_rejected"] > 0
    assert position_error(result.trajectory, truth)[-1] > 1.0


def test_eskf_overconfident_measurement_is_not_a_valid_test_configuration() -> None:
    """Documents why a near-perfect GNSS sigma diverges instead of converging.

    A 1e-6 m position sigma is *tighter than the model error*, so the filter
    becomes overconfident, the innovation is divided by a near-zero S, and the
    bias/position cross-covariance is amplified into a large spurious gyro bias.
    The filter then diverges. This is a property of an inconsistent
    configuration, not a defect, and it is pinned here so the behaviour is not
    rediscovered as a "bug" later.

    Pinned with the ``legacy`` process noise (ADR-0014). The default ``textbook`` form carries more
    process noise, so this configuration no longer rejects a single fix there.
    """
    noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)
    cfg = SyntheticConfig(duration_s=DURATION_S, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(cfg, rate_hz=200.0)
    result = ErrorStateKalmanFilter(
        EskfConfig(
            imu_noise=noise,
            gnss_position_sigma_m=1e-6,
            initial_bias_sigma=0.01,
            process_noise_form="legacy",
        )
    ).run(imu, gnss=gnss_fixes(gt, GnssConfig(sigma_m=1e-6, rate_hz=5.0)), vision=None)
    assert result.stats["gnss_updates_rejected"] > 0


def _vision_benchmark_fixture(
    interval=1,
    anchor_modelled=True,
    noisy=True,
    use_gnss=False,
    vision_enabled=True,
    seed=0,
    outage=None,
    fdir_enabled=True,
):
    """Synthetic vision run used by the covariance-honesty tests.

    ``noisy`` selects between a clean analytic inertial stream and one with the
    benchmark noise model applied. Absolute numbers move by more than an order of
    magnitude between the two, so the tests below assert ratios and bounds
    rather than point values.

    ``fdir_enabled`` exists for one caller. FDIR is default-on in the filter, and
    it partially *masks* the self-confirmation defect these tests pin, because
    isolating a GNSS channel whose covariance has collapsed throws away real
    fixes that would otherwise pull the estimate back. The test that pins the
    defect therefore turns FDIR off, so that it keeps measuring the defect rather
    than the mitigation. ``test_fdir_isolates_a_channel_whose_covariance_has_
    collapsed`` covers the interaction from the other side.
    """
    cfg = SyntheticConfig(duration_s=20.0, rate_hz=100.0)
    gt = synthetic_trajectory(cfg)
    gt = gt.transformed(la.inv(gt.poses[0]))
    imu = synthetic_imu(cfg, rate_hz=200.0)
    noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)
    if noisy:
        imu, _, _ = apply_imu_noise(imu, noise, np.random.default_rng(7))
    vision = visual_updates(gt, VisionConfig(rot_sigma_deg=0.05, trans_sigma_m=0.01, seed=seed))
    gnss = gnss_fixes(gt, GnssConfig(sigma_m=0.1, rate_hz=5.0, seed=3)) if use_gnss else None
    if gnss is not None and outage is not None:
        gnss = apply_gnss_outage(gnss, [outage], True)
    filt = ErrorStateKalmanFilter(
        EskfConfig(
            imu_noise=noise,
            gnss_position_sigma_m=0.1,
            vision_rot_sigma_deg=0.05,
            vision_trans_sigma_m=0.01,
            initial_bias_sigma=0.01,
            vision_keyframe_interval=interval,
            vision_anchor_modelled=anchor_modelled,
            vision_enabled=vision_enabled,
            fdir_config=FdirConfig(enabled=fdir_enabled),
        )
    )
    result = filt.run(imu, gnss=gnss, vision=vision)
    reference = interpolate_trajectory(gt, result.trajectory.t)
    final_error = float(np.linalg.norm(result.trajectory.positions[-1] - reference.positions[-1]))
    claimed = float(np.sqrt(np.trace(result.position_cov[-1])))
    return result, final_error, claimed


def test_relative_pose_fix_collapses_position_covariance_when_it_may_move_position() -> None:
    """Pins the self-confirmation failure so it cannot regress silently.

    Reproduced by setting ``vision_anchor_modelled=False``, which folds the
    anchor error into the innovation covariance instead of estimating it. That
    lets the filter average its own output as independent evidence: the claimed
    1-sigma collapses while the run ends far from the truth, and GNSS fixes
    start being rejected by the gate. The corrected path is asserted in
    test_modelled_anchor_restores_calibration_and_gnss_availability.
    """
    result, final_error, claimed = _vision_benchmark_fixture(
        use_gnss=True, interval=1, anchor_modelled=False, fdir_enabled=False
    )
    assert final_error > 5.0
    assert claimed < 0.01 * final_error
    # The ground-truth-free symptom: valid absolute fixes are gated away.
    assert float(result.stats["gnss_updates_rejected"]) > 0.0


def test_fdir_isolates_a_channel_whose_covariance_has_collapsed() -> None:
    """FDIR catches the collapse, but isolation is not a repair.

    Same broken configuration as the test above, now with FDIR on. The channel is
    isolated and the run is *less* wrong -- several times smaller error -- which is
    worth stating plainly rather than celebrating: the improvement is an artifact
    of throwing away good fixes, not of fixing the model. The filter is still
    overconfident by two orders of magnitude, so the covariance collapse itself is
    untouched. What FDIR adds is that the collapse is now *reported* rather than
    only inferable from a rejection count.
    """
    result, final_error, claimed = _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=False)
    assert float(result.stats["fdir_gnss_faulted"]) == 1.0
    assert float(result.stats["fdir_gnss_rejected"]) > float(result.stats["gnss_fixes_seen"]) / 2
    statuses = {e["status"] for e in result.trajectory.metadata["fdir_events"]}
    assert "SENSOR_FAULT" in statuses
    # Isolation limits the damage; it does not restore honesty about variance.
    assert claimed < 0.01 * final_error


def test_modelled_anchor_restores_calibration_and_gnss_availability() -> None:
    """The corrected path must not be merely less wrong; it must be right.

    Same fixture and same visual measurements as the test above, differing only
    in that the anchor error is estimated rather than folded into the
    innovation covariance. The filter should stay near the GNSS-only control,
    report an uncertainty of the same order, and stop discarding valid absolute
    fixes.
    """
    from navkit.eval.calibration import normalized_error_squared, summarise

    cfg = SyntheticConfig(duration_s=20.0, rate_hz=100.0)
    gt = synthetic_trajectory(cfg).transformed(la.inv(synthetic_trajectory(cfg).poses[0]))

    def mean_nees(result):
        reference = interpolate_trajectory(gt, result.trajectory.t)
        series = normalized_error_squared(result.trajectory.positions, reference.positions, result.position_cov)
        return summarise("eskf", "aided+vision", series).coverage.mean_normalised_error

    modelled, modelled_err, modelled_sigma = _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=True)
    unmodelled, _, _ = _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=False)
    _control, control_err, control_sigma = _vision_benchmark_fixture(use_gnss=True, interval=1, vision_enabled=False)

    # A calibrated 3D filter reports 3.0. The un-modelled path reports ~5e4.
    nees = mean_nees(modelled)
    assert nees < 10.0, f"mean NEES {nees:.3g}"
    assert nees < 0.01 * mean_nees(unmodelled)

    # Same order of magnitude as the control, not orders below it.
    assert 0.1 * control_sigma < modelled_sigma < 10 * control_sigma
    assert modelled_err < 2.0
    assert modelled_err < 10 * control_err

    # The operational alarm: no valid absolute fix is gated out.
    assert float(modelled.stats["gnss_updates_rejected"]) == 0.0
    assert float(unmodelled.stats["gnss_updates_rejected"]) > 0.0


def test_anchor_error_is_modelled_as_a_state_by_default() -> None:
    """The anchor is an estimated nuisance parameter, not assumed exact."""
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.vision_anchor_modelled is True


def test_the_anchor_nuisance_correction_is_computed_but_not_applied() -> None:
    """Pins a recorded limitation, so it cannot be changed silently.

    `_update` forms the gain over all 21 states and therefore computes dx[_IDX_CP]
    and dx[_IDX_CT], but the write-back does not apply them. That is CN-003.

    Applying them was implemented and measured, and it is *not* a safe isolated
    fix. It is inert at the shipped configuration, where vision_keyframe_interval
    == 1 re-commits the anchor immediately after each update. Where the anchor is
    held fixed, c_p and c_t carry no process noise by default, so they are not
    identifiable: the corrected anchor error latches onto any persistent
    discrepancy and absorbs real navigation drift. Measured once on outage_visual
    with the anchor held fixed, applying the correction made both the ATE and the
    mean NEES much worse. That measurement has no generated source, so its figures
    are not kept here.

    This test asserts the current behaviour for two reasons. It stops the line
    being "fixed" without the identifiability decision that CN-003 actually
    needs, and it makes the limitation visible in the suite rather than only in
    an audit document.
    """
    from navkit.estimators.eskf import _IDX_CP, _IDX_CT

    produced: list[np.ndarray] = []
    applied: list[np.ndarray] = []
    original = ErrorStateKalmanFilter._update

    def instrumented(self, x, z, H, Rcov, **kwargs):
        P = x["P"].copy()
        S = H @ P @ H.T + Rcov
        K = np.linalg.solve(S, (P @ H.T).T).T
        dx = K @ np.asarray(z, float)
        before = {"c_p": x["c_p"].copy(), "c_t": x["c_t"].copy()}
        out = original(self, x, z, H, Rcov, **kwargs)
        if not out[0]:
            return out
        for block, key in ((_IDX_CP, "c_p"), (_IDX_CT, "c_t")):
            if np.any(np.abs(H[:, block]) > 0.0):
                produced.append(dx[block].copy())
                applied.append(x[key] - before[key])
        return out

    ErrorStateKalmanFilter._update = instrumented
    try:
        _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=True)
    finally:
        ErrorStateKalmanFilter._update = original

    assert produced, "no accepted visual update coupled to the anchor blocks"
    # The gain does produce a correction: this is not a case of the anchor states
    # simply being unobservable.
    assert np.abs(np.concatenate(produced)).max() > 1e-12
    # And it is dropped, deliberately. If this ever fails, CN-003 has been closed
    # and the identifiability decision it requires has been made and recorded.
    assert np.allclose(np.concatenate(applied), 0.0, atol=0.0)


def test_the_anchor_error_covariance_shrinks_while_the_state_stays_at_zero() -> None:
    """The consequence of the limitation above, stated as a fact.

    The Joseph update reduces P[_IDX_CP, _IDX_CP] and P[_IDX_CT, _IDX_CT] on
    every visual update even though the corresponding states never move. That is
    the specific dishonesty in CN-003: the filter reports a smaller anchor-error
    uncertainty than it has earned.

    If CN-003 is ever closed properly this test should be revisited in the same
    commit, because the two facts are two sides of the same coin.
    """
    from navkit.estimators.eskf import _IDX_CP, _IDX_CT

    observed: list[tuple[np.ndarray, np.ndarray]] = []
    original = ErrorStateKalmanFilter._update

    def instrumented(self, x, z, H, Rcov, **kwargs):
        before_p = float(np.trace(x["P"][_IDX_CP, _IDX_CP]))
        before_t = float(np.trace(x["P"][_IDX_CT, _IDX_CT]))
        out = original(self, x, z, H, Rcov, **kwargs)
        if out[0] and np.any(np.abs(H[:, _IDX_CP]) > 0.0):
            observed.append(
                (
                    np.array([before_p, before_t]),
                    np.array([float(np.trace(x["P"][_IDX_CP, _IDX_CP])), float(np.trace(x["P"][_IDX_CT, _IDX_CT]))]),
                )
            )
        return out

    ErrorStateKalmanFilter._update = instrumented
    try:
        _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=True)
    finally:
        ErrorStateKalmanFilter._update = original

    assert observed, "no accepted visual update coupled to the anchor blocks"
    before = np.array([b for b, _ in observed])
    after = np.array([a for _, a in observed])
    assert after.min() < before.max(), "anchor covariance never shrank; the premise of CN-003 no longer holds"


def test_covariance_stays_positive_semidefinite_across_a_visual_run() -> None:
    """The (I - K H) P shortcut produced negative eigenvalues here.

    The shortcut is symmetric but not positive semidefinite, and with the anchor
    nuisance blocks the smallest eigenvalue went negative within two visual
    updates. A covariance with a negative eigenvalue is not a slightly wrong
    answer, it is an unusable one, and the calibration code decomposes it, so
    this is a hard requirement rather than a numerical nicety.
    """
    result, _, _ = _vision_benchmark_fixture(use_gnss=True, interval=1, anchor_modelled=True)
    smallest = float(la.eigvalsh(0.5 * (result.position_cov + result.position_cov.transpose(0, 2, 1))).min())
    assert smallest > -1e-9, f"position covariance eigenvalue {smallest:.3g}"


def test_visual_only_uncertainty_tracks_its_error_instead_of_denying_it() -> None:
    """Honesty bound, not a calibration claim.

    With the position coupling removed the run is no longer wrong by orders of
    magnitude in normalised error. It is not necessarily calibrated -- the filter
    is honest about a bound it cannot yet justify -- and the test asserts only
    that the failure mode is gone.
    """
    for noisy in (True, False):
        _, final_error, claimed = _vision_benchmark_fixture(interval=1, anchor_modelled=True, noisy=noisy)
        ratio = claimed / final_error
        assert 0.01 < ratio < 2.0, f"claimed/actual = {ratio:.3g} (noisy={noisy})"


def test_vision_only_normalised_error_is_not_orders_of_magnitude_out() -> None:
    """Catches the catastrophic signature without over-claiming calibration.

    The failure this guards against is a mean NEES in the millions, which is what
    a filter looks like when it is certain and wrong. The measured values for the
    current attitude-only path, on noisy and on clean inertial data, are far below
    the bound, which is set to catch the collapse and not to assert success.
    """
    from navkit.eval.calibration import normalized_error_squared, summarise

    for noisy in (True, False):
        result, _, _ = _vision_benchmark_fixture(interval=1, anchor_modelled=True, noisy=noisy)
        cfg = SyntheticConfig(duration_s=20.0, rate_hz=100.0)
        gt = synthetic_trajectory(cfg)
        gt = gt.transformed(la.inv(gt.poses[0]))
        reference = interpolate_trajectory(gt, result.trajectory.t)
        series = normalized_error_squared(result.trajectory.positions, reference.positions, result.position_cov)
        nees = summarise("eskf", "vision-only", series).coverage.mean_normalised_error
        assert nees < 1000.0, f"mean NEES {nees:.3g} (noisy={noisy})"


def test_gnss_aided_filter_keeps_its_absolute_fixes() -> None:
    """With vision off, the filter accepts every absolute fix.

    This is the operational alarm for covariance collapse: when the claimed
    position sigma collapses, GNSS innovations look like outliers and get gated
    away, and the run silently degrades to open-loop drift. Counting rejected
    fixes needs no ground truth, so it is the cheapest health check available.
    """
    result, _, _ = _vision_benchmark_fixture(use_gnss=True, anchor_modelled=True, vision_enabled=False)
    used = float(result.stats["gnss_updates_used"])
    rejected = float(result.stats["gnss_updates_rejected"])
    assert used > 0.0
    assert rejected == 0.0


def test_gnss_denial_still_over_trusts_vision_and_that_is_pinned() -> None:
    """The known remaining limitation, asserted so it stays visible.

    Vision carrying the solution through a GNSS outage is not fixed: the filter
    stays certain while it coasts, and ends far outside its claimed uncertainty.
    This test pins that case only, with a band on the mean NEES and a floor on
    the ratio of the final error to the claimed sigma. It does not assert
    calibration in any other configuration: the ``vision_only`` benchmark row is
    itself badly overconfident (``docs/results.md``). The tests near this one pin
    only that vision does not cause GNSS fixes to be rejected, and a bound on how
    far out the vision-only normalised error may be. The cause is structural,
    not a tuning miss -- the Schur complement of a single-anchor relative-pose
    measurement cannot express "informative about motion, uninformative about
    position" without becoming degenerate, and a whole chain has to be
    considered jointly, which needs a pose graph. See the module docstring.

    This test therefore asserts the limitation rather than a success. If it
    starts failing because the number improved, that is good news and the fix
    belongs in the docstring and the thresholds below.
    """
    from navkit.eval.calibration import normalized_error_squared, summarise

    outage = Outage(start_s=5.0, duration_s=15.0)
    result, final_error, claimed = _vision_benchmark_fixture(
        use_gnss=True, interval=1, anchor_modelled=True, outage=outage
    )
    cfg = SyntheticConfig(duration_s=20.0, rate_hz=100.0)
    gt = synthetic_trajectory(cfg).transformed(la.inv(synthetic_trajectory(cfg).poses[0]))
    reference = interpolate_trajectory(gt, result.trajectory.t)
    series = normalized_error_squared(result.trajectory.positions, reference.positions, result.position_cov)
    nees = summarise("eskf", "denial+vision", series).coverage.mean_normalised_error

    # Documented band: clearly overconfident, and not yet catastrophic.
    assert 1e2 < nees < 1e5, f"denial mean NEES {nees:.3g} left the pinned band"
    assert final_error / claimed > 10.0


def test_enabling_the_visual_channel_no_longer_silences_the_gnss() -> None:
    """The regression this project set out to remove, now asserted as fixed.

    With the anchor error modelled, turning vision on must not cost the run its
    absolute fixes. Gating away valid GNSS is the observable symptom of
    covariance collapse and needs no ground truth to detect, which is why it was
    the alarm used throughout. The previous version of this test asserted that
    more than a quarter of the fixes were rejected; that number is now the bug,
    not the expected behaviour.
    """
    result, final_error, _ = _vision_benchmark_fixture(
        use_gnss=True, anchor_modelled=True, interval=1, vision_enabled=True
    )
    used = float(result.stats["gnss_updates_used"])
    rejected = float(result.stats["gnss_updates_rejected"])
    assert used > 0.0
    assert rejected == 0.0
    # Vision adds information, so the solution should stay near the control
    # rather than degrading.
    assert final_error < 1.0


# --- finite-difference checks of the visual Jacobians ------------------------
#
# The analytic visual Jacobians are where the original defect lived: H_ct = -I
# rather than +I. A sign error there is invisible in review, does not crash, and
# leaves the filter confidently wrong, so it is pinned against a numerical
# derivative of the filter's *own* residual rather than against a restatement of
# the formula. The residual is captured by stubbing `_update`, so this exercises
# the production code path rather than a copy of it.
#
# Two subtleties are encoded here rather than papered over with a loose tolerance:
#
#   1. The code's H is the derivative of the measurement model h, not of the
#      residual z = z_meas - h(x), so dz/dx = -H. Asserting H == dz/dx is the
#      same category of error the source comments warn about: it flips the sign
#      of the correction while still producing a plausible-looking number.
#   2. The attitude is a rotation matrix but H_theta is a derivative with respect
#      to a *rotation increment*, so the perturbation has to be R @ Exp(dtheta).
#      Perturbing a matrix element would test a different parameterisation.

from navkit.estimators.eskf import (
    _IDX_CP,
    _IDX_CT,
    _IDX_P,
    _IDX_THETA,
    _N_STATES,
)

_ROT_SIGMA_DEG = 0.35
_TRANS_SIGMA_M = 0.05
_EPS = 1e-7


def _eskf_with_vision(anchor_modelled: bool = True) -> ErrorStateKalmanFilter:
    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(),
        gnss_enabled=False,
        vision_enabled=True,
        vision_anchor_modelled=anchor_modelled,
    )
    return ErrorStateKalmanFilter(cfg)


def _frozen_state(R_vk, p_vk, R, p, c_p, c_t) -> dict:
    """A state as run() would hold it, mid-episode and before a re-commit."""
    return {
        "R": R.copy(),
        "p": p.copy(),
        "R_vk": R_vk.copy(),
        "p_vk": p_vk.copy(),
        "c_p": c_p.copy(),
        "c_t": c_t.copy(),
        "P": np.eye(_N_STATES) * 0.01,
        "vision_keyframe_set": True,
        "vision_updates": 0,
        "P_theta_vk": np.eye(3) * 0.01,
        "P_p_vk": np.eye(3) * 0.01,
    }


def _capture_blocks(eskf, x, R_rel_meas, t_rel_meas):
    """Run a visual update with the correction stubbed out, returning z and H.

    Stubbing `_update` rather than letting the correction run is what makes this
    a derivative of the *measurement model*. The state is copied in because
    `_vision_update` re-commits the anchor at the end of a successful update;
    sharing the caller's dict would evaluate the unperturbed and perturbed cases
    at different states and the derivative would be measuring the re-commit.
    """
    seen: list[tuple[np.ndarray, np.ndarray]] = []

    def fake_update(_x, z, H, _Rcov, **_kwargs):
        # The keyword arguments are accepted and ignored: `sensor`/`t_s` were
        # added for FDIR (ADR-0005) and this stub is only after the measurement
        # model, which it captures before any gating could run.
        seen.append((np.array(z, float).copy(), np.array(H, float).copy()))
        return True, 0.0

    eskf._update = fake_update
    frozen = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in x.items()}
    try:
        eskf._vision_update(frozen, R_rel_meas, t_rel_meas, _ROT_SIGMA_DEG, _TRANS_SIGMA_M)
    finally:
        del eskf._update
    assert len(seen) == 2, "expected a rotation block and a translation block"
    return seen


def _setup():
    """A pose pair that is neither the identity nor axis aligned.

    An identity or axis-aligned keyframe makes several Jacobian blocks
    numerically indistinguishable, so a wrong sign could still pass.
    """
    R_vk = rot_exp(np.array([0.21, -0.34, 0.47]))
    p_vk = np.array([1.7, -0.9, 0.35])
    R = R_vk @ rot_exp(np.array([-0.15, 0.28, 0.09]))
    p = p_vk + np.array([0.6, 0.25, -0.4])
    c_p = np.array([0.05, -0.02, 0.11])
    c_t = np.array([0.03, -0.07, 0.02])
    t_rel_meas = np.array([0.42, -0.17, 0.09])
    return R_vk, p_vk, R, p, c_p, c_t, t_rel_meas


def _residual(eskf, x, R_rel_meas, t_rel_meas) -> np.ndarray:
    (zr, _), (zt, _) = _capture_blocks(eskf, x, R_rel_meas, t_rel_meas)
    return np.concatenate([zr, zt])


def _numeric(eskf, x, R_rel_meas, t_rel_meas, perturb) -> np.ndarray:
    """Central difference of the real 6-D residual along `perturb`."""
    cols = []
    for k in range(3):
        xp, xm = perturb(k, +_EPS), perturb(k, -_EPS)
        cols.append(
            (_residual(eskf, xp, R_rel_meas, t_rel_meas) - _residual(eskf, xm, R_rel_meas, t_rel_meas)) / (2 * _EPS)
        )
    return np.column_stack(cols)


def _analytic(eskf, x, R_rel_meas, t_rel_meas, block) -> np.ndarray:
    (zr, Hr), (zt, Ht) = _capture_blocks(eskf, x, R_rel_meas, t_rel_meas)
    del zr, zt
    return np.vstack([Hr[:, block], Ht[:, block]])


def test_translation_anchor_jacobian_is_the_exact_derivative() -> None:
    """H_cp = -R_prev^T, checked as a derivative.

    The translation measurement model is linear in c_p, so the analytic block
    must match the numerical derivative to machine precision rather than to
    first order. This is the block whose sign was wrong.
    """
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)

    def perturb(k, h):
        y = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
        y["c_p"][k] += h
        return y

    numeric = _numeric(eskf, x, R_rel_meas, t_rel_meas, perturb)
    analytic = _analytic(eskf, x, R_rel_meas, t_rel_meas, _IDX_CP)
    assert -numeric == pytest.approx(analytic, abs=1e-7)


def test_position_jacobian_is_the_exact_derivative() -> None:
    """H_p = +R_prev^T, also linear and therefore exact."""
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)

    def perturb(k, h):
        y = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
        y["p"][k] += h
        return y

    numeric = _numeric(eskf, x, R_rel_meas, t_rel_meas, perturb)
    analytic = _analytic(eskf, x, R_rel_meas, t_rel_meas, _IDX_P)
    assert -numeric == pytest.approx(analytic, abs=1e-7)


def test_attitude_jacobian_is_the_exact_derivative() -> None:
    """H_theta = +I, differenced through the rotation increment.

    The perturbation is R @ Exp(h * e_k), not an elementwise change, because
    H_theta is defined against a rotation increment. Differencing a matrix
    element would silently test a different parameterisation and would not
    constrain H_theta at all.

    The measurement is made consistent with the prediction (c_t = 0 and
    R_rel_meas = R_rel_pred) so the rotation residual is zero. Log is nonlinear
    away from zero, so at an arbitrary residual the true derivative is rotated
    and the first-order +I claim would not hold; testing there would measure the
    fixture rather than the Jacobian.
    """
    R_vk, p_vk, R, p, c_p, _c_t, t_rel_meas = _setup()
    R_rel_meas = R_vk.T @ R
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, np.zeros(3))

    def perturb(k, h):
        y = _frozen_state(R_vk, p_vk, R, p, c_p, np.zeros(3))
        d = np.zeros(3)
        d[k] = h
        y["R"] = R @ rot_exp(d)
        return y

    assert la.norm(_residual(eskf, x, R_rel_meas, t_rel_meas)[:3]) < 1e-12

    numeric = _numeric(eskf, x, R_rel_meas, t_rel_meas, perturb)
    analytic = _analytic(eskf, x, R_rel_meas, t_rel_meas, _IDX_THETA)
    assert -numeric == pytest.approx(analytic, abs=1e-7)


def test_anchor_attitude_jacobian_is_the_exact_derivative() -> None:
    """H_ct = -R_rel_pred @ J_r(c_t), differenced at a non-zero operating point.

    The operating point uses a non-zero c_t with a measurement made consistent
    with it (R_rel_meas == R_rel_pred Exp(-c_t)), so the rotation residual
    vanishes and the numerical derivative is the Jacobian rather than an
    arbitrary point on the curve.

    The non-zero c_t is the whole point. Differencing at c_t = 0 is easy to pass
    and constrains almost nothing, because J_r(0) == I: the plain -R_rel_pred
    form is exact there. At a non-zero c_t, BCH contributes
    Log(Exp(-c_t) Exp(c_t + d)) ~ (I - 0.5 [c_t]_x) d = J_r(c_t) d, so the
    analytic block must carry the factor. Measured against this test, dropping
    it is wrong by an amount that grows with |c_t| -- a discrepancy small enough
    to look like a rounding artifact at small |c_t| and large enough to bias the
    anchor estimate at larger |c_t|.
    """
    R_vk, p_vk, R, p, c_p, _c_t, t_rel_meas = _setup()
    R_rel_pred = R_vk.T @ R
    for scale in (0.0, 0.05, 0.25, 0.5):
        c_t = np.array([0.3, -0.5, 0.2]) * scale
        R_rel_meas = R_rel_pred @ rot_exp(-c_t)
        eskf = _eskf_with_vision(anchor_modelled=True)
        x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)

        def perturb(k, h, _c_t=c_t):
            y = _frozen_state(R_vk, p_vk, R, p, c_p, _c_t.copy())
            y["c_t"][k] += h
            return y

        # Sanity: the fixture really is at the zero-residual operating point.
        assert la.norm(_residual(eskf, x, R_rel_meas, t_rel_meas)[:3]) < 1e-12

        numeric = _numeric(eskf, x, R_rel_meas, t_rel_meas, perturb)
        analytic = _analytic(eskf, x, R_rel_meas, t_rel_meas, _IDX_CT)
        assert -numeric == pytest.approx(analytic, abs=1e-7)


def test_anchor_blocks_carry_a_negative_sign() -> None:
    """Pins the sign explicitly, so the intent survives a refactor.

    The residual is z = z_meas - h(x) and h depends on the anchor error through
    Exp(-c_t) and -c_p, so d h / d c is negative. A plus sign here is the defect
    this whole project documents.

    The rotation block is negative *and* carries the right Jacobian of SO(3):
    -R_rel_pred @ J_r(c_t). The fixture uses a non-zero c_t precisely because
    J_r(c_t) == I only at c_t == 0, and pinning the value at zero would let the
    J_r factor be dropped without this test noticing.
    """
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
    (_, Hr), (_, Ht) = _capture_blocks(eskf, x, R_rel_meas, t_rel_meas)
    expected_ct = -(R_vk.T @ R) @ rot_right_jacobian(c_t)
    assert np.allclose(Hr[:, _IDX_CT], expected_ct, atol=1e-12)
    assert np.allclose(Ht[:, _IDX_CP], -R_vk.T, atol=1e-12)
    # The sign is the part that is easy to get backwards and that a refactor is
    # most likely to break, so assert it independently of the J_r factor.
    assert np.allclose(np.sign(np.diag(expected_ct)), np.sign(np.diag(Hr[:, _IDX_CT])))


def test_measurement_blocks_are_positive() -> None:
    """H is the derivative of the measurement model h, not of the residual.

    h = (R_rel_pred Exp(dtheta), R_prev^T (p_cur - p_prev)), so d h / d dtheta is
    R_rel_pred and d h / d p is +R_prev^T. Differencing the residual instead
    would flip both and push the state the wrong way, which is why the
    distinction is a test.

    The attitude block is R_rel_pred rather than the identity because
    Log(Q Exp(v) Q^T) == Q v conjugates the increment into the previous body
    frame. Asserting the identity here would pass for any near-static sequence
    and would hide a real frame error.
    """
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
    (_, Hr), (_, Ht) = _capture_blocks(eskf, x, R_rel_meas, t_rel_meas)
    assert np.allclose(Hr[:, _IDX_THETA], R_vk.T @ R, atol=1e-12)
    assert np.allclose(Ht[:, _IDX_P], R_vk.T, atol=1e-12)


def test_unmodelled_anchor_blocks_are_inert() -> None:
    """With the anchor error folded into R, the nuisance blocks carry no
    information: they must be exactly zero in H, not merely small."""
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=False)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
    (_, Hr), (_, Ht) = _capture_blocks(eskf, x, R_rel_meas, t_rel_meas)
    assert np.allclose(Hr[:, _IDX_CT], 0.0, atol=0.0)
    assert np.allclose(Ht[:, _IDX_CP], 0.0, atol=0.0)
    # The measurement blocks are unaffected by the anchor treatment.
    assert np.allclose(Hr[:, _IDX_THETA], R_vk.T @ R, atol=1e-12)
    assert np.allclose(Ht[:, _IDX_P], R_vk.T, atol=1e-12)


def test_anchor_does_not_leak_into_the_innovation_covariance() -> None:
    """The anchor error is a state, never an addition to R.

    Adding the anchor covariance to the innovation instead would let the filter
    average the anchor error away over time, which is the self-confirmation
    failure the state exists to prevent.
    """
    R_vk, p_vk, R, p, c_p, c_t, t_rel_meas = _setup()
    R_rel_meas = rot_exp(np.array([-0.11, 0.19, 0.06]))
    eskf = _eskf_with_vision(anchor_modelled=True)
    x = _frozen_state(R_vk, p_vk, R, p, c_p, c_t)
    seen: list[np.ndarray] = []
    eskf._update = lambda _x, _z, _H, Rcov, **_kw: (seen.append(np.array(Rcov, float)), (True, 0.0))[1]
    try:
        eskf._vision_update(x, R_rel_meas, t_rel_meas, _ROT_SIGMA_DEG, _TRANS_SIGMA_M)
    finally:
        del eskf._update
    assert seen[0] == pytest.approx(np.eye(3) * np.deg2rad(_ROT_SIGMA_DEG) ** 2)
    assert seen[1] == pytest.approx(np.eye(3) * _TRANS_SIGMA_M**2)


# --- EskfConfig.as_dict ------------------------------------------------------


def test_eskf_config_dict_includes_the_anchor_prior_and_drift() -> None:
    """These four fields decide whether a long visual run stays calibrated, so
    they must appear in the serialised config. Omitting them lets a config hash
    and a YAML round trip agree with each other while both disagree with the
    filter that actually ran."""
    d = EskfConfig(
        imu_noise=ImuNoiseModel(gyro_noise_density=0.01),
        vision_enabled=True,
        anchor_pos_sigma_m=2.5,
        anchor_rot_sigma_deg=7.0,
        anchor_pos_drift_sigma_m_sqrt_s=0.03,
        anchor_rot_drift_sigma_deg_sqrt_s=0.11,
    ).as_dict()
    assert d["anchor_pos_sigma_m"] == 2.5
    assert d["anchor_rot_sigma_deg"] == 7.0
    assert d["anchor_pos_drift_sigma_m_sqrt_s"] == 0.03
    assert d["anchor_rot_drift_sigma_deg_sqrt_s"] == 0.11
    assert d["vision_enabled"] is True
    assert d["imu_noise"]["gyro_noise_density"] == 0.01


def test_eskf_config_dict_ships_visual_disabled() -> None:
    """The default is the documented limitation, so it must not be an artefact
    of the dataclass default that never reaches a report."""
    d = EskfConfig(imu_noise=ImuNoiseModel()).as_dict()
    assert d["vision_enabled"] is False
    assert d["vision_anchor_modelled"] is True
    assert d["vision_keyframe_interval"] == 1


def test_fdir_config_as_dict_includes_spoof_params() -> None:
    cfg = FdirConfig(spoof_grant_threshold=3, spoof_lockout_s=120.0, spoof_reexpansion_factor=3.5)
    d = cfg.as_dict()
    assert d["spoof_grant_threshold"] == 3
    assert d["spoof_lockout_s"] == 120.0
    assert d["spoof_reexpansion_factor"] == 3.5


def test_eskf_config_as_dict_spoof_params_change_hash() -> None:
    base = EskfConfig(imu_noise=ImuNoiseModel(), fdir_config=FdirConfig(spoof_grant_threshold=2))
    a = base.as_dict()
    b = EskfConfig(imu_noise=ImuNoiseModel(), fdir_config=FdirConfig(spoof_grant_threshold=3)).as_dict()
    assert a["fdir_config"]["spoof_grant_threshold"] != b["fdir_config"]["spoof_grant_threshold"]
    assert a != b


def test_config_hash_changes_with_spoof_lockout() -> None:
    # Compare esk fconfig dicts
    c1 = EskfConfig(imu_noise=ImuNoiseModel(), fdir_config=FdirConfig(spoof_lockout_s=60.0))
    c2 = EskfConfig(imu_noise=ImuNoiseModel(), fdir_config=FdirConfig(spoof_lockout_s=90.0))
    assert c1.as_dict() != c2.as_dict()


def test_eskf_config_as_dict_covers_every_field() -> None:
    """No EskfConfig field may be absent from as_dict().

    A field the runtime reads but as_dict() omits makes two different filters
    serialise and hash identically, so a provenance record claims they were the
    same run. `gravity` was the instance here: __init__ uses it to replace the
    gravity vector, and it was absent from the serialised form.
    """
    import dataclasses

    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    declared = {f.name for f in dataclasses.fields(EskfConfig)}
    assert declared - set(cfg.as_dict()) == set()


def test_eskf_config_gravity_changes_serialised_config() -> None:
    """A non-default gravity must be visible in as_dict()."""
    base = EskfConfig(imu_noise=ImuNoiseModel())
    tilted = EskfConfig(imu_noise=ImuNoiseModel(), gravity=np.array([0.0, 0.0, -9.81]))
    assert base.as_dict() != tilted.as_dict()
    assert base.as_dict()["gravity"] is None
    assert tilted.as_dict()["gravity"] == [0.0, 0.0, -9.81]
    assert EskfConfig(imu_noise=ImuNoiseModel()).as_dict()["gravity"] is None


# -- the error-state reset and the transition matrix, against finite differences --------------

from navkit.estimators.eskf import _IDX_BA, _IDX_BG, _IDX_V
from navkit.geometry.rigid import rot_log

#: The three sizes of injected attitude correction the reset is checked at (radians).
_RESET_MAGNITUDES = (1e-3, 1e-2, 1e-1)
#: The exact reset Jacobian is J_r(a) = I - 0.5 [a]x + O(|a|^2). Measured on the fixed seeds
#: below, the first-order form misses it by |a|^2 / 6 (the [a]x^2 / 6 term of J_r), at all three
#: sizes. The bound 0.2 |a|^2 adds a little headroom; a wrong sign misses by about |a| and fails by orders of
#: magnitude at the smallest size.
_RESET_C = 0.2


def _full_state(rng: np.random.Generator) -> dict:
    return {
        "R": rot_exp(rng.normal(size=3)),
        "p": rng.normal(size=3),
        "v": rng.normal(size=3),
        "b_g": rng.normal(size=3) * 1e-3,
        "b_a": rng.normal(size=3) * 1e-2,
        "R_vk": rot_exp(rng.normal(size=3)),
        "p_vk": rng.normal(size=3),
        "c_p": np.zeros(3),
        "c_t": np.zeros(3),
        "P": np.eye(_N_STATES),
    }


def _filter_reset_block(eskf: ErrorStateKalmanFilter, dx: np.ndarray, block: slice) -> np.ndarray:
    """Read the reset Jacobian the filter applies, through `_inject_correction` itself.

    With H = 0 and R = 0 the Joseph update leaves P unchanged, so the result is G P G^T. Seeding
    P with a single unit variance in column j returns G[:, j] G[:, j]^T, and G[:, j] follows
    because its diagonal entry is positive. This reads the matrix the filter uses rather than a
    copy of its formula, so the test also holds a refactor to account.
    """
    rng = np.random.default_rng(0)
    out = np.zeros((3, 3))
    for k, j in enumerate(range(block.start, block.stop)):
        x = _full_state(rng)
        x["P"] = np.zeros((_N_STATES, _N_STATES))
        x["P"][j, j] = 1.0
        eskf._inject_correction(
            x, np.eye(_N_STATES), dx.copy(), np.zeros((_N_STATES, _N_STATES)), np.zeros((_N_STATES, _N_STATES))
        )
        col = x["P"][:, j] / np.sqrt(x["P"][j, j])
        out[:, k] = col[block]
    return out


def _exact_reset(a: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Central difference of Log(Exp(-a) Exp(d)) at d = a: the error after injecting `a`."""
    cols = []
    for k in range(3):
        e = np.zeros(3)
        e[k] = eps
        cols.append((rot_log(rot_exp(-a) @ rot_exp(a + e)) - rot_log(rot_exp(-a) @ rot_exp(a - e))) / (2 * eps))
    return np.column_stack(cols)


@pytest.mark.parametrize("magnitude", _RESET_MAGNITUDES)
def test_attitude_reset_jacobian_is_the_exact_derivative(magnitude: float) -> None:
    """The attitude block of the reset matches the derivative of the injection to second order.

    Convention ``R_true = R Exp(dtheta)``. Injecting ``a`` sets ``R+ = R Exp(a)``, so the error
    after the reset is ``Log(Exp(-a) Exp(dtheta))``. Its derivative at ``dtheta = a`` is
    ``J_r(a) = I - 0.5 [a]x + O(|a|^2)``. The bound is ``_RESET_C * |a|^2``.
    """
    rng = np.random.default_rng(11)
    eskf = _eskf_with_vision(anchor_modelled=True)
    for _ in range(5):
        u = rng.normal(size=3)
        a = u / la.norm(u) * magnitude
        dx = np.zeros(_N_STATES)
        dx[_IDX_THETA] = a
        dx[_IDX_P] = rng.normal(size=3) * 1e-2
        err = la.norm(_filter_reset_block(eskf, dx, _IDX_THETA) - _exact_reset(a), ord=2)
        assert err <= _RESET_C * magnitude**2 + 1e-8, f"|a|={magnitude}: reset off by {err:.3e}"


def test_anchor_reset_block_stays_identity_when_the_anchor_correction_is_not_applied() -> None:
    """The anchor model does not inject dx[c_t] (CN-003), so its reset block must stay identity."""
    eskf = _eskf_with_vision(anchor_modelled=True)
    dx = np.zeros(_N_STATES)
    dx[_IDX_THETA] = np.array([0.02, -0.01, 0.03])
    dx[_IDX_CT] = np.array([0.05, 0.04, -0.06])
    assert _filter_reset_block(eskf, dx, _IDX_CT) == pytest.approx(np.eye(3), abs=1e-12)


def _nominal_step(R, p, v, b_g, b_a, accel, gyro, g, dt):
    """The nominal equations of `_propagate`, restated for the test."""
    a_world = R @ (accel - b_a) + g
    return R @ rot_exp((gyro - b_g) * dt), p + v * dt + 0.5 * a_world * dt * dt, v + a_world * dt


def _numeric_transition(eskf, R, p, v, b_g, b_a, accel, gyro, dt, h=1e-6) -> np.ndarray:
    """Central-difference Jacobian of the propagated error with respect to each initial error state.

    Errors use the filter's own convention: ``R_true = R Exp(dtheta)``, everything else additive.
    """
    g = eskf.g
    R1, p1, v1 = _nominal_step(R, p, v, b_g, b_a, accel, gyro, g, dt)

    def err_after(d: np.ndarray) -> np.ndarray:
        Rt, pt, vt = _nominal_step(
            R @ rot_exp(d[_IDX_THETA]),
            p + d[_IDX_P],
            v + d[_IDX_V],
            b_g + d[_IDX_BG],
            b_a + d[_IDX_BA],
            accel,
            gyro,
            g,
            dt,
        )
        return np.concatenate([rot_log(R1.T @ Rt), pt - p1, vt - v1, d[_IDX_BG], d[_IDX_BA]])

    Phi = np.zeros((15, 15))
    for j in range(15):
        e = np.zeros(15)
        e[j] = h
        Phi[:, j] = (err_after(e) - err_after(-e)) / (2 * h)
    return Phi


#: Blocks whose first-order form omits a term of order dt^2: 0.5 dt^2 R[a]x, 0.5 dt^2 R and the
#: difference between -dt and -J_r(w dt) dt. Every other block of the 15-state transition is exact
#: to first order in the error, at any dt.
_SECOND_ORDER_BLOCKS = {
    "p,theta": (_IDX_P, _IDX_THETA),
    "p,b_a": (_IDX_P, _IDX_BA),
    "theta,b_g": (_IDX_THETA, _IDX_BG),
}


def test_transition_matrix_matches_the_nominal_propagation_to_first_order() -> None:
    """F agrees with the differenced nominal propagation, and its error shrinks as dt^2.

    One fixed tolerance would not say much, because the omitted terms differ per block. The
    test asserts the convergence rate instead: halving dt divides the error of each block that
    omits a second-order term by four, and every other block is exact.
    """
    rng = np.random.default_rng(5)
    eskf = _eskf_with_vision(anchor_modelled=True)
    R = rot_exp(rng.normal(size=3))
    p, v = rng.normal(size=3), rng.normal(size=3) * 3.0
    b_g, b_a = rng.normal(size=3) * 1e-3, rng.normal(size=3) * 1e-2
    accel = np.array([0.4, -0.3, 9.81]) + rng.normal(size=3)
    gyro = rng.normal(size=3) * 0.5

    def errors(dt: float) -> np.ndarray:
        F = eskf._transition(R, gyro - b_g, accel - b_a, dt)[:15, :15]
        return _numeric_transition(eskf, R, p, v, b_g, b_a, accel, gyro, dt) - F

    dt = 0.01
    e1, e2 = errors(dt), errors(dt / 2)
    covered = np.zeros((15, 15), bool)
    for name, (r, c) in _SECOND_ORDER_BLOCKS.items():
        n1, n2 = la.norm(e1[r, c]), la.norm(e2[r, c])
        assert n1 > 1e-7, f"{name}: no second-order error to measure"
        assert 3.6 < n1 / n2 < 4.4, f"{name}: error ratio {n1 / n2:.2f} at dt halving, expected 4"
        covered[r, c] = True
    assert np.abs(e1[~covered]).max() < 1e-8
    assert np.abs(e2[~covered]).max() < 1e-8


def test_a_declared_vertical_sigma_changes_only_the_vertical_weight():
    from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
    from navkit.io.imu import DEFAULT_NOISE

    def correction(vertical):
        f = ErrorStateKalmanFilter(EskfConfig(imu_noise=DEFAULT_NOISE, gnss_position_sigma_m=1.0))
        x = f._initial_state()
        f._gnss_update(x, np.array([1.0, 1.0, 1.0]), 1.0, sigma_vertical=vertical)
        return x["p"].copy()

    iso, vert = correction(None), correction(100.0)
    assert iso[0] == pytest.approx(iso[2], rel=1e-6)  # the same weight on every axis
    assert vert[:2] == pytest.approx(iso[:2], rel=1e-6)  # the horizontal update is untouched
    assert abs(vert[2]) < 0.01 * abs(iso[2])  # the height is nearly ignored


def test_the_vertical_sigma_is_serialised_whether_or_not_it_is_set():
    from navkit.estimators.eskf import EskfConfig
    from navkit.io.imu import DEFAULT_NOISE

    assert EskfConfig(imu_noise=DEFAULT_NOISE).as_dict()["gnss_vertical_sigma_m"] is None
    assert EskfConfig(imu_noise=DEFAULT_NOISE, gnss_vertical_sigma_m=50.0).as_dict()["gnss_vertical_sigma_m"] == 50.0
    a = EskfConfig(imu_noise=DEFAULT_NOISE, gnss_vertical_sigma_m=50.0)
    b = EskfConfig(imu_noise=DEFAULT_NOISE, gnss_vertical_sigma_m=60.0)
    assert a.as_dict() != b.as_dict()


def test_a_fix_variance_replaces_the_scalar_sigma_when_given():
    from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
    from navkit.io.imu import DEFAULT_NOISE

    def corrected(variance):
        f = ErrorStateKalmanFilter(EskfConfig(imu_noise=DEFAULT_NOISE, gnss_position_sigma_m=1.0))
        x = f._initial_state()
        f._gnss_update(x, np.array([1.0, 1.0, 1.0]), 1.0, variance=variance)
        return x["p"].copy()

    scalar = corrected(None)
    same = corrected(np.array([1.0, 1.0, 1.0]))
    loose = corrected(np.array([1.0e4, 1.0e4, 1.0e4]))
    mixed = corrected(np.array([1.0, 1.0, 1.0e4]))
    assert same == pytest.approx(scalar, rel=1e-9)
    assert np.all(np.abs(loose) < 0.01 * np.abs(scalar))
    assert mixed[:2] == pytest.approx(scalar[:2], rel=1e-6) and abs(mixed[2]) < 0.01 * abs(scalar[2])


def _fresh_gnss_filter():
    from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
    from navkit.io.imu import DEFAULT_NOISE

    f = ErrorStateKalmanFilter(EskfConfig(imu_noise=DEFAULT_NOISE, gnss_position_sigma_m=1.0))
    return f, f._initial_state()


def test_a_very_small_per_fix_variance_leaves_the_covariance_symmetric_and_semidefinite():
    """1e-12 m^2 is a near-exact fix. The update must stay finite and keep P a covariance."""
    f, x = _fresh_gnss_filter()
    ok, d2 = f._gnss_update(x, np.array([1.0, 1.0, 1.0]), 1.0, variance=np.full(3, 1.0e-12))
    P = x["P"]
    assert ok
    assert np.isfinite(d2), "the innovation test divided by zero or overflowed"
    assert np.all(np.isfinite(P))
    assert np.allclose(P, P.T, atol=1e-12)
    assert float(la.eigvalsh(0.5 * (P + P.T)).min()) > -1e-9
    assert np.all(np.isfinite(x["p"]))


def test_the_vertical_sigma_is_the_same_r_in_the_gate_and_in_the_update():
    """The innovation covariance the gate sees must contain the R the update uses."""
    sigma_v = 7.0
    f, x = _fresh_gnss_filter()
    P_before = x["P"].copy()
    f._gnss_update(x, np.array([0.1, 0.1, 0.1]), 1.0, sigma_vertical=sigma_v)
    _, _, S = f.gnss_innovations[-1]
    assert S[2, 2] == pytest.approx(P_before[5, 5] + sigma_v**2, rel=1e-12)
    assert S[0, 0] == pytest.approx(P_before[3, 3] + 1.0**2, rel=1e-12)
    assert S[0, 1] == pytest.approx(0.0, abs=1e-15)


def test_a_declared_vertical_sigma_decides_whether_a_height_jump_passes_the_gate():
    """With the same 12 m height residual, the declared sigma alone moves the verdict."""
    jump = np.array([0.0, 0.0, 12.0])
    f, x = _fresh_gnss_filter()
    tight_ok, _ = f._gnss_update(x, jump, 1.0)
    f, x = _fresh_gnss_filter()
    loose_ok, _ = f._gnss_update(x, jump, 1.0, sigma_vertical=20.0)
    assert not tight_ok, "a 12 m height jump against a 1 m sigma should be gated"
    assert loose_ok, "the gate did not use the declared vertical sigma"
