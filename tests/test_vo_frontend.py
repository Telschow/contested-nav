"""The two-view front end, tested piece by piece on synthetic data. The real-image check is the study that uses it."""

from __future__ import annotations

import numpy as np
import pytest

from navkit import vo_frontend as vo
from navkit.geometry.rigid import rot_exp

CAM = vo.Camera(
    fx=450.0, fy=450.0, cx=370.0, cy=240.0, dist=(-0.28, 0.07, 0.0002, 0.00002), T_BS=np.eye(4), width=752, height=480
)


def _scene(n=200, seed=0, motion=(0.05, 0.04, 0.02), rot=(0.01, -0.02, 0.015)):
    rng = np.random.default_rng(seed)
    X0 = np.column_stack([rng.uniform(-3, 3, n), rng.uniform(-2, 2, n), rng.uniform(3, 12, n)])
    R = rot_exp(np.array(rot))
    t = np.array(motion)
    X1 = X0 @ R.T + t
    x0 = X0[:, :2] / X0[:, 2:]
    x1 = X1[:, :2] / X1[:, 2:]
    return x0, x1, R, t / np.linalg.norm(t)


def _angle(a, b):
    return float(np.degrees(np.arccos(np.clip(abs(float(a @ b)), 0.0, 1.0))))


def test_distort_and_undistort_are_inverses():
    rng = np.random.default_rng(1)
    x = rng.uniform(-0.6, 0.6, (50, 2))
    assert np.allclose(vo.undistort(vo.distort(x, CAM), CAM), x, atol=1e-7)


def test_eight_point_and_decompose_recover_a_known_motion():
    x0, x1, R, t = _scene()
    E = vo.eight_point(x0, x1)
    assert np.all(vo.sampson(E, x0, x1) < 1e-16)
    Rh, th = vo.decompose(E, x0, x1)
    assert np.linalg.norm(Rh - R) < 1e-6 and _angle(th, t) < 1e-4
    assert th @ t > 0


def test_ransac_survives_outliers_and_noise():
    # A baseline of about 0.6 m against depths of 3 to 12 m: the translation direction needs parallax.
    x0, x1, R, t = _scene(n=300, seed=3, motion=(0.5, 0.4, 0.2))
    rng = np.random.default_rng(5)
    x1 = x1 + rng.normal(0, 0.5 / CAM.fx, x1.shape)
    bad = rng.choice(300, 90, replace=False)
    x1[bad] = rng.uniform(-0.5, 0.5, (90, 2))
    E, inl = vo.essential_ransac(x0, x1, 1.0 / CAM.fx, seed=1)
    Rh, th = vo.decompose(E, x0[inl], x1[inl])
    assert 150 <= inl.sum() <= 215  # 210 true correspondences, each noisy; no outlier should be kept in bulk
    assert np.degrees(np.linalg.norm(vo.rot_log_small(Rh @ R.T))) < 0.3
    assert _angle(th, t) < 3.0


def test_ransac_needs_eight_points():
    with pytest.raises(ValueError):
        vo.essential_ransac(np.zeros((5, 2)), np.zeros((5, 2)), 0.01)


