"""Tests for trajectory evaluation metrics.

``eval/metrics.py`` defines the numbers this project is judged on, and the
alignment convention behind each one is not cosmetic: ``none``, ``rigid``,
``rigid_start`` and ``similarity`` can differ by metres on the same data, and
an ATE quoted without its alignment is not a result. The tests below pin both
the metric definitions and the alignment semantics, including the
``rigid_start`` window, which is easy to misread.

The module docstring refers to ``tests/test_metrics_reference.py`` as a
cross-check against published TUM VI metrics. That file did not exist; the
equivalent check lives in ``tests/test_trajectory_io.py``, which asserts ATE
against the published room1/512/16 figure, and the docstring has been
corrected to point there.
"""

import numpy as np
import pytest

from navkit.eval.metrics import (
    absolute_error,
    associate_nearest,
    ate_bundle,
    drift,
    error_stats,
    outage_summary,
    percentiles,
    pose_errors_with_alignment,
    relative_pose_error,
    time_to_recovery,
)
from navkit.types import Trajectory

# --- error_stats -------------------------------------------------------------


def test_error_stats_of_a_known_sequence():
    s = error_stats([1.0, 2.0, 3.0, 4.0])
    assert s.rmse == pytest.approx(np.sqrt((1 + 4 + 9 + 16) / 4))
    assert s.mean == pytest.approx(2.5)
    assert s.median == pytest.approx(2.5)
    assert s.min == 1.0 and s.max == 4.0
    assert s.count == 4


def test_error_stats_of_a_constant_has_zero_spread():
    s = error_stats([2.0] * 10)
    assert s.std == pytest.approx(0.0)
    assert s.rmse == pytest.approx(2.0)
    assert s.min == s.max == 2.0


def test_error_stats_of_nothing_is_all_nan_not_zero():
    """Zero would read as a perfect result; nan reads as absent."""
    s = error_stats([])
    assert s.count == 0
    assert all(np.isnan(v) for v in (s.rmse, s.mean, s.median, s.std, s.min, s.max))


def test_error_stats_flattens_a_nested_array():
    assert error_stats([[1.0, 2.0], [3.0, 4.0]]).count == 4


def test_error_stats_rejects_ragged_input_rather_than_guessing():
    with pytest.raises(ValueError):
        error_stats([[1.0, 2.0], [3.0]])


def test_error_stats_dict_is_json_shaped():
    d = error_stats([1.0, 2.0]).as_dict()
    assert set(d) == {"rmse", "mean", "median", "std", "min", "max", "count"}


def test_percentiles_of_a_known_sequence():
    p = percentiles([0.0, 1.0, 2.0, 3.0, 4.0], qs=(0.5, 1.0))
    assert p["p50"] == pytest.approx(2.0)
    assert p["p100"] == pytest.approx(4.0)


def test_percentiles_of_nothing_is_nan():
    p = percentiles([], qs=(0.5,))
    assert np.isnan(p["p50"])


# --- fixtures ----------------------------------------------------------------


def _traj(t: np.ndarray, positions: np.ndarray, R: np.ndarray | None = None) -> Trajectory:
    n = len(t)
    poses = np.repeat(np.eye(4)[None, :, :], n, axis=0)
    if R is None:
        R = np.tile(np.eye(3), (n, 1, 1))
    for i in range(n):
        poses[i, :3, :3] = R[i]
        poses[i, :3, 3] = positions[i]
    return Trajectory(t=t, poses=poses, name="t")


def _line(n: int = 100, rate: float = 50.0, speed: float = 1.0) -> Trajectory:
    t = np.arange(n) / rate
    p = np.stack([speed * t, np.zeros_like(t), np.zeros_like(t)], axis=1)
    return _traj(t, p)


def _helix(t: np.ndarray, radius: float = 1.0, pitch: float = 0.3) -> Trajectory:
    """A non-degenerate 3D path: not collinear, so a rigid fit has no
    degenerate direction to exploit."""
    ang = 0.7 * t
    p = np.stack([radius * np.cos(ang), radius * np.sin(ang), pitch * t], axis=1)
    return _traj(t, p)


