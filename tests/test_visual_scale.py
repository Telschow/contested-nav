"""The adaptive visual noise scale of ADR-0031: the estimator, the config rules and the behaviour in the filter.

The scale is a catch-all for model error in the visual channel. It is not an estimate of the sensor noise, and no test
here asserts that it converges to the injected factor: the statistic ``d`` uses ``S0 = H P H^T + R0``, which includes
the state uncertainty, so its expectation is below the true ratio of variances when ``P`` is not small.

Only development seeds are used (0 to 4).
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit.degrade import scenario_from_dict
from navkit.estimators.eskf import EskfConfig
from navkit.estimators.visual_scale import VisualScale
from navkit.io.imu import ImuNoiseModel

# ------------------------------------------------------------------------------------------- the estimator


def _scale(tau: float = 2.0, lo: float = 0.1, hi: float = 10.0) -> VisualScale:
    return VisualScale(tau_s=tau, s_min=lo, s_max=hi)


def test_it_starts_at_one_with_nothing_seen():
    s = _scale()
    assert s.value == 1.0 and s.n_used == 0
    assert s.mean == 1.0 and s.min_seen == 1.0 and s.max_seen == 1.0


def test_a_constant_d_at_a_fixed_dt_follows_the_formula_exactly():
    k, dt, tau = 3.0, 0.1, 2.0
    s = _scale(tau)
    s.update(k, 0.0, True)  # the first accepted update only records the time
    assert s.value == 1.0
    w = 1.0 - math.exp(-dt / tau)
    for n in range(1, 40):
        s.update(k, n * dt, True)
        assert s.value == pytest.approx(k + (1.0 - k) * (1.0 - w) ** n, rel=1e-12, abs=1e-12)


def test_the_first_accepted_update_does_not_move_the_scale_but_is_counted():
    s = _scale()
    s.update(50.0, 7.0, True)
    assert s.value == 1.0 and s.n_used == 1


def test_the_weight_depends_on_the_time_since_the_previous_accepted_update():
    a, b = _scale(tau=5.0), _scale(tau=5.0)
    a.update(1.0, 0.0, True)
    a.update(4.0, 1.0, True)
    b.update(1.0, 0.0, True)
    b.update(4.0, 10.0, True)
    assert a.value == pytest.approx(1.0 + (1.0 - math.exp(-1.0 / 5.0)) * 3.0)
    assert b.value == pytest.approx(1.0 + (1.0 - math.exp(-10.0 / 5.0)) * 3.0)
    assert b.value > a.value


def test_a_rejected_update_changes_nothing_not_even_the_time():
    s, ref = _scale(), _scale()
    for x in (s, ref):
        x.update(2.0, 0.0, True)
    s.update(1000.0, 1.0, False)
    assert (s.value, s.n_used, s.mean, s.min_seen, s.max_seen) == (
        ref.value,
        ref.n_used,
        ref.mean,
        ref.min_seen,
        ref.max_seen,
    )
    s.update(3.0, 2.0, True)
    ref.update(3.0, 2.0, True)  # dt is from the previous ACCEPTED update at 0.0, in both
    assert s.value == ref.value


def test_with_no_update_the_scale_is_held():
    s = _scale()
    s.update(1.0, 0.0, True)
    s.update(4.0, 1.0, True)
    before = (s.value, s.n_used, s.mean, s.min_seen, s.max_seen)
    for _ in range(5):  # reading it any number of times changes nothing: there is no clock inside the estimator
        assert (s.value, s.n_used, s.mean, s.min_seen, s.max_seen) == before


def test_the_scale_is_clipped_to_the_interval():
    s = _scale(tau=1.0, lo=0.5, hi=4.0)
    s.update(100.0, 0.0, True)
    for i in range(1, 60):
        s.update(100.0, float(i), True)
    assert s.value == 4.0 and s.max_seen == 4.0
    low = _scale(tau=1.0, lo=0.5, hi=4.0)
    low.update(0.0, 0.0, True)
    for i in range(1, 60):
        low.update(0.0, float(i), True)
    assert low.value == 0.5 and low.min_seen == 0.5


def test_there_is_no_wind_up_after_a_long_stay_at_a_bound():
    s = _scale(tau=1.0, lo=0.5, hi=4.0)
    s.update(1000.0, 0.0, True)
    for i in range(1, 300):
        s.update(1000.0, float(i), True)
    assert s.value == 4.0
    s.update(1.0, 300.0, True)  # one tau later: it must move at once, not stay pinned by hidden state
    assert s.value == pytest.approx(4.0 + (1.0 - math.exp(-1.0)) * (1.0 - 4.0))
    assert s.value < 4.0


def test_the_running_statistics_are_over_the_accepted_updates():
    s = _scale(tau=1.0, lo=0.1, hi=100.0)
    seen = []
    for i, d in enumerate((1.0, 4.0, 4.0, 0.5)):
        s.update(d, float(i), True)
        seen.append(s.value)
    s.update(99.0, 10.0, False)
    assert s.n_used == 4
    assert s.mean == pytest.approx(float(np.mean(seen)))
    assert s.min_seen == min(seen) and s.max_seen == max(seen)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_d_raises(bad):
    for accepted in (True, False):
        with pytest.raises(ValueError, match="finite"):
            _scale().update(bad, 0.0, accepted)


def test_time_must_not_go_backwards():
    s = _scale()
    s.update(1.0, 5.0, True)
    with pytest.raises(ValueError, match="time"):
        s.update(1.0, 4.0, True)


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


# The factors below are inside the range in which the scale can follow the noise. ``noise`` multiplies the generator's
# visual sigma, so the injected covariance is ``noise ** 2`` times the assumed one. MEASUREMENT on seeds 0 to 4 of
# ``outage_visual_clone``: at a factor of 2.0 the rotation scale ends between 3.7 and 4.0, at 2.25 between 4.6 and 5.1;
# at 2.5 four seeds end between 5.0 and 6.3 and one is stuck near 1. See the limit test below.
IN_RANGE = (2.0, 2.25, 2.5)


@pytest.mark.parametrize("seed", [0, 1])
def test_noise_larger_than_assumed_pushes_the_scale_above_one_in_order_of_the_factor_and_within_the_bound(seed):
    finals = {k: _run(noise=k, seed=seed) for k in IN_RANGE}
    for block in ("rot", "trans"):
        values = [finals[k][f"vision_scale_{block}_final"] for k in IN_RANGE]
        # The translation block starts from a conservative baseline (its scale sits near the lower bound at matched
        # noise, see below), so it needs the larger factors to pass one. The rotation block passes one at every factor.
        above_one = values if block == "rot" else values[1:]
        assert all(v > 1.0 for v in above_one), (block, values)
        assert all(v > 0.5 for v in values), (block, values)
        assert values == sorted(values) and len(set(values)) == len(IN_RANGE), (block, values)  # monotone in the factor
        assert all(v <= 8.0 for v in values)  # s_max of the placeholder default
        for k in IN_RANGE:
            assert finals[k][f"vision_scale_{block}_max"] <= 8.0
    # The base covariance is used for d (not the scaled one): with the scaled one the fixed point of the scale would be
    # about the factor, not its square, and a factor of 2 would end near 2 instead of near 4.
    assert finals[2.0]["vision_scale_rot_final"] > 3.0


def test_a_block_whose_updates_the_gate_rejects_cannot_raise_its_own_scale():
    """The limit of the rule 'only accepted innovations enter the mean' (ADR-0031), as measured.

    With the visual sigma three or four times the assumed one, the chi-square gate rejects nearly every rotation
    update (FDIR declares the channel faulted), so the rotation scale sees a handful of updates and stays near 1. The
    translation block, whose updates are not rejected, does adapt. The scale follows the noise inside the gate's capture
    range and not outside it.
    """
    for k in (3.0, 4.0):
        stats = _run(noise=k, seed=0)
        assert stats["vision_scale_updates_used"] < 10, k  # the rotation block saw almost nothing
        assert stats["vision_scale_rot_final"] < 1.5, k
        assert stats["vision_scale_trans_final"] > 2.0, k


def test_noise_smaller_than_assumed_pushes_the_scale_below_one_and_not_below_the_minimum():
    stats = _run(sigma_scale=2.0)  # the filter assumes twice the sigma the generator injects
    for block in ("rot", "trans"):
        final = stats[f"vision_scale_{block}_final"]
        assert 0.5 <= final < 1.0, (block, final)  # 0.5 is s_min of the placeholder default
        assert stats[f"vision_scale_{block}_min"] >= 0.5


@pytest.mark.parametrize("seed", range(5))
def test_with_matched_noise_the_rotation_scale_stays_near_one(seed):
    """MEASUREMENT on seeds 0 to 4: the rotation scale ends between 0.92 and 1.01, and over a whole run it stays
    between 0.86 and 1.15. The band below keeps a margin of about a quarter on either side of one."""
    stats = _run(seed=seed)
    assert 0.8 <= stats["vision_scale_rot_final"] <= 1.25
    assert stats["vision_scale_rot_min"] >= 0.75 and stats["vision_scale_rot_max"] <= 1.4


@pytest.mark.parametrize("seed", range(5))
def test_with_matched_noise_the_translation_scale_goes_to_its_lower_bound(seed):
    """MEASUREMENT on seeds 0 to 4: the translation scale ends at the lower bound (0.5) on every seed, so the
    translation updates of the clone are smaller than the declared noise says even when the generator injects exactly
    that noise. This is the conservatism that issue #44 reports for the plain clone, seen in the innovations. A test
    that fails here means the behaviour changed, not that a number is wrong."""
    stats = _run(seed=seed)
    assert 0.5 <= stats["vision_scale_trans_final"] <= 0.6


def test_a_rejected_update_does_not_enter_the_mean():
    stats = _run(case="outage_visual_clone_outliers")
    updates = stats["vision_updates_used"] + stats["vision_updates_rejected"]
    assert stats["vision_updates_rejected"] > 0, (
        "the case must produce rejected visual updates for this test to mean anything"
    )
    assert stats["vision_scale_updates_used"] < updates


def test_the_run_is_deterministic():
    def scale_stats(stats):
        return {k: v for k, v in stats.items() if k.startswith("vision_")}

    assert scale_stats(_run(noise=3.0, seed=2)) == scale_stats(_run(noise=3.0, seed=2))
