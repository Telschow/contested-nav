"""Two defects found while building the EuRoC evaluation. Each test states the correct behaviour
and is `xfail(strict=True)`, so it fails the day the defect is fixed and the marker must go.

Neither was fixed in the change that found them: both move numbers the golden snapshot pins, and
the process-noise change needs an ADR. See the changelog entry for the EuRoC evaluation.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.estimators.eskf import _IDX_P, _IDX_THETA, _IDX_V, ErrorStateKalmanFilter, EskfConfig
from navkit.io.imu import ImuNoiseModel
from navkit.types import finite_difference


@pytest.mark.xfail(strict=True, reason="first derivative is the sum of the two one-sided differences, not their mean")
def test_finite_difference_first_derivative_of_a_ramp_is_its_slope():
    t = np.arange(6) * 0.1
    v = finite_difference(t, 2.0 * t).ravel()
    assert np.allclose(v, 2.0)


@pytest.mark.xfail(
    strict=True, reason="IMU white noise barely enters the covariance: no velocity term, dt^3 on attitude"
)
def test_white_imu_noise_grows_the_covariance_as_theory_says():
    """With no prior and no bias, white noise alone gives sigma_a sqrt(t^3/3) in position,
    sigma_a sqrt(t) in velocity and sigma_g sqrt(t) in attitude."""
    sa, sg, dt, horizon = 2.0e-3, 1.7e-4, 0.005, 10.0
    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(gyro_noise_density=sg, accel_noise_density=sa),
        initial_pos_sigma_m=0.0,
        initial_vel_sigma_m_s=0.0,
        initial_rot_sigma_deg=0.0,
    )
    f = ErrorStateKalmanFilter(cfg)
    x = f._initial_state()
    for _ in range(int(horizon / dt)):
        f._propagate(x, np.array([0.0, 0.0, -9.80665]), np.zeros(3), dt)
    P = x["P"]
    assert np.sqrt(P[_IDX_P, _IDX_P][0, 0]) == pytest.approx(sa * np.sqrt(horizon**3 / 3.0), rel=0.2)
    assert np.sqrt(P[_IDX_V, _IDX_V][0, 0]) == pytest.approx(sa * np.sqrt(horizon), rel=0.2)
    assert np.sqrt(P[_IDX_THETA, _IDX_THETA][0, 0]) == pytest.approx(sg * np.sqrt(horizon), rel=0.2)