def _noisy(n: int = 100, rate: float = 50.0, sigma: float = 0.1, seed: int = 0) -> Trajectory:
    gt = _line(n, rate)
    rng = np.random.default_rng(seed)
    return _traj(gt.t, gt.positions + rng.normal(scale=sigma, size=(n, 3)))


# --- association -------------------------------------------------------------


def test_associate_nearest_pairs_each_estimate_with_a_reference():
    est = _line(20, rate=10.0)
    ref = _line(20, rate=10.0)
    i, j = associate_nearest(est, ref)
    assert len(i) == len(j) == 20
    assert np.array_equal(i, np.arange(20))
    assert np.array_equal(j, np.arange(20))


def test_associate_nearest_drops_estimates_far_from_any_reference():
    est = _line(20, rate=1.0)
    ref = _line(3, rate=1.0)  # only the first second exists in the reference
    i, _ = associate_nearest(est, ref, max_difference_s=0.2)
    assert len(i) < 20
    assert set(i.tolist()) == {0, 1, 2}, "only the first three seconds exist in the reference"


def test_associate_nearest_prefers_the_closest_sample():
    est = _traj(np.array([0.5]), np.zeros((1, 3)))
    ref = _traj(np.array([0.0, 1.0]), np.zeros((2, 3)))
    _, j = associate_nearest(est, ref, max_difference_s=1.0)
    assert j[0] == 0, "0.5 s is closer to t=0 than to t=1"


def test_unknown_association_is_rejected():
    with pytest.raises(ValueError, match="unknown association"):
        absolute_error(_line(), _line(), association="cubic")


# --- ATE ---------------------------------------------------------------------


def test_ate_of_an_identical_trajectory_is_zero():
    gt = _line()
    r = absolute_error(gt, gt, alignment="none")
    assert r.position_m.rmse == pytest.approx(0.0, abs=1e-12)
    assert r.rotation_deg.rmse == pytest.approx(0.0, abs=1e-9)
    assert r.associated_poses == len(gt)


def test_ate_none_reports_the_raw_error():
    """A constant frame offset must survive 'none' rather than be fitted away."""
    gt = _line()
    est = _traj(gt.t, gt.positions + np.array([5.0, 0.0, 0.0]))
    assert absolute_error(est, gt, alignment="none").position_m.rmse == pytest.approx(5.0)


def test_ate_rigid_removes_a_constant_offset():
    gt = _line()
    est = _traj(gt.t, gt.positions + np.array([5.0, 0.0, 0.0]))
    assert absolute_error(est, gt, alignment="rigid").position_m.rmse == pytest.approx(0.0, abs=1e-9)


def test_ate_rigid_removes_a_rotation_of_the_positions():
    th = np.deg2rad(30.0)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
    gt = _line()
    est = _traj(gt.t, gt.positions @ R.T, np.tile(R, (len(gt), 1, 1)))
    assert absolute_error(est, gt, alignment="rigid").position_m.rmse == pytest.approx(0.0, abs=1e-6)


def test_ate_rigid_does_not_remove_the_rotation_error():
    """The fit uses positions only, so attitude error survives it untouched.

    A reader who assumes "rigid alignment" means "6-DoF pose alignment" would
    otherwise quote an attitude error several times smaller than reality.
    """
    th = np.deg2rad(30.0)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
    gt = _line()
    est = _traj(gt.t, gt.positions @ R.T, np.tile(R, (len(gt), 1, 1)))
    r = absolute_error(est, gt, alignment="rigid")
    assert r.rotation_deg.rmse == pytest.approx(30.0, abs=1e-6)


def test_ate_none_reports_the_rotation_error_too():
    th = np.deg2rad(30.0)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
    gt = _line()
    est = _traj(gt.t, gt.positions @ R.T, np.tile(R, (len(gt), 1, 1)))
    assert absolute_error(est, gt, alignment="none").rotation_deg.rmse == pytest.approx(30.0, abs=1e-6)


