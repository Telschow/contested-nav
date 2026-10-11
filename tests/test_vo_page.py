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


def _variant(clone, name):
    sel = [r for r in clone if r["variant"] == name]
    return (
        float(np.median([float(r["nees_mean"]) for r in sel])),
        float(np.median([float(r["coverage_2sigma"]) for r in sel])),
    )


def test_blocks_match_the_csvs(rows, clone):
    text = PAGE.read_text(encoding="utf-8")
    assert ve.summary_markdown(rows) in text
    assert ve.clone_markdown(clone) in text


def test_the_one_frame_errors_are_small_and_shorter_lived_than_the_clone_needs(rows):
    s = ve.summary(rows, 1, ve.FRAME_STEP_S)
    assert 0.05 < s["rot_rms_deg"] < 0.12 and 0.005 < s["lat_rms_m"] < 0.012
    assert s["rot_rms_deg"] < 0.35 and s["lat_rms_m"] < 0.05  # the surrogate's defaults
    assert 0.1 <= s["rot_corr_time_s"] <= 0.3 and 0.15 <= s["lat_corr_time_s"] <= 0.3
    assert max(s["rot_corr_time_s"], s["lat_corr_time_s"]) < 0.5


def test_a_longer_baseline_gives_a_better_direction_and_more_outliers(rows):
    by = {g: ve.summary(rows, g, ve.FRAME_STEP_S) for g in (1, 2, 4, 6, 10)}
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
    page.write_text(
        "<!-- vo-errors:start -->\n<!-- vo-errors:end -->\n<!-- vo-clone:start -->\n<!-- vo-clone:end -->\n"
    )
    args = [
        "--from-csv",
        str(ROOT / "docs/data/vo_errors.csv"),
        "--clone-csv",
        str(ROOT / "docs/data/vo_clone_check.csv"),
    ]
    assert ve.main([*args, "--page", str(page)]) == 0
    assert "Rotation RMS" in page.read_text() and "replay, clone" in page.read_text()
    bare = tmp_path / "b.md"
    bare.write_text("none\n")
    assert ve.main([*args, "--page", str(bare)]) == 1
