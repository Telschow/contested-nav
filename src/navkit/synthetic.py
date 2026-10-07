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

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from .geometry.rigid import quat_mul, quat_to_matrix, rot_exp
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


#: Multiplicative range for each scene parameter under :func:`seeded_scene`.
#:
#: These bounds are the honest ones for a *generalisation* claim rather than a
#: robustness one. They hold the motion inside the regime the estimator was
#: configured for -- a slow wander with mild rotation, no loops, no reversals,
#: and the same duration and rate as the committed baseline so the number stays
#: comparable to the published one. What varies is the geometry: how far the
#: platform travels, how quickly, and how it turns.
#:
#: The narrower of the two is `radius_m`, at 0.6x. A shorter path leaves less
#: distance for drift to accumulate, so it is the favourable direction for an
#: estimator, not a neutral one. Widening it to 0.4x would make the spread
#: easier to find and much easier to overstate.
_SCENE_RANGES: dict[str, tuple[float, float]] = {
    "radius_m": (0.6, 1.4),
    "circles": (0.6, 1.4),
    "sway_amplitude_m": (0.5, 1.5),
    "sway_cycles": (0.7, 1.3),
    "yaw_amplitude_deg": (0.7, 1.3),
    "yaw_cycles": (0.7, 1.3),
    "roll_amplitude_deg": (0.5, 1.5),
    "roll_cycles": (0.8, 1.2),
    "height_amplitude_m": (0.5, 1.5),
}


def seeded_scene(cfg: SyntheticConfig, seed: int) -> SyntheticConfig:
    """A :class:`SyntheticConfig` with its motion parameters varied by ``seed``.

    The seed sweep already exists and varies sensor noise. That answers "is this
    filter overconfident under this noise", which is not the same question as
    "does this filter overconfident in general". Every published number comes
    from one trajectory, so a result that is an artefact of that trajectory --
    a particular excursion, a particular turn -- would be indistinguishable from
    a property of the estimator. This makes that distinction testable.

    Two invariants are preserved, and both are load-bearing:

    * ``duration_s`` and ``rate_hz`` are untouched, so a swept result is
      directly comparable to the committed single-scene baseline.
    * The motion is still built from ``1 - cos(w t)`` terms, so position,
      velocity, and rotation are exactly zero at ``t = 0`` regardless of the
      seed. An estimator initialised at the identity pose with zero velocity
      remains *exactly* correct at the first sample, which is the property that
      makes the fixture a known-answer test. A generator that varied the start
      state would quietly break that and make every error un-attributable.

    Parameters are drawn jointly from one generator, so a given seed is a single
    reproducible scene rather than a sequence of independent ones.
    """
    rng = np.random.default_rng(seed)
    varied: dict[str, Any] = {}
    for name, (lo, hi) in _SCENE_RANGES.items():
        current = float(getattr(cfg, name))
        # A multiplicative log-uniform draw: uniform-in-multiplier is what keeps
        # the geometric centre of the range at the configured value, so the
        # swept ensemble is centred on the committed baseline rather than
        # biased towards one end of it.
        varied[name] = current * float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
    return replace(cfg, **varied)


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

    x = cfg.start_position[0] + _swing(cfg.radius_m, w_orbit, t) + _swing(cfg.sway_amplitude_m, w_sway, t)
    y = cfg.start_position[1] + _swing(0.6 * cfg.radius_m, 1.5 * w_orbit, t)
    z = cfg.start_position[2] + _swing(cfg.height_amplitude_m, 0.7 * w_sway, t)

    yaw = np.deg2rad(cfg.yaw_amplitude_deg) * (1.0 - np.cos(w_yaw * t))
    roll = np.deg2rad(cfg.roll_amplitude_deg) * (1.0 - np.cos(w_roll * t))
    # Yaw about the world Z, roll about the body X.
    q_yaw = np.stack([np.cos(yaw / 2.0), np.zeros_like(yaw), np.zeros_like(yaw), np.sin(yaw / 2.0)], axis=1)
    q_roll = np.stack([np.cos(roll / 2.0), np.sin(roll / 2.0), np.zeros_like(roll), np.zeros_like(roll)], axis=1)

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


def analytic_kinematics(cfg: SyntheticConfig, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World acceleration and body angular velocity of the closed-form motion, by derivation.

    Position is ``x0 + A (1 - cos(w t))`` per axis, so the acceleration is
    ``A w^2 cos(w t)``. Attitude is ``R = Rz(yaw) Rx(roll)``, so the angular velocity
    in the body frame is ``(roll_dot, yaw_dot sin(roll), yaw_dot cos(roll))``. Both are
    exact, and neither involves a difference of nearly equal numbers.

    This replaces a second finite difference of :func:`analytic_pose` with a step of
    1e-5 s. That version divided a rounding error of about 1e-16 by 1e-10, so a one-ulp
    change in ``cos`` (which differs between math libraries) moved the accelerometer by up
    to 7e-5 m/s^2, and the benchmark disagreed between Linux and macOS or Windows at the
    1e-7 level. Returns ``(a_world (N, 3), omega_body (N, 3))``.
    """
    t = np.asarray(t, dtype=float).reshape(-1)
    tau = 2.0 * np.pi
    w_orbit = tau * cfg.circles / cfg.duration_s
    w_sway = tau * cfg.sway_cycles / cfg.duration_s
    w_yaw = tau * cfg.yaw_cycles / cfg.duration_s
    w_roll = tau * cfg.roll_cycles / cfg.duration_s

    ax = cfg.radius_m * w_orbit**2 * np.cos(w_orbit * t) + cfg.sway_amplitude_m * w_sway**2 * np.cos(w_sway * t)
    ay = 0.6 * cfg.radius_m * (1.5 * w_orbit) ** 2 * np.cos(1.5 * w_orbit * t)
    az = cfg.height_amplitude_m * (0.7 * w_sway) ** 2 * np.cos(0.7 * w_sway * t)
    a_world = np.stack([ax, ay, az], axis=1)

    yaw_amp = np.deg2rad(cfg.yaw_amplitude_deg)
    roll_amp = np.deg2rad(cfg.roll_amplitude_deg)
    roll = roll_amp * (1.0 - np.cos(w_roll * t))
    yaw_rate = yaw_amp * w_yaw * np.sin(w_yaw * t)
    roll_rate = roll_amp * w_roll * np.sin(w_roll * t)
    omega_body = np.stack([roll_rate, yaw_rate * np.sin(roll), yaw_rate * np.cos(roll)], axis=1)
    return a_world, omega_body


def synthetic_imu(cfg: SyntheticConfig | None = None, rate_hz: float = 200.0):
    """Analytic gyro and specific force for the synthetic motion.

    The derivatives come from :func:`analytic_kinematics`, in closed form, so a test that
    integrates this signal and compares against :func:`analytic_pose` is testing the
    propagation maths and nothing else, on every platform.
    """

    cfg = cfg or SyntheticConfig()
    n = int(round(cfg.duration_s * rate_hz)) + 1
    t = np.arange(n) / rate_hz
    pose = analytic_pose(cfg, t)
    a_world, gyro = analytic_kinematics(cfg, t)
    accel = np.einsum("nji,nj->ni", pose[:, :3, :3], a_world - GRAVITY[None, :])
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
