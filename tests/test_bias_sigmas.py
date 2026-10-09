"""The initial IMU bias sigmas: drawn by the generator, known to the filter, and per bias.

Before ADR-0014's companion change these were accepted, scaled and hashed but read by nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.benchmark import _eskf_config
from navkit.degrade.config import scenario_from_dict
from navkit.degrade.inject import apply_imu_noise
from navkit.estimators.eskf import _IDX_BA, _IDX_BG, ErrorStateKalmanFilter, EskfConfig
from navkit.io.imu import ImuNoiseModel
from navkit.types import ImuSample


def _imu(n: int = 400) -> ImuSample:
    t = np.arange(n) * 0.005
    return ImuSample(t=t, accel=np.tile([0.0, 0.0, -9.80665], (n, 1)), gyro=np.zeros((n, 3)))


def _scenario(gyro_sigma: float, accel_sigma: float, scale: float = 1.0, name: str = "s"):
    sc = scenario_from_dict({"name": name, "imu_noise_scale": scale})
    assert sc is not None
    sc.imu_noise = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, gyro_sigma, accel_sigma)
    return sc


def test_a_zero_sigma_leaves_the_initial_bias_at_zero():
    _, gyro_bias, accel_bias = apply_imu_noise(_imu(), _scenario(0.0, 0.0))
    assert np.allclose(gyro_bias[0], 0.0) and np.allclose(accel_bias[0], 0.0)


def test_a_positive_sigma_draws_a_nonzero_initial_bias_that_is_reproducible():
    sc = _scenario(0.01, 0.2)
    _, g1, a1 = apply_imu_noise(_imu(), sc)
    _, g2, a2 = apply_imu_noise(_imu(), sc)
    assert np.array_equal(g1, g2) and np.array_equal(a1, a2)
    assert np.linalg.norm(g1[0]) > 0.0 and np.linalg.norm(a1[0]) > 0.0


def test_the_initial_bias_is_a_constant_offset_and_leaves_the_noise_draws_unchanged():
    """It has its own stream, so scenarios that had no bias sigma keep their white noise bit for bit."""
    base, _, _ = apply_imu_noise(_imu(), _scenario(0.0, 0.0))
    biased, g, a = apply_imu_noise(_imu(), _scenario(0.01, 0.2))
    assert np.allclose(biased.gyro - base.gyro, g[0], atol=1e-12)
    assert np.allclose(biased.accel - base.accel, a[0], atol=1e-12)


def test_the_spread_of_the_initial_bias_follows_the_sigma():
    draws = np.array([apply_imu_noise(_imu(8), _scenario(0.0, 0.2, name=f"s{k}"))[2][0] for k in range(400)])
    assert draws.std() == pytest.approx(0.2, rel=0.15)
    assert abs(draws.mean()) < 0.05


def test_the_noise_scale_scales_the_bias_sigma_too():
    _, _, a1 = apply_imu_noise(_imu(8), _scenario(0.0, 0.2, scale=1.0))
    _, _, a2 = apply_imu_noise(_imu(8), _scenario(0.0, 0.2, scale=3.0))
    assert np.allclose(a2[0], 3.0 * a1[0])


def test_the_benchmark_filter_is_told_the_sigmas_the_generator_used():
    sc = _scenario(0.01, 0.2, scale=2.0)
    cfg = _eskf_config(sc, {})
    assert cfg.initial_gyro_bias_sigma == pytest.approx(0.02)
    assert cfg.initial_accel_bias_sigma == pytest.approx(0.4)


def test_the_filter_takes_the_two_bias_sigmas_separately_and_falls_back_to_the_shared_one():
    noise = ImuNoiseModel(2e-4, 2e-3)
    split = ErrorStateKalmanFilter(
        EskfConfig(imu_noise=noise, initial_gyro_bias_sigma=0.01, initial_accel_bias_sigma=0.3)
    )
    P = split._initial_covariance()
    assert np.allclose(np.diag(P[_IDX_BG, _IDX_BG]), 0.01**2) and np.allclose(np.diag(P[_IDX_BA, _IDX_BA]), 0.3**2)
    shared = ErrorStateKalmanFilter(EskfConfig(imu_noise=noise, initial_bias_sigma=0.05))._initial_covariance()
    assert np.allclose(np.diag(shared[_IDX_BG, _IDX_BG]), 0.05**2) and np.allclose(
        np.diag(shared[_IDX_BA, _IDX_BA]), 0.05**2
    )
    mixed = ErrorStateKalmanFilter(EskfConfig(imu_noise=noise, initial_bias_sigma=0.05, initial_gyro_bias_sigma=0.0))
    P = mixed._initial_covariance()
    assert np.allclose(P[_IDX_BG, _IDX_BG], 0.0) and np.allclose(np.diag(P[_IDX_BA, _IDX_BA]), 0.05**2)


def test_both_keys_are_serialised():
    d = EskfConfig(imu_noise=ImuNoiseModel(), initial_accel_bias_sigma=0.3).as_dict()
    assert d["initial_gyro_bias_sigma"] is None and d["initial_accel_bias_sigma"] == 0.3
