"""Regression tests for inertial noise injection.

``apply_imu_noise`` built per-sample covariance of shape ``(N, 1)`` while
``ImuSample`` requires diagonal ``(N, 3)``, so every call raised ``ValueError``
and the whole IMU-noise degradation path was unreachable. These tests exist to
keep it reachable.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.io.imu import DEFAULT_NOISE, ImuNoiseModel, apply_imu_noise, imu_residual
from navkit.synthetic import SyntheticConfig, synthetic_imu
from navkit.types import ImuSample


@pytest.fixture()
def clean_imu():
    return synthetic_imu(SyntheticConfig(duration_s=2.0, rate_hz=100.0), rate_hz=200.0)


def test_apply_imu_noise_returns_diagonal_covariance_of_the_right_shape(clean_imu) -> None:
    model = ImuNoiseModel(1e-3, 1e-2, 1e-5, 1e-4, 1e-4, 1e-3)
    noisy, gyro_bias, accel_bias = apply_imu_noise(
        clean_imu, model, np.random.default_rng(0)
    )
    n = len(clean_imu)
    assert len(noisy) == n
    assert noisy.accel_cov.shape == (n, 3)
    assert noisy.gyro_cov.shape == (n, 3)
    assert np.all(np.isfinite(noisy.accel_cov))
    assert np.all(noisy.accel_cov > 0.0)
    assert gyro_bias.shape == (n, 3)
    assert accel_bias.shape == (n, 3)


def test_apply_imu_noise_preserves_the_time_base(clean_imu) -> None:
    noisy, _, _ = apply_imu_noise(clean_imu, DEFAULT_NOISE, np.random.default_rng(1))
    assert np.array_equal(noisy.t, clean_imu.t)
    assert noisy.accel.shape == clean_imu.accel.shape
    assert noisy.gyro.shape == clean_imu.gyro.shape


def test_apply_imu_noise_actually_changes_the_samples(clean_imu) -> None:
    noisy, _, _ = apply_imu_noise(clean_imu, DEFAULT_NOISE, np.random.default_rng(2))
    assert not np.allclose(noisy.accel, clean_imu.accel)
    assert not np.allclose(noisy.gyro, clean_imu.gyro)


def test_apply_imu_noise_is_reproducible_for_a_fixed_generator(clean_imu) -> None:
    a, _, _ = apply_imu_noise(clean_imu, DEFAULT_NOISE, np.random.default_rng(3))
    b, _, _ = apply_imu_noise(clean_imu, DEFAULT_NOISE, np.random.default_rng(3))
    assert np.array_equal(a.accel, b.accel)
    assert np.array_equal(a.gyro, b.gyro)


def test_apply_imu_noise_leaves_a_clean_stream_alone_for_a_zero_model(clean_imu) -> None:
    zero = ImuNoiseModel()
    noisy, gyro_bias, accel_bias = apply_imu_noise(clean_imu, zero, np.random.default_rng(4))
    assert np.allclose(noisy.accel, clean_imu.accel)
    assert np.allclose(noisy.gyro, clean_imu.gyro)
    assert np.allclose(gyro_bias, 0.0)
    assert np.allclose(accel_bias, 0.0)


def test_apply_imu_noise_applies_a_constant_bias(clean_imu) -> None:
    # Zero white noise, so the constant bias is the only difference and can be
    # asserted exactly rather than within the tolerance of a noise estimate.
    model = ImuNoiseModel()
    gb0 = np.array([0.01, 0.0, 0.0])
    ab0 = np.array([0.0, 0.0, 0.2])
    noisy, gyro_bias, accel_bias = apply_imu_noise(
        clean_imu, model, np.random.default_rng(5), bias_gyro_0=gb0, bias_accel_0=ab0
    )
    assert np.allclose(gyro_bias, gb0)
    assert np.allclose(accel_bias, ab0)
    residual = imu_residual(noisy, clean_imu)
    assert residual["gyro_bias_mean_rad_s"] == pytest.approx(0.01, rel=1e-6)
    assert residual["gyro_bias_xyz_rad_s"] == pytest.approx([0.01, 0.0, 0.0], abs=1e-9)
    assert residual["samples"] == len(clean_imu)
    # The pooled noise std is deliberately not asserted to be zero: a constant
    # per-axis bias makes it non-zero, which is why the per-axis mean exists.


def test_apply_imu_noise_needs_at_least_two_samples() -> None:
    base = synthetic_imu(SyntheticConfig(duration_s=0.01, rate_hz=100.0), rate_hz=100.0)
    single = ImuSample(t=base.t[:1], accel=base.accel[:1], gyro=base.gyro[:1])
    with pytest.raises(ValueError, match="at least 2 IMU samples"):
        apply_imu_noise(single, DEFAULT_NOISE, np.random.default_rng(6))
