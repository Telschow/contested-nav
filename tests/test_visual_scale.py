"""The adaptive visual noise scale of ADR-0031: the estimator, the config rules and the behaviour in the filter.

The scale is a catch-all for model error in the visual channel. It is not an estimate of the sensor noise, and no test
here asserts that it converges to the injected factor: the statistic ``d`` uses ``S0 = H P H^T + R0``, which includes
the state uncertainty, so its expectation is below the true ratio of variances when ``P`` is not small.

Only development seeds are used (0 to 4).
"""

from __future__ import annotations

import copy
import inspect
import math

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit.degrade import scenario_from_dict
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.estimators.visual_scale import VisualScale
from navkit.io.imu import ImuNoiseModel

# ------------------------------------------------------------------------------------------- the estimator


def _scale(tau: float = 2.0, lo: float = 0.1, hi: float = 10.0) -> VisualScale:
    return VisualScale(tau_s=tau, s_min=lo, s_max=hi)


def test_it_starts_at_one_with_nothing_seen():
    s = _scale()
    assert s.value == 1.0 and s.n_used == 0 and s.n_rejected_used == 0 and s.n_skipped_nonfinite == 0
    assert s.mean == 1.0 and s.min_seen == 1.0 and s.max_seen == 1.0


def test_update_takes_a_statistic_and_a_time_and_no_gate_decision():
    """ADR-0032: every visual update contributes, so the gate's decision is not an argument."""
    assert list(inspect.signature(VisualScale.update).parameters) == ["self", "d", "t_s"]


def test_a_constant_d_at_a_fixed_dt_follows_the_formula_exactly():
    k, dt, tau = 3.0, 0.1, 2.0
    s = _scale(tau)
    s.update(k, 0.0)  # the first update only records the time
    assert s.value == 1.0
    w = 1.0 - math.exp(-dt / tau)
    for n in range(1, 40):
        s.update(k, n * dt)
        assert s.value == pytest.approx(k + (1.0 - k) * (1.0 - w) ** n, rel=1e-12, abs=1e-12)


def test_the_first_update_does_not_move_the_scale_but_is_counted():
    s = _scale()
    s.update(5.0, 7.0)
    assert s.value == 1.0 and s.n_used == 1


def test_the_weight_depends_on_the_time_since_the_previous_update():
    a, b = _scale(tau=5.0), _scale(tau=5.0)
    a.update(1.0, 0.0)
    a.update(4.0, 1.0)
    b.update(1.0, 0.0)
    b.update(4.0, 10.0)
    assert a.value == pytest.approx(1.0 + (1.0 - math.exp(-1.0 / 5.0)) * 3.0)
    assert b.value == pytest.approx(1.0 + (1.0 - math.exp(-10.0 / 5.0)) * 3.0)
    assert b.value > a.value


def test_a_d_above_s_max_enters_as_s_max():
    big, capped = _scale(tau=1.0, lo=0.5, hi=8.0), _scale(tau=1.0, lo=0.5, hi=8.0)
    for x in (big, capped):
        x.update(1.0, 0.0)
    for i in range(1, 6):
        big.update(100.0, float(i))
        capped.update(8.0, float(i))
    assert big.value == capped.value and big.mean == capped.mean and big.max_seen == capped.max_seen


def test_the_cap_applies_before_the_average_and_not_only_to_the_state():
    """With s_max = 8 a single d of 1000 must move the scale by w * (8 - s), not by w * (1000 - s)."""
    s = _scale(tau=1.0, lo=0.5, hi=8.0)
    s.update(1.0, 0.0)
    s.update(1000.0, 1.0)
    w = 1.0 - math.exp(-1.0)
    assert s.value == pytest.approx(1.0 + w * (8.0 - 1.0))
    assert s.value < 8.0  # the state was not simply clipped from a huge step


