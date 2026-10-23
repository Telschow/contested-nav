"""The Gauss-Markov model of the correlated visual error (ADR-0034): ``EskfConfig.vision_gm_error``.

The model adds six error states to the stochastic clone: ``e_rot`` and ``e_trans``, one per axis of the rotation and
translation measurement. Each is a first-order Gauss-Markov process. The tests state what makes it that and nothing
more:

* the configuration is validated, refused where the ADR refuses it, and serialised (so the config hash covers it);
* with the flag off nothing changes: 21 states, no new statistics, the new settings have no effect;
* the propagation block is the exact discrete Gauss-Markov step, and it keeps a stationary variance stationary;
* the two new Jacobian columns are the exact derivative of the filter's own residual, and the old columns still are;
* the Joseph form holds with 27 states, the re-commit leaves the new states alone, and a correction is injected
  additively;
* on a stream whose visual error is the generator's autoregressive process, the model with the matching correlation
  time claims more uncertainty and is better scored than the filter without it. That is a sanity check that the model
  does what it says. It is not a gate claim, and it is run on development seeds 0 to 4 only.

The new names are read inside the tests, not imported at the top, so that on a tree without the feature each test
fails by itself.
"""

from __future__ import annotations

import copy
import math
from typing import ClassVar

import numpy as np
import pytest
import yaml

from navkit import benchmark
from navkit.b1_gate import window_arrays
from navkit.benchmark import _eskf_config, default_config_path, run_case
from navkit.degrade.config import scenario_from_dict
from navkit.estimators import eskf as eskf_mod
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.geometry.rigid import rot_exp, rot_right_jacobian
from navkit.io.imu import ImuNoiseModel

ER = slice(21, 24)
ET = slice(24, 27)
N_ON, N_OFF = 27, 21
GRID_TAU = (0.25, 0.5, 1.0, 2.0)
GRID_RHO = (0.5, 0.75, 0.9)
DEV_SEEDS = (0, 1, 2, 3, 4)
ROT_SIGMA_DEG, TRANS_SIGMA_M = 0.35, 0.05
#: Tolerance on the analytic against the numerical Jacobian columns of the new states. Measured: 1.3e-10 for e_rot and
#: 2.9e-11 for e_trans (central difference, step 1e-7), so this is 80 times the larger.
FD_TOL = 1e-8


# ---------------------------------------------------------------------------------------------- helpers


def _cfg(**kw):
    return EskfConfig(imu_noise=ImuNoiseModel(), gnss_enabled=False, vision_enabled=True, vision_model="clone", **kw)


def _off(**kw):
    return ErrorStateKalmanFilter(_cfg(**kw))


def _gm(tau=1.0, rho=0.5, **kw):
    return ErrorStateKalmanFilter(_cfg(vision_gm_error=True, vision_gm_tau_s=tau, vision_gm_rho=rho, **kw))


def _sigmas():
    return math.radians(ROT_SIGMA_DEG), TRANS_SIGMA_M


def _spd(n, seed):
    a = np.random.default_rng(seed).standard_normal((n, n))
    return a @ a.T / n + 0.05 * np.eye(n)


def _state(eskf, R_vk, p_vk, R, p, e_rot=None, e_trans=None):
    """A filter state with the keyframe set. ``P`` is a small multiple of the identity of the filter's size."""
    x = {
        "R": R.copy(),
        "p": p.copy(),
        "v": np.zeros(3),
        "b_a": np.zeros(3),
        "b_g": np.zeros(3),
        "R_vk": R_vk.copy(),
        "p_vk": p_vk.copy(),
        "c_p": np.zeros(3),
        "c_t": np.zeros(3),
        "P": np.eye(eskf._n) * 0.01,
        "vision_keyframe_set": True,
        "vision_updates": 0,
        "P_theta_vk": np.eye(3) * 0.01,
        "P_p_vk": np.eye(3) * 0.01,
    }
    if e_rot is not None:
        x["e_rot"], x["e_trans"] = np.array(e_rot, float), np.array(e_trans, float)
    return x


def _copy(x):
    return {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in x.items()}


def _with(x, **changes):
    y = _copy(x)
    y.update(changes)
    return y


def _unit(k):
    e = np.zeros(3)
    e[k] = 1.0
    return e