def test_ate_similarity_also_corrects_a_scale_error():
    gt = _line()
    est = _traj(gt.t, gt.positions * 1.1)
    r = absolute_error(est, gt, alignment="similarity")
    assert r.position_m.rmse == pytest.approx(0.0, abs=1e-6)
    assert r.scale == pytest.approx(1.0 / 1.1, rel=1e-3)


def test_ate_rigid_cannot_correct_a_scale_error_on_a_3d_path():
    """Rigid has no scale degree of freedom, so a scaled 3D track must still
    show error. This is the difference between the two alignments.

    The path has to be non-degenerate: on a straight line a rigid fit can flip
    the track back through 180 degrees and absorb a scale error exactly, which
    would make this test pass for the wrong reason.
    """
    t = np.linspace(0, 10, 200)
    gt = _helix(t)
    est = _traj(t, gt.positions * 1.1)
    assert absolute_error(est, gt, alignment="rigid").position_m.rmse > 0.1
    assert absolute_error(est, gt, alignment="similarity").position_m.rmse == pytest.approx(0.0, abs=1e-6)


def test_ate_rigid_can_absorb_scale_on_a_straight_line():
    """The degenerate case, pinned so the test above is not a tautology: a
    straight path is a line, and a line can be reversed by a rigid motion."""
    gt = _line()
    est = _traj(gt.t, gt.positions * 1.1)
    assert absolute_error(est, gt, alignment="rigid").position_m.rmse < 0.1


def test_rigid_start_fits_only_on_the_leading_window():
    """`fractions=(0, 0.2)` must fit on the first 20% and apply to everything.

    A drift introduced late must therefore survive, which is the whole point
    of the convention: `rigid` hides it, `rigid_start` does not.
    """
    gt = _line(200, rate=50.0)
    drifted = gt.positions.copy()
    drifted[40:, 1] += 2.0  # a step error after the first 20%
    est = _traj(gt.t, drifted)

    rigid = absolute_error(est, gt, alignment="rigid").position_m.rmse
    start = absolute_error(est, gt, alignment="rigid_start", fractions=(0.0, 0.2)).position_m.rmse
    assert start > rigid, "rigid_start must expose error that rigid absorbs"
    assert start > 0.5


def test_ate_bundle_labels_rigid_start_as_its_own_convention():
    """Fitted with kind='rigid' but over 20% of the sequence, so reporting it
    as 'rigid' would put a different number under a familiar name."""
    b = ate_bundle(_noisy(), _line())
    assert b["rigid_start"].alignment == "rigid_start"
    assert b["rigid_start"].fractions == (0.0, 0.2)
    assert b["rigid"].fractions == (0.0, 1.0)


def test_rigid_start_is_reached_through_the_bundle_not_the_alignment_name():
    """'rigid_start' is a bundle key, not an alignment kind: passing it to
    absolute_error would hit an unknown umeyama kind."""
    assert ate_bundle(_line(), _line())["rigid_start"].fractions == (0.0, 0.2)


def test_rigid_start_on_a_constant_error_curve_behaves_like_rigid():
    gt = _line()
    est = _traj(gt.t, gt.positions + np.array([1.0, 0.0, 0.0]))
    a = absolute_error(est, gt, alignment="rigid", fractions=(0.0, 0.2)).position_m.rmse
    b = absolute_error(est, gt, alignment="rigid_start", fractions=(0.0, 0.2)).position_m.rmse
    assert a == pytest.approx(b, abs=1e-6)


def test_ate_result_percentiles_agree_with_its_own_per_pose_errors():
    gt = _line()
    r = absolute_error(_noisy(), gt, alignment="none")
    assert r.position_percentiles_m["p50"] == pytest.approx(float(np.percentile(r.per_pose_position_m, 50)))
    assert len(r.per_pose_position_m) == len(gt)


def test_ate_nearest_association_pairs_by_time():
    est = _line(50, rate=10.0)
    ref = _line(50, rate=10.0)
    r = absolute_error(est, ref, alignment="none", association="nearest")
    assert r.association == "nearest"
    assert r.associated_poses == len(est)


