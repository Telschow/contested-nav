"""Tests for failure detection and deterministic degradation injection.

Both modules turn a continuous signal into a discrete, actionable statement,
which is exactly where a quiet bug hides: a detector that never fires looks
identical to a system that never failed. So the clean-signal cases matter as
much as the failure cases.
"""

import numpy as np
import pytest

from navkit.degrade.config import (
    CameraDropConfig,
    Outage,
    Scenario,
    scenario_from_dict,
)
from navkit.degrade.inject import (
    apply_camera_drop,
    apply_gnss_outage,
    apply_imu_outage,
    config_hash,
    in_any,
    inject,
    mark_outages,
)
from navkit.eval.thresholds import ThresholdSet, detect_failures
from navkit.sensors.models import GnssConfig, VisionConfig, gnss_fixes, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory
from navkit.types import GnssFix, ImuSample, VisionUpdate


def thr(sustained: float = 0.5, peak: float | None = None, **kw) -> ThresholdSet:
    """A coherent ThresholdSet.

    ``position_peak_m >= sustained_error_m`` is an enforced invariant, so a
    test that lowers the sustained threshold must lower the peak too, or the
    detector will refuse the whole set.
    """
    return ThresholdSet(
        sustained_error_m=sustained,
        position_peak_m=sustained if peak is None else max(peak, sustained),
        **kw,
    )


# --- _runs / ThresholdSet ----------------------------------------------------


def _only_event(report, kind):
    """Return the single event of ``kind``, asserting exactly one exists.

    ``[x for x in events if x.kind == k][0]`` also passes when a second event of
    the same kind was emitted, so a duplicated failure event -- which would be
    reported to a reader as two separate problems -- went unnoticed.
    """
    matches = [x for x in report.events if x.kind == kind]
    assert len(matches) == 1, f"expected exactly 1 {kind!r} event, got {len(matches)}"
    return matches[0]


def test_thresholds_defaults_are_self_consistent():
    assert ThresholdSet().violations() == []


@pytest.mark.parametrize(
    "field,value,fragment",
    [
        ("sustained_error_m", 0.0, "sustained_error_m must be > 0"),
        ("min_duration_s", 0.0, "min_duration_s must be > 0"),
        ("divergence_window_s", 0.0, "divergence_window_s must be > 0"),
        ("drift_pct_path_length", 0.0, "drift_pct_path_length must be > 0"),
    ],
)
def test_threshold_violations_are_detected(field, value, fragment):
    t = ThresholdSet(**{field: value})
    assert any(fragment in v for v in t.violations())


def test_peak_below_sustained_is_a_violation():
    v = ThresholdSet(position_peak_m=0.1, sustained_error_m=0.5).violations()
    assert any("position_peak_m must be >= sustained_error_m" in x for x in v)


def test_invalid_thresholds_are_refused_rather_than_silently_clamped():
    """A detector given incoherent thresholds must fail, not guess."""
    with pytest.raises(ValueError, match="invalid thresholds"):
        detect_failures(np.array([0.0, 1.0]), np.array([0.1, 0.2]), ThresholdSet(min_duration_s=-1.0))


# --- clean signals -----------------------------------------------------------


def test_a_flat_clean_curve_produces_no_events_and_passes():
    t = np.linspace(0, 20, 400)
    rep = detect_failures(t, np.full_like(t, 0.05), ThresholdSet())
    assert rep.events == []
    assert rep.passed
    assert rep.reasons == []


def test_empty_error_curve_fails_rather_than_passing_vacuously():
    """No data is not a pass. Reporting an empty run as healthy is the failure
    mode this guards."""
    rep = detect_failures(np.array([]), np.array([]), ThresholdSet())
    assert not rep.passed
    assert "empty error curve" in rep.reasons


def test_mismatched_lengths_fail_rather_than_truncating():
    rep = detect_failures(np.array([0.0, 1.0, 2.0]), np.array([0.1, 0.2]), ThresholdSet())
    assert not rep.passed
    assert "empty error curve" in rep.reasons


def test_single_sample_run_does_not_crash():
    rep = detect_failures(np.array([0.0]), np.array([0.1]), ThresholdSet())
    assert isinstance(rep.passed, bool)


# --- threshold_exceeded ------------------------------------------------------


