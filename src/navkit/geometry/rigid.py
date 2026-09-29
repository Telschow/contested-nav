"""SO(3)/SE(3) utilities.

Conventions used consistently across this package:

* A pose ``T_wb`` maps a point from body frame ``b`` to world frame ``w``:
  ``p_w = R_wb @ p_b + t_wb``.
* Quaternions are stored ``(w, x, y, z)``, the TUM trajectory file order.
  Dataset readers that supply a different order convert on read.
* Hat/vee matrices map a 3-vector to/from a skew-symmetric matrix.
* Rotation Jacobians and logs follow the standard robotics literature
  (Barfoot, Sola, Forster). Exp/log are the right Jacobians' inverses where a
  closed form exists; the branch is chosen so ``Exp(Log(R)) == R`` for all
  rotations without a sign flip at pi.

Nothing here is copied from an existing SLAM library. The formulas are the
standard textbook ones and each is unit tested against an independent
construction in ``tests/test_geometry.py``.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-12


# ---------------------------------------------------------------- SO(3) ---


def skew(v: np.ndarray) -> np.ndarray:
    """Return the 3x3 skew-symmetric matrix of ``v``."""
    v = np.asarray(v, dtype=float).reshape(3)
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def unskew(m: np.ndarray) -> np.ndarray:
    """Inverse of :func:`skew`."""
    m = np.asarray(m, dtype=float)
    return 0.5 * np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]])


def rot_exp(phi: np.ndarray) -> np.ndarray:
    """Exponential map ``so(3) -> SO(3)`` (Rodrigues' formula)."""
    phi = np.asarray(phi, dtype=float).reshape(3)
    theta = float(np.linalg.norm(phi))
    k = skew(phi)
    if theta < 1e-8:
        # Second order is enough here: theta^4 ~ 1e-32.
        return np.eye(3) + k + 0.5 * k @ k
    s, c = np.sin(theta), np.cos(theta)
    return np.eye(3) + (s / theta) * k + ((1.0 - c) / (theta * theta)) * (k @ k)


def rot_log(R: np.ndarray) -> np.ndarray:
    """Logarithmic map ``SO(3) -> so(3)``.

    The rotation angle is recovered with

        ``theta = atan2(0.5 * ||vee(R - R^T)||, 0.5 * (trace(R) - 1))``

    rather than ``arccos(0.5 * (trace(R) - 1))``. This matters a great deal
    here: the increments this library has to resolve are small (a 200 Hz
    gyroscope sees 5 ms of rotation, a 20 Hz camera sees 50 ms), and
    ``arccos`` loses roughly half the significant digits as its argument
    approaches 1. With the ``arccos`` form the relative error in the recovered
    angle is of order ``1/theta``, so a 1 mrad increment is already 30% wrong --
    which silently corrupts every gyro sample and every visual rotation
    residual. ``atan2`` is well conditioned across the whole range.
    """
    R = np.asarray(R, dtype=float)
    w = unskew(R - R.T)  # has magnitude 2 sin(theta)
    cos_term = 0.5 * (float(R[0, 0] + R[1, 1] + R[2, 2]) - 1.0)
    sin_term = 0.5 * float(np.linalg.norm(w))
    theta = float(np.arctan2(sin_term, cos_term))
    if theta < 1e-8:
        # Limit of the general branch: 0.5 * w == 0.5 * vee(R - R^T) == theta
        # * axis. (Note it is *not* 0.5 * vee(R - I), which is half the answer.)
        return 0.5 * w
    if np.pi - theta < 1e-6:
        # Near pi the (R - I)/sin(theta) form loses precision. Recover the axis
        # from the symmetric part, which is well conditioned there.
        A = 0.5 * (R + np.eye(3))
        axis = np.sqrt(np.clip(np.diag(A), 0.0, None))
        k = int(np.argmax(axis))
        if A[k, k] > _EPS:
            axis = A[:, k] / axis[k]
        axis = axis / max(float(np.linalg.norm(axis)), _EPS)
        # Disambiguate the sign using the antisymmetric part.
        if float(w @ axis) < 0.0:
            axis = -axis
        return theta * axis
    if sin_term > _EPS:
        # w has magnitude 2 sin(theta), so theta/(2 sin) * w == theta * axis.
        return (theta / (2.0 * sin_term)) * w
    return 0.5 * w


def rot_left_jacobian(phi: np.ndarray) -> np.ndarray:
    """Left Jacobian of ``SO(3)``."""
    phi = np.asarray(phi, dtype=float).reshape(3)
    theta = float(np.linalg.norm(phi))
    k = skew(phi)
    if theta < 1e-8:
        return np.eye(3) + 0.5 * k + (1.0 / 6.0) * (k @ k)
    t2 = theta * theta
    return np.eye(3) + ((1.0 - np.cos(theta)) / t2) * k + ((theta - np.sin(theta)) / (t2 * theta)) * (k @ k)


def rot_log_batch(R: np.ndarray) -> np.ndarray:
    """Vectorised :func:`rot_log` over a stack of rotations.

    Accepts ``(3, 3)`` or ``(N, 3, 3)`` and returns ``(3,)`` or ``(N, 3)``.
    """
    R = np.asarray(R, dtype=float)
    single = R.ndim == 2
    stack = R.reshape(-1, 3, 3)
    out = np.array([rot_log(m) for m in stack]).reshape(-1, 3)
    return out.reshape(3) if single else out


def rot_angle_batch(R: np.ndarray) -> np.ndarray:
    """Geodesic angle in radians of a stack of rotations."""
    return np.linalg.norm(rot_log_batch(R), axis=-1)


# ------------------------------------------------------- SO(3) quaternion ---


def quat_normalize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float).reshape(4)
    n = float(np.linalg.norm(q))
    if n < _EPS:
        raise ValueError("zero-norm quaternion")
    q = q / n
    # Canonical hemisphere: keep w >= 0 so that log/exp round trips are stable.
    return -q if q[0] < 0.0 else q


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """Convert a ``(w, x, y, z)`` quaternion to a rotation matrix."""
    q = quat_normalize(q)
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_to_quat(R: np.ndarray) -> np.ndarray:
    """Convert a rotation matrix to a ``(w, x, y, z)`` quaternion."""
    R = np.asarray(R, dtype=float)
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        q = np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        q = np.array([(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s])
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        q = np.array([(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s])
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        q = np.array([(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s])
    return quat_normalize(q)


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a * b`` for ``(w, x, y, z)`` quaternions."""
    aw, ax, ay, az = np.asarray(a, dtype=float).reshape(4)
    bw, bx, by, bz = np.asarray(b, dtype=float).reshape(4)
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def quat_conj(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float).reshape(4)
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_angle(q: np.ndarray) -> float:
    """Geodesic angle in radians of the rotation represented by ``q``."""
    q = quat_normalize(q)
    return 2.0 * float(np.arccos(np.clip(abs(q[0]), -1.0, 1.0)))


def quat_geodesic_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Rotation angle in radians between two quaternions."""
    return quat_angle(quat_mul(np.asarray(a, float), quat_conj(np.asarray(b, float))))


# -------------------------------------------------------------- SE(3) ----


def pose_exp(xi: np.ndarray) -> np.ndarray:
    """Exponential map ``se(3) -> SE(3)``.

    ``xi = [rho (3), phi (3)]`` with translation in the *tangent* frame:
    ``T = Exp([phi], [J_l(phi) rho])``.
    """
    xi = np.asarray(xi, dtype=float).reshape(6)
    rho, phi = xi[:3], xi[3:]
    T = np.eye(4)
    T[:3, :3] = rot_exp(phi)
    T[:3, 3] = rot_left_jacobian(phi) @ rho
    return T


def pose_log(T: np.ndarray) -> np.ndarray:
    """Logarithmic map ``SE(3) -> se(3)``, inverse of :func:`pose_exp`."""
    T = np.asarray(T, dtype=float)
    phi = rot_log(T[:3, :3])
    J_inv = np.linalg.inv(rot_left_jacobian(phi))
    return np.concatenate([J_inv @ T[:3, 3], phi])


def pose_inverse(T: np.ndarray) -> np.ndarray:
    T = np.asarray(T, dtype=float)
    R, t = T[:3, :3], T[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def make_pose(R: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Assemble a 4x4 pose from a rotation and a position."""
    T = np.eye(4)
    T[:3, :3] = np.asarray(R, dtype=float)
    T[:3, 3] = np.asarray(p, dtype=float).reshape(3)
    return T


def pose_from_quat(q: np.ndarray, p: np.ndarray) -> np.ndarray:
    return make_pose(quat_to_matrix(q), p)


def transform_points(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 4x4 transform to an ``(N, 3)`` array of points."""
    T = np.asarray(T, dtype=float)
    pts = np.asarray(pts, dtype=float).reshape(-1, 3)
    return pts @ T[:3, :3].T + T[:3, 3]