def test_a_d_below_s_min_enters_uncapped_and_only_the_state_is_clipped():
    low, at_min = _scale(tau=2.0, lo=0.5, hi=8.0), _scale(tau=2.0, lo=0.5, hi=8.0)
    for x in (low, at_min):
        x.update(1.0, 0.0)
    low.update(0.0, 1.0)  # d is not floored at s_min ...
    at_min.update(0.5, 1.0)
    w = 1.0 - math.exp(-0.5)
    assert low.value == pytest.approx(1.0 + w * (0.0 - 1.0))
    assert at_min.value == pytest.approx(1.0 + w * (0.5 - 1.0))
    assert low.value < at_min.value
    for i in range(2, 80):  # ... but the stored state never leaves the interval
        low.update(0.0, float(i))
    assert low.value == 0.5 and low.min_seen == 0.5


def test_with_no_update_the_scale_is_held():
    s = _scale()
    s.update(1.0, 0.0)
    s.update(4.0, 1.0)
    before = (s.value, s.n_used, s.mean, s.min_seen, s.max_seen)
    for _ in range(5):  # reading it any number of times changes nothing: there is no clock inside the estimator
        assert (s.value, s.n_used, s.mean, s.min_seen, s.max_seen) == before


def test_the_scale_is_clipped_to_the_interval():
    s = _scale(tau=1.0, lo=0.5, hi=4.0)
    s.update(100.0, 0.0)
    for i in range(1, 60):
        s.update(100.0, float(i))
    assert s.value == 4.0 and s.max_seen == 4.0
    low = _scale(tau=1.0, lo=0.5, hi=4.0)
    low.update(0.0, 0.0)
    for i in range(1, 60):
        low.update(0.0, float(i))
    assert low.value == 0.5 and low.min_seen == 0.5


def test_there_is_no_wind_up_after_a_long_stay_at_a_bound():
    s = _scale(tau=1.0, lo=0.5, hi=4.0)
    s.update(1000.0, 0.0)
    for i in range(1, 300):
        s.update(1000.0, float(i))
    assert s.value == 4.0
    s.update(1.0, 300.0)  # one tau later: it must move at once, not stay pinned by hidden state
    assert s.value == pytest.approx(4.0 + (1.0 - math.exp(-1.0)) * (1.0 - 4.0))
    assert s.value < 4.0


def test_the_running_statistics_are_over_every_update():
    s = _scale(tau=1.0, lo=0.1, hi=100.0)
    seen = []
    for i, d in enumerate((1.0, 4.0, 4.0, 0.5)):
        s.update(d, float(i))
        seen.append(s.value)
    assert s.n_used == 4
    assert s.mean == pytest.approx(float(np.mean(seen)))
    assert s.min_seen == min(seen) and s.max_seen == max(seen)


def test_the_two_side_counters_start_at_zero_and_count_when_told():
    s = _scale()
    s.mark_rejected_used()
    s.mark_rejected_used()
    s.skip_nonfinite()
    assert (s.n_rejected_used, s.n_skipped_nonfinite) == (2, 1)
    assert s.n_used == 0 and s.value == 1.0  # counting does not touch the scale


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_d_passed_to_the_class_raises(bad):
    with pytest.raises(ValueError, match="finite"):
        _scale().update(bad, 0.0)


def test_time_must_not_go_backwards():
    s = _scale()
    s.update(1.0, 5.0)
    with pytest.raises(ValueError, match="time"):
        s.update(1.0, 4.0)


# --------------------------------------------------------------------------- the helpers in the filter


def test_a_gate_rejected_update_enters_the_mean_and_is_counted_as_such():
    scale = VisualScale(2.0, 0.1, 10.0)
    ErrorStateKalmanFilter._scale_after(scale, 1.0, 0.0, True)
    ErrorStateKalmanFilter._scale_after(scale, 6.0, 1.0, False)  # the gate rejected this one
    ErrorStateKalmanFilter._scale_after(scale, 6.0, 2.0, True)
    assert scale.n_used == 3 and scale.n_rejected_used == 1
    assert scale.value > 1.0  # the rejected update moved it
    ref = VisualScale(2.0, 0.1, 10.0)
    for t, d in ((0.0, 1.0), (1.0, 6.0), (2.0, 6.0)):
        ref.update(d, t)
    assert scale.value == ref.value  # exactly as if the gate decision did not exist


