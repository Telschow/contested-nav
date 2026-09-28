"""Trajectory alignment (Umeyama) for consistent error reporting.

Two alignments are supported and the difference matters when reading results:

``rigid``
    Rigid transform, scale fixed to 1. Use this when the scale of the estimate
    is physically meaningful (metric odometry, GNSS-aided fusion). Any scale
    error shows up in the reported error instead of being absorbed.

``sim3``
    Rigid transform plus a global scale. Use this to separate *shape* error
    from *scale* error, or to compare monocular estimates that have an
    arbitrary gauge.

Both follow Umeyama (1991) and use the same SVD-based construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rigid import make_pose


@dataclass(frozen=True)
class Alignment:
    """A similarity transform mapping an estimate onto a reference."""

    scale: float
    R: np.ndarray  # (3, 3)
    t: np.ndarray  # (3,)
    kind: str  # "rigid" or "similarity"

    @property
    def T(self) -> np.ndarray:
        """4x4 matrix. The scale is kept out of the matrix on purpose."""
        return make_pose(self.R, self.t)

    def apply(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        return self.scale * (pts @ self.R.T) + self.t


def umeyama(
    source: np.ndarray,
    target: np.ndarray,
    with_scale: bool = True,
    kind: str = "similarity",
) -> Alignment:
    """Least-squares similarity transform ``target ~= scale * source @ R.T + t``.

    ``kind`` selects the model: ``"rigid"`` ignores ``with_scale`` and pins
    ``scale`` to 1.0.
    """
    src = np.asarray(source, dtype=float).reshape(-1, 3)
    dst = np.asarray(target, dtype=float).reshape(-1, 3)
    if src.shape != dst.shape:
        raise ValueError(f"shape mismatch: {src.shape} vs {dst.shape}")
    if src.shape[0] < 3:
        raise ValueError("need at least 3 points to fit a similarity transform")

    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    S = src - mu_s
    D = dst - mu_d
    cov = (D.T @ S) / src.shape[0]
    U, sv, Vt = np.linalg.svd(cov)

    Dg = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0.0:
        # Reflection in the least-squares solution: flip the smallest singular
        # direction so that the result is a proper rotation.
        Dg[2, 2] = -1.0
    R = U @ Dg @ Vt

    if kind == "rigid" or not with_scale:
        return Alignment(scale=1.0, R=R, t=mu_d - R @ mu_s, kind="rigid")

    var_s = float((S**2).sum() / src.shape[0])
    if var_s < 1e-18:
        # Degenerate (a single repeated point) -- no scale is observable.
        return Alignment(scale=1.0, R=R, t=mu_d - R @ mu_s, kind="similarity")
    scale = float(np.trace(np.diag(sv) @ Dg) / var_s)
    return Alignment(scale=scale, R=R, t=mu_d - scale * (R @ mu_s), kind="similarity")


def align_subset(
    source: np.ndarray,
    target: np.ndarray,
    fractions: tuple[float, float] = (0.0, 0.2),
    kind: str = "rigid",
) -> tuple[Alignment, np.ndarray]:
    """Fit the alignment on a leading fraction of the trajectory.

    The TUM VI benchmark reports both an "ate_start" (fit on the first 20% and
    evaluate everywhere) and a full "ate" number. Fitting only on the start is
    the stricter, more informative choice for drift analysis: it cannot hide
    accumulated drift inside the alignment itself. The returned mask marks the
    poses used for fitting.
    """
    src = np.asarray(source, dtype=float).reshape(-1, 3)
    n = src.shape[0]
    lo, hi = fractions
    i0 = int(np.floor(lo * n))
    i1 = max(i0 + 3, int(np.ceil(hi * n)))
    i1 = min(i1, n)
    if i1 - i0 < 3:
        i0, i1 = 0, min(n, 3)
    mask = np.zeros(n, dtype=bool)
    mask[i0:i1] = True
    return umeyama(src[mask], target[mask], with_scale=(kind == "similarity"), kind=kind), mask
