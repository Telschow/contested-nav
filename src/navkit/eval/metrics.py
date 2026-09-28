"""Trajectory evaluation metrics.

Definitions follow the conventions established by Sturm et al., "A Benchmark for
the Evaluation of RGB-D SLAM Systems" (IROS 2012) and by the TUM VI benchmark
(Schubert et al., IROS 2018), because those are the numbers a reader will
compare against. They are implemented here from the published definitions.

Absolute pose error (APE / "ATE")
    For every estimate pose the reference trajectory is interpolated at the
    estimate's timestamp and the position difference is taken. APE is the norm
    of that difference. RMSE over all poses is the headline number. The
    alignment mode is reported alongside every value, because "ATE = 0.09 m"
    is meaningless without it.

Relative pose error (RPE)
    Error in the relative transformation between two poses separated by a fixed
    time ``delta`` seconds or a fixed travelled distance ``delta`` metres. The
    translation error is ``||(Q_i^-1 Q_j) - (P_i^-1 P_j)||`` on the
    translational part; the rotation error is the geodesic angle
    ``angle(R_i^T R_j)``.

Drift
    Reported two ways, because they answer different questions:

    ``drift_pct_path_length``
        ``100 * APE(t) / path_length_gt(t)``. "How much error per metre
        travelled" -- comparable across sequences of different size.
    ``drift_pct_time``
        ``100 * APE(t) / t``. "How much error per second" -- what a
        navigation system actually cares about for a time-to-fix estimate.

Cross-check
-----------
``tests/test_trajectory_io.py`` contains a TUM VI regression test that reads
the published room1/512/16 estimate and ground truth and asserts ATE against
the benchmark's own figure. That is a real validation of this implementation
against a third party, not a self-consistency check.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import numpy as np

from ..geometry.align import Alignment, align_subset, umeyama
from ..types import Trajectory, interpolate_trajectory, rot_log_batch


@dataclass
class ErrorStats:
    """Summary of a set of scalar errors."""

    rmse: float
    mean: float
    median: float
    std: float
    min: float
    max: float
    count: int

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}


def error_stats(err: Sequence[float] | np.ndarray) -> ErrorStats:
    """RMSE / mean / median / std / min / max of a scalar error sequence."""
    e = np.asarray(err, dtype=float).reshape(-1)
    if e.size == 0:
        nan = float("nan")
        return ErrorStats(nan, nan, nan, nan, nan, nan, 0)
    return ErrorStats(
        rmse=float(np.sqrt(np.mean(e**2))),
        mean=float(np.mean(e)),
        median=float(np.median(e)),
        std=float(np.std(e)),
        min=float(np.min(e)),
        max=float(np.max(e)),
        count=int(e.size),
    )


def percentiles(err: Sequence[float] | np.ndarray, qs: Sequence[float] = (0.5, 0.95, 0.99)) -> dict[str, float]:
    e = np.asarray(err, dtype=float).reshape(-1)
    if e.size == 0:
        return {f"p{int(q * 100)}": float("nan") for q in qs}
    return {f"p{int(round(q * 100))}": float(np.percentile(e, q * 100.0)) for q in qs}


def associate_nearest(
    estimate: Trajectory, reference: Trajectory, max_difference_s: float = 0.02
) -> tuple[np.ndarray, np.ndarray]:
    """Greedy nearest-timestamp association, the TUM benchmark convention.

    For every estimate pose the closest reference pose within
    ``max_difference_s`` is selected. This is what ``evaluate_ate.py`` from the
    TUM RGB-D and TUM VI benchmark tools do, and reproducing it is what allows
    a direct comparison with published numbers.

    Returns index arrays into ``estimate`` and ``reference``. An estimate pose
    may be associated with the same reference pose as its neighbour; that is
    the behaviour of the original tool and is kept for comparability.

    Why not interpolate? Interpolating the reference at the estimate's
    timestamp is the better estimator when the reference is smooth and sampled
    densely, and it is the default here. Association is offered because it is
    what published numbers are computed with, and because it never invents a
    reference pose. See ``docs/metrics.md``.
    """
    if max_difference_s <= 0:
        raise ValueError(f"max_difference_s must be > 0, got {max_difference_s}")
    est_idx: list[int] = []
    ref_idx: list[int] = []
    rt = reference.t
    for k, tk in enumerate(estimate.t):
        pos = int(np.searchsorted(rt, tk))
        best, best_diff = -1, max_difference_s
        for j in (pos - 1, pos):
            if 0 <= j < rt.size:
                diff = abs(float(rt[j]) - float(tk))
                if diff < best_diff:
                    best, best_diff = j, diff
        if best >= 0:
            est_idx.append(k)
            ref_idx.append(best)
    if not est_idx:
        raise ValueError(
            f"no reference pose within {max_difference_s}s of any estimate pose; "
            "check the timestamp units of both files"
        )
    return np.asarray(est_idx, dtype=int), np.asarray(ref_idx, dtype=int)


def _reference_at(estimate: Trajectory, reference: Trajectory, association: str) -> Trajectory:
    """Build the reference stream that errors are measured against."""
    if association == "interpolate":
        return interpolate_trajectory(reference, estimate.t)
    if association == "nearest":
        i, j = associate_nearest(estimate, reference)
        return Trajectory(
            t=estimate.t[i],
            poses=reference.poses[j],
            name=f"{reference.name}@assoc",
            metadata={"index": i.tolist(), "reference_index": j.tolist()},
        )
    raise ValueError(f"unknown association {association!r}; use 'interpolate' or 'nearest'")


# ------------------------------------------------------------------- APE ---


def align_trajectory(
    estimate: Trajectory,
    reference: Trajectory,
    mode: str = "rigid",
    fractions: tuple[float, float] = (0.0, 1.0),
    association: str = "interpolate",
) -> tuple[Alignment, np.ndarray, np.ndarray]:
    """Fit an alignment and apply it, returning the aligned estimate and mask.

    Only the *positions* are used to fit the transform. Fitting on 6-DoF poses
    would require a pose-graph solve for a result that, for a rigid sensor
    platform, is identical to the least-squares rigid fit on positions; that is
    the standard choice in the SLAM evaluation literature and it is stated here
    so the number can be reproduced.
    """
    ref = _reference_at(estimate, reference, association)
    if association == "interpolate":
        mask = np.ones(len(estimate), dtype=bool)
    else:
        mask = np.asarray(ref.metadata["index"], dtype=int)
    if fractions == (0.0, 1.0):
        A = umeyama(estimate.positions[mask], ref.positions, with_scale=(mode == "similarity"), kind=mode)
    else:
        A, sub = align_subset(estimate.positions[mask], ref.positions, fractions=fractions, kind=mode)
        mask = mask.copy()
        mask[np.flatnonzero(mask)[sub]] = True
    return A, ref, mask


@dataclass
class AteResult:
    """Absolute trajectory error under a specific alignment."""

    alignment: str
    association: str
    fractions: tuple[float, float]
    position_m: ErrorStats
    rotation_deg: ErrorStats
    position_percentiles_m: dict[str, float]
    per_pose_position_m: np.ndarray = field(repr=False)
    per_pose_rotation_deg: np.ndarray = field(repr=False)
    t: np.ndarray = field(repr=False)
    aligned_positions: np.ndarray = field(repr=False)
    reference_positions: np.ndarray = field(repr=False)
    scale: float = 1.0
    associated_poses: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "alignment": self.alignment,
            "association": self.association,
            "fractions": list(self.fractions),
            "scale": self.scale,
            "associated_poses": self.associated_poses,
            "position_m": self.position_m.as_dict(),
            "position_percentiles_m": self.position_percentiles_m,
            "rotation_deg": self.rotation_deg.as_dict(),
        }


def absolute_error(
    estimate: Trajectory,
    reference: Trajectory,
    alignment: str = "rigid",
    fractions: tuple[float, float] = (0.0, 1.0),
    association: str = "interpolate",
) -> AteResult:
    """ATE for one alignment choice.

    ``alignment="none"`` reports the raw error with no transform applied, which
    is the honest number when the estimate's frame is already the reference
    frame (the case for a GNSS-aided filter). ``"rigid"`` and ``"similarity"`` fit and
    apply a similarity transform first.
    """
    if alignment == "none":
        ref = _reference_at(estimate, reference, association)
        if association == "nearest":
            keep = np.asarray(ref.metadata["index"], dtype=int)
            est = Trajectory(
                t=estimate.t[keep],
                poses=estimate.poses[keep],
                name=estimate.name,
                metadata=estimate.metadata,
            )
        else:
            est = estimate
        est_pos = est.positions
        A = Alignment(scale=1.0, R=np.eye(3), t=np.zeros(3), kind="none")
    else:
        A, ref, _ = align_trajectory(
            estimate, reference, mode=alignment, fractions=fractions, association=association
        )
        if association == "nearest":
            keep = np.asarray(ref.metadata["index"], dtype=int)
            est_pos = A.apply(estimate.positions[keep])
        else:
            est_pos = A.apply(estimate.positions)

    est_traj = estimate
    if association == "nearest":
        keep = np.asarray(ref.metadata["index"], dtype=int)
        est_traj = Trajectory(
            t=estimate.t[keep], poses=estimate.poses[keep], name=estimate.name,
            metadata=estimate.metadata,
        )
    est_rot = est_traj.rotations
    d_pos = est_pos - ref.positions
    pos_err = np.linalg.norm(d_pos, axis=1)
    rot_err_deg = np.rad2deg(
        np.array(
            [np.linalg.norm(rot_log_batch(R @ Rt.T)) for R, Rt in zip(est_rot, ref.rotations)]
        )
    )
    return AteResult(
        alignment=alignment,
        association=association,
        fractions=fractions,
        position_m=error_stats(pos_err),
        rotation_deg=error_stats(rot_err_deg),
        position_percentiles_m=percentiles(pos_err),
        per_pose_position_m=pos_err,
        per_pose_rotation_deg=rot_err_deg,
        t=est_traj.t.copy(),
        aligned_positions=est_pos,
        reference_positions=ref.positions,
        scale=A.scale,
        associated_poses=len(est_traj),
    )


def ate_bundle(
    estimate: Trajectory, reference: Trajectory, association: str = "interpolate"
) -> dict[str, AteResult]:
    """The four ATE variants reported for every run.

    ``none``          -- no alignment, raw error in the estimator's own frame.
    ``rigid``           -- rigid alignment over the whole sequence.
    ``rigid_start``     -- rigid alignment fitted on the first 20% only. The
                         strictest of the four, and the one that cannot absorb
                         accumulated drift into the fit. This mirrors the TUM VI
                         ``ate_start`` metric.
    ``similarity``      -- alignment with a free scale, for scale-free estimates.

    The ``rigid_start`` result is fitted with ``kind="rigid"`` but is labelled
    ``"rigid_start"``, because an ATE reported as "rigid" while having been
    fitted on 20% of the sequence is a different number under the same name.
    """
    start = absolute_error(
        estimate, reference, alignment="rigid", fractions=(0.0, 0.2), association=association
    )
    start.alignment = "rigid_start"
    return {
        "none": absolute_error(estimate, reference, alignment="none", association=association),
        "rigid": absolute_error(estimate, reference, alignment="rigid", association=association),
        "rigid_start": start,
        "similarity": absolute_error(estimate, reference, alignment="similarity", association=association),
    }


# ------------------------------------------------------------------- RPE ---


@dataclass
class RpeResult:
    delta: str
    value: float
    delta_s: float
    translation_m: ErrorStats
    rotation_deg: ErrorStats
    pairs: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "delta": self.delta,
            "delta_s": self.delta_s,
            "translation_m": self.translation_m.as_dict(),
            "rotation_deg": self.rotation_deg.as_dict(),
        }


def relative_pose_error(
    estimate: Trajectory,
    reference: Trajectory,
    delta: float = 1.0,
    mode: str = "time",
    association: str = "interpolate",
) -> RpeResult:
    """RPE at a fixed time offset or a fixed travelled distance.

    ``mode="time"`` pairs every pose with the one ``delta`` seconds later.
    ``mode="distance"`` pairs every pose with the first pose at least ``delta``
    metres further along the reference path.

    A single global alignment cannot be applied to a relative error: the
    definition is invariant to it, and the error that matters is the change in
    relative pose. Poses beyond the end of the sequence are excluded rather
    than clamped, because clamping would compare a pose with itself.
    """
    ref = _reference_at(estimate, reference, association)
    est = estimate
    if association == "nearest":
        keep = np.asarray(ref.metadata["index"], dtype=int)
        est = Trajectory(
            t=estimate.t[keep], poses=estimate.poses[keep], name=estimate.name,
            metadata=estimate.metadata,
        )
    t = est.t

    if mode == "time":
        if delta <= 0:
            raise ValueError(f"delta must be > 0 for mode='time', got {delta}")
        idx = np.searchsorted(t, t + delta, side="left")
        valid = idx < len(t)
        i = np.arange(len(t))[valid]
        j = idx[valid]
        delta_desc = f"{delta:g}s"
    elif mode == "distance":
        if delta <= 0:
            raise ValueError(f"delta must be > 0 for mode='distance', got {delta}")
        cum = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(ref.positions, axis=0), axis=1))]
        )
        j = np.searchsorted(cum, cum + delta, side="left")
        i = np.arange(len(t))
        valid = j < len(t)
        i = i[valid]
        j = j[valid]
        delta_desc = f"{delta:g}m"
    else:
        raise ValueError(f"unknown RPE mode {mode!r}; use 'time' or 'distance'")

    if i.size == 0:
        return RpeResult(
            delta=delta_desc, value=delta, delta_s=delta,
            translation_m=error_stats([]), rotation_deg=error_stats([]), pairs=0,
        )

    # E = (Q_i^-1 Q_j)^-1 (P_i^-1 P_j): the error of the relative motion, in
    # the frame of pose i. This is the Sturm et al. (2012) definition.
    Q_i, Q_j = est.poses[i], est.poses[j]
    P_i, P_j = ref.poses[i], ref.poses[j]
    E = np.linalg.inv(np.linalg.inv(Q_i) @ Q_j) @ (np.linalg.inv(P_i) @ P_j)
    trans = np.linalg.norm(E[:, :3, 3], axis=1)
    rot = np.rad2deg(np.linalg.norm(rot_log_batch(E[:, :3, :3]), axis=1))
    tr = error_stats(trans)
    return RpeResult(
        delta=delta_desc,
        value=delta,
        delta_s=delta,
        translation_m=tr,
        rotation_deg=error_stats(rot),
        pairs=int(i.size),
    )


# ----------------------------------------------------------------- drift ---


@dataclass
class DriftResult:
    """Error growth relative to travelled distance and elapsed time."""

    max_drift_pct_path: float
    final_drift_pct_path: float
    max_drift_pct_time: float
    final_drift_pct_time: float
    total_path_length_m: float
    duration_s: float
    growth: DriftGrowth | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {
            "max_drift_pct_path_length": self.max_drift_pct_path,
            "final_drift_pct_path_length": self.final_drift_pct_path,
            "max_drift_pct_time": self.max_drift_pct_time,
            "final_drift_pct_time": self.final_drift_pct_time,
            "total_path_length_m": self.total_path_length_m,
            "duration_s": self.duration_s,
        }
        if self.growth is not None:
            d["growth"] = self.growth.as_dict()
        return d


@dataclass
class DriftGrowth:
    """Least-squares slope of error against time, in metres per second.

    Reported over the second half of the sequence only. A single slope over the
    whole run is dominated by the initial convergence transient, which says
    nothing about steady-state drift.
    """

    slope_m_per_s: float
    intercept_m: float
    r_squared: float
    window_s: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "slope_m_per_s": self.slope_m_per_s,
            "intercept_m": self.intercept_m,
            "r_squared": self.r_squared,
            "window_s": list(self.window_s),
        }


def drift(
    ate: AteResult,
    reference: Trajectory,
    fit_growth: bool = True,
) -> DriftResult:
    """Drift statistics from an ATE result and the reference path.

    Uses the ``rigid_start``-style error curve: the alignment must have been
    fitted on the start of the sequence, otherwise "drift" measures the
    alignment, not the estimator. The caller passes the ATE variant it wants.
    """
    ref = interpolate_trajectory(reference, ate.t)
    t = ate.t - ate.t[0]
    cum = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(ref.positions, axis=0), axis=1))]
    )
    err = ate.per_pose_position_m
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_path = np.where(cum > 1e-6, 100.0 * err / np.maximum(cum, 1e-6), 0.0)
        pct_time = np.where(t > 1e-6, 100.0 * err / np.maximum(t, 1e-6), 0.0)
    growth = None
    if fit_growth and len(t) >= 10:
        m = t >= 0.5 * t[-1]
        if m.sum() >= 5:
            slope, intercept = np.polyfit(t[m], err[m], 1)
            pred = slope * t[m] + intercept
            ss_res = float(np.sum((err[m] - pred) ** 2))
            ss_tot = float(np.sum((err[m] - err[m].mean()) ** 2))
            growth = DriftGrowth(
                slope_m_per_s=float(slope),
                intercept_m=float(intercept),
                r_squared=float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
                window_s=(float(t[m][0]), float(t[m][-1])),
            )
    return DriftResult(
        max_drift_pct_path=float(np.max(pct_path)),
        final_drift_pct_path=float(pct_path[-1]),
        max_drift_pct_time=float(np.max(pct_time)),
        final_drift_pct_time=float(pct_time[-1]),
        total_path_length_m=float(cum[-1]),
        duration_s=float(t[-1]),
        growth=growth,
    )


# ----------------------------------------------------- recovery / outages ---


def time_to_recovery(
    t: np.ndarray,
    error: np.ndarray,
    window: tuple[float, float],
    threshold_m: float,
    hold_s: float = 1.0,
) -> float | None:
    """Seconds from the end of ``window`` until the error settles below a threshold.

    ``window`` is ``(start_s, end_s)`` in trajectory time. ``hold_s`` requires
    the error to stay below the threshold for that long, so a single lucky
    sample does not count as recovery. Returns ``None`` if it never recovers.
    """
    lo, hi = window
    t = np.asarray(t, float)
    error = np.asarray(error, float)
    m = t >= hi
    if not m.any():
        return None
    tt, ee = t[m], error[m]
    below = ee <= threshold_m
    if not below.any():
        return None
    dt = float(np.median(np.diff(tt))) if len(tt) > 1 else 0.0
    need = max(1, int(round(hold_s / dt))) if dt > 0 else 1
    run = 0
    for i, b in enumerate(below):
        run = run + 1 if b else 0
        if run >= need:
            end_idx = i
            start_idx = end_idx - need + 1
            return float(tt[start_idx] - hi)
    return None


def outage_summary(
    t: np.ndarray,
    error: np.ndarray,
    outages: list[tuple[float, float]],
    baseline_error_m: float,
) -> list[dict[str, Any]]:
    """Per-outage error growth, using ``baseline_error_m`` as the reference.

    For each outage window the report contains the error at the moment the
    outage begins, the peak error inside it, the error when it ends, and the
    growth across the window. Growth measured against the pre-outage error
    rather than against zero is what makes a GNSS outage interpretable: an
    outage of a well-localised system should show a *rise* from a small
    baseline, not a large absolute number.
    """
    out: list[dict[str, Any]] = []
    t = np.asarray(t, float)
    error = np.asarray(error, float)
    for start, end in outages:
        before = error[t < start]
        inside = (t >= start) & (t < end)
        after = error[t >= end]
        base = float(before[-1]) if before.size else float(baseline_error_m)
        out.append(
            {
                "start_s": float(start),
                "end_s": float(end),
                "duration_s": float(end - start),
                "error_before_m": float(before[-1]) if before.size else float("nan"),
                "error_peak_m": float(np.max(error[inside])) if inside.any() else float("nan"),
                "error_after_m": float(after[0]) if after.size else float("nan"),
                "growth_m": float(np.max(error[inside]) - base) if inside.any() else float("nan"),
                "samples_inside": int(inside.sum()),
            }
        )
    return out


def pose_errors_with_alignment(
    estimate: Trajectory, reference: Trajectory, alignment: str = "rigid_start"
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convenience: timestamps, aligned positions and per-pose errors."""
    res = absolute_error(estimate, reference, alignment=alignment)
    return res.t, res.aligned_positions, res.per_pose_position_m