def test_ate_result_dict_reports_the_alignment_it_used():
    gt = _line()
    d = absolute_error(_noisy(), gt, alignment="similarity").as_dict()
    assert d["alignment"] == "similarity"
    assert d["association"] == "interpolate"
    assert d["fractions"] == [0.0, 1.0]
    assert "position_m" in d and "rotation_deg" in d


def test_ate_bundle_covers_every_documented_alignment():
    b = ate_bundle(_noisy(), _line())
    assert set(b) == {"none", "rigid", "rigid_start", "similarity"}
    for name, res in b.items():
        assert res.alignment == name


def test_ate_bundle_none_is_never_better_than_rigid_on_a_whole_loop():
    """A closed trajectory admits an exact rigid fit, so `rigid` must be the
    lower of the two. A violation would mean the fit is not actually fitting."""
    t = np.linspace(0, 2 * np.pi, 200)
    poses = np.repeat(np.eye(4)[None, :, :], 200, axis=0)
    p = np.stack([np.cos(t), np.sin(t), np.zeros_like(t)], axis=1)
    for i in range(200):
        poses[i, :3, 3] = p[i]
    loop = Trajectory(t=np.linspace(0, 10, 200), poses=poses, name="loop")
    b = ate_bundle(loop, loop)
    assert b["rigid"].position_m.rmse <= b["none"].position_m.rmse + 1e-9


def test_pose_errors_with_alignment_returns_aligned_arrays():
    gt = _line()
    t, pos, rot = pose_errors_with_alignment(_noisy(), gt)
    assert len(t) == len(pos) == len(rot) == len(gt)
    assert np.allclose(t, gt.t)


# --- RPE ---------------------------------------------------------------------


def test_rpe_of_an_identical_trajectory_is_zero():
    gt = _line(400, rate=50.0)
    r = relative_pose_error(gt, gt, delta=1.0, mode="time")
    assert r.translation_m.rmse == pytest.approx(0.0, abs=1e-9)
    assert r.rotation_deg.rmse == pytest.approx(0.0, abs=1e-9)


def test_rpe_is_invariant_to_a_global_frame_offset():
    """Relative motion does not change when the whole trajectory is shifted,
    which is the property that makes RPE worth reporting alongside ATE."""
    gt = _line(400, rate=50.0)
    est = _traj(gt.t, gt.positions + np.array([100.0, -50.0, 7.0]))
    a = relative_pose_error(gt, gt, delta=1.0, mode="time").translation_m.rmse
    b = relative_pose_error(est, gt, delta=1.0, mode="time").translation_m.rmse
    assert a == pytest.approx(b, abs=1e-9)


def test_rpe_by_distance_uses_travelled_path_length():
    gt = _line(400, rate=50.0)
    r = relative_pose_error(_noisy(400, 50.0, sigma=0.2, seed=1), gt, delta=1.0, mode="distance")
    assert r.translation_m.count > 0
    assert np.isfinite(r.translation_m.rmse)


def test_rpe_grows_with_the_baseline():
    """A longer baseline accumulates more error; if it did not, the metric
    would not be measuring anything.

    The fixture carries a constant velocity error in y, so the error it
    accumulates is strictly proportional to the baseline.
    """
    gt = _line(2000, rate=100.0)
    est = _traj(gt.t, gt.positions + np.stack([np.zeros_like(gt.t), 0.01 * gt.t, np.zeros_like(gt.t)], axis=1))
    short = relative_pose_error(est, gt, delta=0.1, mode="time").translation_m.rmse
    long = relative_pose_error(est, gt, delta=2.0, mode="time").translation_m.rmse
    assert long > short
    assert long / short == pytest.approx(20.0, rel=0.05), "error must scale with the baseline"


def test_rpe_result_dict_reports_its_baseline():
    r = relative_pose_error(_line(), _line(), delta=2.5, mode="time")
    d = r.as_dict()
    assert d["delta_s"] == pytest.approx(2.5)
    assert isinstance(d["delta"], str) and "2.5" in d["delta"]
    assert "translation_m" in d and "rotation_deg" in d


# --- drift -------------------------------------------------------------------


