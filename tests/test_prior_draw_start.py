"""ADR-0027: every synthetic ESKF case starts at the truth plus a seeded draw from its own declared prior.

The draw is a helper in ``navkit.benchmark`` (``draw_start_error`` and ``start_state``), tested on its own for speed.
Whole cases are run only where the claim is about a run: the switch changes nothing else, the sensor streams do not
move, the truth mode starts with no error, the dead-reckoning control keeps the true start.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit.estimators.dead_reckoning import DeadReckoning
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.eval.statistics import chi2_ppf
from navkit.geometry.rigid import rot_exp, rot_log
from navkit.io.imu import ImuNoiseModel

#: Not the library default, so a draw that ignored the config would be caught.
CFG = EskfConfig(
    imu_noise=ImuNoiseModel(), initial_pos_sigma_m=1.5, initial_vel_sigma_m_s=0.4, initial_rot_sigma_deg=3.0
)
SIGMAS = np.array([1.5] * 3 + [0.4] * 3 + [np.deg2rad(3.0)] * 3)


def _loaded() -> tuple[dict[str, Any], dict[str, Any]]:
    doc = yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))
    return doc["defaults"], doc["cases"]


def _run(name: str, mode: str | None, seed: int | None = None, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one case with a start mode and keep what the estimator was called with."""
    defaults, cases = _loaded()
    defaults = copy.deepcopy(defaults)
    if mode is not None:
        defaults.setdefault("estimator", {})["initial_start"] = mode
    seen: dict[str, Any] = {}
    original = ErrorStateKalmanFilter.run

    def spy(self: ErrorStateKalmanFilter, imu: Any, *args: Any, **kw: Any) -> Any:
        seen["imu"], seen["args"], seen["kwargs"] = imu, args, dict(kw)
        return original(self, imu, *args, **kw)

    ErrorStateKalmanFilter.run = spy  # type: ignore[method-assign]
    try:
        record = bm.run_case(name, copy.deepcopy(cases[name]), defaults, seed=seed, **kwargs)
    finally:
        ErrorStateKalmanFilter.run = original  # type: ignore[method-assign]
    return record, seen


# ----------------------------------------------------------------------- the helper


def test_the_same_seed_gives_the_same_draw_and_another_seed_another_draw():
    a, b, c = bm.draw_start_error(CFG, 7), bm.draw_start_error(CFG, 7), bm.draw_start_error(CFG, 8)
    for x, y in zip((a.dp, a.dv, a.dtheta), (b.dp, b.dv, b.dtheta), strict=True):
        np.testing.assert_array_equal(x, y)
    assert not np.array_equal(a.dp, c.dp) and not np.array_equal(a.dtheta, c.dtheta)


def test_the_draw_has_its_own_stream_and_is_not_the_one_the_seed_gives_a_sensor():
    err = bm.draw_start_error(CFG, 7)
    flat = np.concatenate([err.dp / 1.5, err.dv / 0.4, err.dtheta / np.deg2rad(3.0)])
    sensor_like = np.random.default_rng(7).standard_normal(9)
    assert not np.allclose(flat, sensor_like)
    assert isinstance(bm.PRIOR_DRAW_STREAM, int)
    # the draw consumes nothing from a generator seeded the usual way
    rng = np.random.default_rng(7)
    first = rng.standard_normal(3)
    bm.draw_start_error(CFG, 7)
    np.testing.assert_array_equal(first, np.random.default_rng(7).standard_normal(3))


