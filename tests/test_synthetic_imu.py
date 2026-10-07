"""The synthetic IMU is derived analytically, so it is exact and does not depend on the math library."""

from __future__ import annotations

import numpy as np
import pytest

import navkit.synthetic as synthetic
from navkit.geometry.rigid import rot_log_batch
from navkit.synthetic import SyntheticConfig, analytic_kinematics, analytic_pose, synthetic_imu
from navkit.types import GRAVITY


@pytest.fixture(scope="module")
def cfg() -> SyntheticConfig:
    return SyntheticConfig()


def test_acceleration_matches_a_wide_step_finite_difference(cfg: SyntheticConfig) -> None:
    """An independent check: central second difference with a step wide enough to be accurate."""
    t = np.linspace(0.5, 29.5, 59)
    h = 1e-3

    def position(tt: np.ndarray) -> np.ndarray:
        return analytic_pose(cfg, tt)[:, :3, 3]

    fd = (position(t + h) - 2.0 * position(t) + position(t - h)) / h**2
    a_world, _ = analytic_kinematics(cfg, t)
    # Truncation error of the difference is h^2 f''''/12, about 1e-7 here.
    assert np.allclose(a_world, fd, atol=1e-5)


def test_angular_velocity_matches_the_attitude_it_derives_from(cfg: SyntheticConfig) -> None:
    t = np.linspace(0.5, 29.5, 59)
    h = 1e-4
    R0 = analytic_pose(cfg, t - h)[:, :3, :3]
    R1 = analytic_pose(cfg, t + h)[:, :3, :3]
    fd = rot_log_batch(np.einsum("nji,njk->nik", R0, R1)) / (2.0 * h)
    _, omega = analytic_kinematics(cfg, t)
    assert np.allclose(omega, fd, atol=1e-7)


def test_the_motion_starts_at_rest(cfg: SyntheticConfig) -> None:
    _, omega = analytic_kinematics(cfg, np.array([0.0]))
    assert np.allclose(omega, 0.0, atol=1e-15)


def test_specific_force_at_rest_is_minus_gravity_in_the_body_frame(cfg: SyntheticConfig) -> None:
    """At t = 0 the attitude is the identity, so the accelerometer reads a_world - g."""
    imu = synthetic_imu(cfg)
    a_world, _ = analytic_kinematics(cfg, np.array([0.0]))
    assert np.allclose(imu.accel[0], a_world[0] - GRAVITY)


def test_a_one_ulp_change_in_cos_barely_moves_the_imu(cfg: SyntheticConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression behind the cross-platform failures.

    The previous finite-difference IMU moved by up to 7e-5 m/s^2 under this perturbation,
    which is what made the benchmark differ between Linux and macOS or Windows at 1e-7.
    """
    base = synthetic_imu(cfg)
    real_cos = np.cos

    def jittered(x, *args, **kwargs):  # type: ignore[no-untyped-def]
        y = real_cos(x, *args, **kwargs)
        return y + np.spacing(y) * np.sign(np.sin(np.asarray(x) * 1000.0))

    monkeypatch.setattr(synthetic.np, "cos", jittered)
    perturbed = synthetic_imu(cfg)
    assert np.max(np.abs(perturbed.accel - base.accel)) < 1e-12
    assert np.max(np.abs(perturbed.gyro - base.gyro)) < 1e-12