def test_drift_reports_percent_of_path_length():
    gt = _line(500, rate=50.0)
    est = _traj(gt.t, gt.positions + np.array([0.0, 1.0, 0.0]))
    ate = absolute_error(est, gt, alignment="none")
    d = drift(ate, gt)
    path = float(np.sum(np.linalg.norm(np.diff(gt.positions, axis=0), axis=1)))
    assert d.final_drift_pct_path == pytest.approx(100.0 / path, rel=1e-6)


def test_drift_reports_percent_of_time():
    gt = _line(500, rate=50.0)
    est = _traj(gt.t, gt.positions + np.array([0.0, 1.0, 0.0]))
    d = drift(absolute_error(est, gt, alignment="none"), gt)
    assert d.final_drift_pct_time == pytest.approx(100.0 / gt.t[-1], rel=1e-6)


def test_drift_fits_a_growth_slope_when_asked():
    t = np.linspace(0, 20, 200)
    stationary = _traj(t, np.stack([np.zeros_like(t)] * 3, axis=1))
    ate = absolute_error(stationary, _traj(t, np.zeros((200, 3))), alignment="none")
    growing = _traj(t, np.stack([0.05 * t, np.zeros_like(t), np.zeros_like(t)], axis=1))
    d = drift(absolute_error(growing, _traj(t, np.zeros((200, 3))), alignment="none"), _traj(t, np.zeros((200, 3))))
    assert d.growth is not None
    assert d.growth.slope_m_per_s == pytest.approx(0.05, rel=0.05)
    assert 0.0 <= d.growth.r_squared <= 1.0
    del ate


def test_drift_without_a_fit_returns_no_growth():
    gt = _line(200, rate=50.0)
    d = drift(absolute_error(gt, gt, alignment="none"), gt, fit_growth=False)
    assert d.growth is None


def test_drift_dict_is_json_shaped():
    gt = _line(200, rate=50.0)
    est = _traj(gt.t, gt.positions + np.array([0.0, 0.5, 0.0]))
    d = drift(absolute_error(est, gt, alignment="none"), gt).as_dict()
    assert "final_drift_pct_path_length" in d
    assert "final_drift_pct_time" in d


# --- recovery ----------------------------------------------------------------


def test_time_to_recovery_is_none_when_the_error_never_returns():
    t = np.linspace(0, 30, 300)
    e = np.where(t > 5, 2.0, 0.05)
    assert time_to_recovery(t, e, (5.0, 20.0), threshold_m=0.25, hold_s=1.0) is None


def test_time_to_recovery_is_none_when_the_window_ends_the_data():
    t = np.linspace(0, 10, 100)
    e = np.full_like(t, 0.05)
    assert time_to_recovery(t, e, (5.0, 20.0), threshold_m=0.25) is None


def test_time_to_recovery_is_none_while_the_error_is_above_threshold():
    t = np.linspace(0, 20, 200)
    e = np.full_like(t, 2.0)
    assert time_to_recovery(t, e, (0.0, 20.0), threshold_m=0.25) is None


def test_time_to_recovery_is_zero_when_the_error_is_already_back():
    """Recovery is measured from the end of the window, not from the onset."""
    t = np.linspace(0, 30, 300)
    e = np.where((t > 5) & (t <= 20), 2.0, 0.05)  # back below the instant the window ends
    ttr = time_to_recovery(t, e, (5.0, 20.0), threshold_m=0.25, hold_s=0.5)
    assert ttr == pytest.approx(0.0, abs=0.1)


def test_time_to_recovery_counts_the_delay_after_the_window():
    t = np.linspace(0, 40, 400)
    e = np.where(t > 25, 0.05, 2.0)  # settles at t=25, window ends at t=20
    ttr = time_to_recovery(t, e, (5.0, 20.0), threshold_m=0.25, hold_s=0.5)
    assert ttr == pytest.approx(5.0, abs=0.5)


def test_time_to_recovery_requires_the_hold_to_be_met():
    """A single good sample is not a recovery; a brief dip must not count."""
    t = np.linspace(0, 20, 200)
    e = np.full_like(t, 2.0)
    e[(t > 6) & (t < 6.1)] = 0.0  # a momentary dip
    assert time_to_recovery(t, e, (5.0, 20.0), threshold_m=0.25, hold_s=1.0) is None