def _blocks(eskf, x, R_meas, t_meas):
    """The (z, H, R) the filter hands to ``_update`` for the rotation and the translation half."""
    seen = []

    def fake(_x, z, H, Rcov, **_k):
        seen.append((np.array(z, float), np.array(H, float), np.array(Rcov, float)))
        return True, 0.0

    eskf._update = fake
    try:
        eskf._vision_update(_copy(x), R_meas, t_meas, ROT_SIGMA_DEG, TRANS_SIGMA_M)
    finally:
        del eskf._update
    assert len(seen) == 2
    return seen


def _residual(eskf, x, R_meas, t_meas):
    (zr, _, _), (zt, _, _) = _blocks(eskf, x, R_meas, t_meas)
    return np.concatenate([zr, zt])


def _numeric(eskf, base, R_meas, t_meas, perturb, eps=1e-7):
    cols = [
        (
            _residual(eskf, perturb(base, k, +eps), R_meas, t_meas)
            - _residual(eskf, perturb(base, k, -eps), R_meas, t_meas)
        )
        / (2 * eps)
        for k in range(3)
    ]
    return np.column_stack(cols)


def _analytic(eskf, x, R_meas, t_meas, block):
    (_, Hr, _), (_, Ht, _) = _blocks(eskf, x, R_meas, t_meas)
    return np.vstack([Hr[:, block], Ht[:, block]])


E_ROT0 = np.array([0.07, -0.05, 0.09])  # radians: large enough that the left Jacobian is not the identity to 1e-3
E_TRANS0 = np.array([0.03, -0.02, 0.04])  # metres


def _setup(eskf):
    """A generic pose pair, a nonzero estimate of both Gauss-Markov states, and a rotation measurement that is exactly
    what the filter predicts, so that the Log has a vanishing residual and its derivative is the linearised one."""
    R_vk = rot_exp(np.array([0.21, -0.34, 0.47]))
    p_vk = np.array([1.7, -0.9, 0.35])
    R = R_vk @ rot_exp(np.array([-0.15, 0.28, 0.09]))
    p = p_vk + np.array([0.6, 0.25, -0.4])
    x = _state(eskf, R_vk, p_vk, R, p, E_ROT0, E_TRANS0)
    R_meas = (R_vk.T @ R) @ rot_exp(E_ROT0)
    t_meas = np.array([0.42, -0.17, 0.09])
    return x, R_meas, t_meas


def _short_case(name, estimator, seed=None):
    doc = yaml.safe_load(default_config_path().read_text())
    case = copy.deepcopy(doc["cases"][name])
    case["estimator"] = {**case.get("estimator", {}), **estimator}
    return case, doc["defaults"]


# ---------------------------------------------------------------------------------------------- config


def test_the_three_settings_are_off_by_default_and_the_defaults_are_inside_the_grid():
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.vision_gm_error is False
    assert cfg.vision_gm_tau_s in GRID_TAU
    assert cfg.vision_gm_rho in GRID_RHO


def test_the_three_settings_are_in_the_serialised_config_and_change_it():
    d = _cfg(vision_gm_error=True, vision_gm_tau_s=2.0, vision_gm_rho=0.9).as_dict()
    assert (d["vision_gm_error"], d["vision_gm_tau_s"], d["vision_gm_rho"]) == (True, 2.0, 0.9)
    base = _cfg().as_dict()
    assert base != d
    assert base != _cfg(vision_gm_tau_s=2.0).as_dict()  # the config hash covers them even with the flag off
    assert base != _cfg(vision_gm_rho=0.9).as_dict()


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("tau", [0.0, -1.0, float("nan"), float("inf")])
def test_a_correlation_time_that_is_not_finite_and_positive_is_refused(tau, flag):
    with pytest.raises(ValueError, match="vision_gm_tau_s"):
        _cfg(vision_gm_error=flag, vision_gm_tau_s=tau)


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("rho", [0.0, 1.0, -0.1, 1.5, float("nan")])
def test_a_correlated_share_outside_zero_to_one_is_refused(rho, flag):
    with pytest.raises(ValueError, match="vision_gm_rho"):
        _cfg(vision_gm_error=flag, vision_gm_rho=rho)


def test_the_flag_needs_the_clone_and_the_message_names_both_settings():
    with pytest.raises(ValueError) as err:
        EskfConfig(imu_noise=ImuNoiseModel(), vision_model="anchor", vision_gm_error=True)
    assert "vision_gm_error" in str(err.value) and "vision_model" in str(err.value)