def test_an_unusable_innovation_covariance_is_skipped_counted_and_never_raises():
    scale = VisualScale(2.0, 0.1, 10.0)
    ErrorStateKalmanFilter._scale_after(scale, 3.0, 0.0, True)
    ErrorStateKalmanFilter._scale_after(scale, 4.0, 1.0, True)
    held = (scale.value, scale.n_used)
    for accepted in (True, False):
        ErrorStateKalmanFilter._scale_after(scale, float("nan"), 2.0, accepted)
        ErrorStateKalmanFilter._scale_after(scale, float("inf"), 2.5, accepted)
    assert (scale.value, scale.n_used) == held
    assert scale.n_skipped_nonfinite == 4 and scale.n_rejected_used == 0
    # the time of a skipped update is not recorded: the next update is weighted from t = 1, not from t = 2.5
    ref = VisualScale(2.0, 0.1, 10.0)
    ref.update(3.0, 0.0)
    ref.update(4.0, 1.0)
    ErrorStateKalmanFilter._scale_after(scale, 5.0, 3.0, True)
    ref.update(5.0, 3.0)
    assert scale.value == ref.value


def test_a_singular_innovation_covariance_gives_a_non_finite_statistic_and_not_an_exception():
    x = {"P": np.zeros((21, 21))}
    d = ErrorStateKalmanFilter._scale_statistic(x, np.ones(3), np.zeros((3, 21)), np.zeros((3, 3)))  # type: ignore[arg-type]
    assert not math.isfinite(d)


_NAN, _INF = float("nan"), float("inf")


@pytest.mark.parametrize(
    ("tau", "lo", "hi"),
    [
        (0.0, 0.5, 8.0),
        (-1.0, 0.5, 8.0),
        (_NAN, 0.5, 8.0),
        (_INF, 0.5, 8.0),
        (5.0, 0.0, 8.0),
        (5.0, -1.0, 8.0),
        (5.0, 1.5, 8.0),
        (5.0, 0.5, 0.9),
        (5.0, _NAN, 8.0),
        (5.0, 0.5, _INF),
    ],
)
def test_bad_parameters_are_refused(tau, lo, hi):
    with pytest.raises(ValueError):
        VisualScale(tau_s=tau, s_min=lo, s_max=hi)


# ------------------------------------------------------------------------------------------------ the config


def _cfg(**kw):
    kw.setdefault("vision_model", "clone")
    return EskfConfig(imu_noise=ImuNoiseModel(), **kw)


def test_it_is_off_by_default_and_the_numeric_defaults_are_placeholders_inside_the_adr_grid():
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.vision_adaptive_scale is False
    assert cfg.vision_scale_tau_s in (2.0, 5.0, 10.0)
    assert cfg.vision_scale_min in (0.25, 0.5)
    assert cfg.vision_scale_max in (8.0, 16.0)


def test_the_flag_is_accepted_with_the_clone():
    assert _cfg(vision_adaptive_scale=True).vision_adaptive_scale is True


def test_the_flag_is_refused_with_the_anchor_model_and_the_message_names_both():
    with pytest.raises(ValueError) as info:
        EskfConfig(imu_noise=ImuNoiseModel(), vision_adaptive_scale=True, vision_model="anchor")
    assert "vision_adaptive_scale" in str(info.value) and "vision_model" in str(info.value)
    with pytest.raises(ValueError):
        EskfConfig(imu_noise=ImuNoiseModel(), vision_adaptive_scale=True)  # the default model is the anchor


@pytest.mark.parametrize("tau", [0.0, -2.0, float("nan"), float("inf")])
def test_a_bad_tau_is_refused(tau):
    with pytest.raises(ValueError, match="vision_scale_tau_s"):
        _cfg(vision_adaptive_scale=True, vision_scale_tau_s=tau)