def _texture(h=120, w=160, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.random((h, w)).astype(np.float32)
    for _ in range(3):
        img = (img + np.roll(img, 1, 0) + np.roll(img, -1, 0) + np.roll(img, 1, 1) + np.roll(img, -1, 1)) / 5.0
    return (img - img.min()) / (img.max() - img.min())


def test_corners_are_found_on_texture_and_not_on_a_flat_image():
    assert len(vo.shi_tomasi(_texture(), cell=16, border=8)) > 20
    assert len(vo.shi_tomasi(np.full((120, 160), 0.5, dtype=np.float32), cell=16, border=8)) == 0


def test_corners_are_found_on_a_checkerboard():
    y, x = np.mgrid[0:120, 0:160]
    board = (((x // 20) + (y // 20)) % 2).astype(np.float32)
    pts = vo.shi_tomasi(board, cell=16, border=8)
    assert len(pts) >= 10
    near = [(abs(p[0] / 20 - round(p[0] / 20)) * 20, abs(p[1] / 20 - round(p[1] / 20)) * 20) for p in pts]
    assert np.median([max(a, b) for a, b in near]) < 3.0


def test_lucas_kanade_recovers_a_subpixel_shift():
    img0 = _texture(seed=2)
    h, w = img0.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    shift = np.array([3.2, -1.7])
    img1 = vo.bilinear(img0, xx - shift[0], yy - shift[1]).astype(np.float32)  # content moves by +shift
    pts = vo.shi_tomasi(img0, cell=16, border=16)
    out, ok = vo.track(img0, img1, pts)
    assert ok.sum() > 0.5 * len(pts)
    err = np.linalg.norm((out[ok] - pts[ok]) - shift, axis=1)
    assert np.median(err) < 0.1


def test_tracking_rejects_points_that_leave_the_image():
    img = _texture(seed=4)
    h, w = img.shape
    pts = np.array([[w - 4.0, 50.0], [80.0, 60.0]])
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    moved = vo.bilinear(img, xx - 10.0, yy).astype(np.float32)
    _, ok = vo.track(img, moved, pts)
    assert not ok[0]


def test_relative_pose_from_exact_tracks(monkeypatch):
    x0, x1, R, t = _scene(n=150, seed=7)
    px0, px1 = vo.distort(x0, CAM), vo.distort(x1, CAM)
    monkeypatch.setattr(vo, "shi_tomasi", lambda img: px0)
    monkeypatch.setattr(vo, "track", lambda a, b, p: (px1, np.ones(len(p), dtype=bool)))
    res = vo.relative_pose(np.zeros((480, 752), dtype=np.float32), np.zeros((480, 752), dtype=np.float32), CAM)
    assert res is not None and res.inliers == 150
    Rm, tm = vo.motion_from_pair(res)
    assert np.linalg.norm(Rm - R.T) < 1e-3
    assert _angle(tm, -R.T @ t) < 0.1


def test_relative_pose_gives_none_when_nothing_is_tracked(monkeypatch):
    monkeypatch.setattr(vo, "shi_tomasi", lambda img: np.zeros((5, 2)))
    assert vo.relative_pose(np.zeros((48, 75), dtype=np.float32), np.zeros((48, 75), dtype=np.float32), CAM) is None
    monkeypatch.setattr(vo, "shi_tomasi", lambda img: np.zeros((50, 2)))
    monkeypatch.setattr(vo, "track", lambda a, b, p: (p, np.zeros(len(p), dtype=bool)))
    assert vo.relative_pose(np.zeros((48, 75), dtype=np.float32), np.zeros((48, 75), dtype=np.float32), CAM) is None


def test_camera_is_read_from_a_euroc_sensor_yaml(tmp_path):
    yaml_text = (
        "intrinsics: [458.654, 457.296, 367.215, 248.375]\n"
        "distortion_coefficients: [-0.28340811, 0.07395907, 0.00019359, 1.76187114e-05]\n"
        "resolution: [752, 480]\n"
        "T_BS:\n  cols: 4\n  rows: 4\n  data: [0.0148655429818, -0.999880929698, 0.00414029679422, -0.0216401454975,\n"
        "    0.999557249008, 0.0149672133247, 0.025715529948, -0.064676986768,\n"
        "    -0.0257744366974, 0.00375618835797, 0.999660727178, 0.00981073058949,\n"
        "    0.0, 0.0, 0.0, 1.0]\n"
    )
    path = tmp_path / "sensor.yaml"
    path.write_text(yaml_text)
    cam = vo.camera_from_yaml(path)
    assert cam.fx == pytest.approx(458.654) and cam.width == 752 and cam.T_BS.shape == (4, 4)
    assert cam.T_BS[3].tolist() == [0.0, 0.0, 0.0, 1.0]


def test_a_png_is_read_as_a_single_float_channel(tmp_path):
    import matplotlib.image as mpimg

    path = tmp_path / "a.png"
    mpimg.imsave(str(path), (_texture(24, 32) * 255).astype(np.uint8), cmap="gray")
    img = vo.load_gray(path)
    assert img.shape == (24, 32) and img.min() >= 0.0 and img.max() <= 1.0


def test_a_chain_of_tracks_survives_a_motion_too_large_for_one_step():
    img0 = _texture(seed=6)
    h, w = img0.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    frames = [vo.bilinear(img0, xx - 8.0 * k, yy).astype(np.float32) for k in range(4)]  # 8 px per frame
    pts = vo.shi_tomasi(img0, cell=16, border=40)
    chain = vo.track_chain(frames, pts)
    pos, alive = chain[-1]
    assert alive.sum() > 0.4 * len(pts)
    assert np.median(np.abs((pos[alive, 0] - pts[alive, 0]) - 24.0)) < 0.3


def test_relative_poses_along_a_chain_use_the_points_still_tracked(monkeypatch):
    x0, x1, _R, _t = _scene(n=150, seed=8)
    px0, px1 = vo.distort(x0, CAM), vo.distort(x1, CAM)
    monkeypatch.setattr(vo, "shi_tomasi", lambda img: px0)
    keep = np.arange(150) < 100  # only 100 points survive the second step

    def fake_chain(images, pts, levels=3, fb_tolerance=0.5):
        return [(px1, np.ones(150, dtype=bool)), (px1, keep)]

    monkeypatch.setattr(vo, "track_chain", fake_chain)
    blank = np.zeros((480, 752), dtype=np.float32)
    out = vo.relative_poses_along([blank, blank, blank], (1, 2), CAM)
    assert out[1] is not None and out[2] is not None
    assert out[1].tracked == 150 and out[2].tracked == 100
    with pytest.raises(ValueError):
        vo.relative_poses_along([blank, blank], (1, 5), CAM)
    monkeypatch.setattr(vo, "shi_tomasi", lambda img: np.zeros((3, 2)))
    assert vo.relative_poses_along([blank, blank], (1,), CAM) == {1: None}