def test_the_flag_is_refused_together_with_the_adaptive_scale_and_the_message_names_both_settings():
    with pytest.raises(ValueError) as err:
        _cfg(vision_gm_error=True, vision_adaptive_scale=True)
    assert "vision_gm_error" in str(err.value) and "vision_adaptive_scale" in str(err.value)


def _scenario():
    doc = yaml.safe_load(default_config_path().read_text())
    return scenario_from_dict(doc["cases"]["outage_visual_clone"]["scenario"])


def test_the_benchmark_refuses_the_flag_together_with_a_noise_preset_and_names_both_settings():
    keys = {"vision_model": "clone", "vision_gm_error": True, "vision_noise_preset": "measured-front-end"}
    with pytest.raises(ValueError) as err:
        _eskf_config(_scenario(), keys)
    assert "vision_gm_error" in str(err.value) and "vision_noise_preset" in str(err.value)


def test_the_benchmark_passes_the_three_settings_on_and_leaves_the_defaults_when_they_are_absent():
    keys = {"vision_model": "clone", "vision_gm_error": True, "vision_gm_tau_s": 2, "vision_gm_rho": 0.9}
    cfg = _eskf_config(_scenario(), keys)
    assert (cfg.vision_gm_error, cfg.vision_gm_tau_s, cfg.vision_gm_rho) == (True, 2.0, 0.9)
    plain = _eskf_config(_scenario(), {"vision_model": "clone"})
    assert plain.vision_gm_error is False
    assert (plain.vision_gm_tau_s, plain.vision_gm_rho) == (1.0, 0.5)


# ----------------------------------------------------------------------------- the size of the state


def test_the_new_states_are_appended_after_the_clone_blocks():
    assert eskf_mod._IDX_ER == ER and eskf_mod._IDX_ET == ET
    assert eskf_mod._N_STATES == N_OFF  # kept for the tests and for back-compat
    assert _gm()._n == N_ON and _off()._n == N_OFF


def test_with_the_flag_off_every_array_is_21_by_21_and_the_state_has_no_new_entries():
    f = _off()
    assert f._initial_covariance().shape == (N_OFF, N_OFF)
    assert f._process_noise(0.01).shape == (N_OFF, N_OFF)
    assert ErrorStateKalmanFilter._transition(np.eye(3), np.zeros(3), np.zeros(3), 0.01).shape == (N_OFF, N_OFF)
    x = f._initial_state()
    assert "e_rot" not in x and "e_trans" not in x
    f._propagate(x, np.array([0.0, 0.0, 9.80665]), np.zeros(3), 0.01)
    assert x["P"].shape == (N_OFF, N_OFF)


def test_with_the_flag_on_every_array_is_27_by_27():
    f = _gm()
    assert f._initial_covariance().shape == (N_ON, N_ON)
    assert f._process_noise(0.01).shape == (N_ON, N_ON)
    x = f._initial_state()
    assert x["e_rot"].shape == (3,) and x["e_trans"].shape == (3,)
    assert not np.any(x["e_rot"]) and not np.any(x["e_trans"])  # the states start at zero
    f._propagate(x, np.array([0.0, 0.0, 9.80665]), np.zeros(3), 0.01)
    assert x["P"].shape == (N_ON, N_ON)


def test_the_initial_covariance_of_the_new_blocks_is_the_stationary_one_and_the_old_block_is_unchanged():
    rho = 0.75
    P, P0 = _gm(rho=rho)._initial_covariance(), _off()._initial_covariance()
    sr, st = _sigmas()
    assert np.array_equal(P[:N_OFF, :N_OFF], P0)
    assert np.allclose(P[ER, ER], rho * sr**2 * np.eye(3), rtol=1e-12, atol=0.0)
    assert np.allclose(P[ET, ET], rho * st**2 * np.eye(3), rtol=1e-12, atol=0.0)
    assert not np.any(P[N_OFF:, :N_OFF]) and not np.any(P[ER, ET])


# ------------------------------------------------------------------------------------- propagation

ACCEL_AT_REST = np.array([0.0, 0.0, 9.80665])  # specific force that cancels gravity: nothing else moves


