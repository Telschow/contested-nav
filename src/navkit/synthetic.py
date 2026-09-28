"""Synthetic sequence generator.

CI must not download anything, so the test suite needs a sequence that is
small, fast, and physically consistent. This module builds one from a
closed-form motion: a superposition of smooth translation and rotation on a
circlet-like path, sampled at any rate, from which the same IMU / GNSS /
visual streams are synthesised as for a recorded sequence.

What this is good for
---------------------
* deterministic, dependency-free tests of parsing, sync, injection, metrics
  and the estimators;
* a known-answer test: because the motion is analytic, the synthesised IMU can
  be integrated back and compared against the analytic pose, which validates
  the propagation maths independently of any dataset.

What this is not good for
-------------------------
It has no noise floor, no vibration, no motion blur, no lighting change and no
operator behaviour. It must not be used to claim anything about real
localization performance. It is a test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .geometry.rigid import quat_mul, quat_to_matrix, rot_exp, rot_log_batch
from .types import GRAVITY, ImuSample, Trajectory


@dataclass
class SyntheticConfig:
    """Motion parameters for the generator.

    Every amplitude is a **peak-to-trough excursion** and the motion is built
    from ``1 - cos(w t)`` terms, which means position, velocity, rotation and
    angular rate are all zero at ``t = 0``. That is deliberate and it is what
    makes the fixture usable as a known-answer test: an estimator initialised at
    the identity pose with zero velocity is then *exactly* correct at t=0, so
    any subsequent error is attributable to the estimator and not to an
    uninitialised state. A circular orbit cannot satisfy this -- every point on
    a circle is a point of nonzero speed -- which is why the path is a smooth
    wander rather than a loop.
    """

    duration_s: float = 30.0
    rate_hz: float = 100.0
    radius_m: float = 4.0
    circles: float = 1.5
    sway_amplitude_m: float = 0.6
    sway_cycles: float = 3.0
    yaw_amplitude_deg: float = 35.0
    yaw_cycles: float = 1.0
    roll_amplitude_deg: float = 4.0
    roll_cycles: float = 6.0
    height_amplitude_m: float = 0.15
    start_position: tuple[float, float, float] = (1.0, 0.0, 1.6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "rate_hz": self.rate_hz,
            "radius_m": self.radius_m,
            "circles": self.circles,
            "sway_amplitude_m": self.sway_amplitude_m,
            "sway_cycles": self.sway_cycles,
            "yaw_amplitude_deg": self.yaw_amplitude_deg,
            "yaw_cycles": self.yaw_cycles,
            "roll_amplitude_deg": self.roll_amplitude_deg,
            "roll_cycles": self.roll_cycles,
            "height_amplitude_m": self.height_amplitude_m,
            "start_position": list(self.start_position),
        }


def _swing(amplitude: float, w: float, t: np.ndarray) -> np.ndarray:
    """``amplitude * (1 - cos(w t))``: zero value and zero slope at t=0."""
    return amplitude * (1.0 - np.cos(w * t))


def analytic_pose(cfg: SyntheticConfig, t: np.ndarray) -> np.ndarray:
    """Pose at times ``t`` from the closed-form motion. Returns ``(N, 4, 4)``.

    The body starts at the identity attitude (yaw and roll both zero) and the
    first pose is exactly ``start_position``.
    """
    t = np.asarray(t, dtype=float).reshape(-1)
    tau = 2.0 * np.pi
    w_orbit = tau * cfg.circles / cfg.duration_s
    w_sway = tau * cfg.sway_cycles / cfg.duration_s
    w_yaw = tau * cfg.yaw_cycles / cfg.duration_s
    w_roll = tau * cfg.roll_cycles / cfg.duration_s

    x = cfg.start_position[0] + _swing(cfg.radius_m, w_orbit, t) + _swing(
        cfg.sway_amplitude_m, w_sway, t
    )
    y = cfg.start_position[1] + _swing(0.6 * cfg.radius_m, 1.5 * w_orbit, t)
    z = cfg.start_position[2] + _swing(cfg.height_amplitude_m, 0.7 * w_sway, t)

    yaw = np.deg2rad(cfg.yaw_amplitude_deg) * (1.0 - np.cos(w_yaw * t))
    roll = np.deg2rad(cfg.roll_amplitude_deg) * (1.0 - np.cos(w_roll * t))
    # Yaw about the world Z, roll about the body X.
    q_yaw = np.stack([np.cos(yaw / 2.0), np.zeros_like(yaw), np.zeros_like(yaw), np.sin(yaw / 2.0)], axis=1)
    q_roll = np.stack(
        [np.cos(roll / 2.0), np.sin(roll / 2.0), np.zeros_like(roll), np.zeros_like(roll)], axis=1
    )

    out = np.zeros((len(t), 4, 4))
    for i in range(len(t)):
        R = quat_to_matrix(quat_mul(q_yaw[i], q_roll[i]))
        out[i, :3, :3] = R
        out[i, :3, 3] = (x[i], y[i], z[i])
        out[i, 3, :3] = 0.0
        out[i, 3, 3] = 1.0
    return out


def synthetic_trajectory(cfg: SyntheticConfig | None = None, name: str = "synthetic") -> Trajectory:
    """Sample the analytic motion into a :class:`Trajectory`."""
    cfg = cfg or SyntheticConfig()
    n = int(round(cfg.duration_s * cfg.rate_hz)) + 1
    t = np.arange(n) / cfg.rate_hz
    return Trajectory(t=t, poses=analytic_pose(cfg, t), name=name, metadata={"synthetic": True})


def synthetic_imu(cfg: SyntheticConfig | None = None, rate_hz: float = 200.0):
    """Analytic gyro and specific force for the synthetic motion.

    Differentiating the closed form analytically instead of numerically removes
    discretisation error from the fixture, so a test that integrates this signal
    and compares against :func:`analytic_pose` is testing the propagation
    maths and nothing else.
    """
    from .types import ImuSample

    cfg = cfg or SyntheticConfig()
    n = int(round(cfg.duration_s * rate_hz)) + 1
    t = np.arange(n) / rate_hz
    eps = 1e-5
    p0 = analytic_pose(cfg, t)
    p_before = analytic_pose(cfg, t - eps)
    p_after = analytic_pose(cfg, t + eps)
    a_world = (p_after[:, :3, 3] - 2.0 * p0[:, :3, 3] + p_before[:, :3, 3]) / eps**2
    R = p0[:, :3, :3]
    accel = np.einsum("nji,nj->ni", R, a_world - GRAVITY[None, :])

    R_before = p_before[:, :3, :3]
    R_after = p_after[:, :3, :3]
    R_rel = np.einsum("nji,njk->nik", R_before, R_after)
    gyro = rot_log_batch(R_rel) / (2.0 * eps)
    return ImuSample(t=t, accel=accel, gyro=gyro, name="imu_synthetic")


def offset_rotation_sequence(duration_s: float, rate_hz: float, omega: float) -> Trajectory:
    """A pure constant-rate yaw about world Z, starting at the identity.

    The simplest possible trajectory with a non-trivial, exactly predictable
    angular rate. Used by tests that need a known answer.
    """
    t = np.arange(int(round(duration_s * rate_hz)) + 1) / rate_hz
    poses = np.zeros((len(t), 4, 4))
    for i, ti in enumerate(t):
        R = rot_exp(np.array([0.0, 0.0, omega * ti]))
        poses[i, :3, :3] = R
        poses[i, :3, 3] = (omega * 0.1 * ti**2, 0.0, 0.0)
        poses[i, 3, 3] = 1.0
    return Trajectory(t=t, poses=poses, name="offset_rotation")