def test_sustained_exceedance_is_detected():
    t = np.linspace(0, 20, 400)
    e = np.where(t > 5, 2.0, 0.05)
    ev = [x for x in detect_failures(t, e, thr(0.5)).events if x.kind == "threshold_exceeded"]
    assert len(ev) == 1
    assert ev[0].start_s == pytest.approx(5.0, abs=0.1)
    assert ev[0].peak_m == pytest.approx(2.0)


def test_a_brief_spike_is_not_a_sustained_exceedance():
    """A 0.2 s excursion is noise, not a failure. min_duration_s is the guard."""
    t = np.linspace(0, 20, 400)
    e = np.full_like(t, 0.05)
    e[(t > 5) & (t < 5.2)] = 2.0
    rep = detect_failures(t, e, thr(0.5, min_duration_s=2.0))
    assert not [x for x in rep.events if x.kind == "threshold_exceeded"]


def test_each_sustained_exceedance_run_produces_its_own_event():
    t = np.linspace(0, 30, 600)
    e = np.full_like(t, 0.05)
    e[(t > 5) & (t < 8)] = 2.0
    e[(t > 20) & (t < 24)] = 3.0
    ev = detect_failures(t, e, thr(0.5)).events
    assert len([x for x in ev if x.kind == "threshold_exceeded"]) == 2


def test_exceedance_run_that_touches_the_end_of_the_array_is_found():
    """A run that never returns below the threshold has no closing edge; the
    detector must still close it at the last sample."""
    t = np.linspace(0, 20, 400)
    e = np.where(t > 15, 2.0, 0.05)
    ev = [x for x in detect_failures(t, e, thr(0.5)).events if x.kind == "threshold_exceeded"]
    assert len(ev) == 1


def test_event_records_the_threshold_that_fired_it():
    t = np.linspace(0, 20, 400)
    e = np.where(t > 5, 2.0, 0.05)
    ev = _only_event(detect_failures(t, e, thr(0.5)), "threshold_exceeded")
    assert ev.threshold_m == 0.5
    assert "0.5 m" in ev.detail


# --- divergence --------------------------------------------------------------


def test_monotonic_growth_is_flagged_as_divergence():
    t = np.linspace(0, 30, 600)
    e = np.linspace(0.0, 5.0, 600)
    rep = detect_failures(t, e, thr(99.0, 99.0, divergence_window_s=5.0, divergence_growth_m=0.5))
    assert [x.kind for x in rep.events] == ["divergence"]


def test_growth_with_a_recovery_is_not_divergence():
    """A signal that keeps falling back is not a runaway.

    A tent function would be the wrong test here: its rising edge really is
    monotonic, so flagging it is correct. This triangle wave puts a fall larger
    than the 10%-of-growth tolerance inside every window, which is exactly what
    the monotonicity guard exists to reject.
    """
    t = np.linspace(0, 30, 600)
    e = np.abs(((t * 4.0) % 2.0) - 1.0) * 4.0
    rep = detect_failures(t, e, thr(sustained=99.0, peak=99.0, divergence_window_s=5.0, divergence_growth_m=0.5))
    assert not [x for x in rep.events if x.kind == "divergence"]


def test_a_monotonic_rising_edge_inside_a_recovery_is_still_divergence():
    """The counterpart: the detector looks at windows, not the whole curve."""
    t = np.linspace(0, 30, 600)
    e = np.concatenate([np.linspace(0, 5, 300), np.linspace(5, 0, 300)])
    rep = detect_failures(t, e, thr(sustained=99.0, peak=99.0, divergence_window_s=5.0, divergence_growth_m=0.5))
    assert [x.kind for x in rep.events] == ["divergence"]


def test_growth_below_the_configured_amount_is_not_divergence():
    t = np.linspace(0, 30, 600)
    e = np.linspace(0.0, 0.2, 600)
    rep = detect_failures(t, e, thr(99.0, 99.0, divergence_growth_m=1.0, divergence_window_s=5.0))
    assert not [x for x in rep.events if x.kind == "divergence"]


def test_at_most_one_divergence_event_is_emitted():
    """One flag is enough to mark the run; a sliding window would otherwise
    emit dozens of near-identical events."""
    t = np.linspace(0, 60, 1200)
    e = np.linspace(0.0, 20.0, 1200)
    rep = detect_failures(t, e, thr(1e9, 1e9, divergence_window_s=5.0))
    assert len([x for x in rep.events if x.kind == "divergence"]) == 1