@pytest.mark.parametrize(("tau", "dt"), [(1.0, 0.01), (0.25, 0.05), (2.0, 1.0), (0.5, 0.25)])
def test_an_isolated_gauss_markov_block_evolves_as_a2_p_plus_sigma2_one_minus_a2(tau, dt):
    """One step of dt gives ``a^2 P + sigma_e^2 (1 - a^2)`` with ``a = exp(-dt / tau)``, the exact exponential.

    The last two parameters have dt / tau of 0.5 and 2, where ``1 - dt / tau`` is a poor stand-in for the exponential.
    """
    rho = 0.75
    f = _gm(tau=tau, rho=rho)
    sr, st = _sigmas()
    a = math.exp(-dt / tau)
    for block, sigma in ((ER, sr), (ET, st)):
        x = f._initial_state()
        p0 = 3.0 * rho * sigma**2  # not the stationary value
        x["P"][block, block] = np.eye(3) * p0
        f._propagate(x, ACCEL_AT_REST, np.zeros(3), dt)
        want = a**2 * p0 + rho * sigma**2 * (1.0 - a**2)
        assert np.allclose(x["P"][block, block], want * np.eye(3), rtol=1e-12, atol=0.0)
        assert not np.any(x["P"][N_OFF:, :N_OFF]), "no coupling between the new states and the others"
    x = f._initial_state()
    x["e_rot"], x["e_trans"] = np.array([0.1, -0.2, 0.3]), np.array([0.4, 0.5, -0.6])
    f._propagate(x, ACCEL_AT_REST, np.zeros(3), dt)
    assert np.allclose(x["e_rot"], a * np.array([0.1, -0.2, 0.3]), rtol=1e-14)
    assert np.allclose(x["e_trans"], a * np.array([0.4, 0.5, -0.6]), rtol=1e-14)


def test_the_process_noise_of_the_new_blocks_is_the_stationary_variance_times_one_minus_a2():
    f = _gm(tau=0.5, rho=0.5)
    sr, st = _sigmas()
    dt = 0.5  # a = exp(-1)
    a2 = math.exp(-2.0)
    Q = f._process_noise(dt)
    assert np.allclose(Q[ER, ER], 0.5 * sr**2 * (1.0 - a2) * np.eye(3), rtol=1e-12, atol=0.0)
    assert np.allclose(Q[ET, ET], 0.5 * st**2 * (1.0 - a2) * np.eye(3), rtol=1e-12, atol=0.0)
    assert np.array_equal(Q[:N_OFF, :N_OFF], _off()._process_noise(dt))


def test_a_stationary_variance_stays_stationary_to_rounding():
    f = _gm(tau=0.5, rho=0.9)
    x = f._initial_state()
    P0 = x["P"].copy()
    for _ in range(2000):
        f._propagate(x, ACCEL_AT_REST, np.zeros(3), 0.01)
    assert np.allclose(x["P"][ER, ER], P0[ER, ER], rtol=1e-10, atol=0.0)
    assert np.allclose(x["P"][ET, ET], P0[ET, ET], rtol=1e-10, atol=0.0)


def test_a_variance_away_from_the_stationary_one_relaxes_to_it():
    f = _gm(tau=0.5, rho=0.5)
    x = f._initial_state()
    sr, _ = _sigmas()
    x["P"][ER, ER] = np.eye(3) * 10.0 * 0.5 * sr**2
    for _ in range(1000):  # 10 s is 20 correlation times
        f._propagate(x, ACCEL_AT_REST, np.zeros(3), 0.01)
    assert np.allclose(x["P"][ER, ER], 0.5 * sr**2 * np.eye(3), rtol=1e-6, atol=0.0)


# ------------------------------------------------------------------------------------- the Jacobians


def test_the_rotation_measurement_has_the_exact_derivative_with_respect_to_e_rot():
    """``R_meas = R_rel Exp(e)`` (the generator applies the rotation noise on the right of the true relative rotation),
    so the residual ``Log(R_meas (R_rel_pred Exp(e_hat))^T)`` gives ``dz/de = -R_rel_pred J_l(e_hat)``.

    ``R_rel_pred`` alone, the first-order form, is off by about 5e-2 here, and the identity by 0.26. The tolerance is
    1e-8, 80 times the disagreement measured between the analytic and the numerical column (1.3e-10 at a step of
    1e-7, on one machine) and 5e6 times smaller than what the first-order form would show.
    """
    f = _gm()
    x, Rm, tm = _setup(f)
    num = _numeric(f, x, Rm, tm, lambda b, k, e: _with(b, e_rot=b["e_rot"] + e * _unit(k)))
    ana = _analytic(f, x, Rm, tm, ER)
    assert np.allclose(ana[:3], -num[:3], atol=FD_TOL, rtol=0.0)
    assert np.allclose(num[3:], 0.0, atol=FD_TOL), "e_rot does not enter the translation residual"
    R_rel = x["R_vk"].T @ x["R"]
    assert np.allclose(ana[:3], R_rel @ rot_right_jacobian(-E_ROT0), atol=1e-12)  # J_l(e) = J_r(-e)
    assert np.abs(ana[:3] - R_rel).max() > 1e-2 and np.abs(ana[:3] - np.eye(3)).max() > 1e-2


