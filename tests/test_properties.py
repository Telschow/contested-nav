"""Property tests: invariants that must hold for every input, not just the benchmark's.

The benchmark and the golden snapshot pin what the filter does on seven fixed
scenarios. They cannot say that the covariance stays a covariance for an input nobody
thought to try, which is the failure that matters most in a navigation filter: a
covariance that has lost symmetry or positive semi-definiteness still produces numbers,
and they are wrong without any error being raised.

Each test states an invariant and lets Hypothesis search for a counterexample.
Examples are derived deterministically from the source (see ``conftest.py``), so a CI
failure replays exactly. To search wider, run with ``HYPOTHESIS_PROFILE=explore``.

What these tests can and cannot see. They check necessary conditions: finite, symmetric,
positive semi-definite, orthonormal. Mutating the filter shows where the line sits:

* first-order attitude propagation instead of the exponential map: caught (R leaves SO(3));
* propagating the covariance as ``F P`` instead of ``F P F^T``: caught (asymmetry);
* replacing the Joseph update with the textbook ``(I - K H) P``: NOT caught. With the
  optimal gain the two are algebraically identical, and on realistic input they agree to
  rounding, so no invariant here separates them. The Joseph form is kept for robustness
  against a sub-optimal gain, which these tests do not construct;
* a sign error in the bias random-walk noise: NOT caught, because the term is ~1e-10 per
  step against a prior of 1e-4 and the tolerance is relative to the largest entry of P.

Whether the filter is *right* is the golden snapshot's and the calibration tests' job.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.eval.calibration import normalized_error_squared
from navkit.eval.statistics import chi2_cdf, chi2_ppf
from navkit.geometry.rigid import (
    matrix_to_quat,
    pose_exp,
    pose_log,
    quat_normalize,
    quat_to_matrix,
    rot_exp,
    rot_log,
)
from navkit.io.imu import ImuNoiseModel

finite = {"allow_nan": False, "allow_infinity": False}


def vec3(limit: float) -> st.SearchStrategy[np.ndarray]:
    return st.lists(st.floats(-limit, limit, **finite), min_size=3, max_size=3).map(np.array)


# ---------------------------------------------------------------- rotations ---


def _is_rotation(R: np.ndarray, tol: float = 1e-12) -> bool:
    return bool(np.allclose(R @ R.T, np.eye(3), atol=tol) and abs(np.linalg.det(R) - 1.0) < tol)


@given(vec3(50.0))
def test_rot_exp_is_always_a_rotation(phi: np.ndarray) -> None:
    assert _is_rotation(rot_exp(phi))


@given(vec3(3.0))
def test_rot_log_inverts_rot_exp_inside_the_principal_ball(phi: np.ndarray) -> None:
    # Angles up to ~3.0 rad stay clear of the pi cut, where the log is two-valued.
    if np.linalg.norm(phi) >= 3.0:
        phi = phi * (3.0 / np.linalg.norm(phi))
    assert np.allclose(rot_log(rot_exp(phi)), phi, atol=1e-9)


@given(vec3(50.0))
def test_rot_exp_of_the_negative_is_the_transpose(phi: np.ndarray) -> None:
    assert np.allclose(rot_exp(-phi), rot_exp(phi).T, atol=1e-12)


@given(st.lists(st.floats(-1.0, 1.0, **finite), min_size=4, max_size=4).filter(lambda q: np.linalg.norm(q) > 1e-3))
def test_quaternion_to_matrix_is_a_rotation_and_round_trips(q: list[float]) -> None:
    q_unit = quat_normalize(np.array(q))
    R = quat_to_matrix(q_unit)
    assert _is_rotation(R)
    # q and -q are one rotation. The w >= 0 convention fixes the sign except at w == 0
    # (a half turn), where either sign is canonical, so compare up to sign. Hypothesis
    # found that case on its first run: q = (0, 0, 0, -1) came back as (0, 0, 0, 1).
    back = matrix_to_quat(R)
    assert min(np.linalg.norm(back - q_unit), np.linalg.norm(back + q_unit)) < 1e-9
    assert np.allclose(quat_to_matrix(back), R, atol=1e-9)


@given(vec3(3.0), vec3(100.0))
def test_pose_log_inverts_pose_exp(phi: np.ndarray, rho: np.ndarray) -> None:
    if np.linalg.norm(phi) >= 3.0:
        phi = phi * (3.0 / np.linalg.norm(phi))
    xi = np.concatenate([rho, phi])  # pose_exp takes [rho (3), phi (3)]
    assert np.allclose(pose_log(pose_exp(xi)), xi, atol=1e-8)


# ----------------------------------------------------------------- filter ---

_NOISE = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)

#: One filter operation: ("imu", accel, gyro, dt), ("gnss", offset_m) or
#: ("vision", rotation_vector_rad, translation_m). Each sensor has a plausible regime,
#: whose measurements the gate accepts and which therefore move the covariance, and an
#: absurd one, which exercises the rejection and FDIR paths. Only absurd inputs would
#: leave most of the update code untouched.
_ops = st.one_of(
    st.tuples(st.just("imu"), vec3(30.0), vec3(6.0), st.floats(1e-3, 5e-2, **finite)),
    st.tuples(st.just("gnss"), vec3(1.0)),
    st.tuples(st.just("gnss"), vec3(60.0)),
    st.tuples(st.just("vision"), vec3(0.01), vec3(0.1)),
    st.tuples(st.just("vision"), vec3(0.3), vec3(2.0)),
)


def _check_state(x: dict, step: str) -> None:
    P = x["P"]
    assert np.all(np.isfinite(P)), f"{step}: non-finite covariance"
    for key in ("R", "p", "v", "b_a", "b_g"):
        assert np.all(np.isfinite(x[key])), f"{step}: non-finite {key}"
    scale = max(1.0, float(np.max(np.abs(P))))
    asym = float(np.max(np.abs(P - P.T)))
    assert asym <= 1e-9 * scale, f"{step}: covariance asymmetry {asym:.3e} (scale {scale:.3e})"
    w = np.linalg.eigvalsh(0.5 * (P + P.T))
    assert w[0] >= -1e-9 * scale, f"{step}: negative eigenvalue {w[0]:.3e} (scale {scale:.3e})"
    assert _is_rotation(x["R"], tol=1e-9), f"{step}: attitude left SO(3)"


@pytest.mark.parametrize(
    ("vision_modelled", "keyframe_interval"),
    [(True, 1), (True, None), (False, 1)],
    ids=["anchor_modelled", "anchor_held", "anchor_in_noise"],
)
@given(ops=st.lists(_ops, min_size=1, max_size=40))
def test_filter_keeps_a_valid_covariance_and_attitude(
    vision_modelled: bool, keyframe_interval: int | None, ops: list[tuple]
) -> None:
    """After every propagate, GNSS update and visual update, P is a covariance and R a rotation.

    The measurements are deliberately unreasonable (60 m GNSS offsets, 2 m visual steps
    per frame), so the gate, the FDIR inflation and the rejection paths are all
    exercised along with the accepted ones.
    """
    cfg = EskfConfig(
        imu_noise=_NOISE,
        vision_enabled=True,
        vision_anchor_modelled=vision_modelled,
        vision_keyframe_interval=keyframe_interval,
        initial_bias_sigma=0.01,
    )
    kf = ErrorStateKalmanFilter(cfg)
    x = kf._initial_state()
    t = 0.0
    _check_state(x, "initial")
    for i, op in enumerate(ops):
        if op[0] == "imu":
            _, accel, gyro, dt = op
            t += dt
            kf._propagate(x, accel, gyro, dt)
        elif op[0] == "gnss":
            kf._gnss_update(x, x["p"] + op[1], cfg.gnss_position_sigma_m, t_s=t)
        else:
            kf._vision_update(
                x,
                rot_exp(op[1]),
                op[2],
                cfg.vision_rot_sigma_deg,
                cfg.vision_trans_sigma_m,
                t_s=t,
            )
        _check_state(x, f"op {i} ({op[0]})")


# ------------------------------------------------------------------- NEES ---


def _psd(entries: list[float], rank: int) -> np.ndarray:
    A = np.array(entries).reshape(3, 3)
    A[:, rank:] = 0.0
    return A @ A.T


@given(
    err=vec3(1e3),
    entries=st.lists(st.floats(-10.0, 10.0, **finite), min_size=9, max_size=9),
    rank=st.integers(0, 3),
)
def test_nees_is_finite_and_non_negative_even_for_singular_covariances(
    err: np.ndarray, entries: list[float], rank: int
) -> None:
    """The scorer floors the smallest eigenvalue, so a collapsed covariance cannot give NaN or a negative score."""
    series = normalized_error_squared(err[None], np.zeros((1, 3)), _psd(entries, rank)[None])
    assert math.isfinite(float(series.squared[0]))
    assert series.squared[0] >= 0.0


@given(
    err=vec3(10.0),
    scale=st.floats(0.1, 100.0, **finite),
    entries=st.lists(st.floats(0.5, 5.0, **finite), min_size=3, max_size=3),
)
def test_nees_is_invariant_to_a_common_rescaling_of_error_and_covariance(
    err: np.ndarray, scale: float, entries: list[float]
) -> None:
    """Scaling the error by s and the covariance by s^2 is a change of units and must not change the score."""
    P = np.diag(entries)
    a = normalized_error_squared(err[None], np.zeros((1, 3)), P[None]).squared[0]
    b = normalized_error_squared((scale * err)[None], np.zeros((1, 3)), (scale**2 * P)[None]).squared[0]
    assert b == pytest.approx(a, rel=1e-9, abs=1e-9)


# --------------------------------------------------------------- chi-square ---


@given(st.floats(0.0, 500.0, **finite), st.floats(0.0, 500.0, **finite), st.integers(1, 12))
def test_chi2_cdf_is_a_monotone_probability(a: float, b: float, dof: int) -> None:
    lo, hi = sorted((a, b))
    assert 0.0 <= chi2_cdf(lo, dof) <= chi2_cdf(hi, dof) <= 1.0


@given(st.floats(0.01, 0.999, **finite), st.integers(1, 12))
def test_chi2_ppf_inverts_chi2_cdf(q: float, dof: int) -> None:
    assert chi2_cdf(chi2_ppf(q, dof), dof) == pytest.approx(q, abs=1e-9)