# --- filter-health and drift events ------------------------------------------


def test_rejected_updates_become_a_filter_health_event():
    t = np.linspace(0, 20, 400)
    rep = detect_failures(t, np.full_like(t, 0.05), ThresholdSet(), rejected_runs=12)
    ev = _only_event(rep, "rejected_updates")
    assert "12" in ev.detail
    assert np.isnan(ev.peak_m)
    assert not rep.passed, "a filter rejecting its own measurements is a failure"


def test_no_rejected_updates_produces_no_event():
    t = np.linspace(0, 20, 400)
    rep = detect_failures(t, np.full_like(t, 0.05), ThresholdSet(), rejected_runs=0)
    assert not [x for x in rep.events if x.kind == "rejected_updates"]


def test_drift_above_threshold_becomes_an_event():
    t = np.linspace(0, 20, 400)
    rep = detect_failures(t, np.full_like(t, 0.05), ThresholdSet(drift_pct_path_length=5.0), drift_pct_path=9.0)
    ev = _only_event(rep, "drift_exceeded")
    assert "9.00%" in ev.detail


def test_drift_within_threshold_produces_no_event():
    t = np.linspace(0, 20, 400)
    rep = detect_failures(t, np.full_like(t, 0.05), ThresholdSet(drift_pct_path_length=5.0), drift_pct_path=1.0)
    assert not [x for x in rep.events if x.kind == "drift_exceeded"]


# --- verdicts ----------------------------------------------------------------


def test_rmse_and_peak_verdicts_are_recorded_separately():
    t = np.linspace(0, 20, 400)
    e = np.full_like(t, 0.9)
    rep = detect_failures(t, e, thr(sustained=0.1, peak=0.5, position_rmse_m=0.5))
    joined = " ".join(rep.reasons)
    assert "ATE RMSE" in joined
    assert "peak error" in joined
    assert not rep.passed


def test_a_run_exactly_at_the_threshold_passes():
    t = np.linspace(0, 20, 400)
    e = np.full_like(t, 0.5)
    rep = detect_failures(t, e, thr(0.5, 0.5))
    assert rep.passed, "comparison must be strict, so a run at the bound is not a failure"


def test_report_as_dict_is_json_shaped():
    t = np.linspace(0, 20, 400)
    d = detect_failures(t, np.where(t > 5, 2.0, 0.05), thr(0.5)).as_dict()
    assert set(d) == {"passed", "count", "events", "thresholds", "reasons"}
    assert d["count"] == len(d["events"])
    assert set(d["events"][0]) == {"kind", "start_s", "end_s", "peak_m", "duration_s", "threshold_m", "detail"}


# --- outage primitives -------------------------------------------------------


def test_in_any_is_false_for_no_outages():
    assert not in_any(5.0, [])


def test_in_any_uses_half_open_windows():
    o = [Outage(start_s=5.0, duration_s=15.0)]
    assert in_any(5.0, o)
    assert in_any(19.9, o)
    assert not in_any(20.0, o), "endpoint excluded, matching Outage.covers"
    assert not in_any(4.9, o)


def test_in_any_is_true_if_any_window_covers():
    o = [Outage(start_s=0.0, duration_s=1.0), Outage(start_s=10.0, duration_s=1.0)]
    assert in_any(10.5, o)
    assert not in_any(5.0, o)


def test_mark_outages_returns_a_boolean_mask():
    t = np.array([0.0, 4.9, 5.0, 10.0, 20.0])
    mask = mark_outages(t, [Outage(start_s=5.0, duration_s=15.0)])
    assert mask.dtype == bool
    assert mask.tolist() == [False, False, True, True, False]


def test_mark_outages_with_no_windows_is_all_false():
    assert not mark_outages(np.array([0.0, 1.0]), []).any()


def test_mark_outages_with_empty_input_is_empty():
    assert mark_outages(np.array([]), [Outage(0.0, 1.0)]).shape == (0,)


# --- gnss outage -------------------------------------------------------------


