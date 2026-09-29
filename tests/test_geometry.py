"""Unit tests for the SO(3)/SE(3) primitives.

These are the lowest layer of the stack: if these are wrong, every metric and
every estimator result is wrong, so they are tested directly rather than only
through a downstream consumer.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.geometry.rigid import (
    matrix_to_quat,
    pose_exp,
    pose_inverse,
    pose_log,
    quat_normalize,
    quat_to_matrix,
    rot_exp,
    rot_log,
    rot_log_batch,
)


def rotation_about(axis: np.ndarray, angle: float) -> np.ndarray:
    a = np.asarray(axis, float)
    return rot_exp(a / np.linalg.norm(a) * angle)


@pytest.mark.parametrize(
    "angle",
    [0.0, 1e-12, 1e-9, 1e-6, 1e-3, 0.1, 1.0, 3.0, np.pi - 1e-7, np.pi],
)
@pytest.mark.parametrize("axis", [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 2.0, 3.0]])
def test_rot_exp_log_round_trip(angle: float, axis: list[float]) -> None:
    R = rotation_about(axis, angle)
    v = rot_log(R)
    assert np.allclose(rot_exp(v), R, atol=1e-12)
    # Below the small-angle cutoff the exact axis magnitude is not recoverable
    # from R - I, so only the direction and the small-angle limit are checked.
    if angle > 1e-6:
        assert np.isclose(np.linalg.norm(v), angle, rtol=1e-9)


def test_rot_log_small_angle_is_linear() -> None:
    """Near identity the log must return the rotation vector, not arccos noise.

    ``arccos((tr R - 1) / 2)`` loses all precision as the angle approaches zero;
    the atan2 formulation keeps full relative accuracy.
    """
    for scale in (1e-3, 1e-5, 1e-7, 1e-9):
        w = np.array([0.3, -0.2, 0.5])
        w = w / np.linalg.norm(w) * scale
        v = rot_log(rot_exp(w))
        assert np.allclose(v, w, rtol=1e-6, atol=1e-18), f"scale={scale}"


def test_rot_log_small_angle_relative_error() -> None:
    """Regression guard: the old arccos recovery lost accuracy below ~1e-6 rad."""
    w = np.array([1.0, 0.0, 0.0]) * 1e-9
    v = rot_log(rot_exp(w))
    rel = np.linalg.norm(v - w) / np.linalg.norm(w)
    assert rel < 1e-6, f"relative error {rel:.3e}"


def test_rot_log_near_pi_keeps_axis_sign() -> None:
    """Just below pi the log is well defined, but the axis is the delicate part."""
    for eps in (1e-3, 1e-6, 1e-9):
        R = rotation_about([0.0, 0.0, 1.0], np.pi - eps)
        v = rot_log(R)
        assert np.allclose(rot_exp(v), R, atol=1e-12)
        assert v[2] > 0.0


def test_rot_log_batch_matches_scalar() -> None:
    rng = np.random.default_rng(7)
    axes = rng.standard_normal((64, 3))
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    angles = rng.uniform(0.0, np.pi - 1e-3, 64)
    Rs = np.stack([rot_exp(a * t) for a, t in zip(axes, angles, strict=False)])
    batch = rot_log_batch(Rs)
    assert batch.shape == (64, 3)
    for i, R in enumerate(Rs):
        assert np.allclose(batch[i], rot_log(R), atol=1e-12)


def test_rot_log_principal_value_wraps_past_pi() -> None:
    """Past pi the log wraps to the equivalent rotation about the opposite axis.

    The logarithm is multi valued, so returning the principal value in [0, pi] is
    the correct behaviour, and ``exp(log(R)) == R`` must still hold exactly.
    """
    for eps in (1e-3, 0.1, 0.5):
        R = rotation_about([0.0, 0.0, 1.0], np.pi + eps)
        v = rot_log(R)
        assert np.allclose(rot_exp(v), R, atol=1e-12)
        assert np.isclose(float(np.linalg.norm(v)), np.pi - eps, atol=1e-9)


def test_rot_exp_orthonormal_and_deterministic() -> None:
    R = rot_exp([0.1, -0.2, 0.3])
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-14)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-14)


def test_pose_exp_inverse_is_inverse() -> None:
    T = pose_exp(np.array([1.0, 2.0, 3.0, 0.1, -0.2, 0.3]))
    assert np.allclose(pose_inverse(T) @ T, np.eye(4), atol=1e-12)
    assert np.allclose(T @ pose_inverse(T), np.eye(4), atol=1e-12)


def test_pose_exp_composition_is_not_additive() -> None:
    """SE(3) is non-abelian, so exp(xi1) @ exp(xi2) != exp(xi1 + xi2).

    Recorded as a test so that a future "simplification" of pose_exp into a
    linear map is caught immediately.
    """
    xi1 = np.array([1.0, 0.0, -2.0, 0.05, 0.1, -0.02])
    xi2 = np.array([-0.5, 3.0, 0.25, -0.03, 0.07, 0.11])
    assert not np.allclose(pose_exp(xi1) @ pose_exp(xi2), pose_exp(xi1 + xi2), atol=1e-6)


def test_pose_log_exp_round_trip() -> None:
    xi = np.array([0.3, -0.7, 1.1, 0.2, -0.1, 0.4])
    T = pose_exp(xi)
    assert np.allclose(pose_log(T), xi, atol=1e-12)
    assert np.allclose(pose_exp(pose_log(T)), T, atol=1e-12)


# REMOVED: se3_adjoint / so3_adjoint.
#
# The adjoint helpers were exported from navkit.geometry but used nowhere in the
# package, and their convention could not be verified: neither the spatial
# identity (Exp(eta) T = T Exp(Ad_T eta)) nor the body-adjoint conjugation held
# against pose_exp under finite differences. Rather than keep a public function
# whose contract was unknown, both were deleted. Nothing depended on them, and
# an untested Lie-theory helper in a geometry module is a liability: it looks
# authoritative, so a future caller would trust it.


def test_quaternion_round_trip_in_wxyz_order() -> None:
    """Internal quaternions are (w, x, y, z); TUM uses (qx, qy, qz, qw)."""
    R = rotation_about([1.0, 2.0, -1.0], 0.9)
    q = matrix_to_quat(R)
    assert q.shape == (4,)
    assert np.isclose(np.linalg.norm(q), 1.0, atol=1e-12)
    assert np.allclose(quat_to_matrix(q), R, atol=1e-12)


def test_quaternion_normalises_its_input() -> None:
    R = rotation_about([0.0, 1.0, 0.0], -2.0)
    q = matrix_to_quat(R)
    assert np.isclose(np.linalg.norm(quat_normalize(q)), 1.0, atol=1e-14)