def test_the_draw_follows_the_declared_prior_in_distribution():
    """9 degrees of freedom (position, velocity, attitude), each axis independent and zero mean.

    The sum of the squared normalised components over N draws is chi-square with 9N degrees of freedom, so its mean
    over N has a two-sided 95% band from ``chi2_ppf``. Each component's mean and sd are checked as well. The sd of a
    sample sd of N = 4000 normal draws is about 1.1%, so 5% is more than four of them, and the mean is within four
    standard errors of zero.
    """
    n = 4000
    draws = np.array([np.concatenate([e.dp, e.dv, e.dtheta]) for e in (bm.draw_start_error(CFG, s) for s in range(n))])
    z = draws / SIGMAS
    mean_sq = float((z**2).sum(axis=1).mean())
    assert chi2_ppf(0.025, 9 * n) / n <= mean_sq <= chi2_ppf(0.975, 9 * n) / n
    assert np.all(np.abs(draws.mean(axis=0)) < 4.0 * SIGMAS / np.sqrt(n))
    np.testing.assert_allclose(draws.std(axis=0, ddof=1) / SIGMAS, 1.0, atol=0.05)
    # independent axes: the sample correlation of any two components is small (4 standard errors)
    corr = np.corrcoef(z.T)
    assert np.abs(corr - np.eye(9)).max() < 4.0 / np.sqrt(n)


def test_the_attitude_error_is_in_the_filters_convention():
    """The filter injects ``R <- R Exp(dtheta)``. The estimate is built so that the truth is ``R_est Exp(dtheta)``.

    Measured with the same expression the filter's reset uses and with the matrix logarithm, the error comes back as
    the draw, to rounding.
    """
    rng = np.random.default_rng(3)
    true_r = rot_exp(rng.standard_normal(3))
    err = bm.draw_start_error(CFG, 11)
    start = bm.start_state(true_r, np.array([1.0, 0.0, 1.6]), np.zeros(3), err)
    np.testing.assert_allclose(start.R @ rot_exp(err.dtheta), true_r, atol=1e-12)
    np.testing.assert_allclose(rot_log(start.R.T @ true_r), err.dtheta, atol=1e-12)
    np.testing.assert_allclose(np.array([1.0, 0.0, 1.6]) - start.p, err.dp)
    np.testing.assert_allclose(-start.v, err.dv)
    np.testing.assert_array_equal(start.b_a, np.zeros(3))
    np.testing.assert_array_equal(start.b_g, np.zeros(3))


def test_the_synthetic_truth_starts_at_rest_so_the_true_velocity_is_zero():
    """``start_state`` is given the true velocity. The synthetic motion is zero there by construction (not a finite
    difference of the positions), which this checks against the analytic pose with a centred difference."""
    from navkit.synthetic import SyntheticConfig, analytic_pose

    cfg = SyntheticConfig(duration_s=30.0, rate_hz=100.0)
    h = 1e-5
    p = analytic_pose(cfg, np.array([-h, h]))[:, :3, 3]
    assert np.linalg.norm((p[1] - p[0]) / (2 * h)) < 1e-6


# ------------------------------------------------------------------------ the switch


def test_the_benchmark_file_sets_the_prior_draw_and_the_modes_are_named():
    defaults, _ = _loaded()
    assert defaults["estimator"]["initial_start"] == "prior_draw"
    assert bm.START_MODES == ("origin", "truth", "prior_draw")


def test_an_unknown_start_mode_is_refused():
    with pytest.raises(ValueError, match="initial_start"):
        _run("gnss_only", "somewhere")


def test_origin_calls_the_filter_exactly_as_before_and_the_mode_is_in_the_hash():
    rec_o, seen_o = _run("gnss_only", "origin")
    rec_p, seen_p = _run("gnss_only", "prior_draw")
    rec_t, _ = _run("gnss_only", "truth")
    assert seen_o["kwargs"].get("initial") is None
    assert seen_p["kwargs"]["initial"] is not None
    assert rec_o["estimator"]["initial_start"] == "origin"
    assert len({rec_o["config_hash"], rec_p["config_hash"], rec_t["config_hash"]}) == 3
    # the setting is the only difference in the estimator block
    a, b = dict(rec_o["estimator"]), dict(rec_p["estimator"])
    a.pop("initial_start"), b.pop("initial_start")
    assert a == b