def test_the_translation_measurement_has_the_exact_derivative_with_respect_to_e_trans_in_the_previous_frame():
    """The generator adds the translation noise to ``t_rel``, which is expressed in the previous frame, so the column
    is the identity and not ``R_vk^T``. ``R_vk`` is a generic rotation here, so a column in the wrong frame fails."""
    f = _gm()
    x, Rm, tm = _setup(f)
    num = _numeric(f, x, Rm, tm, lambda b, k, e: _with(b, e_trans=b["e_trans"] + e * _unit(k)))
    ana = _analytic(f, x, Rm, tm, ET)
    assert np.allclose(ana[3:], -num[3:], atol=FD_TOL, rtol=0.0)
    assert np.allclose(num[:3], 0.0, atol=FD_TOL), "e_trans does not enter the rotation residual"
    assert np.array_equal(ana[3:], np.eye(3))
    assert np.abs(x["R_vk"].T - np.eye(3)).max() > 0.1


@pytest.mark.parametrize(
    ("name", "block", "perturb"),
    [
        ("theta", eskf_mod._IDX_THETA, lambda b, k, e: _with(b, R=b["R"] @ rot_exp(e * _unit(k)))),
        ("p", eskf_mod._IDX_P, lambda b, k, e: _with(b, p=b["p"] + e * _unit(k))),
        ("c_t", eskf_mod._IDX_CT, lambda b, k, e: _with(b, R_vk=b["R_vk"] @ rot_exp(e * _unit(k)))),
        ("c_p", eskf_mod._IDX_CP, lambda b, k, e: _with(b, p_vk=b["p_vk"] + e * _unit(k))),
    ],
)
def test_the_existing_clone_columns_are_still_the_exact_derivative_with_the_flag_on(name, block, perturb):
    f = _gm()
    x, _, tm = _setup(f)
    # for a perturbation of the pose the rotation measurement must stay the exact prediction, so it is rebuilt
    Rm = (x["R_vk"].T @ x["R"]) @ rot_exp(E_ROT0)
    num = _numeric(f, x, Rm, tm, perturb)
    assert np.allclose(_analytic(f, x, Rm, tm, block), -num, atol=1e-5), name


def test_the_old_columns_and_the_old_residuals_are_those_of_the_filter_without_the_model_when_the_estimates_are_zero():
    on, off = _gm(), _off()
    x_on, Rm, tm = _setup(on)
    x_on["e_rot"], x_on["e_trans"] = np.zeros(3), np.zeros(3)
    x_off, _, _ = _setup(off)
    Rm = x_on["R_vk"].T @ x_on["R"]
    (zr1, Hr1, _), (zt1, Ht1, _) = _blocks(on, x_on, Rm, tm)
    (zr0, Hr0, _), (zt0, Ht0, _) = _blocks(off, x_off, Rm, tm)
    assert np.array_equal(Hr1[:, :N_OFF], Hr0) and np.array_equal(Ht1[:, :N_OFF], Ht0)
    assert np.array_equal(zr1, zr0) and np.array_equal(zt1, zt0)


def test_the_new_columns_are_zero_in_the_other_half_and_the_white_covariance_is_one_minus_rho_of_the_total():
    rho = 0.75
    f = _gm(rho=rho)
    x, Rm, tm = _setup(f)
    (_, Hr, Rr), (_, Ht, Rt) = _blocks(f, x, Rm, tm)
    assert Hr.shape == Ht.shape == (3, N_ON)
    assert not np.any(Hr[:, ET]) and not np.any(Ht[:, ER])
    sr, st = _sigmas()
    assert np.allclose(Rr, (1.0 - rho) * sr**2 * np.eye(3), rtol=1e-12, atol=0.0)
    assert np.allclose(Rt, (1.0 - rho) * st**2 * np.eye(3), rtol=1e-12, atol=0.0)
    # the total declared variance of each block is unchanged: white part plus the stationary Gauss-Markov part
    assert np.allclose(Rr + rho * sr**2 * np.eye(3), sr**2 * np.eye(3), rtol=1e-12, atol=0.0)


