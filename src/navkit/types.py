"""Core data structures shared by the replay pipeline.

All time is in seconds (float64) relative to an arbitrary but recorded epoch.
All poses are 4x4 ``T_wb`` matrices: body frame to world frame.

These containers are plain dataclasses holding numpy arrays. They are
intentionally mutable-ish and cheap: a 141 s sequence at 120 Hz is ~17k poses
and a few megabytes, so there is no reason to add a storage abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .geometry.rigid import matrix_to_quat, quat_to_matrix, skew, rot_log_batch, transform_points

GRAVITY = np.array([0.0, 0.0, 9.80665])


def _as_sorted(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=float).reshape(-1)
    if t.size > 1 and np.any(np.diff(t) < 0):
        raise ValueError("timestamps must be non-decreasing")
    return t


@dataclass
class Trajectory:
    """A timestamped sequence of poses."""

    t: np.ndarray  # (N,) seconds, strictly increasing
    poses: np.ndarray  # (N, 4, 4) T_wb
    name: str = "trajectory"
    frame: str = "world"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.t = _as_sorted(self.t)
        self.poses = np.asarray(self.poses, dtype=float).reshape(-1, 4, 4)
        if self.t.shape[0] != self.poses.shape[0]:
            raise ValueError(
                f"t has {self.t.shape[0]} entries but poses has {self.poses.shape[0]}"
            )
        if self.t.size == 0:
            raise ValueError("empty trajectory")
        if not np.allclose(self.poses[:, 3, :], np.array([0, 0, 0, 1.0]), atol=1e-6):
            raise ValueError("last row of every pose must be [0, 0, 0, 1]")

    def __len__(self) -> int:
        return int(self.t.shape[0])

    @property
    def positions(self) -> np.ndarray:
        return self.poses[:, :3, 3]

    @property
    def rotations(self) -> np.ndarray:
        return self.poses[:, :3, :3]

    @property
    def quaternions(self) -> np.ndarray:
        """(N, 4) as ``(w, x, y, z)`` -- this library's internal order.

        Note that this is *not* the order used in TUM ``data.txt`` files, which
        are ``(qx, qy, qz, qw)``. The readers and writers in
        :mod:`navkit.io.trajectory` are the only place that conversion happens.
        """
        return np.array([matrix_to_quat(R) for R in self.rotations])

    @property
    def duration(self) -> float:
        return float(self.t[-1] - self.t[0])

    @property
    def t0(self) -> float:
        return float(self.t[0])

    def rate_hz(self) -> float:
        span = self.duration
        return float(len(self) - 1) / span if span > 0 else float("inf")

    def subset(self, t0: float | None = None, t1: float | None = None) -> "Trajectory":
        lo = self.t[0] if t0 is None else max(self.t[0], float(t0))
        hi = self.t[-1] if t1 is None else min(self.t[-1], float(t1))
        m = (self.t >= lo) & (self.t <= hi)
        return Trajectory(
            t=self.t[m],
            poses=self.poses[m],
            name=self.name,
            frame=self.frame,
            metadata=dict(self.metadata),
        )

    def time_offset(self, dt: float) -> "Trajectory":
        """Return a copy with every timestamp shifted by ``dt`` seconds."""
        return Trajectory(
            t=self.t + float(dt),
            poses=self.poses.copy(),
            name=self.name,
            frame=self.frame,
            metadata=dict(self.metadata),
        )

    def transformed(self, T: np.ndarray) -> "Trajectory":
        """Return a copy with every pose left-multiplied by ``T``."""
        return Trajectory(
            t=self.t.copy(),
            poses=np.einsum("ij,njk->nik", np.asarray(T, float), self.poses),
            name=self.name,
            frame=self.frame,
            metadata=dict(self.metadata),
        )

    def path_length(self) -> float:
        p = self.positions
        return float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1)))

    def velocities(self) -> np.ndarray:
        """Central-difference velocity in the world frame, (N, 3)."""
        return finite_difference(self.t, self.positions, second=False)

    def accelerations(self) -> np.ndarray:
        return finite_difference(self.t, self.positions, second=True)

    def angular_velocities(self) -> np.ndarray:
        """Body-frame angular rate, (N, 3), from central differences of R."""
        n = len(self)
        if n < 2:
            return np.zeros((n, 3))
        R = self.rotations
        dt = np.diff(self.t).reshape(-1, 1)
        # R_k^T R_{k+1}: the rotation increment expressed in the *previous*
        # body frame, which is the frame an IMU measures angular rate in. The
        # opposite product, R_{k+1} R_k^T, is the same rotation expressed in
        # the world frame and is a different signal.
        R_rel = np.einsum("nji,njk->nik", R[:-1], R[1:])
        omega = np.array([rot_log_batch(Rr) for Rr in R_rel]) / dt
        out = np.zeros((n, 3))
        out[:-1] = omega
        out[-1] = omega[-1]
        return out


def finite_difference(
    t: np.ndarray, x: np.ndarray, second: bool = False
) -> np.ndarray:
    """Non-uniform central differences, with one-sided ends.

    Deliberately simple: this repository replays trajectories at 100-200 Hz
    where a higher-order stencil buys nothing. ``second=True`` differentiates
    twice, which is what the IMU synthesis needs; its accuracy is limited by
    the ground-truth sample rate and is documented as such in
    ``docs/limitations.md``.
    """
    t = _as_sorted(t)
    x = np.asarray(x, dtype=float).reshape(len(t), -1)
    n = len(t)
    v = np.zeros_like(x)
    if n < 2:
        return v
    dt = np.diff(t).reshape(-1, 1)
    d = (x[1:] - x[:-1]) / dt
    v[:-1] += d
    v[1:] += d
    v[0] = (x[1] - x[0]) / dt[0]
    v[-1] = (x[-1] - x[-2]) / dt[-1]
    if not second:
        return v
    a = np.zeros_like(x)
    # Second difference at the interior point uses the mean step around it:
    # a[i+1] = (d[i+1] - d[i]) / ((t[i+2] - t[i]) / 2).
    da = (d[1:] - d[:-1]) / (0.5 * (t[2:] - t[:-2])).reshape(-1, 1)
    a[1:-1] += da
    a[0] = da[0]
    a[-1] = da[-1]
    return a


@dataclass
class ImuSample:
    """Inertial measurement, body frame."""

    t: np.ndarray  # (N,)
    accel: np.ndarray  # (N, 3) specific force, m/s^2 (at rest: (0, 0, -g))
    gyro: np.ndarray  # (N, 3) angular rate, rad/s
    accel_cov: np.ndarray | None = None  # (N, 3) diagonal variances
    gyro_cov: np.ndarray | None = None
    name: str = "imu"

    def __post_init__(self) -> None:
        self.t = _as_sorted(self.t)
        self.accel = np.asarray(self.accel, dtype=float).reshape(-1, 3)
        self.gyro = np.asarray(self.gyro, dtype=float).reshape(-1, 3)
        if not (self.t.shape[0] == self.accel.shape[0] == self.gyro.shape[0]):
            raise ValueError("imu arrays have inconsistent lengths")
        if self.accel_cov is not None:
            self.accel_cov = np.asarray(self.accel_cov, float).reshape(-1, 3)
        if self.gyro_cov is not None:
            self.gyro_cov = np.asarray(self.gyro_cov, float).reshape(-1, 3)

    def __len__(self) -> int:
        return int(self.t.shape[0])

    def rate_hz(self) -> float:
        span = float(self.t[-1] - self.t[0])
        return float(len(self) - 1) / span if span > 0 else float("inf")

    def time_offset(self, dt: float) -> "ImuSample":
        """Return a copy with every timestamp shifted by ``dt`` seconds."""
        return ImuSample(
            t=self.t + float(dt),
            accel=self.accel.copy(),
            gyro=self.gyro.copy(),
            accel_cov=self.accel_cov,
            gyro_cov=self.gyro_cov,
            name=self.name,
        )

    def subset(self, t0: float | None = None, t1: float | None = None) -> "ImuSample":
        lo = self.t[0] if t0 is None else max(self.t[0], float(t0))
        hi = self.t[-1] if t1 is None else min(self.t[-1], float(t1))
        m = (self.t >= lo) & (self.t <= hi)
        return ImuSample(
            t=self.t[m],
            accel=self.accel[m],
            gyro=self.gyro[m],
            accel_cov=None if self.accel_cov is None else self.accel_cov[m],
            gyro_cov=None if self.gyro_cov is None else self.gyro_cov[m],
            name=self.name,
        )


@dataclass
class GnssFix:
    """A GNSS position fix, world frame, with a diagonal covariance."""

    t: np.ndarray  # (N,)
    positions: np.ndarray  # (N, 3)
    cov: np.ndarray | None = None  # (N, 3) diagonal variances
    available: np.ndarray | None = None  # (N,) bool, False = outage
    name: str = "gnss"

    def __post_init__(self) -> None:
        self.t = _as_sorted(self.t)
        self.positions = np.asarray(self.positions, float).reshape(-1, 3)
        if self.t.shape[0] != self.positions.shape[0]:
            raise ValueError("gnss t/positions length mismatch")
        if self.cov is not None:
            self.cov = np.asarray(self.cov, float).reshape(-1, 3)
        if self.available is not None:
            self.available = np.asarray(self.available, dtype=bool).reshape(-1)

    def __len__(self) -> int:
        return int(self.t.shape[0])

    def valid(self) -> "GnssFix":
        """Return a copy with unavailable fixes removed."""
        if self.available is None:
            return self
        m = self.available
        return GnssFix(
            t=self.t[m],
            positions=self.positions[m],
            cov=None if self.cov is None else self.cov[m],
            available=None,
            name=self.name,
        )

    def outage_intervals(
        self, t0: float | None = None, t1: float | None = None
    ) -> list[tuple[float, float]]:
        """Contiguous ``[start, end]`` intervals where the fix is unavailable.

        A sample at time ``t_i`` is treated as covering ``[t_i - dt/2, t_i +
        dt/2]``, so an outage is measured in wall-clock time rather than in
        sample counts.
        """
        lo = float(self.t[0] if t0 is None else t0)
        hi = float(self.t[-1] if t1 is None else t1)
        if self.available is None or len(self) == 0:
            return []
        dt = np.gradient(self.t) if len(self) > 1 else np.array([0.0])
        out: list[tuple[float, float]] = []
        start: float | None = None
        end = lo
        for ti, av, di in zip(self.t, self.available, dt):
            half = 0.5 * float(di)
            if not av:
                if start is None:
                    start = float(ti) - half
                end = float(ti) + half
            elif start is not None:
                out.append((max(start, lo), min(end, hi)))
                start = None
        if start is not None:
            out.append((max(start, lo), min(end, hi)))
        return [(a, b) for a, b in out if b > a]


@dataclass
class VisionUpdate:
    """A relative-pose measurement as a visual front end would emit it.

    For the current frame ``i`` the measurement is the transform
    ``T_prev_cur = T_{i-1}^{-1} T_i`` expressed in the *previous* camera frame:

    * ``R_rel[i] = R_{i-1}^T R_i`` -- current-frame axes in the previous frame;
    * ``t_rel[i] = R_{i-1}^T (p_i - p_{i-1})`` -- current origin in the previous
      frame.

    ``R_rel`` is the rotation of ``T_prev_cur``. It must not be confused with
    ``R_i R_{i-1}^T``, the rotation of the inverse transform, because pairing
    that with ``t_rel`` yields a measurement that does not telescope.
    This is the output of a standard two-frame relative-pose estimator. The
    proxy generator documents the simplification of assuming a known, small
    camera-to-IMU extrinsic.
    """

    t: np.ndarray  # (N,) timestamp of the current frame
    R_rel: np.ndarray  # (N, 3, 3)
    t_rel: np.ndarray  # (N, 3)
    rot_cov: np.ndarray | None = None  # (N, 3) diagonal variances
    trans_cov: np.ndarray | None = None
    dropped: np.ndarray | None = None  # (N,) bool, True = simulated dropped frame
    name: str = "vision"

    def __post_init__(self) -> None:
        self.t = _as_sorted(self.t)
        self.R_rel = np.asarray(self.R_rel, float).reshape(-1, 3, 3)
        self.t_rel = np.asarray(self.t_rel, float).reshape(-1, 3)
        n = self.t.shape[0]
        if self.R_rel.shape[0] != n or self.t_rel.shape[0] != n:
            raise ValueError("vision t/measurement length mismatch")
        if self.rot_cov is not None:
            self.rot_cov = np.asarray(self.rot_cov, float).reshape(n, 3)
        if self.trans_cov is not None:
            self.trans_cov = np.asarray(self.trans_cov, float).reshape(n, 3)
        if self.dropped is not None:
            self.dropped = np.asarray(self.dropped, dtype=bool).reshape(n)

    def __len__(self) -> int:
        return int(self.t.shape[0])

    def valid(self) -> "VisionUpdate":
        """Return only the measurements that were not dropped."""
        if self.dropped is None:
            return self
        m = ~self.dropped
        return VisionUpdate(
            t=self.t[m],
            R_rel=self.R_rel[m],
            t_rel=self.t_rel[m],
            rot_cov=None if self.rot_cov is None else self.rot_cov[m],
            trans_cov=None if self.trans_cov is None else self.trans_cov[m],
            dropped=None,
            name=self.name,
        )

    def time_offset(self, dt: float) -> "VisionUpdate":
        return VisionUpdate(
            t=self.t + float(dt),
            R_rel=self.R_rel,
            t_rel=self.t_rel,
            rot_cov=self.rot_cov,
            trans_cov=self.trans_cov,
            dropped=self.dropped,
            name=self.name,
        )


def interpolate_trajectory(traj: Trajectory, t_query: np.ndarray) -> Trajectory:
    """Sample a trajectory at arbitrary times by SLERP + linear translation.

    Queries outside the trajectory span are clamped to the endpoints and the
    out-of-range mask is returned, because silently extrapolating a pose is a
    reliable way to manufacture a fake metric.
    """
    t_query = np.asarray(t_query, dtype=float).reshape(-1)
    lo, hi = float(traj.t[0]), float(traj.t[-1])
    inside = (t_query >= lo) & (t_query <= hi)
    tq = np.clip(t_query, lo, hi)

    pos = np.stack(
        [np.interp(tq, traj.t, traj.positions[:, k]) for k in range(3)], axis=1
    )
    idx = np.clip(np.searchsorted(traj.t, tq, side="right") - 1, 0, len(traj) - 2)
    t0, t1 = traj.t[idx], traj.t[idx + 1]
    alpha = np.clip((tq - t0) / np.maximum(t1 - t0, 1e-12), 0.0, 1.0)

    q = traj.quaternions
    out = np.empty((len(tq), 4, 4))
    for i in range(len(tq)):
        out[i, :3, :3] = quat_to_matrix(_slerp(q[idx[i]], q[idx[i] + 1], float(alpha[i])))
        out[i, :3, 3] = pos[i]
        out[i, 3, :3] = 0.0
        out[i, 3, 3] = 1.0
    return Trajectory(t=tq, poses=out, name=f"{traj.name}@query", metadata={"inside": inside})


def _slerp(q0: np.ndarray, q1: np.ndarray, a: float) -> np.ndarray:
    q0 = np.asarray(q0, float)
    q1 = np.asarray(q1, float)
    d = float(q0 @ q1)
    if d < 0.0:
        q1 = -q1
        d = -d
    if d > 0.9995:  # nearly parallel: lerp + renormalise is stable
        q = q0 + a * (q1 - q0)
        return q / np.linalg.norm(q)
    th0 = np.arccos(np.clip(d, -1.0, 1.0))
    s = np.sin(th0)
    return (np.sin((1.0 - a) * th0) / s) * q0 + (np.sin(a * th0) / s) * q1


def residual_errors(
    estimate: Trajectory, reference: Trajectory
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-pose position error (m) and rotation error (rad) versus reference.

    The estimate is associated with the reference by timestamp: the reference
    is interpolated at the estimate's timestamps. No alignment is applied here;
    alignment happens in the metric layer.
    """
    ref = interpolate_trajectory(reference, estimate.t)
    dp = estimate.positions - ref.positions
    pos_err = np.linalg.norm(dp, axis=1)
    rot_err = np.array(
        [np.linalg.norm(rot_log_batch(R @ Rt.T)) for R, Rt in zip(estimate.rotations, ref.rotations)]
    )
    return pos_err, rot_err, dp


__all__ = [
    "GRAVITY",
    "GnssFix",
    "ImuSample",
    "Trajectory",
    "VisionUpdate",
    "finite_difference",
    "interpolate_trajectory",
    "quat_to_matrix",
    "residual_errors",
    "skew",
    "rot_log_batch",
    "transform_points",
]