@pytest.mark.parametrize(
    ("lo", "hi"),
    [(0.0, 8.0), (-1.0, 8.0), (1.5, 8.0), (0.5, 0.5), (0.5, 0.9), (float("nan"), 8.0), (0.5, float("inf"))],
)
def test_bad_bounds_are_refused(lo, hi):
    with pytest.raises(ValueError, match="vision_scale_m"):
        _cfg(vision_adaptive_scale=True, vision_scale_min=lo, vision_scale_max=hi)


def test_the_bounds_may_equal_one():
    _cfg(vision_adaptive_scale=True, vision_scale_min=1.0, vision_scale_max=1.0)


def test_the_four_fields_are_in_as_dict_and_change_the_hash():
    d = _cfg().as_dict()
    for key in ("vision_adaptive_scale", "vision_scale_tau_s", "vision_scale_min", "vision_scale_max"):
        assert key in d
    assert d != _cfg(vision_adaptive_scale=True).as_dict()
    assert _cfg(vision_scale_tau_s=2.0).as_dict() != _cfg(vision_scale_tau_s=10.0).as_dict()


def _scenario():
    doc = yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))
    return scenario_from_dict(doc["cases"]["outage_visual_clone"]["scenario"])


def test_the_benchmark_refuses_the_scale_together_with_a_preset_and_names_both():
    keys = {
        "vision_fuse": True,
        "vision_model": "clone",
        "vision_adaptive_scale": True,
        "vision_noise_preset": "measured-front-end",
    }
    with pytest.raises(ValueError) as info:
        bm._eskf_config(_scenario(), keys)
    assert "vision_adaptive_scale" in str(info.value) and "vision_noise_preset" in str(info.value)


def test_the_benchmark_passes_the_settings_to_the_filter_and_a_numeric_scale_is_allowed():
    keys = {
        "vision_fuse": True,
        "vision_model": "clone",
        "vision_adaptive_scale": True,
        "vision_scale_tau_s": 10.0,
        "vision_scale_min": 0.25,
        "vision_scale_max": 16.0,
        "vision_sigma_scale": 2.0,
    }
    cfg = bm._eskf_config(_scenario(), keys)
    assert cfg.vision_adaptive_scale and (cfg.vision_scale_tau_s, cfg.vision_scale_min, cfg.vision_scale_max) == (
        10.0,
        0.25,
        16.0,
    )
    off = bm._eskf_config(_scenario(), {"vision_fuse": True, "vision_model": "clone"})
    assert off.vision_adaptive_scale is False


def test_the_benchmark_refuses_the_scale_with_the_anchor_model():
    with pytest.raises(ValueError):
        bm._eskf_config(_scenario(), {"vision_fuse": True, "vision_adaptive_scale": True})


# -------------------------------------------------------------------------------------- inside the filter


def _doc():
    return yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))


def _run(seed=0, noise=1.0, sigma_scale=None, adaptive=True, case="outage_visual_clone", **est):
    """One 30 s run of a clone case. ``noise`` multiplies the generator's visual noise, not the filter's."""
    doc = _doc()
    c = copy.deepcopy(doc["cases"][case])
    c["scenario"].setdefault("vision", {})["noise_multiplier"] = noise
    if adaptive:
        c["estimator"]["vision_adaptive_scale"] = True
    if sigma_scale is not None:
        c["estimator"]["vision_sigma_scale"] = sigma_scale
    c["estimator"].update(est)
    return bm.run_case(case, c, doc["defaults"], seed=seed)["stats"]


def test_with_the_flag_off_there_are_no_scale_statistics():
    stats = _run(adaptive=False)
    assert not [k for k in stats if k.startswith("vision_scale")]


def test_with_the_flag_on_the_run_statistics_report_both_blocks():
    stats = _run()
    for block in ("rot", "trans"):
        for suffix in ("mean", "min", "max", "final"):
            assert f"vision_scale_{block}_{suffix}" in stats
    assert stats["vision_scale_updates_used"] > 0
    for block in ("rot", "trans"):
        assert (
            stats[f"vision_scale_{block}_min"]
            <= stats[f"vision_scale_{block}_mean"]
            <= stats[f"vision_scale_{block}_max"]
        )
        assert (
            stats[f"vision_scale_{block}_min"]
            <= stats[f"vision_scale_{block}_final"]
            <= stats[f"vision_scale_{block}_max"]
        )