def _fixes(n: int = 101, hz: float = 5.0) -> GnssFix:
    # arange rather than linspace so a sample lands exactly on a round second,
    # which is what the endpoint test needs to probe.
    t = np.arange(n) / hz
    return GnssFix(
        t=t,
        positions=np.zeros((n, 3)),
        cov=np.full((n, 3), 0.64),
        available=np.ones(n, dtype=bool),
    )


def test_gnss_outage_marks_the_window_unavailable():
    g = apply_gnss_outage(_fixes(), [Outage(start_s=5.0, duration_s=15.0)], True)
    assert len(g.valid()) == 26, "5 Hz over 20 s is 101 fixes, minus the 75 in the window"
    assert bool(g.available[0]) and not bool(g.available[25])


def test_gnss_outage_leaves_the_endpoint_fix_available():
    """The fix at exactly t=20 is outside the half-open window."""
    g = apply_gnss_outage(_fixes(), [Outage(start_s=5.0, duration_s=15.0)], True)
    assert bool(g.available[np.isclose(g.t, 20.0)][0])


def test_disabled_gnss_makes_every_fix_unavailable():
    g = apply_gnss_outage(_fixes(), [Outage(start_s=5.0, duration_s=15.0)], False)
    assert not g.available.any()


def test_gnss_outage_always_populates_availability():
    """Downstream code gets one shape to handle, outage or not."""
    g = apply_gnss_outage(_fixes(), [], True)
    assert g.available is not None and g.available.all()


def test_gnss_outage_with_no_windows_is_a_no_op():
    g = apply_gnss_outage(_fixes(), [], True)
    assert g.available.all()


def test_gnss_outage_does_not_mutate_its_input():
    src = _fixes()
    apply_gnss_outage(src, [Outage(5.0, 15.0)], True)
    assert src.available.all()


def test_multiple_gnss_outages_compose():
    g = apply_gnss_outage(_fixes(), [Outage(2.0, 2.0), Outage(10.0, 2.0)], True)
    assert not g.available[10:20].any()
    assert bool(g.available[0])


def test_gnss_outage_intervals_are_reported_for_the_manifest():
    g = apply_gnss_outage(_fixes(), [Outage(5.0, 15.0)], True)
    iv = g.outage_intervals()
    assert len(iv) == 1
    # Intervals are reported in wall-clock time, padded by half a sample each
    # side, so the edges land near the nominal window rather than on it.
    start, end = iv[0]
    assert start == pytest.approx(5.0, abs=0.2)
    assert end == pytest.approx(20.0, abs=0.2)


# --- imu outage --------------------------------------------------------------


def _imu(n: int = 2000, hz: float = 200.0) -> ImuSample:
    t = np.linspace(0.0, n / hz, n)
    return ImuSample(
        t=t,
        accel=np.tile([0.0, 0.0, -9.81], (n, 1)),
        gyro=np.zeros((n, 3)),
    )


def test_imu_outage_removes_samples_inside_the_window():
    imu = apply_imu_outage(_imu(), [Outage(start_s=2.0, duration_s=1.0)])
    assert len(imu) < 2000
    t = imu.t
    assert not ((t >= 2.0) & (t < 3.0)).any()
    assert imu.accel.shape[0] == imu.t.shape[0], "arrays must stay aligned after removal"


def test_imu_with_no_outage_is_untouched():
    imu = _imu()
    assert apply_imu_outage(imu, []) is imu


def test_imu_outage_that_removes_almost_everything_is_refused():
    """The filter cannot propagate from a single sample; refuse rather than
    return something that will fail later, far from the cause."""
    with pytest.raises(ValueError, match="fewer than 2 samples"):
        apply_imu_outage(_imu(10, hz=1.0), [Outage(0.0, 100.0)])


# --- camera drop -------------------------------------------------------------


def _vision(n: int = 200) -> VisionUpdate:
    t = np.linspace(0.0, n / 20.0, n)
    return VisionUpdate(
        t=t,
        R_rel=np.tile(np.eye(3), (n, 1, 1)),
        t_rel=np.zeros((n, 3)),
        dropped=np.zeros(n, dtype=bool),
    )


def test_camera_drop_is_deterministic_for_a_fixed_seed():
    a = apply_camera_drop(_vision(), 0.3, 1.0, 11)
    b = apply_camera_drop(_vision(), 0.3, 1.0, 11)
    assert np.array_equal(a.dropped, b.dropped)