def test_the_residual_includes_the_current_estimate_of_the_correlated_error():
    f = _gm()
    x, Rm, tm = _setup(f)
    (zr, _, _), (zt, _, _) = _blocks(f, x, Rm, tm)
    assert np.allclose(zr, 0.0, atol=1e-12)  # the measurement is the prediction including e_rot
    R_vk, p_vk, p = x["R_vk"], x["p_vk"], x["p"]
    assert np.allclose(zt, tm - R_vk.T @ (p - p_vk) - E_TRANS0, atol=1e-14)


# ------------------------------------------------------------------ the Joseph form and the reset


def test_a_correction_is_injected_additively_into_the_new_states():
    f = _gm()
    x = f._initial_state()
    x["e_rot"], x["e_trans"] = np.array([0.1, 0.2, 0.3]), np.array([0.4, 0.5, 0.6])
    dx = np.zeros(N_ON)
    dx[ER] = [0.01, -0.02, 0.03]
    dx[ET] = [-0.04, 0.05, -0.06]
    x["P"] = _spd(N_ON, 1)
    f._inject_correction(x, np.eye(N_ON), dx.copy(), np.zeros((N_ON, N_ON)), np.zeros((N_ON, N_ON)))
    assert np.allclose(x["e_rot"], [0.11, 0.18, 0.33], atol=1e-15)
    assert np.allclose(x["e_trans"], [0.36, 0.55, 0.54], atol=1e-15)


def test_the_attitude_reset_does_not_touch_the_new_states_and_acts_on_their_cross_terms_like_any_other_state():
    f = _gm()
    x = f._initial_state()
    P0 = _spd(N_ON, 2)
    x["P"] = P0.copy()
    dx = np.zeros(N_ON)
    dx[eskf_mod._IDX_THETA] = [0.2, -0.1, 0.15]
    dx[eskf_mod._IDX_CT] = [-0.05, 0.1, 0.02]
    f._inject_correction(x, np.eye(N_ON), dx, np.zeros((N_ON, N_ON)), np.zeros((N_ON, N_ON)))
    G = eskf_mod._reset_jacobian(dx, clone=True, n=N_ON)
    assert G.shape == (N_ON, N_ON)
    assert np.array_equal(G[N_OFF:, :], np.eye(N_ON)[N_OFF:, :]) and np.array_equal(
        G[:, N_OFF:], np.eye(N_ON)[:, N_OFF:]
    )
    assert np.allclose(x["P"][ER, ER], P0[ER, ER], rtol=1e-12, atol=0.0)  # untouched
    assert np.allclose(x["P"][ET, ET], P0[ET, ET], rtol=1e-12, atol=0.0)
    th = eskf_mod._IDX_THETA
    assert np.allclose(x["P"][ER, th], P0[ER, th] @ G[th, th].T, rtol=1e-12, atol=1e-15)  # as any other state's


def test_the_reset_jacobian_keeps_its_old_size_by_default():
    assert eskf_mod._reset_jacobian(np.zeros(N_OFF)).shape == (N_OFF, N_OFF)


class _Recording(ErrorStateKalmanFilter):
    """Records how far the covariance is from symmetric and from positive semidefinite after every correction."""

    log: ClassVar[list[tuple[float, float, float, int]]] = []

    def _inject_correction(self, x, K, residual, H, Rcov):
        super()._inject_correction(x, K, residual, H, Rcov)
        P = x["P"]
        scale = float(np.abs(P).max())
        asym = float(np.abs(P - P.T).max()) / scale
        low = float(np.linalg.eigvalsh(0.5 * (P + P.T)).min()) / scale
        type(self).log.append((asym, low, float(np.diag(P).min()), P.shape[0]))