# ``noise`` multiplies the generator's visual sigma, so the injected covariance is ``noise ** 2`` times the assumed one.
# MEASUREMENT on seeds 0 to 4 of ``outage_visual_clone`` under the rule of ADR-0032 (every update counts) and the
# per-axis translation noise of ADR-0033, final rotation / translation scale: factor 2.0: 3.47 to 3.75 / 3.48 to 3.66;
# 2.5: 4.72 to 4.96 / 4.72 to 4.86; 3.0: 5.65 to 5.86 / 5.60 to 5.79; 4.0: 6.72 to 6.90 / 6.65 to 6.91. Before
# ADR-0033 the generator drew a third of the declared translation variance, and the translation values were
# 1.28 to 1.52, 1.83 to 2.17, 2.37 to 2.74 and 3.29 to 3.64; the rotation values were the same as now. Under the rule of
# ADR-0031 (accepted updates only) the rotation scale was stuck near 1 for factor 4 on every seed, for factor 3 on two
# seeds and for factor 2.5 on one.
FACTORS = (2.0, 2.5, 3.0, 4.0)


@pytest.mark.parametrize("seed", [0, 1])
def test_noise_larger_than_assumed_pushes_the_scale_above_one_in_order_of_the_factor_and_within_the_bound(seed):
    finals = {k: _run(noise=k, seed=seed) for k in FACTORS}
    for block in ("rot", "trans"):
        values = [finals[k][f"vision_scale_{block}_final"] for k in FACTORS]
        assert all(v > 1.0 for v in values), (block, values)  # the smallest measured is 3.47
        assert values == sorted(values) and len(set(values)) == len(FACTORS), (block, values)  # monotone in the factor
        assert all(v <= 8.0 for v in values)  # s_max of the placeholder default
        for k in FACTORS:
            assert finals[k][f"vision_scale_{block}_max"] <= 8.0
    # The base covariance is used for d (not the scaled one): with the scaled one the fixed point of the scale would be
    # about the factor, not its square, and a factor of 2 would end near 2 instead of near 3.5.
    assert finals[2.0]["vision_scale_rot_final"] > 3.0


@pytest.mark.parametrize("seed", range(5))
def test_a_block_whose_updates_the_gate_used_to_reject_now_follows_the_noise(seed):
    """The opposite of the censoring that ADR-0031 had and ADR-0032 removes.

    With the visual sigma 2.5, 3 and 4 times the assumed one, the old rule left the rotation scale near 1 on the
    seeds where the gate rejected nearly every rotation update (at factor 4 it was at most 1.21 on all five seeds).
    Now the rejected updates enter the mean. The bounds below leave a margin of about a quarter under the smallest
    measured values (4.7 at 2.5, 5.65 at 3, 6.7 at 4 for rotation; 4.7, 5.6 and 6.65 for translation, under the
    per-axis translation noise of ADR-0033; the translation bounds were 1.4, 1.8 and 2.5 under the earlier draw). They do not
    assert convergence to the injected variance (6.25, 9 and 16 times): ``d`` uses ``S0 = H P H^T + R0``, which includes
    the state uncertainty, so ``E[d]`` is below the true ratio when ``P`` is not small, and the scale is capped at
    ``s_max`` besides.
    """
    runs = {k: _run(noise=k, seed=seed) for k in (2.5, 3.0, 4.0)}
    lower_rot = {2.5: 3.5, 3.0: 4.2, 4.0: 5.0}
    lower_trans = {2.5: 3.5, 3.0: 4.2, 4.0: 5.0}
    for k, stats in runs.items():
        assert stats["vision_scale_rot_final"] > lower_rot[k], (k, stats["vision_scale_rot_final"])
        assert stats["vision_scale_trans_final"] > lower_trans[k], (k, stats["vision_scale_trans_final"])
    for block in ("rot", "trans"):
        values = [runs[k][f"vision_scale_{block}_final"] for k in (2.5, 3.0, 4.0)]
        assert values == sorted(values) and len(set(values)) == 3, (block, values)
    # the adaptation came, in part, from updates the gate had rejected, and the statistics say so
    assert runs[4.0]["vision_scale_rot_rejected_used"] > 20
    assert runs[4.0]["vision_scale_rot_rejected_used"] < runs[4.0]["vision_scale_updates_used"]
    assert runs[4.0]["vision_scale_skipped_nonfinite"] == 0


