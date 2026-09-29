"""Dead-reckoning reference estimator.

Integrates the (possibly degraded) inertial stream with no external updates. It
exists for two reasons:

1. It is the honest lower bound: with no aiding, inertial integration error
   accumulates without bound. Any aiding scheme must beat it, and showing the
   gap is more informative than showing one number.
2. It isolates the *replay harness* from the *fusion algorithm*. If dead
   reckoning diverges by roughly the amount implied by the injected noise and
   bias, the harness is behaving; the divergence is not a bug in the replay
   plumbing.

Nominal propagation (world frame, gravity assumed known):

    v <- v + (R f + g) dt
    p <- p + v dt + 0.5 (R f + g) dt^2
    R <- R Exp(omega dt)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..geometry.rigid import rot_exp
from ..types import GRAVITY, ImuSample, Trajectory


@dataclass
class EstimatorResult:
    """Output of any estimator: the estimated trajectory plus run metadata."""

    trajectory: Trajectory
    runtime_s: float
    stats: dict[str, float] = field(default_factory=dict)
    name: str = "estimator"
    #: (N, 3, 3) position covariance at each estimate, when the estimator
    #: propagates one. Dead reckoning and other unaided integrators set this to
    #: ``None`` because they have no uncertainty model to report -- reporting a
    #: covariance that was never computed would be the same mistake as
    #: reporting a covariance the estimator does not deserve.
    position_cov: np.ndarray | None = None

    def summary(self) -> dict[str, object]:
        return {
            "name": self.name,
            "runtime_s": self.runtime_s,
            "poses": len(self.trajectory),
            "trajectory_duration_s": self.trajectory.duration,
            "path_length_m": self.trajectory.path_length(),
            "reports_covariance": self.position_cov is not None,
            **dict(self.stats),
        }


class DeadReckoning:
    """Midpoint (constant-acceleration) inertial integrator."""

    name = "dead_reckoning"

    def __init__(self, gravity: np.ndarray | None = None) -> None:
        self.g = GRAVITY.copy() if gravity is None else np.asarray(gravity, float)

    def run(self, imu: ImuSample, t0: float | None = None, t_end: float | None = None) -> EstimatorResult:
        t_start = time.perf_counter()
        t = imu.t
        if t_end is not None:
            imu = imu.subset(t0=t0, t1=t_end)
            t = imu.t
        elif t0 is not None:
            imu = imu.subset(t0=t0)
            t = imu.t
        n = len(imu)
        if n < 2:
            raise ValueError("dead reckoning needs at least 2 IMU samples")

        poses = np.zeros((n, 4, 4))
        R = np.eye(3)
        p = np.zeros(3)
        v = np.zeros(3)
        poses[0, :3, :3] = R
        poses[0, :3, 3] = p
        poses[0, 3, 3] = 1.0

        for k in range(n - 1):
            dt = float(t[k + 1] - t[k])
            a = R @ imu.accel[k] + self.g
            p = p + v * dt + 0.5 * a * dt * dt
            v = v + a * dt
            R = R @ rot_exp(imu.gyro[k] * dt)
            poses[k + 1, :3, :3] = R
            poses[k + 1, :3, 3] = p
            poses[k + 1, 3, 3] = 1.0

        traj = Trajectory(t=t, poses=poses, name=self.name)
        elapsed = time.perf_counter() - t_start
        return EstimatorResult(
            trajectory=traj,
            runtime_s=elapsed,
            stats={
                "final_speed_m_s": float(np.linalg.norm(v)),
                "realtime_factor": traj.duration / elapsed if elapsed > 0 else float("inf"),
            },
            name=self.name,
        )