def test_time_to_recovery_on_a_clean_curve_is_immediate():
    t = np.linspace(0, 20, 200)
    assert time_to_recovery(t, np.full_like(t, 0.0), (0.0, 20.0), 0.25) == pytest.approx(0.0)


# --- outage summary ----------------------------------------------------------


def test_outage_summary_reports_one_block_per_window():
    t = np.linspace(0, 30, 300)
    e = np.where((t > 5) & (t < 20), 2.0, 0.05)
    blocks = outage_summary(t, e, [(5.0, 20.0)], baseline_error_m=0.05)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["start_s"] == 5.0
    assert b["end_s"] == 20.0
    assert b["duration_s"] == pytest.approx(15.0)
    assert b["error_peak_m"] == pytest.approx(2.0)
    assert b["samples_inside"] == 150


def test_outage_summary_keeps_one_block_per_window_when_there_are_several():
    t = np.linspace(0, 60, 600)
    e = np.where(((t > 5) & (t < 15)) | ((t > 40) & (t < 50)), 2.0, 0.05)
    blocks = outage_summary(t, e, [(5.0, 15.0), (40.0, 50.0)], baseline_error_m=0.05)
    assert [b["start_s"] for b in blocks] == [5.0, 40.0]
    assert [b["duration_s"] for b in blocks] == [10.0, 10.0]


def test_outage_summary_measures_growth_against_the_pre_outage_error():
    """Growth is relative to the error just before the outage, not to zero.

    This is what makes a GNSS outage interpretable: a well-localised filter
    should show a small rise from a small baseline, not a large absolute number.
    """
    t = np.linspace(0, 30, 300)
    e = np.where((t > 5) & (t < 20), 2.0, 0.30)
    b = outage_summary(t, e, [(5.0, 20.0)], baseline_error_m=0.99)[0]
    assert b["error_before_m"] == pytest.approx(0.30)
    assert b["growth_m"] == pytest.approx(2.0 - 0.30)
    assert b["growth_m"] < 2.0, "growth must not be measured against zero"


def test_outage_summary_reports_the_error_after_the_window():
    t = np.linspace(0, 30, 300)
    e = np.where((t > 5) & (t < 20), 2.0, 0.05)
    b = outage_summary(t, e, [(5.0, 20.0)], baseline_error_m=0.05)[0]
    assert b["error_after_m"] == pytest.approx(0.05)


def test_outage_summary_distinguishes_a_weak_and_a_strong_outage():
    """Two outages, same length, different magnitude: growth must separate them."""
    t = np.linspace(0, 40, 400)
    e = np.where((t > 5) & (t < 15), 0.5, 0.05)
    e = np.where((t > 25) & (t < 35), 3.0, e)
    weak, strong = outage_summary(t, e, [(5.0, 15.0), (25.0, 35.0)], baseline_error_m=0.05)
    assert strong["growth_m"] > 3 * weak["growth_m"]


def test_outage_summary_with_no_outages_is_empty():
    t = np.linspace(0, 10, 100)
    assert outage_summary(t, np.full_like(t, 0.1), [], baseline_error_m=0.1) == []


def test_outage_summary_on_an_empty_window_is_nan_not_zero():
    """No samples inside the window must read as absent, not as no error."""
    t = np.linspace(0, 10, 100)
    b = outage_summary(t, np.full_like(t, 0.1), [(50.0, 60.0)], baseline_error_m=0.1)[0]
    assert b["samples_inside"] == 0
    assert np.isnan(b["error_peak_m"])
    assert np.isnan(b["growth_m"])


def test_outage_summary_falls_back_to_the_baseline_with_no_preceding_data():
    t = np.linspace(0, 10, 100)
    b = outage_summary(t, np.full_like(t, 0.1), [(0.0, 4.0)], baseline_error_m=0.42)[0]
    assert np.isnan(b["error_before_m"]), "a window starting at t=0 has no preceding sample"
    assert b["growth_m"] == pytest.approx(0.1 - 0.42), "the supplied baseline is the reference"