def test_camera_drop_differs_between_seeds():
    a = apply_camera_drop(_vision(400), 0.3, 1.0, 1)
    b = apply_camera_drop(_vision(400), 0.3, 1.0, 2)
    assert not np.array_equal(a.dropped, b.dropped)


def test_camera_drop_actually_drops_frames():
    v = apply_camera_drop(_vision(200), 0.3, 1.0, 3)
    assert v.dropped.sum() > 0


def test_camera_drop_matches_the_requested_fraction():
    v = apply_camera_drop(_vision(200), 0.3, 1.0, 3)
    assert v.dropped.sum() == pytest.approx(60, abs=2)


def test_zero_drop_fraction_keeps_every_frame():
    assert not apply_camera_drop(_vision(100), 0.0, 1.0, 1).dropped.any()


def test_full_drop_fraction_drops_every_frame():
    assert apply_camera_drop(_vision(100), 1.0, 1.0, 1).dropped.all()


def test_camera_drop_does_not_mutate_its_input():
    v = _vision(100)
    apply_camera_drop(v, 0.5, 1.0, 2)
    assert not v.dropped.any()


def test_camera_drop_always_drops_the_first_frame():
    """The first frame has no predecessor, so it is never usable."""
    v = apply_camera_drop(_vision(200), 0.3, 1.0, 5)
    assert v.dropped[0]


# --- scenario hashing --------------------------------------------------------


def test_config_hash_depends_on_scenario_content():
    assert config_hash(Scenario(name="a")) == config_hash(Scenario(name="a"))
    assert config_hash(Scenario(name="a")) != config_hash(Scenario(name="b"))


def test_config_hash_changes_when_an_outage_changes():
    a = Scenario(name="x")
    b = Scenario(name="x", gnss_outages=[Outage(5.0, 15.0)])
    assert config_hash(a) != config_hash(b)


def test_config_hash_is_short_and_hex():
    h = config_hash(Scenario(name="x"))
    assert len(h) == 16
    int(h, 16)


def test_config_hash_folds_in_the_estimator():
    """The estimator must change the provenance hash even when the scenario matches.

    The estimator is configured separately from the scenario, and several of its
    settings change the filter without touching the scenario at all. Hashing the
    scenario alone let three structurally different filters share one hash, so a
    record could not be told apart from another by its provenance.
    """
    sc = Scenario(name="x")
    base = config_hash(sc, estimator={"class": "ErrorStateKalmanFilter", "vision_enabled": True})
    off = config_hash(sc, estimator={"class": "ErrorStateKalmanFilter", "vision_enabled": False})
    assert base != off
    # Same inputs must stay reproducible, and the scenario-only form must still
    # be usable for the injection manifest, which has no estimator to report.
    assert base == config_hash(sc, estimator={"class": "ErrorStateKalmanFilter", "vision_enabled": True})
    assert config_hash(sc) != base


def test_config_hash_estimator_key_is_namespaced():
    """An estimator block must not collide with a scenario that hashes the same."""
    sc = Scenario(name="x")
    assert config_hash(sc, estimator={"a": 1}) != config_hash(sc, estimator={"a": 2})


# --- end-to-end inject -------------------------------------------------------


def _streams():
    cfg = SyntheticConfig(duration_s=20.0, rate_hz=50.0)
    gt = synthetic_trajectory(cfg)
    imu = synthetic_imu(cfg, rate_hz=200.0)
    gnss = gnss_fixes(gt, GnssConfig(rate_hz=5.0, sigma_m=0.8, seed=1))
    vis = visual_updates(gt, VisionConfig(rate_hz=10.0, seed=2))
    return gt, imu, gnss, vis


def test_inject_is_reproducible_for_a_fixed_scenario():
    gt, imu, gnss, vis = _streams()
    scen = Scenario(name="gnss_denied", gnss_outages=[Outage(5.0, 15.0)])
    a = inject(scen, imu, gnss, vis, gt)
    b = inject(scen, imu, gnss, vis, gt)
    assert np.array_equal(a.imu.accel, b.imu.accel)
    assert np.array_equal(a.gnss.available, b.gnss.available)
    assert np.array_equal(a.vision.dropped, b.vision.dropped)
    assert a.manifest == b.manifest