def test_the_sensor_streams_do_not_move_with_the_start_mode():
    """The IMU, GNSS and vision samples are identical with ``origin`` and ``prior_draw`` for the same seed."""
    streams = {}
    for mode in ("origin", "prior_draw"):
        _, seen = _run("outage_visual", mode, seed=4)
        gnss, vision = seen["kwargs"]["gnss"], seen["kwargs"]["vision"]
        streams[mode] = (seen["imu"], gnss, vision)
    (imu_a, gnss_a, vis_a), (imu_b, gnss_b, vis_b) = streams["origin"], streams["prior_draw"]
    np.testing.assert_array_equal(imu_a.accel, imu_b.accel)
    np.testing.assert_array_equal(imu_a.gyro, imu_b.gyro)
    np.testing.assert_array_equal(gnss_a.positions, gnss_b.positions)
    np.testing.assert_array_equal(gnss_a.t, gnss_b.t)
    np.testing.assert_array_equal(vis_a.t_rel, vis_b.t_rel)
    np.testing.assert_array_equal(vis_a.R_rel, vis_b.R_rel)


def test_the_truth_mode_starts_with_no_error():
    """The initial state is the truth to the last bit; with no GNSS fix at the first sample, so is the estimate."""
    rec, seen = _run("gnss_only", "truth")
    start = seen["kwargs"]["initial"]
    np.testing.assert_array_equal(start.v, np.zeros(3))
    np.testing.assert_array_equal(start.b_a, np.zeros(3))
    np.testing.assert_array_equal(start.b_g, np.zeros(3))
    np.testing.assert_array_equal(start.p, np.array(rec["synthetic"]["start_position"]))
    np.testing.assert_allclose(start.R, np.eye(3), atol=1e-12)  # the synthetic truth starts with the identity attitude
    # vision_only has no GNSS, and its first visual measurement has no predecessor, so the first estimate is the start
    rec2, _ = _run("vision_only", "truth", trajectories=True)
    est0 = np.array(rec2["trajectory_est"]["positions"])[0]
    ref0 = np.array(rec2["trajectory_ref"]["positions"])[0]
    assert np.linalg.norm(est0 - ref0) < 1e-9


def test_the_prior_draw_starts_away_from_the_truth_by_the_drawn_error_and_it_follows_the_case_seed():
    rec3, seen3 = _run("gnss_only", "prior_draw", seed=3, trajectories=True)
    rec4, seen4 = _run("gnss_only", "prior_draw", seed=4)
    cfg = EskfConfig(imu_noise=ImuNoiseModel())  # the prior the case declares (library defaults)
    expect = bm.draw_start_error(
        EskfConfig(
            imu_noise=ImuNoiseModel(),
            initial_pos_sigma_m=rec3["estimator"]["initial_pos_sigma_m"],
            initial_vel_sigma_m_s=rec3["estimator"]["initial_vel_sigma_m_s"],
            initial_rot_sigma_deg=rec3["estimator"]["initial_rot_sigma_deg"],
        ),
        3,
    )
    assert cfg.initial_pos_sigma_m == rec3["estimator"]["initial_pos_sigma_m"]
    start = seen3["kwargs"]["initial"]
    np.testing.assert_allclose(-start.v, expect.dv)
    np.testing.assert_allclose(np.array(rec3["synthetic"]["start_position"]) - start.p, expect.dp)
    assert not np.allclose(start.p, seen4["kwargs"]["initial"].p)
    assert rec3["seed"] == 3 and rec4["seed"] == 4


def test_the_dead_reckoning_control_keeps_the_true_start():
    original = DeadReckoning.run
    seen: dict[str, Any] = {}

    def spy(self: DeadReckoning, imu: Any, *args: Any, **kw: Any) -> Any:
        seen["initial"] = kw.get("initial")
        return original(self, imu, *args, **kw)

    DeadReckoning.run = spy  # type: ignore[method-assign]
    try:
        rec, _ = _run("dead_reckoning", "prior_draw")
    finally:
        DeadReckoning.run = original  # type: ignore[method-assign]
    assert rec["estimator"]["initial_start"] == "truth"
    np.testing.assert_allclose(seen["initial"].R, np.eye(3), atol=1e-12)
    np.testing.assert_array_equal(seen["initial"].v, np.zeros(3))
