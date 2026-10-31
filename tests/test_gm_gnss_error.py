"""The optional Gauss-Markov model of a time-correlated GNSS error (issue #244, in the style of ADR-0034).

``EskfConfig.gnss_gm_error`` adds three error states, ``e_gnss``, one per axis of the GNSS position. Each is a
first-order Gauss-Markov process with the declared correlation time and stationary standard deviation, and the GNSS
measurement becomes ``p + e + n``. The tests state what makes it that and nothing more:

* off by default, refused with the visual Gauss-Markov model, and part of the serialised config only when on;
* with it off the output is byte-identical, whatever the two other settings say;
* the propagation is the exact discrete Gauss-Markov step, and the GNSS Jacobian has a unit column on the new states;
* on a synthetic first-order error with the declared correlation time, the filter that models it claims more
  uncertainty and is better scored than the one that does not.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.io.imu import ImuNoiseModel
from navkit.types import GnssFix, ImuSample

EG = slice(21, 24)


def _cfg(**kw):
    return EskfConfig(imu_noise=ImuNoiseModel(), gnss_position_sigma_m=0.5, **kw)


def _gm(tau=30.0, sigma=1.5, **kw):
    return ErrorStateKalmanFilter(_cfg(gnss_gm_error=True, gnss_gm_tau_s=tau, gnss_gm_sigma_m=sigma, **kw))


def test_off_by_default_and_not_in_the_serialised_config():
    cfg = _cfg()
    assert cfg.gnss_gm_error is False
    assert not any(k.startswith("gnss_gm") for k in cfg.as_dict())
    on = _cfg(gnss_gm_error=True).as_dict()
    assert on["gnss_gm_tau_s"] == cfg.gnss_gm_tau_s
    assert on["gnss_gm_sigma_m"] == cfg.gnss_gm_sigma_m


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_bad_correlation_time_or_amplitude_is_refused(bad):
    with pytest.raises(ValueError, match="gnss_gm_tau_s"):
        _cfg(gnss_gm_tau_s=bad)
    with pytest.raises(ValueError, match="gnss_gm_sigma_m"):
        _cfg(gnss_gm_sigma_m=bad)


def test_it_is_refused_together_with_the_visual_model_and_the_message_names_both():
    with pytest.raises(ValueError, match=r"gnss_gm_error.*vision_gm_error"):
        _cfg(gnss_gm_error=True, vision_gm_error=True, vision_model="clone", vision_enabled=True)


def test_state_sizes():
    off = ErrorStateKalmanFilter(_cfg())
    on = _gm()
    assert off._initial_covariance().shape == (21, 21)
    assert "e_gnss" not in off._initial_state()
    assert on._initial_covariance().shape == (24, 24)
    assert np.all(on._initial_state()["e_gnss"] == 0.0)


def test_initial_variance_is_the_stationary_one():
    p0 = _gm(sigma=1.5)._initial_covariance()
    assert np.allclose(p0[EG, EG], np.eye(3) * 1.5**2)
    assert np.all(p0[EG, :21] == 0.0)


@pytest.mark.parametrize(("tau", "dt"), [(30.0, 0.005), (5.0, 0.2), (0.5, 1.0)])
def test_propagation_is_the_exact_gauss_markov_step(tau, dt):
    f = _gm(tau=tau, sigma=1.5)
    x = f._initial_state()
    x["e_gnss"] = np.array([1.0, -2.0, 0.5])
    p_block = x["P"][EG, EG].copy()
    f._propagate(x, np.array([0.0, 0.0, -9.81]), np.zeros(3), dt)
    a = math.exp(-dt / tau)
    assert np.allclose(x["e_gnss"], a * np.array([1.0, -2.0, 0.5]))
    assert np.allclose(x["P"][EG, EG], a**2 * p_block + 1.5**2 * (1 - a**2) * np.eye(3))


def test_the_gnss_jacobian_has_a_unit_column_on_the_new_states_and_the_residual_ignores_them_when_zero():
    f = _gm()
    x = f._initial_state()
    seen = {}

    def spy(x_, residual, H, Rcov, sensor="unknown", t_s=0.0):
        seen.update(H=H.copy(), residual=residual.copy())
        return True, 0.0

    f._update = spy  # type: ignore[method-assign]
    f._gnss_update(x, np.array([1.0, 2.0, 3.0]), 0.5)
    assert seen["H"].shape == (3, 24)
    assert np.array_equal(seen["H"][:, 3:6], np.eye(3))
    assert np.array_equal(seen["H"][:, EG], np.eye(3))
    assert np.array_equal(seen["residual"], [1.0, 2.0, 3.0])
    x["e_gnss"] = np.array([0.5, 0.0, 0.0])
    f._gnss_update(x, np.array([1.0, 2.0, 3.0]), 0.5)
    assert np.array_equal(seen["residual"], [0.5, 2.0, 3.0])


def test_a_correction_is_injected_additively_into_the_new_states():
    f = _gm()
    x = f._initial_state()
    H = np.zeros((3, 24))
    H[:, 3:6] = np.eye(3)
    H[:, EG] = np.eye(3)
    P = x["P"]
    S = H @ P @ H.T + np.eye(3) * 0.25
    K = f._kalman_gain(P, H, S)
    res = np.array([1.0, 0.0, 0.0])
    f._inject_correction(x, K, res, H, np.eye(3) * 0.25)
    assert np.allclose(x["e_gnss"], (K @ res)[EG])
    assert np.linalg.eigvalsh(x["P"]).min() > -1e-12


# ------------------------------------------------------------------------------------------- run level


def _static_stream(seed, n_s=300, tau=30.0, sigma=1.5, white=0.3):
    """A stationary receiver at the origin with a first-order Gauss-Markov error on every fix (1 Hz)."""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, n_s, 0.05)
    imu = ImuSample(t=t, accel=np.tile([0.0, 0.0, -9.80665], (len(t), 1)), gyro=np.zeros((len(t), 3)), name="static")
    tg = np.arange(1.0, n_s, 1.0)
    a = math.exp(-1.0 / tau)
    e = np.zeros((len(tg), 3))
    e[0] = rng.normal(0, sigma, 3)
    for k in range(1, len(tg)):
        e[k] = a * e[k - 1] + math.sqrt(1 - a * a) * sigma * rng.normal(size=3)
    pos = e + rng.normal(0, white, e.shape)
    return imu, GnssFix(t=tg, positions=pos, name="gm")


def test_with_it_off_the_output_is_byte_identical_whatever_the_other_two_settings_say():
    imu, gnss = _static_stream(0, n_s=60)
    a = ErrorStateKalmanFilter(_cfg()).run(imu, gnss=gnss)
    b = ErrorStateKalmanFilter(_cfg(gnss_gm_tau_s=3.0, gnss_gm_sigma_m=9.0)).run(imu, gnss=gnss)
    assert a.trajectory.poses.tobytes() == b.trajectory.poses.tobytes()
    assert a.position_cov.tobytes() == b.position_cov.tobytes()


def test_the_run_reports_the_state_statistics_only_when_on():
    imu, gnss = _static_stream(0, n_s=60)
    off = ErrorStateKalmanFilter(_cfg()).run(imu, gnss=gnss)
    on = _gm().run(imu, gnss=gnss)
    assert not any(k.startswith("gnss_gm") for k in off.stats)
    assert {"gnss_gm_state_rms", "gnss_gm_std_final"} <= set(on.stats)


def test_a_filter_that_models_the_correlated_error_stays_consistent_where_the_one_without_it_does_not():
    """The filter without the term rejects most fixes on this stream and drifts away. With it, the NEES is sane."""
    nees, rejected = [], {False: 0.0, True: 0.0}
    for seed in range(5):
        imu, gnss = _static_stream(seed)
        for flag in (False, True):
            res = (_gm() if flag else ErrorStateKalmanFilter(_cfg())).run(imu, gnss=gnss)
            rejected[flag] += res.stats["gnss_updates_rejected"]
            if flag:
                err = res.trajectory.poses[:, :3, 3][1000:, :2]
                cov = res.position_cov[1000:, :2, :2]
                nees.append(float(np.mean(np.einsum("ni,ni->n", err, np.linalg.solve(cov, err[..., None])[..., 0]))))
    assert rejected[False] > 100 * max(rejected[True], 1.0)
    assert float(np.mean(nees)) < 6.0