def test_the_covariance_stays_symmetric_and_positive_semidefinite_over_a_clone_run_with_27_states(monkeypatch):
    """Joseph form with the new states. The scale of P is the largest entry, so the eigenvalue is read relative to it.

    Tolerances are stated from the values measured on this run (429 corrections, one machine): the asymmetry is at most
    5.2e-14 of the scale, so the bound is 1e-12; no eigenvalue is negative (the smallest is exactly 0, from the states
    that start with no variance), so the bound is -1e-12 of the scale. A covariance update that lost the Joseph form
    would show a negative eigenvalue many orders above that.
    """
    _Recording.log = []
    monkeypatch.setattr(benchmark, "ErrorStateKalmanFilter", _Recording)
    case, defaults = _short_case(
        "outage_visual_clone_correlated",
        {"vision_gm_error": True, "vision_gm_tau_s": 2.0, "vision_gm_rho": 0.9},
    )
    defaults["synthetic"]["duration_s"] = 10.0
    case["scenario"]["gnss_outages"] = [{"start_s": 3.0, "duration_s": 4.0, "reason": "contested"}]
    record = run_case("outage_visual_clone_correlated", case, defaults, seed=0)
    assert record["stats"]["vision_updates_used"] > 100
    log = np.array(_Recording.log)
    assert len(log) > 300
    assert np.all(log[:, 3] == N_ON), "the run really used the 27-state filter"
    assert log[:, 0].max() <= 1e-12
    assert log[:, 1].min() >= -1e-12
    assert log[:, 2].min() >= 0.0


# ------------------------------------------------------------------------------------ the re-commit


def test_the_clone_re_commit_does_not_alter_the_new_states_or_their_covariance_blocks():
    f = _gm()
    P = _spd(N_ON, 3)
    before = P.copy()
    f._commit_anchor_covariance(P)
    live = np.r_[0:15]
    e = np.r_[N_OFF:N_ON]
    assert np.array_equal(P[np.ix_(e, e)], before[np.ix_(e, e)])  # the Gauss-Markov blocks, bit for bit
    assert np.array_equal(P[np.ix_(e, live)], before[np.ix_(e, live)])  # and their correlation with the live state
    # the clone is rebuilt from the live pose, so its correlation with the new states is the live pose's
    assert np.array_equal(P[eskf_mod._IDX_CP, ER], before[eskf_mod._IDX_P, ER])
    assert np.array_equal(P[eskf_mod._IDX_CT, ET], before[eskf_mod._IDX_THETA, ET])


def test_a_full_clone_update_leaves_the_estimates_of_the_new_states_where_the_correction_put_them():
    f = _gm()
    x, Rm, tm = _setup(f)
    x["P"] = _spd(N_ON, 4)
    e_rot, e_trans = x["e_rot"].copy(), x["e_trans"].copy()
    P_ee = x["P"][np.r_[N_OFF:N_ON], :][:, np.r_[N_OFF:N_ON]].copy()

    def accept(_x, _z, _H, _R, **_k):  # the update itself is not the subject: only what the re-commit does
        return True, 0.0

    f._update = accept
    f._vision_update_clone(x, Rm, tm, ROT_SIGMA_DEG, TRANS_SIGMA_M, 0.0)
    assert np.array_equal(x["e_rot"], e_rot) and np.array_equal(x["e_trans"], e_trans)
    assert np.array_equal(x["P"][np.r_[N_OFF:N_ON], :][:, np.r_[N_OFF:N_ON]], P_ee)
    assert np.array_equal(x["R_vk"], x["R"]) and np.array_equal(x["p_vk"], x["p"])  # the clone did re-commit


# -------------------------------------------------------------------------------- run statistics


def test_with_the_flag_off_a_clone_case_has_no_gauss_markov_statistics_and_ignores_tau_and_rho():
    case, defaults = _short_case("outage_visual_clone", {})
    a = run_case("outage_visual_clone", case, defaults, seed=0)
    case2, _ = _short_case("outage_visual_clone", {"vision_gm_tau_s": 0.25, "vision_gm_rho": 0.9})
    b = run_case("outage_visual_clone", case2, defaults, seed=0)
    assert not [k for k in a["stats"] if k.startswith("vision_gm_")]
    assert not [k for k in a["summary"] if k.startswith("vision_gm_")]
    assert a["stats"].keys() == b["stats"].keys()
    for k in a["stats"]:
        if k != "realtime_factor":
            assert a["stats"][k] == b["stats"][k], k
    assert a["headline"] == b["headline"] and a["error_time_series"] == b["error_time_series"]


GM_STATS = (
    "vision_gm_rot_state_rms",
    "vision_gm_trans_state_rms",
    "vision_gm_rot_std_final",
    "vision_gm_trans_std_final",
)


