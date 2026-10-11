"""A small two-view visual front end, in NumPy only.

Its purpose is to measure what the errors of a real visual front end look like (size, outliers, and above all how
long they stay correlated), which decides whether the stochastic clone's independence assumption holds
(ADR-0017, ADR-0020).
It is not a visual odometry system, and it makes no claim to match a production one. Its steps are plain and each is
tested on synthetic data: Shi-Tomasi corners, pyramidal Lucas-Kanade tracking with a forward-backward check, a
radial-tangential undistortion, an eight-point essential matrix inside a RANSAC loop, and a cheirality test to pick the
relative pose. The result is a rotation and a translation direction. A monocular pair has no scale.

Convention: ``X1 = R X0 + t`` for a point seen in camera 0 and camera 1, so ``(R, t)`` is the pose of camera 0 in camera
1. The motion of the camera from frame 0 to frame 1 is the inverse, ``T_c0_c1 = [R', -R' t]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
import yaml


@dataclass(frozen=True)
class Camera:
    """Pinhole intrinsics, radial-tangential distortion, and the camera pose in the body frame."""

    fx: float
    fy: float
    cx: float
    cy: float
    dist: tuple[float, float, float, float]  # k1, k2, p1, p2
    T_BS: np.ndarray  # (4, 4) camera (sensor) frame in the body frame
    width: int
    height: int


def camera_from_yaml(path: str | Path) -> Camera:
    """Read an EuRoC ``sensor.yaml`` of a camera."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    fx, fy, cx, cy = (float(v) for v in cfg["intrinsics"])
    k1, k2, p1, p2 = (float(v) for v in cfg["distortion_coefficients"])
    t = cfg["T_BS"]
    T = np.array(t["data"], dtype=float).reshape(int(t["rows"]), int(t["cols"]))
    w, h = (int(v) for v in cfg["resolution"])
    return Camera(fx, fy, cx, cy, (k1, k2, p1, p2), T, w, h)


def load_gray(path: str | Path) -> np.ndarray:
    """A PNG as a float32 image in [0, 1], one channel. Matplotlib reads it; no other image library is used."""
    import matplotlib.image as mpimg

    img = np.asarray(mpimg.imread(str(path)), dtype=np.float32)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    return img


# --------------------------------------------------------------------- geometry


def undistort(px: np.ndarray, cam: Camera, iterations: int = 8) -> np.ndarray:
    """Pixels ``(N, 2)`` to undistorted normalised image coordinates ``(N, 2)``, by fixed-point iteration."""
    k1, k2, p1, p2 = cam.dist
    xd = np.stack([(px[:, 0] - cam.cx) / cam.fx, (px[:, 1] - cam.cy) / cam.fy], axis=1)
    x = xd.copy()
    for _ in range(iterations):
        r2 = (x**2).sum(axis=1)
        radial = 1.0 + k1 * r2 + k2 * r2**2
        dx = 2 * p1 * x[:, 0] * x[:, 1] + p2 * (r2 + 2 * x[:, 0] ** 2)
        dy = p1 * (r2 + 2 * x[:, 1] ** 2) + 2 * p2 * x[:, 0] * x[:, 1]
        x = np.stack([(xd[:, 0] - dx) / radial, (xd[:, 1] - dy) / radial], axis=1)
    return x


def distort(x: np.ndarray, cam: Camera) -> np.ndarray:
    """Normalised coordinates to pixels. The inverse of :func:`undistort`, used by the tests."""
    k1, k2, p1, p2 = cam.dist
    r2 = (x**2).sum(axis=1)
    radial = 1.0 + k1 * r2 + k2 * r2**2
    xd = x[:, 0] * radial + 2 * p1 * x[:, 0] * x[:, 1] + p2 * (r2 + 2 * x[:, 0] ** 2)
    yd = x[:, 1] * radial + p1 * (r2 + 2 * x[:, 1] ** 2) + 2 * p2 * x[:, 0] * x[:, 1]
    return np.stack([xd * cam.fx + cam.cx, yd * cam.fy + cam.cy], axis=1)


def rot_log_small(R: np.ndarray) -> np.ndarray:
    """The rotation vector of ``R`` in radians (angle-axis), by the standard logarithm."""
    cos = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    angle = float(np.arccos(cos))
    if angle < 1e-9:
        return np.zeros(3)
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2.0 * np.sin(angle))
    return axis * angle


def _essential_from_nullvec(e: np.ndarray) -> np.ndarray:
    """Project a 3x3 matrix onto the essential matrices: singular values (1, 1, 0)."""
    u, _, vt = np.linalg.svd(e.reshape(3, 3))
    return u @ np.diag([1.0, 1.0, 0.0]) @ vt