def test_inject_applies_the_declared_gnss_outage():
    gt, imu, gnss, vis = _streams()
    scen = Scenario(name="gnss_denied", gnss_outages=[Outage(5.0, 15.0)])
    out = inject(scen, imu, gnss, vis, gt)
    assert not out.gnss.available.all()
    assert out.manifest["gnss"]["unavailable_fixes"] > 0


def test_inject_manifest_reports_measured_counts_not_claimed_ones():
    gt, imu, gnss, vis = _streams()
    out = inject(Scenario(name="gnss_denied", gnss_outages=[Outage(5.0, 15.0)]), imu, gnss, vis, gt)
    m = out.manifest
    assert m["gnss"]["emitted_fixes"] == len(gnss)
    assert m["gnss"]["usable_fixes"] == int(out.gnss.available.sum())
    assert m["imu"]["samples"] == len(out.imu)
    assert len(m["config_hash"]) == 16
    assert m["scenario"] == "gnss_denied"


def test_inject_with_a_clean_scenario_denies_nothing():
    gt, imu, gnss, vis = _streams()
    out = inject(Scenario(name="normal"), imu, gnss, vis, gt)
    assert out.gnss.available.all()
    assert out.manifest["gnss"]["unavailable_fixes"] == 0


def test_inject_applies_imu_noise_and_records_the_bias():
    gt, imu, gnss, vis = _streams()
    out = inject(Scenario(name="imu_noise", imu_noise_scale=3.0), imu, gnss, vis, gt)
    assert not np.array_equal(out.imu.accel, imu.accel)
    assert out.manifest["imu"]["noise_scale"] == 3.0


def test_inject_with_zero_noise_scale_is_a_passthrough():
    gt, imu, gnss, vis = _streams()
    scen = Scenario(name="normal", imu_noise_scale=0.0)
    scen.imu_noise = scen.imu_noise.__class__(**dict.fromkeys(scen.imu_noise.as_dict(), 0.0))
    out = inject(scen, imu, gnss, vis, gt)
    assert np.array_equal(out.imu.accel, imu.accel)


def test_inject_applies_camera_drops():

    gt, imu, gnss, vis = _streams()
    scen = Scenario(name="camera_drop", camera_drop=CameraDropConfig(drop_fraction=0.4, burst_period_s=1.0, seed=4))
    out = inject(scen, imu, gnss, vis, gt)
    assert out.manifest["vision"]["dropped_frames"] > 0
    assert out.manifest["vision"]["usable_frames"] < out.manifest["vision"]["emitted_frames"]


def test_inject_applies_a_vision_time_offset():
    gt, imu, gnss, vis = _streams()
    out = inject(Scenario(name="timestamp_offset", vision_time_offset_s=0.02), imu, gnss, vis, gt)
    assert np.allclose(out.vision.t - vis.t, 0.02)


def test_inject_with_disabled_gnss_marks_everything_unavailable():
    gt, imu, gnss, vis = _streams()
    scen = Scenario(name="normal")
    scen.gnss.enabled = False
    out = inject(scen, imu, gnss, vis, gt)
    assert not out.gnss.available.any()


def test_a_negative_outage_is_rejected_by_the_scenario_parser():
    """Validation lives in scenario_from_dict, which is what load_config calls.

    Constructing Scenario() directly bypasses it, so the guard is tested at the
    boundary that actually runs in production.
    """
    problems: list[str] = []
    scenario_from_dict({"name": "x", "gnss_outages": [{"start_s": -5.0, "duration_s": -1.0}]}, problems)
    assert problems, "a negative outage window must be reported, not silently accepted"


def test_a_valid_scenario_passes_the_parser():
    problems: list[str] = []
    s = scenario_from_dict({"name": "x", "gnss_outages": [{"start_s": 5.0, "duration_s": 15.0}]}, problems)
    assert problems == []
    assert s.gnss_outages[0].duration_s == 15.0


def test_inject_vision_noise_scaling_needs_a_reference():
    """Regenerating the vision stream requires truth; refuse clearly rather
    than silently keeping the old noise."""
    _gt, imu, gnss, vis = _streams()
    scen = Scenario(name="normal")
    scen.vision.noise_multiplier = 2.0
    with pytest.raises(AssertionError, match="needs the reference trajectory"):
        inject(scen, imu, gnss, vis, None)