def test_with_the_flag_on_the_run_reports_four_statistics_and_nothing_else_is_added():
    base_case, defaults = _short_case("outage_visual_clone", {})
    on_case, _ = _short_case("outage_visual_clone", {"vision_gm_error": True, "vision_gm_tau_s": 0.25})
    a = run_case("outage_visual_clone", base_case, defaults, seed=0)
    b = run_case("outage_visual_clone", on_case, defaults, seed=0)
    assert set(b["stats"]) - set(a["stats"]) == set(GM_STATS)
    assert set(a["stats"]) - set(b["stats"]) == set()
    for k in GM_STATS:
        assert math.isfinite(b["stats"][k]) and b["stats"][k] > 0.0, k


def test_the_statistics_are_exact_when_no_visual_update_arrives():
    """No vision: the estimates stay zero, so their RMS is zero, and the final standard deviation is the stationary
    one, ``sqrt(rho) * sigma``, because a stationary variance stays stationary."""
    rho = 0.75
    case, defaults = _short_case(
        "outage_visual_clone",
        {"vision_fuse": False, "vision_gm_error": True, "vision_gm_tau_s": 0.5, "vision_gm_rho": rho},
    )
    stats = run_case("outage_visual_clone", case, defaults, seed=0)["stats"]
    sr, st = _sigmas()
    assert stats["vision_gm_rot_state_rms"] == 0.0 and stats["vision_gm_trans_state_rms"] == 0.0
    assert stats["vision_gm_rot_std_final"] == pytest.approx(math.sqrt(rho) * sr, rel=1e-9)
    assert stats["vision_gm_trans_std_final"] == pytest.approx(math.sqrt(rho) * st, rel=1e-9)


def test_the_same_case_twice_gives_identical_statistics():
    est = {"vision_gm_error": True, "vision_gm_tau_s": 2.0, "vision_gm_rho": 0.9}
    case, defaults = _short_case("outage_visual_clone_correlated", est)
    a = run_case("outage_visual_clone_correlated", case, defaults, seed=1)
    b = run_case("outage_visual_clone_correlated", case, defaults, seed=1)
    assert set(GM_STATS) <= set(a["stats"])
    for k in a["stats"]:
        if k != "realtime_factor":
            assert a["stats"][k] == b["stats"][k], k
    assert a["headline"] == b["headline"]
    assert a["config_hash"] == b["config_hash"]


# ------------------------------------------------------------- the model helps on a known error


#: Margins for the consistency check, from the values measured on seeds 0 to 4 on one machine, before they were set:
#: the claimed sigma over the outage window rose by a factor of 3.46 to 4.05, and the window NEES fell to between 0.009
#: and 0.165 of the value without the model. The bounds sit well inside those, so the test does not move with a
#: platform's rounding. The reason for the direction: the plain clone averages a correlated error down as if it were
#: independent, so its position covariance is too small and its NEES too large; the model keeps the correlated part in
#: the state and does not average it down.
MIN_CLAIMED_RATIO = 2.0
MAX_NEES_RATIO = 0.5


def _window_score(estimator, seed):
    """Mean claimed sigma and mean NEES over the outage window of S2 (visual error correlated over 2 s)."""
    case, defaults = _short_case("outage_visual_clone_correlated", estimator)
    box = {}
    run_case("outage_visual_clone_correlated", case, defaults, seed=seed, nees_out=box)
    w = window_arrays(box)
    return float(np.mean(w["sigma"])), float(np.mean(w["nees"]))


def test_on_a_stream_with_the_generators_correlated_error_the_model_claims_more_and_is_better_scored():
    """Seeds 0 to 4 only. The visual error of S2 is the generator's AR(1) process with a correlation time of 2 s. The
    filter with the model at the matching ``tau`` and ``rho = 0.9`` (a point of the ADR-0034 grid) is compared with the
    same filter without it. This checks that the model does what it says; it is not a gate claim."""
    on = {"vision_gm_error": True, "vision_gm_tau_s": 2.0, "vision_gm_rho": 0.9}
    claimed_ratio, nees_ratio = [], []
    for seed in DEV_SEEDS:
        sigma_off, nees_off = _window_score({}, seed)
        sigma_on, nees_on = _window_score(on, seed)
        claimed_ratio.append(sigma_on / sigma_off)
        nees_ratio.append(nees_on / nees_off)
    assert min(claimed_ratio) > MIN_CLAIMED_RATIO, claimed_ratio
    assert max(nees_ratio) < MAX_NEES_RATIO, nees_ratio