def eight_point(x0: np.ndarray, x1: np.ndarray) -> np.ndarray:
    """Essential matrix from at least eight normalised correspondences, ``x1' E x0 = 0``."""
    a = np.stack(
        [
            x1[:, 0] * x0[:, 0],
            x1[:, 0] * x0[:, 1],
            x1[:, 0],
            x1[:, 1] * x0[:, 0],
            x1[:, 1] * x0[:, 1],
            x1[:, 1],
            x0[:, 0],
            x0[:, 1],
            np.ones(len(x0)),
        ],
        axis=1,
    )
    _, _, vt = np.linalg.svd(a)
    return _essential_from_nullvec(vt[-1])


def sampson(E: np.ndarray, x0: np.ndarray, x1: np.ndarray) -> np.ndarray:
    """Squared Sampson distance of each correspondence to ``E`` (normalised units)."""
    h0 = np.concatenate([x0, np.ones((len(x0), 1))], axis=1)
    h1 = np.concatenate([x1, np.ones((len(x1), 1))], axis=1)
    ex0 = h0 @ E.T
    etx1 = h1 @ E
    num = (h1 * ex0).sum(axis=1) ** 2
    den = ex0[:, 0] ** 2 + ex0[:, 1] ** 2 + etx1[:, 0] ** 2 + etx1[:, 1] ** 2
    return num / np.maximum(den, 1e-18)


