"""The error study of the two-view front end, tested with the front end replaced by one that has known errors."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import vo_error as ve
from navkit import vo_frontend as vf
from navkit.euroc_cli import main as euroc_main
from navkit.geometry.rigid import rot_exp


def _write_cam(seq_dir: Path, t_start: float, t_stop: float, rate: float = 20.0) -> None:
    import matplotlib.image as mpimg

    first_ns = None
    for line in (seq_dir / "mav0/imu0/data.csv").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            first_ns = int(line.split(",")[0])
            break
    cam = seq_dir / "mav0/cam0"
    (cam / "data").mkdir(parents=True)
    (cam / "sensor.yaml").write_text(
        "intrinsics: [450.0, 450.0, 32.0, 24.0]\n"
        "distortion_coefficients: [0.0, 0.0, 0.0, 0.0]\n"
        "resolution: [64, 48]\n"
        "T_BS:\n  cols: 4\n  rows: 4\n  data: [1,0,0,0.05, 0,1,0,0, 0,0,1,0, 0,0,0,1]\n"
    )
    rows = ["#timestamp [ns],filename"]
    for k in range(int((t_stop - t_start) * rate)):
        ts = first_ns + int((t_start + k / rate) * 1e9)
        rows.append(f"{ts},{ts}.png")
        img = np.zeros((48, 64, 3), dtype=np.uint8)  # RGB: saved as it is, with no colour map to quantise it
        img[0, 0, :], img[0, 1, :] = k // 256, k % 256  # the frame index, for a replacement front end to read back
        mpimg.imsave(str(cam / "data" / f"{ts}.png"), img)
    (cam / "data.csv").write_text("\n".join(rows) + "\n")


@pytest.fixture
def seq_dir(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=2)
    d = tmp_path / "MH_01_easy"
    _write_cam(d, 5.0, 15.0)
    return d


def _index(img):
    return int(round(float(img[0, 0]) * 255)) * 256 + int(round(float(img[0, 1]) * 255))


def _exact(monkeypatch, seq_dir, noise_deg=0.0, seed=0):
    """Replace the front end by one that returns the true relative pose plus a random rotation error."""
    seq = ee.load_sequence(seq_dir.parent, seq_dir.name)
    cam = vf.camera_from_yaml(seq_dir / "mav0/cam0/sensor.yaml")
    times = [t for t, _ in ve.frame_list(seq_dir)]
    rng = np.random.default_rng(seed)

    def fake(images, gaps, camera, seed=0):
        out = {}
        for g in gaps:
            t0, t1 = times[_index(images[0])], times[_index(images[g])]
            R, t = ve.true_motion(seq.truth, cam, t0, t1)
            Rm = R @ rot_exp(np.radians(noise_deg) * rng.standard_normal(3))
            norm = np.linalg.norm(t)
            u = t / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
            out[g] = vf.PairResult(R=Rm.T, t_dir=-Rm.T @ u, tracked=100, inliers=90)
        return out

    monkeypatch.setattr(ve, "relative_poses_along", fake)


def test_frame_list_is_sorted_on_the_imu_clock_and_skips_missing_files(seq_dir):
    frames = ve.frame_list(seq_dir)
    assert len(frames) == 200
    assert frames[0][0] == pytest.approx(5.0) and frames[1][0] - frames[0][0] == pytest.approx(0.05)
    next(iter((seq_dir / "mav0/cam0/data").iterdir())).unlink()
    assert len(ve.frame_list(seq_dir)) == 199


def test_true_motion_follows_the_extrinsic(seq_dir):
    seq = ee.load_sequence(seq_dir.parent, seq_dir.name)
    cam = vf.camera_from_yaml(seq_dir / "mav0/cam0/sensor.yaml")
    R, t = ve.true_motion(seq.truth, cam, 10.0, 10.5)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and np.linalg.norm(t) > 0.0
    # with no extrinsic offset the translation is the body's own, rotated into the start frame
    cam0 = vf.Camera(**{**cam.__dict__, "T_BS": np.eye(4)})
    R0, t0 = ve.true_motion(seq.truth, cam0, 10.0, 10.5)
    assert np.allclose(R, R0, atol=1e-9) and not np.allclose(t, t0)


def test_a_perfect_pair_has_no_error():
    R = rot_exp(np.array([0.01, -0.02, 0.03]))
    u = np.array([0.6, 0.0, 0.8])

    class Truth:
        pass

    est = vf.PairResult(R=R.T, t_dir=-R.T @ u, tracked=50, inliers=40)
    seq_cam = vf.Camera(450, 450, 32, 24, (0, 0, 0, 0), np.eye(4), 64, 48)
    traj = _line_trajectory(R, u * 0.4)
    row = ve.pair_row("s", 1, 0.0, 1.0, est, traj, seq_cam)
    assert row is not None
    assert abs(row["rot_x_deg"]) + abs(row["rot_y_deg"]) + abs(row["rot_z_deg"]) < 1e-6
    assert abs(row["lat_x_m"]) + abs(row["lat_y_m"]) + abs(row["lat_z_m"]) < 1e-9 and row["dir_err_deg"] < 1e-6
    assert row["baseline_m"] == pytest.approx(0.4)


def _line_trajectory(R, t):
    from navkit.types import Trajectory

    poses = np.stack([np.eye(4), np.eye(4)])
    poses[1, :3, :3] = R
    poses[1, :3, 3] = t
    return Trajectory(t=np.array([0.0, 1.0]), poses=poses)


def test_a_rotation_error_and_a_direction_error_are_measured():
    R = np.eye(3)
    u = np.array([1.0, 0.0, 0.0])
    off = rot_exp(np.radians([1.0, 0.0, 0.0]))
    tilted = np.array([np.cos(np.radians(10)), np.sin(np.radians(10)), 0.0])
    est = vf.PairResult(R=(R @ off).T, t_dir=-(R @ off).T @ tilted, tracked=10, inliers=9)
    cam = vf.Camera(450, 450, 32, 24, (0, 0, 0, 0), np.eye(4), 64, 48)
    row = ve.pair_row("s", 1, 0.0, 1.0, est, _line_trajectory(R, u * 0.5), cam)
    assert row is not None
    assert abs(row["rot_x_deg"]) == pytest.approx(1.0, abs=1e-6)
    assert row["dir_err_deg"] == pytest.approx(10.0, abs=1e-6)
    assert abs(row["lat_y_m"]) == pytest.approx(0.5 * np.sin(np.radians(10)), abs=1e-6)


def test_autocorrelation_and_correlation_time_of_known_series():
    rng = np.random.default_rng(0)
    white = rng.standard_normal(4000)
    ar = np.zeros(4000)
    for i in range(1, 4000):
        ar[i] = 0.9 * ar[i - 1] + rng.standard_normal()
    a_white, a_ar = ve.autocorrelation(white), ve.autocorrelation(ar)
    assert a_white[0] == pytest.approx(1.0) and abs(a_white[1]) < 0.06
    assert a_ar[1] == pytest.approx(0.9, abs=0.04)
    assert ve.correlation_time(a_white, 0.05) == pytest.approx(0.05)
    assert 0.35 < ve.correlation_time(a_ar, 0.05) < 0.65  # -dt / ln(0.9) is 0.47 s
    assert np.isnan(ve.autocorrelation(np.ones(10))).all() and np.isnan(ve.autocorrelation(white[:10])).all()
    assert ve.correlation_time(np.ones(5), 0.1) == pytest.approx(0.5)


def test_measure_runs_the_pairs_and_summary_reads_them(seq_dir, monkeypatch):
    _exact(monkeypatch, seq_dir, noise_deg=0.0)
    rows = ve.measure(seq_dir, gaps=(1, 4))
    assert {int(r["gap_frames"]) for r in rows} == {1, 4}
    assert max(abs(float(r["rot_x_deg"])) for r in rows) < 1e-6
    s = ve.summary(rows, 1, 0.05)
    assert s["pairs"] > 100 and s["rot_rms_deg"] < 1e-6
    assert "Gap, frames" in ve.summary_markdown(rows)


def test_measure_refuses_too_few_frames(seq_dir):
    with pytest.raises(ValueError, match="not enough"):
        ve.measure(seq_dir, gaps=(500,))


def test_measure_skips_pairs_the_front_end_could_not_solve(seq_dir, monkeypatch):
    monkeypatch.setattr(ve, "relative_poses_along", lambda images, gaps, cam, seed=0: dict.fromkeys(gaps))
    assert ve.measure(seq_dir, gaps=(1,)) == []


def test_csv_round_trip_cli_and_the_error_path(seq_dir, monkeypatch, tmp_path, capsys):
    _exact(monkeypatch, seq_dir, noise_deg=0.5, seed=1)
    rows = ve.measure(seq_dir, gaps=(1,))
    out = tmp_path / "vo.csv"
    ve.write_csv(out, rows)
    assert len(ve.read_csv(out)) == len(rows)
    assert euroc_main(["vo", "--from-csv", str(out), "--markdown"]) == 0
    assert "Rotation correlation time" in capsys.readouterr().out
    assert ve.main(["--sequence", "MH_01_easy", "--root", str(tmp_path / "nowhere")]) == 1


def test_a_pair_where_the_camera_did_not_move_is_skipped():
    still = _line_trajectory(np.eye(3), np.zeros(3))
    cam = vf.Camera(450, 450, 32, 24, (0, 0, 0, 0), np.eye(4), 64, 48)
    est = vf.PairResult(R=np.eye(3), t_dir=np.array([1.0, 0.0, 0.0]), tracked=10, inliers=9)
    assert ve.pair_row("s", 1, 0.0, 1.0, est, still, cam) is None
