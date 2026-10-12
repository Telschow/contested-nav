"""docs/real_front_end.md against the committed CSVs, and the replay and clone checks on a synthetic sequence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import vo_error as ve
from navkit import vo_frontend as vf

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "real_front_end.md"


@pytest.fixture(scope="module")
def rows():
    return ve.read_csv(ROOT / "docs" / "data" / "vo_errors.csv")


@pytest.fixture(scope="module")
def clone():
    return ve.read_csv(ROOT / "docs" / "data" / "vo_clone_check.csv")


@pytest.fixture(scope="module")
def wide():
    return ve.read_csv(ROOT / "docs" / "data" / "vo_wide.csv")


@pytest.fixture(scope="module")
def first(rows):
    """The window measured first, at all five gaps."""
    return ve.rows_in(rows, *ve.ORIGINAL_WINDOW)


def _variant(clone, name):
    sel = [r for r in clone if r["variant"] == name]
    return (
        float(np.median([float(r["nees_mean"]) for r in sel])),
        float(np.median([float(r["coverage_2sigma"]) for r in sel])),
    )


def test_blocks_match_the_csvs(rows, clone, wide, first):
    text = PAGE.read_text(encoding="utf-8")
    assert ve.summary_markdown(first) in text
    assert ve.clone_markdown(clone) in text
    assert ve.windows_markdown(rows, wide) in text
    assert ve.wide_markdown(wide) in text


def test_the_one_frame_errors_are_small_and_shorter_lived_than_the_clone_needs(first):
    s = ve.summary(first, 1, ve.FRAME_STEP_S)
    assert 0.05 < s["rot_rms_deg"] < 0.12 and 0.005 < s["lat_rms_m"] < 0.012
    assert s["rot_rms_deg"] < 0.35 and s["lat_rms_m"] < 0.05  # the surrogate's defaults
    assert 0.1 <= s["rot_corr_time_s"] <= 0.3 and 0.15 <= s["lat_corr_time_s"] <= 0.3
    assert max(s["rot_corr_time_s"], s["lat_corr_time_s"]) < 0.5


def test_a_longer_baseline_gives_a_better_direction_and_more_outliers(first):
    by = {g: ve.summary(first, g, ve.FRAME_STEP_S) for g in (1, 2, 4, 6, 10)}
    direction = [by[g]["dir_median_deg"] for g in (1, 2, 4, 6, 10)]
    outliers = [by[g]["outlier_share"] for g in (1, 2, 4, 6, 10)]
    lateral = [by[g]["lat_rms_m"] for g in (1, 2, 4, 6, 10)]
    assert direction == sorted(direction, reverse=True) and direction[0] > 10 > 2 > direction[-1] - 0.0
    assert outliers[0] < 0.03 and 0.1 < outliers[-1] < 0.16 and outliers == sorted(outliers)
    assert lateral == sorted(lateral) and 0.03 < lateral[-1] < 0.05


def test_the_surrogate_passes_and_the_replay_at_the_measured_size_fails(clone):
    nees, cov = _variant(clone, "clone, measured correlation")
    assert nees < 10 and cov > 0.9
    nees, cov = _variant(clone, "replay, clone")
    assert nees > 10 and cov < 0.9
    assert 20 < nees < 40 and 0.5 < cov < 0.6


def test_four_times_the_noise_brings_the_replay_back_narrowly(clone):
    nees, cov = _variant(clone, "replay, clone, noise assumed x4")
    assert nees < 10 and 0.9 < cov < 0.95


def test_the_anchor_and_the_imu_alone(clone):
    nees, cov = _variant(clone, "replay, anchor")
    assert nees > 1000 and cov < 0.1
    sel = {r["variant"]: float(r["final_error_m"]) for r in clone if r["seed"] == "0"}
    assert sel["IMU only"] > 30.0 and sel["replay, clone"] < 1.0


def test_the_replay_carries_one_error_series_whatever_the_seed(clone):
    # the seeds change the simulated GNSS only; the visual errors are the same, which the page says
    seeds = {r["seed"] for r in clone if r["variant"] == "replay, clone"}
    assert seeds == {"0", "1", "2", "3", "4"}


# ---------------------------------------------------------------- synthetic checks of the code


def _synthetic(tmp_path):
    from test_vo_error import _write_cam

    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=45.0, seed=2)
    d = tmp_path / "MH_01_easy"
    _write_cam(d, 5.0, 40.0)
    return d


def _exact_frontend(monkeypatch, seq_dir, noise_deg=0.0):
    from test_vo_error import _exact

    _exact(monkeypatch, seq_dir, noise_deg=noise_deg)


def test_a_replay_stream_with_no_errors_is_the_true_body_motion(tmp_path, monkeypatch):
    d = _synthetic(tmp_path)
    _exact_frontend(monkeypatch, d)
    rows = ve.measure(d, gaps=(1,))
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    cam = vf.camera_from_yaml(d / "mav0/cam0/sensor.yaml")
    stream = ve.replay_stream(rows, seq.truth, cam, 5.0, 40.0)
    assert len(stream) == len(rows) and np.all(np.diff(stream.t) > 0)
    from navkit.types import interpolate_trajectory

    k = len(stream) // 2
    t1 = float(stream.t[k])
    p = interpolate_trajectory(seq.truth, np.array([t1 - 0.05, t1])).poses
    assert np.allclose(stream.R_rel[k], p[0][:3, :3].T @ p[1][:3, :3], atol=1e-6)
    assert np.allclose(stream.t_rel[k], p[0][:3, :3].T @ (p[1][:3, 3] - p[0][:3, 3]), atol=1e-6)
    with pytest.raises(ValueError):
        ve.replay_stream(rows, seq.truth, cam, 100.0, 110.0)


def test_clone_and_replay_runs_on_a_synthetic_sequence(tmp_path, monkeypatch):
    d = _synthetic(tmp_path)
    _exact_frontend(monkeypatch, d, noise_deg=0.05)
    rows = ve.measure(d, gaps=(1,))
    monkeypatch.setattr(ve, "CLONE_WINDOW", (5.0, 30.0, 10.0))
    monkeypatch.setattr(
        ve, "CLONE_VARIANTS", {k: ve.CLONE_VARIANTS[k] for k in ("IMU only", "clone, independent errors")}
    )
    monkeypatch.setattr(ve, "REPLAY_VARIANTS", {"replay, clone": ve.REPLAY_VARIANTS["replay, clone"]})
    sim = ve.clone_rows(tmp_path, "MH_01_easy", 0.08, 0.008, 0.25, seeds=1)
    rep = ve.replay_rows(tmp_path, "MH_01_easy", rows, seeds=1)
    assert {r["variant"] for r in sim} == set(ve.CLONE_VARIANTS)
    assert {r["variant"] for r in rep} == set(ve.REPLAY_VARIANTS)
    imu = next(r for r in sim if r["variant"] == "IMU only")
    clone = next(r for r in rep if r["variant"] == "replay, clone")
    assert float(clone["final_error_m"]) < float(imu["final_error_m"]) + 1.0
    out = tmp_path / "c.csv"
    ve.write_clone_csv(out, sim + rep)
    assert len(ve.read_clone_csv(out)) == len(sim) + len(rep)
    assert "replay, clone" in ve.clone_markdown(sim + rep)


def test_cli_fills_a_page_and_refuses_one_without_markers(rows, clone, tmp_path):
    page = tmp_path / "p.md"
    names = ("vo-errors", "vo-clone", "vo-wide-errors", "vo-wide-clone")
    page.write_text("".join(f"<!-- {n}:start -->\n<!-- {n}:end -->\n" for n in names))
    args = [
        "--from-csv",
        str(ROOT / "docs/data/vo_errors.csv"),
        "--clone-csv",
        str(ROOT / "docs/data/vo_clone_check.csv"),
        "--wide-csv",
        str(ROOT / "docs/data/vo_wide.csv"),
    ]
    assert ve.main([*args, "--page", str(page)]) == 0
    text = page.read_text()
    assert "Rotation RMS" in text and "replay, clone" in text and "clone x4" in text
    bare = tmp_path / "b.md"
    bare.write_text("none\n")
    assert ve.main([*args, "--page", str(bare)]) == 1


# ------------------------------------------------------------------ the wider measurement


def _windows(wide):
    return sorted({(r["sequence"], float(r["window_start_s"])) for r in wide})


def _passing(wide, variant):
    ok = 0
    for key in _windows(wide):
        sel = [r for r in wide if (r["sequence"], float(r["window_start_s"])) == key and r["variant"] == variant]
        nees = float(np.median([float(r["nees_mean"]) for r in sel]))
        cov = float(np.median([float(r["coverage_2sigma"]) for r in sel]))
        ok += ve.passes(nees, cov)
    return ok


def test_the_wider_measurement_has_six_windows_across_five_sequences(wide):
    keys = _windows(wide)
    assert len(keys) == 6 and {k[0] for k in keys} == set(ve.WIDE_SEQUENCES)
    assert sum(k[0] == "MH_01_easy" for k in keys) == 2
    assert {r["variant"] for r in wide} == {n for n, _, _ in ve.WIDE_SCALES}


def test_the_design_was_fixed_before_the_run():
    assert ve.WIDE_GAPS == (1, 4) and ve.WIDE_LENGTH_S == 30.0 and ve.WIDE_OUTAGE_AT_S == 10.0 and ve.WIDE_SEEDS == 3
    assert [(n, s) for n, _, s in ve.WIDE_SCALES] == [
        ("clone x1", 1.0),
        ("clone x2", 2.0),
        ("clone x4", 4.0),
        ("clone x8", 8.0),
        ("anchor x1", 1.0),
    ]


def test_the_measured_noise_meets_the_gate_in_two_of_six_windows_and_four_times_in_all(wide):
    assert _passing(wide, "clone x1") == 2 and _passing(wide, "clone x2") == 2
    assert _passing(wide, "clone x4") == 6 and _passing(wide, "clone x8") == 6
    assert _passing(wide, "anchor x1") == 0


def test_four_times_is_tightest_on_the_first_window(wide):
    sel = [r for r in wide if r["variant"] == "clone x4"]
    covs = sorted(
        float(np.median([float(r["coverage_2sigma"]) for r in sel if (r["sequence"], r["window_start_s"]) == k]))
        for k in {(r["sequence"], r["window_start_s"]) for r in sel}
    )
    assert 0.9 < covs[0] < 0.93 and covs[1] > 0.98


def test_the_errors_are_small_in_every_window_and_the_longest_correlation_sits_at_half_a_second(rows, wide):
    worst_corr = 0.0
    for seq, start in _windows(wide):
        sel = ve.rows_in_window(rows, seq, start, ve.WIDE_LENGTH_S)
        s = ve.summary(sel, 1, ve.FRAME_STEP_S)
        assert 0.05 < s["rot_rms_deg"] < 0.2 and 0.004 < s["lat_rms_m"] < 0.025
        worst_corr = max(worst_corr, s["rot_corr_time_s"], s["lat_corr_time_s"])
    assert worst_corr == pytest.approx(0.5)


def test_windows_are_defined_by_where_their_pairs_start():
    def row(t):
        return {"sequence": "s", "t_s": t, "dt_s": 0.05, "gap_frames": 1}

    rows = [row(89.9), row(89.955), row(90.005), row(119.9), row(119.955)]
    first = ve.rows_in_window(rows, "s", 60.005, 30.0)
    second = ve.rows_in_window(rows, "s", 90.005, 30.0)
    assert [r["t_s"] for r in first] == [89.9]  # the pair that straddles 90.005 belongs to neither
    assert [r["t_s"] for r in second] == [90.005, 119.9]
    assert ve.rows_in(rows, "s", 90.0, 120.0)[0]["t_s"] == 90.005
    assert ve.rows_in(rows, "other", 0.0, 500.0) == []


def test_contiguous_runs_of_pairs_are_found_as_windows():
    def row(t):
        return {"sequence": "s", "t_s": t, "dt_s": 0.05, "gap_frames": 1}

    rows = [row(10 + 0.05 * k) for k in range(40)] + [row(50 + 0.05 * k) for k in range(40)]
    got = ve.windows(rows)
    assert [(a, round(b - a)) for _, a, b in got] == [(10.0, 2), (50.0, 2)]
    assert ve.windows([]) == []


def test_pick_window_prefers_the_fastest_stretch_and_avoids_what_it_is_told():
    from navkit.types import Trajectory

    t = np.arange(0.0, 200.0, 1.0)
    x = np.where(t < 100.0, 0.1 * t, 10.0 + 2.0 * (t - 100.0))  # slow, then fast
    poses = np.tile(np.eye(4), (len(t), 1, 1))
    poses[:, 0, 3] = x
    truth = Trajectory(t=t, poses=poses)
    best = ve.pick_window(truth, 30.0, step_s=5.0, earliest_s=30.0, margin_s=5.0)
    assert best >= 85.0  # the median of a window is fast once more than half of it is
    other = ve.pick_window(truth, 30.0, step_s=5.0, earliest_s=30.0, margin_s=5.0, avoid=((best, best + 30.0),))
    assert other + 30.0 <= best or other >= best + 30.0
    with pytest.raises(ValueError):
        ve.pick_window(truth, 500.0)


def test_the_gate_is_nees_below_ten_and_coverage_above_ninety_percent():
    assert ve.passes(9.9, 0.91) and not ve.passes(10.0, 0.95) and not ve.passes(2.0, 0.9)


def test_wide_study_on_a_synthetic_sequence(tmp_path, monkeypatch):
    from test_vo_error import _write_cam

    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=45.0, seed=2)
    d = tmp_path / "MH_01_easy"
    _write_cam(d, 5.0, 40.0)
    _exact_frontend(monkeypatch, d)
    monkeypatch.setattr(ve, "WIDE_LENGTH_S", 25.0)
    monkeypatch.setattr(ve, "WIDE_SCALES", (("clone x4", "clone", 4.0),))
    new_rows, replay = ve.wide_study(tmp_path, ("MH_01_easy",), existing=None, seeds=1, fetch=False, earliest_s=5.0)
    assert new_rows and replay
    assert {r["variant"] for r in replay} == {"clone x4"} and {r["sequence"] for r in replay} == {"MH_01_easy"}
    out = tmp_path / "w.csv"
    ve.write_wide_csv(out, replay)
    assert "clone x4" in ve.wide_markdown(ve.read_csv(out))
    assert ve.windows_markdown(new_rows, replay).count("MH_01_easy") >= 1


def test_the_wide_flag_runs_the_study_and_reports_a_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ve, "wide_study", lambda *a, **k: ([], []))
    assert ve.main(["--wide", "--wide-csv", str(tmp_path / "w.csv")]) == 0
    assert (tmp_path / "w.csv").is_file()

    def boom(*a, **k):
        raise ValueError("no window fits")

    monkeypatch.setattr(ve, "wide_study", boom)
    assert ve.main(["--wide", "--wide-csv", str(tmp_path / "x.csv")]) == 1
    assert "no window fits" in capsys.readouterr().err