def test_noise_smaller_than_assumed_pushes_the_scale_below_one_and_not_below_the_minimum():
    stats = _run(sigma_scale=2.0)  # the filter assumes twice the sigma the generator injects
    for block in ("rot", "trans"):
        final = stats[f"vision_scale_{block}_final"]
        assert 0.5 <= final < 1.0, (block, final)  # 0.5 is s_min of the placeholder default
        assert stats[f"vision_scale_{block}_min"] >= 0.5


@pytest.mark.parametrize("seed", range(5))
def test_with_matched_noise_the_rotation_scale_stays_near_one(seed):
    """MEASUREMENT on seeds 0 to 4. Rule of ADR-0031: the rotation scale ended between 0.92 and 1.01, and over a whole
    run it stayed between 0.86 and 1.15. Rule of ADR-0032: it ends between 0.95 and 1.04 and over a whole run stays
    between 0.86 and 1.15. The measured band did not leave the tolerance, so the tolerance is unchanged: a margin of
    about a quarter on either side of one."""
    stats = _run(seed=seed)
    assert 0.8 <= stats["vision_scale_rot_final"] <= 1.25
    assert stats["vision_scale_rot_min"] >= 0.75 and stats["vision_scale_rot_max"] <= 1.4


@pytest.mark.parametrize("seed", range(5))
def test_with_matched_noise_the_translation_scale_stays_near_one(seed):
    """MEASUREMENT on seeds 0 to 4, with the per-axis translation noise of ADR-0033: the translation scale ends between
    0.94 and 1.02, and over a whole run stays between 0.85 and 1.10, as the rotation scale does.

    What this test pinned before: the translation scale ended at the lower bound (0.5) on every seed. That was not a
    property of the filter. The generator drew the translation noise with a third of the variance that the stream
    declares and the filter assumes (a random unit direction times one scalar), so the innovations were three times
    smaller than the declared noise and the scale went to its lower bound. Issue #44 reported this as conservatism of
    the plain clone. ADR-0033 draws each axis with the declared standard deviation, and the scale now stays near one.

    The tolerance is the one of the rotation test: a margin of about a quarter either side of one. The measured spread
    is about plus or minus 0.1, so the margin is more than twice the spread."""
    stats = _run(seed=seed)
    assert 0.8 <= stats["vision_scale_trans_final"] <= 1.25
    assert stats["vision_scale_trans_min"] >= 0.75 and stats["vision_scale_trans_max"] <= 1.4


def test_a_gate_rejected_update_does_enter_the_mean_and_is_counted():
    stats = _run(case="outage_visual_clone_outliers")
    updates = stats["vision_updates_used"] + stats["vision_updates_rejected"]
    assert stats["vision_updates_rejected"] > 0, (
        "the case must produce rejected visual updates for this test to mean anything"
    )
    assert stats["vision_scale_updates_used"] == updates  # every visual update reached the rotation scale
    assert stats["vision_scale_rot_rejected_used"] > 0
    assert stats["vision_scale_trans_rejected_used"] > 0
    assert stats["vision_scale_skipped_nonfinite"] == 0


def test_with_the_flag_off_the_new_statistics_are_absent_too():
    stats = _run(adaptive=False)
    for key in ("vision_scale_rot_rejected_used", "vision_scale_trans_rejected_used", "vision_scale_skipped_nonfinite"):
        assert key not in stats


def test_the_run_is_deterministic():
    def scale_stats(stats):
        return {k: v for k, v in stats.items() if k.startswith("vision_")}

    assert scale_stats(_run(noise=3.0, seed=2)) == scale_stats(_run(noise=3.0, seed=2))
