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


def _sigmas(form: str, accel_noise: float, gyro_noise: float, dt: float = 0.005, horizon: float = 10.0):
    """1-sigma position, velocity and attitude after ``horizon`` s from one white-noise source alone.

    Separately, because gyro noise also reaches velocity and position through gravity (a tilt of
    theta is a horizontal acceleration of g * theta), and that is physics, not process noise.
    """
    cfg = EskfConfig(
        imu_noise=ImuNoiseModel(gyro_noise_density=gyro_noise, accel_noise_density=accel_noise),
        initial_pos_sigma_m=0.0,
        initial_vel_sigma_m_s=0.0,
        initial_rot_sigma_deg=0.0,
        process_noise_form=form,
    )
    f = ErrorStateKalmanFilter(cfg)
    x = f._initial_state()
    for _ in range(int(horizon / dt)):
        f._propagate(x, np.array([0.0, 0.0, -9.80665]), np.zeros(3), dt)
    P = x["P"]
    return (
        float(np.sqrt(P[_IDX_P, _IDX_P][0, 0])),
        float(np.sqrt(P[_IDX_V, _IDX_V][0, 0])),
        float(np.sqrt(P[_IDX_THETA, _IDX_THETA][0, 0])),
    )


def _assert_white_noise_growth(form: str) -> None:
    sa, sg, horizon = 2.0e-3, 1.7e-4, 10.0
    pos, vel, _ = _sigmas(form, accel_noise=sa, gyro_noise=0.0)
    assert pos == pytest.approx(sa * np.sqrt(horizon**3 / 3.0), rel=0.2)
    assert vel == pytest.approx(sa * np.sqrt(horizon), rel=0.2)
    _, _, att = _sigmas(form, accel_noise=0.0, gyro_noise=sg)
    assert att == pytest.approx(sg * np.sqrt(horizon), rel=0.2)


@pytest.mark.xfail(strict=True, reason="legacy form: no velocity term, and dt^3 on attitude")
def test_white_imu_noise_grows_the_covariance_as_theory_says():
    """Position sigma_a sqrt(t^3/3), velocity sigma_a sqrt(t) and attitude sigma_g sqrt(t), no prior, no bias."""
    _assert_white_noise_growth("legacy")


def test_the_textbook_process_noise_form_gives_the_white_noise_growth():
    """The form the xfail above asks for. It is the default since ADR-0014."""
    _assert_white_noise_growth("textbook")


def test_the_default_process_noise_form_is_textbook_and_is_serialised():
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.process_noise_form == "textbook"
    assert cfg.as_dict()["process_noise_form"] == "textbook"
    legacy = EskfConfig(imu_noise=ImuNoiseModel(), process_noise_form="legacy")
    assert legacy.as_dict()["process_noise_form"] == "legacy"


def test_an_unknown_process_noise_form_is_rejected():
    f = ErrorStateKalmanFilter(EskfConfig(imu_noise=ImuNoiseModel(accel_noise_density=1e-3), process_noise_form="x"))
    with pytest.raises(ValueError, match="process_noise_form"):
        f._propagate(f._initial_state(), np.zeros(3), np.zeros(3), 0.005)