def essential_ransac(
    x0: np.ndarray, x1: np.ndarray, threshold: float, iterations: int = 200, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Essential matrix and inlier mask by RANSAC over eight-point models. ``threshold`` is in normalised units."""
    n = len(x0)
    if n < 8:
        raise ValueError("need at least eight correspondences")
    rng = np.random.default_rng(seed)
    best_e, best_in, best_count = None, None, -1
    for _ in range(iterations):
        idx = rng.choice(n, size=8, replace=False)
        try:
            e = eight_point(x0[idx], x1[idx])
        except np.linalg.LinAlgError:  # pragma: no cover - a degenerate sample
            continue
        inl = sampson(e, x0, x1) < threshold**2
        if inl.sum() > best_count:
            best_e, best_in, best_count = e, inl, int(inl.sum())
    if best_e is None or best_in is None or best_count < 8:
        raise ValueError("RANSAC found no model with eight inliers")
    # Local optimisation with a shrinking threshold: refit on everything inside 4x, 3x, 2x and then 1x the threshold. A
    # model from eight noisy points is poor, and fitting on a wide band first is what pulls it onto the true geometry.
    model, inliers = best_e, best_in
    for mult in (4.0, 3.0, 2.0, 1.5, 1.0, 1.0):
        band = sampson(model, x0, x1) < (mult * threshold) ** 2
        if band.sum() < 8:
            break
        model = eight_point(x0[band], x1[band])
        inliers = sampson(model, x0, x1) < threshold**2
    if inliers.sum() < 8:
        return best_e, best_in
    return model, inliers


def decompose(E: np.ndarray, x0: np.ndarray, x1: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(R, t)`` with ``X1 = R X0 + t`` and ``|t| = 1``, chosen by the number of points in front of both cameras."""
    u, _, vt = np.linalg.svd(E)
    if np.linalg.det(u) < 0:
        u[:, -1] *= -1
    if np.linalg.det(vt) < 0:
        vt[-1] *= -1
    w = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    best = (-1, np.eye(3), np.array([1.0, 0.0, 0.0]))
    for r in (u @ w @ vt, u @ w.T @ vt):
        for t in (u[:, 2], -u[:, 2]):
            count = _in_front(r, t, x0, x1)
            if count > best[0]:
                best = (count, r, t)
    return best[1], best[2]


def _in_front(R: np.ndarray, t: np.ndarray, x0: np.ndarray, x1: np.ndarray) -> int:
    """Points with positive depth in both cameras, by linear triangulation of each correspondence."""
    h0 = np.concatenate([x0, np.ones((len(x0), 1))], axis=1)
    h1 = np.concatenate([x1, np.ones((len(x1), 1))], axis=1)
    # depth d0 along h0 and d1 along h1: d1 h1 = R (d0 h0) + t  ->  least squares for (d0, d1)
    rh0 = h0 @ R.T
    a = np.stack([rh0, -h1], axis=2)  # (N, 3, 2)
    ata = np.einsum("nij,nik->njk", a, a)
    atb = np.einsum("nij,i->nj", a, -t)
    d = np.linalg.solve(ata + 1e-12 * np.eye(2), atb[..., None])[..., 0]
    return int(((d[:, 0] > 0) & (d[:, 1] > 0)).sum())


# --------------------------------------------------------------------- images


def pyramid(img: np.ndarray, levels: int) -> list[np.ndarray]:
    """A Gaussian-like pyramid by 2x2 averaging."""
    out = [img]
    for _ in range(levels - 1):
        a = out[-1]
        h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
        out.append(0.25 * (a[0:h:2, 0:w:2] + a[1:h:2, 0:w:2] + a[0:h:2, 1:w:2] + a[1:h:2, 1:w:2]))
    return out


def _box(a: np.ndarray, r: int) -> np.ndarray:
    """Sum over a (2r+1)^2 window with zero padding, by two cumulative sums."""
    k = 2 * r + 1
    p = np.pad(a, r + 1, mode="constant")
    c = p.cumsum(axis=0).cumsum(axis=1)
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _gradients(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gx = np.zeros_like(img)
    gy = np.zeros_like(img)
    gx[:, 1:-1] = 0.5 * (img[:, 2:] - img[:, :-2])
    gy[1:-1, :] = 0.5 * (img[2:, :] - img[:-2, :])
    return gx, gy


def shi_tomasi(
    img: np.ndarray, max_corners: int = 400, cell: int = 24, border: int = 20, min_quality: float = 0.01
) -> np.ndarray:
    """Corners ``(N, 2)`` as ``(x, y)`` pixels: the best structure-tensor minimum eigenvalue in each grid cell."""
    gx, gy = _gradients(img)
    sxx, syy, sxy = _box(gx * gx, 2), _box(gy * gy, 2), _box(gx * gy, 2)
    lam = 0.5 * (sxx + syy - np.sqrt((sxx - syy) ** 2 + 4 * sxy**2))
    lam[:border, :] = 0
    lam[-border:, :] = 0
    lam[:, :border] = 0
    lam[:, -border:] = 0
    floor = min_quality * float(lam.max())
    pts: list[tuple[float, float, float]] = []
    h, w = lam.shape
    for y0 in range(0, h, cell):
        for x0 in range(0, w, cell):
            block = lam[y0 : y0 + cell, x0 : x0 + cell]
            k = int(np.argmax(block))
            v = float(block.flat[k])
            if v > floor:
                yy, xx = divmod(k, block.shape[1])
                pts.append((float(x0 + xx), float(y0 + yy), v))
    pts.sort(key=lambda p: -p[2])
    return np.array([(p[0], p[1]) for p in pts[:max_corners]], dtype=float).reshape(-1, 2)


def bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Sample ``img`` at float coordinates (any shape). Coordinates outside the image are clamped to its edge."""
    h, w = img.shape
    x = np.clip(x, 0.0, w - 1.001)
    y = np.clip(y, 0.0, h - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    return (
        img[y0, x0] * (1 - fx) * (1 - fy)
        + img[y0, x0 + 1] * fx * (1 - fy)
        + img[y0 + 1, x0] * (1 - fx) * fy
        + img[y0 + 1, x0 + 1] * fx * fy
    )


def lucas_kanade(
    pyr0: list[np.ndarray],
    pyr1: list[np.ndarray],
    pts: np.ndarray,
    win: int = 7,
    iterations: int = 15,
    min_det: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Pyramidal Lucas-Kanade from ``pyr0`` to ``pyr1``. Returns the tracked points and a mask of usable tracks."""
    n = len(pts)
    r = win // 2
    off = np.arange(-r, r + 1, dtype=float)
    ox, oy = np.meshgrid(off, off)
    flow = np.zeros((n, 2))
    ok = np.ones(n, dtype=bool)
    for lvl in range(len(pyr0) - 1, -1, -1):
        a0, a1 = pyr0[lvl], pyr1[lvl]
        gx, gy = _gradients(a0)
        scale = 2.0**lvl
        p = pts / scale
        px = p[:, 0, None, None] + ox[None]
        py = p[:, 1, None, None] + oy[None]
        t0 = bilinear(a0, px, py)
        ix, iy = bilinear(gx, px, py), bilinear(gy, px, py)
        gxx, gyy, gxy = (ix * ix).sum((1, 2)), (iy * iy).sum((1, 2)), (ix * iy).sum((1, 2))
        det = gxx * gyy - gxy**2
        good = det > min_det
        ok &= good
        det = np.where(good, det, 1.0)
        if lvl < len(pyr0) - 1:
            flow = flow * 2.0
        for _ in range(iterations):
            t1 = bilinear(a1, px + flow[:, 0, None, None], py + flow[:, 1, None, None])
            err = t0 - t1
            bx, by = (ix * err).sum((1, 2)), (iy * err).sum((1, 2))
            dx = (gyy * bx - gxy * by) / det
            dy = (gxx * by - gxy * bx) / det
            flow += np.stack([dx, dy], axis=1)
            if float(np.max(np.abs(np.stack([dx, dy])))) < 0.01:
                break
    return pts + flow, ok


def track(
    img0: np.ndarray, img1: np.ndarray, pts: np.ndarray, levels: int = 3, fb_tolerance: float = 0.5
) -> tuple[np.ndarray, np.ndarray]:
    """Track ``pts`` from ``img0`` to ``img1`` with a forward-backward check. Returns the points and a usable mask."""
    p0, p1 = pyramid(img0, levels), pyramid(img1, levels)
    fwd, ok_f = lucas_kanade(p0, p1, pts)
    back, ok_b = lucas_kanade(p1, p0, fwd)
    h, w = img0.shape
    inside = (fwd[:, 0] > 2) & (fwd[:, 0] < w - 3) & (fwd[:, 1] > 2) & (fwd[:, 1] < h - 3)
    consistent = np.linalg.norm(back - pts, axis=1) < fb_tolerance
    return fwd, ok_f & ok_b & inside & consistent


# ------------------------------------------------------------------ the front end


@dataclass(frozen=True)
class PairResult:
    """The estimate for one pair of frames."""

    R: np.ndarray  # camera 0 in camera 1: X1 = R X0 + t
    t_dir: np.ndarray  # unit vector, same convention
    tracked: int
    inliers: int


def relative_pose(
    img0: np.ndarray, img1: np.ndarray, cam: Camera, seed: int = 0, ransac_px: float = 1.0
) -> PairResult | None:
    """Rotation and translation direction between two frames, or None if too few points survive."""
    corners = shi_tomasi(img0)
    if len(corners) < 20:
        return None
    nxt, ok = track(img0, img1, corners)
    if int(ok.sum()) < 20:
        return None
    x0, x1 = undistort(corners[ok], cam), undistort(nxt[ok], cam)
    try:
        E, inl = essential_ransac(x0, x1, ransac_px / cam.fx, seed=seed)
    except ValueError:
        return None
    R, t = decompose(E, x0[inl], x1[inl])
    return PairResult(R=R, t_dir=t / np.linalg.norm(t), tracked=int(ok.sum()), inliers=int(inl.sum()))


def motion_from_pair(res: PairResult) -> tuple[np.ndarray, np.ndarray]:
    """The camera's own motion ``T_c0_c1``: its rotation and the direction of its translation, in camera 0."""
    return res.R.T, -res.R.T @ res.t_dir


def track_chain(
    images: list[np.ndarray], pts: np.ndarray, levels: int = 3, fb_tolerance: float = 0.5
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Track ``pts`` of ``images[0]`` through every later frame, one step at a time.

    Returns, for each later frame, the positions and the mask of points that survived every step so far. Tracking
    step by step is how a feature tracker copes with the large image motion of a long baseline.
    """
    alive = np.ones(len(pts), dtype=bool)
    cur = pts.copy()
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for prev, nxt in pairwise(images):
        moved, ok = track(prev, nxt, cur, levels=levels, fb_tolerance=fb_tolerance)
        alive &= ok
        cur = np.where(alive[:, None], moved, cur)
        out.append((cur.copy(), alive.copy()))
    return out


def relative_poses_along(
    images: list[np.ndarray], gaps: tuple[int, ...], cam: Camera, seed: int = 0, ransac_px: float = 1.0
) -> dict[int, PairResult | None]:
    """The relative pose from ``images[0]`` to ``images[g]`` for each gap ``g``, from one chain of tracks.

    The corners are found once in ``images[0]``; a gap's pose uses the points still tracked at that frame.
    """
    if max(gaps) >= len(images):
        raise ValueError("need a frame for every gap")
    corners = shi_tomasi(images[0])
    result: dict[int, PairResult | None] = dict.fromkeys(gaps)
    if len(corners) < 20:
        return result
    chain = track_chain(images[: max(gaps) + 1], corners)
    for g in gaps:
        pos, alive = chain[g - 1]
        if int(alive.sum()) < 20:
            continue
        x0, x1 = undistort(corners[alive], cam), undistort(pos[alive], cam)
        try:
            E, inl = essential_ransac(x0, x1, ransac_px / cam.fx, seed=seed)
        except ValueError:
            continue
        R, t = decompose(E, x0[inl], x1[inl])
        result[g] = PairResult(R=R, t_dir=t / np.linalg.norm(t), tracked=int(alive.sum()), inliers=int(inl.sum()))
    return result
