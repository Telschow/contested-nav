"""The stochastic-clone visual model (blocker B1 spike): ``EskfConfig.vision_model = "clone"``.

The Jacobians are checked against numerical derivatives of the filter's own residual, the way the anchor
model's are. The structural tests state what makes a clone a clone: it starts perfectly correlated with the
live pose, a measurement taken straight after the commit carries no information, and the covariance stays a
valid covariance. Nothing here says the model closes B1; the sweeps do, and the changelog says what they found.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
import yaml

from navkit.benchmark import default_config_path, run_case
from navkit.estimators.eskf import (
    _IDX_CP,
    _IDX_CT,
    _IDX_P,
    _IDX_THETA,
    _N_STATES,
    ErrorStateKalmanFilter,
    EskfConfig,
)
from navkit.geometry.rigid import rot_exp
from navkit.io.imu import ImuNoiseModel

_EPS = 1e-7


def _eskf(model: str = "clone", **kw) -> ErrorStateKalmanFilter:
    return ErrorStateKalmanFilter(
        EskfConfig(imu_noise=ImuNoiseModel(), gnss_enabled=False, vision_enabled=True, vision_model=model, **kw)
    )


def _state(R_vk, p_vk, R, p) -> dict:
    return {
        "R": R.copy(),
        "p": p.copy(),
        "R_vk": R_vk.copy(),
        "p_vk": p_vk.copy(),
        "c_p": np.zeros(3),
        "c_t": np.zeros(3),
        "P": np.eye(_N_STATES) * 0.01,
        "vision_keyframe_set": True,
        "vision_updates": 0,
        "P_theta_vk": np.eye(3) * 0.01,
        "P_p_vk": np.eye(3) * 0.01,
    }


def _blocks(eskf, x, R_meas, t_meas):
    seen: list[tuple[np.ndarray, np.ndarray]] = []

    def fake(_x, z, H, _R, **_k):
        seen.append((np.array(z, float), np.array(H, float)))
        return True, 0.0

    eskf._update = fake
    try:
        eskf._vision_update(
            {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in x.items()}, R_meas, t_meas, 0.35, 0.05
        )
    finally:
        del eskf._update
    assert len(seen) == 2
    return seen


def _residual(eskf, x, R_meas, t_meas):
    (zr, _), (zt, _) = _blocks(eskf, x, R_meas, t_meas)
    return np.concatenate([zr, zt])


def _setup():
    R_vk = rot_exp(np.array([0.21, -0.34, 0.47]))
    p_vk = np.array([1.7, -0.9, 0.35])
    R = R_vk @ rot_exp(np.array([-0.15, 0.28, 0.09]))
    p = p_vk + np.array([0.6, 0.25, -0.4])
    # The rotation residual is a Log, whose derivative equals the linearised Jacobian only where the residual
    # vanishes, so the rotation measurement is the exact prediction. The translation one is linear and is not.
    R_meas = R_vk.T @ R
    t_meas = np.array([0.42, -0.17, 0.09])
    return R_vk, p_vk, R, p, R_meas, t_meas


def _numeric(eskf, base, R_meas, t_meas, perturb):
    cols = []
    for k in range(3):
        cols.append(
            (
                _residual(eskf, perturb(base, k, +_EPS), R_meas, t_meas)
                - _residual(eskf, perturb(base, k, -_EPS), R_meas, t_meas)
            )
            / (2 * _EPS)
        )
    return np.column_stack(cols)


def _analytic(eskf, x, R_meas, t_meas, block):
    (_, Hr), (_, Ht) = _blocks(eskf, x, R_meas, t_meas)
    return np.vstack([Hr[:, block], Ht[:, block]])


def _unit(k):
    e = np.zeros(3)
    e[k] = 1.0
    return e


def _with(x, **changes):
    y = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in x.items()}
    y.update(changes)
    return y


@pytest.fixture
def fixture():
    R_vk, p_vk, R, p, R_meas, t_meas = _setup()
    return _eskf(), _state(R_vk, p_vk, R, p), R_meas, t_meas


def test_the_live_attitude_jacobian_is_the_exact_derivative(fixture):
    eskf, x, Rm, tm = fixture
    num = _numeric(eskf, x, Rm, tm, lambda b, k, e: _with(b, R=b["R"] @ rot_exp(e * _unit(k))))
    assert np.allclose(_analytic(eskf, x, Rm, tm, _IDX_THETA), -num, atol=1e-5)


def test_the_live_position_jacobian_is_the_exact_derivative(fixture):
    eskf, x, Rm, tm = fixture
    num = _numeric(eskf, x, Rm, tm, lambda b, k, e: _with(b, p=b["p"] + e * _unit(k)))
    assert np.allclose(_analytic(eskf, x, Rm, tm, _IDX_P), -num, atol=1e-5)


def test_the_clone_attitude_jacobian_is_the_exact_derivative(fixture):
    """Both the rotation block (-I) and the translation block ([t_pred]x)."""
    eskf, x, Rm, tm = fixture
    num = _numeric(eskf, x, Rm, tm, lambda b, k, e: _with(b, R_vk=b["R_vk"] @ rot_exp(e * _unit(k))))
    assert np.allclose(_analytic(eskf, x, Rm, tm, _IDX_CT), -num, atol=1e-5)


def test_the_clone_position_jacobian_is_the_exact_derivative(fixture):
    eskf, x, Rm, tm = fixture
    num = _numeric(eskf, x, Rm, tm, lambda b, k, e: _with(b, p_vk=b["p_vk"] + e * _unit(k)))
    assert np.allclose(_analytic(eskf, x, Rm, tm, _IDX_CP), -num, atol=1e-5)


# ---------------------------------------------------------------- structure


def _committed_state(eskf, seed=0):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((_N_STATES, _N_STATES))
    P = A @ A.T * 1e-2
    P[_IDX_CP, :] = 0.0
    P[:, _IDX_CP] = 0.0
    P[_IDX_CT, :] = 0.0
    P[:, _IDX_CT] = 0.0
    eskf._commit_anchor_covariance(P)
    return P


def test_a_new_clone_is_perfectly_correlated_with_the_live_pose():
    eskf = _eskf()
    P = _committed_state(eskf)
    assert np.allclose(P[_IDX_CP, _IDX_CP], P[_IDX_P, _IDX_P])
    assert np.allclose(P[_IDX_CT, _IDX_CT], P[_IDX_THETA, _IDX_THETA])
    assert np.allclose(P[_IDX_CP, _IDX_CT], P[_IDX_P, _IDX_THETA])
    for sl in (slice(0, 3), slice(6, 9), slice(9, 12), slice(12, 15)):  # cross terms with the other states
        assert np.allclose(P[sl, _IDX_CP], P[sl, _IDX_P]) and np.allclose(P[sl, _IDX_CT], P[sl, _IDX_THETA])
    assert np.allclose(P, P.T) and np.linalg.eigvalsh(P).min() > -1e-9


def test_the_anchor_commit_is_unchanged_by_the_flag_being_available():
    eskf = _eskf("anchor")
    P = _committed_state(eskf)
    assert np.allclose(P[_IDX_CP, _IDX_CP], np.eye(3) * eskf.cfg.anchor_pos_sigma_m**2)
    assert np.allclose(P[_IDX_P, _IDX_CP], 0.0)


def test_a_measurement_straight_after_the_commit_carries_no_information():
    """The clone and the live pose are the same random variable, so their difference has no uncertainty."""
    eskf = _eskf()
    R_vk, p_vk, _, _, _, _ = _setup()
    x = _state(R_vk, p_vk, R_vk, p_vk)
    x["P"] = _committed_state(eskf, seed=3)
    P_before = x["P"].copy()
    est_before = (x["R"].copy(), x["p"].copy())
    eskf._vision_update_clone(x, rot_exp(np.array([0.05, 0.0, 0.0])), np.array([0.3, 0.0, 0.0]), 0.35, 0.05, 0.0)
    assert np.allclose(x["p"], est_before[1], atol=1e-9) and np.allclose(x["R"], est_before[0], atol=1e-9)
    # The re-commit rebuilds the clone blocks from the live ones, so compare the navigation block.
    assert np.allclose(x["P"][:15, :15], P_before[:15, :15], atol=1e-9)


def test_the_clone_correlation_is_kept_by_propagation_and_the_clone_block_does_not_move():
    eskf = _eskf()
    x = eskf._initial_state()
    x["P"] = _committed_state(eskf, seed=5)
    P0 = x["P"].copy()
    for _ in range(50):
        eskf._propagate(x, np.array([0.1, 0.0, -9.8]), np.array([0.0, 0.2, 0.1]), 0.005)
    P = x["P"]
    cc = np.r_[15:21]
    assert np.allclose(P[np.ix_(cc, cc)], P0[np.ix_(cc, cc)], atol=1e-12)  # a stored pose does not drift
    assert not np.allclose(P[:15, cc], P0[:15, cc])  # but its correlation with the live state evolves
    assert np.allclose(P, P.T) and np.linalg.eigvalsh(P).min() > -1e-9


def test_the_default_is_the_anchor_and_an_unknown_model_is_refused():
    assert EskfConfig(imu_noise=ImuNoiseModel()).vision_model == "anchor"
    assert EskfConfig(imu_noise=ImuNoiseModel()).as_dict()["vision_model"] == "anchor"
    eskf = _eskf("rubber-duck")
    with pytest.raises(ValueError, match="vision_model"):
        eskf._propagate(eskf._initial_state(), np.zeros(3), np.zeros(3), 0.005)


# -------------------------------------------------------------- benchmark


def _case(name: str, model: str):
    cfg = yaml.safe_load(default_config_path().read_text())
    case = copy.deepcopy(cfg["cases"][name])
    case.setdefault("estimator", {})["vision_model"] = model
    return run_case(name, case, cfg["defaults"])


def test_a_case_without_vision_is_identical_under_either_model():
    a, b = _case("outage_control", "anchor"), _case("outage_control", "clone")
    assert a["headline"]["ate_rmse_m"] == b["headline"]["ate_rmse_m"]
    assert a["headline"]["nees_mean"] == b["headline"]["nees_mean"]


def test_the_clone_keeps_the_covariance_valid_through_a_gnss_outage_with_vision():
    record = _case("outage_visual", "clone")
    assert record["estimator"]["vision_model"] == "clone"
    series = record["error_time_series"]["claimed_sigma_p_m"]
    assert np.all(np.isfinite(series)) and min(series) > 0.0
    assert record["stats"]["vision_updates_used"] > 100
