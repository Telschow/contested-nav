"""How wrong, and how correlated, are the errors of a real two-view front end?

ADR-0017 made the stochastic clone calibrated for independent visual errors and found it fails when they are
correlated over about 0.5 to 2 s. ADR-0020 made the question of which a real front end has the next step. This runs
the small front end of :mod:`navkit.vo_frontend` on real camera frames and compares each pair with the ground truth.

A monocular pair has no scale, so the translation error is the error of the direction, expressed as a lateral distance
by multiplying with the true baseline. That is what a front end with a perfect scale would hand the filter. A real
monocular front end would be worse. The ground truth is itself an estimate (millimetres for the Machine Hall).

Frames are paired ``gap`` frames apart. A pair of consecutive 20 Hz frames has a baseline of centimetres, too short for
a translation direction, so larger gaps are measured too.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .euroc_compare import CONFIGS
from .euroc_eval import RunOptions, load_sequence, run_sequence
from .geometry.rigid import rot_exp, rot_log
from .report.page import write_block
from .types import Trajectory, VisionUpdate, interpolate_trajectory
from .vo_frontend import Camera, camera_from_yaml, load_gray, motion_from_pair, relative_poses_along

GAPS = (1, 2, 4, 6, 10)
FRAME_STEP_S = 0.05  # the camera is 20 Hz
#: Below this true baseline the direction of the motion is undefined and the pair is skipped.
MIN_TRUE_BASELINE_M = 1e-3
#: Floors on the noise the filter is told to assume (0.01 degrees, 1 mm). Real windows are well above them.
MIN_ROT_SIGMA_DEG = 0.01
MIN_TRANS_SIGMA_M = 0.001
MAX_LAG = 40
CSV_COLUMNS = (
    "sequence",
    "gap_frames",
    "t_s",
    "dt_s",
    "baseline_m",
    "rot_x_deg",
    "rot_y_deg",
    "rot_z_deg",
    "lat_x_m",
    "lat_y_m",
    "lat_z_m",
    "dir_err_deg",
    "tracked",
    "inliers",
)


def frame_list(seq_dir: Path) -> list[tuple[float, Path]]:
    """``(time on the IMU clock in s, path)`` for every fetched frame, in time order."""
    first_ns = None
    with (seq_dir / "mav0/imu0/data.csv").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip() and not line.startswith("#"):
                first_ns = int(line.split(",")[0])
                break
    if first_ns is None:
        raise ValueError(f"{seq_dir}: the IMU file has no samples")
    out = []
    with (seq_dir / "mav0/cam0/data.csv").open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            ts, name = (c.strip() for c in line.split(",")[:2])
            path = seq_dir / "mav0/cam0/data" / Path(name).name
            if path.is_file():
                out.append(((int(ts) - first_ns) / 1e9, path))
    return sorted(out)


def true_motion(truth: Trajectory, cam: Camera, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
    """The camera's motion from time ``t0`` to ``t1`` in the camera 0 frame: ``(R_c0_c1, t_c0_c1)``."""
    poses = interpolate_trajectory(truth, np.array([t0, t1])).poses
    T0 = poses[0] @ cam.T_BS
    T1 = poses[1] @ cam.T_BS
    rel = np.linalg.inv(T0) @ T1
    return rel[:3, :3], rel[:3, 3]


def pair_row(
    name: str, gap: int, t0: float, t1: float, estimate: Any, truth: Trajectory, cam: Camera
) -> dict[str, Any] | None:
    """The error of one pair against the ground truth, as a CSV row. None when the camera did not move."""
    R_true, t_true = true_motion(truth, cam, t0, t1)
    R_est, u_est = motion_from_pair(estimate)
    baseline = float(np.linalg.norm(t_true))
    if baseline < MIN_TRUE_BASELINE_M:
        return None
    u_true = t_true / baseline
    rot = np.degrees(rot_log(R_true.T @ R_est))
    diff = u_est - u_true
    lateral = baseline * (diff - (diff @ u_true) * u_true)
    angle = float(np.degrees(np.arccos(np.clip(float(u_est @ u_true), -1.0, 1.0))))
    return {
        "sequence": name,
        "gap_frames": gap,
        "t_s": t0,
        "dt_s": t1 - t0,
        "baseline_m": baseline,
        "rot_x_deg": rot[0],
        "rot_y_deg": rot[1],
        "rot_z_deg": rot[2],
        "lat_x_m": lateral[0],
        "lat_y_m": lateral[1],
        "lat_z_m": lateral[2],
        "dir_err_deg": angle,
        "tracked": estimate.tracked,
        "inliers": estimate.inliers,
    }


def measure(
    seq_dir: Path,
    gaps: tuple[int, ...] = GAPS,
    min_baseline_m: float = 0.0,
    window: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Run the front end on every pair ``gap`` frames apart and return one row per pair that produced an estimate."""
    seq = load_sequence(seq_dir.parent, seq_dir.name)
    cam = camera_from_yaml(seq_dir / "mav0/cam0/sensor.yaml")
    frames = frame_list(seq_dir)
    if window is not None:
        frames = [f for f in frames if window[0] <= f[0] <= window[1]]
    if len(frames) < max(gaps) + 2:
        raise ValueError(f"{seq_dir.name}: {len(frames)} frames are not enough for gaps up to {max(gaps)}")
    images: dict[int, np.ndarray] = {}

    def image(i: int) -> np.ndarray:
        if i not in images:
            images[i] = load_gray(frames[i][1])
            images.pop(i - 2 * max(gaps) - 4, None)  # keep memory bounded
        return images[i]

    rows: list[dict[str, Any]] = []
    top = max(gaps)
    for i in range(0, len(frames) - top):
        if frames[i + top][0] - frames[i][0] > top * FRAME_STEP_S * 1.5:
            continue  # the frames are not contiguous here: a gap between two fetched windows
        stack = [image(i + k) for k in range(top + 1)]
        found = relative_poses_along(stack, gaps, cam, seed=i)
        for gap in gaps:
            est = found[gap]
            (t0, _), (t1, _) = frames[i], frames[i + gap]
            if est is None or not (seq.truth.t[0] <= t0 and t1 <= seq.truth.t[-1]):
                continue
            row = pair_row(seq_dir.name, gap, t0, t1, est, seq.truth, cam)
            if row is not None and row["baseline_m"] >= min_baseline_m:
                rows.append(row)
    return rows


# ------------------------------------------------------------------ statistics


def pick_window(
    truth: Trajectory,
    length_s: float = 30.0,
    step_s: float = 5.0,
    earliest_s: float = 30.0,
    margin_s: float = 5.0,
    avoid: tuple[tuple[float, float], ...] = (),
) -> float:
    """The start of the window with the highest median speed, so that the camera moves and a direction exists.

    Starts are on a ``step_s`` grid from ``earliest_s``; the window must end ``margin_s`` before the recording does
    and must not overlap any ``(start, stop)`` in ``avoid``. This is the rule used for the wider measurement, fixed
    before it was run.
    """
    t, p = truth.t, truth.positions
    speed = np.linalg.norm(np.diff(p, axis=0), axis=1) / np.diff(t)
    best: tuple[float, float] | None = None
    start = earliest_s
    while start + length_s <= float(t[-1]) - margin_s:
        if not any(start < b and a < start + length_s for a, b in avoid):
            m = (t[1:] >= start) & (t[1:] < start + length_s)
            if m.any():
                med = float(np.median(speed[m]))
                if best is None or med > best[0]:
                    best = (med, start)
        start += step_s
    if best is None:
        raise ValueError("no window fits")
    return best[1]


def windows(rows: list[dict[str, Any]], max_gap_s: float = 1.0) -> list[tuple[str, float, float]]:
    """``(sequence, start, stop)`` of each run of contiguous pairs in the rows."""
    out: list[tuple[str, float, float]] = []
    for seq in sorted({r["sequence"] for r in rows}):
        ts = sorted({float(r["t_s"]) for r in rows if r["sequence"] == seq and int(r["gap_frames"]) == 1})
        if not ts:
            continue
        start = prev = ts[0]
        for t in ts[1:]:
            if t - prev > max_gap_s:
                out.append((seq, start, prev + FRAME_STEP_S))
                start = t
            prev = t
        out.append((seq, start, prev + FRAME_STEP_S))
    return out


def autocorrelation(x: np.ndarray, max_lag: int = MAX_LAG) -> np.ndarray:
    """Normalised autocorrelation at lags 0 to ``max_lag`` of a series (mean removed)."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    var = float(x @ x)
    if var <= 0.0 or len(x) <= max_lag:
        return np.full(max_lag + 1, np.nan)
    return np.array([float(x[: len(x) - k] @ x[k:]) / var for k in range(max_lag + 1)])


def _mean_acf(series: list[np.ndarray]) -> np.ndarray:
    """The mean autocorrelation of the components, or all NaN when no component is long enough to have one."""
    acfs = np.array([autocorrelation(x) for x in series])
    if np.isnan(acfs).all():
        return np.full(acfs.shape[1], np.nan)
    return np.asarray(np.nanmean(acfs, axis=0))


def correlation_time(acf: np.ndarray, step_s: float) -> float:
    """Seconds until the autocorrelation first falls below 1/e. Capped at the longest lag if it never does.

    NaN when the series was too short to have an autocorrelation.
    """
    if np.isnan(acf).all():
        return float("nan")
    below = np.flatnonzero(acf < np.exp(-1.0))
    return float((below[0] if len(below) else len(acf)) * step_s)


def summary(rows: list[dict[str, Any]], gap: int, step_s: float) -> dict[str, float]:
    """Sizes, outliers and the correlation time of one gap's errors. ``step_s`` is the spacing between pairs."""
    sel = sorted((r for r in rows if int(r["gap_frames"]) == gap), key=lambda r: float(r["t_s"]))
    rot = np.array([[float(r[k]) for k in ("rot_x_deg", "rot_y_deg", "rot_z_deg")] for r in sel])
    lat = np.array([[float(r[k]) for k in ("lat_x_m", "lat_y_m", "lat_z_m")] for r in sel])
    ang = np.array([float(r["dir_err_deg"]) for r in sel])
    base = np.array([float(r["baseline_m"]) for r in sel])
    rot_mag = np.linalg.norm(rot, axis=1)
    lat_mag = np.linalg.norm(lat, axis=1)
    med = float(np.median(rot_mag))
    mad = float(np.median(np.abs(rot_mag - med))) * 1.4826
    acf_rot = _mean_acf([rot[:, k] for k in range(3)])
    acf_lat = _mean_acf([lat[:, k] for k in range(3)])
    return {
        "pairs": float(len(sel)),
        "baseline_m": float(np.median(base)),
        "rot_rms_deg": float(np.sqrt((rot**2).mean())),
        "rot_median_deg": med,
        "lat_rms_m": float(np.sqrt((lat**2).sum(axis=1).mean() / 2.0)),
        "dir_median_deg": float(np.median(ang)),
        "outlier_share": float(np.mean(rot_mag > med + 5.0 * max(mad, 1e-9))),
        "rot_acf_lag1": float(acf_rot[1]),
        "lat_acf_lag1": float(acf_lat[1]),
        "rot_corr_time_s": correlation_time(acf_rot, step_s),
        "lat_corr_time_s": correlation_time(acf_lat, step_s),
        "lat_median_m": float(np.median(lat_mag)),
    }


CLONE_COLUMNS = ("variant", "seed", "nees_mean", "coverage_2sigma", "final_error_m", "max_error_m", "claimed_sigma_m")
#: Variant name -> (vision model or None, correlation time as a multiple of the measured one, assumed-noise scale).
CLONE_VARIANTS: dict[str, tuple[str | None, float, float]] = {
    "IMU only": (None, 0.0, 1.0),
    "anchor, measured errors": ("anchor", 1.0, 1.0),
    "clone, independent errors": ("clone", 0.0, 1.0),
    "clone, measured correlation": ("clone", 1.0, 1.0),
    "clone, measured correlation, noise assumed x4": ("clone", 1.0, 4.0),
}


def replay_stream(
    rows: list[dict[str, Any]], truth: Trajectory, cam: Camera, t_from: float, t_to: float
) -> VisionUpdate:
    """The measured errors of the one-frame pairs, applied to the true relative motion, as a visual stream.

    Each pair's rotation and lateral errors (measured in the camera frame) are added to the true relative camera pose;
    the result is moved to the body frame with the camera-to-body extrinsic, which is the frame the filter's visual
    update works in. The stream carries the real errors, with their correlation and their outliers, in place of
    a Gaussian surrogate. The translation has the true scale (a monocular front end has none).
    """
    sel = sorted(
        (
            r
            for r in rows
            if int(r["gap_frames"]) == 1 and t_from <= float(r["t_s"]) and float(r["t_s"]) + float(r["dt_s"]) <= t_to
        ),
        key=lambda r: float(r["t_s"]),
    )
    if not sel:
        raise ValueError("no one-frame pairs inside the window")
    T_bs = cam.T_BS
    times, R_rel, t_rel = [], [], []
    for r in sel:
        t0, t1 = float(r["t_s"]), float(r["t_s"]) + float(r["dt_s"])
        R_c, t_c = true_motion(truth, cam, t0, t1)
        e_rot = np.radians([float(r["rot_x_deg"]), float(r["rot_y_deg"]), float(r["rot_z_deg"])])
        lateral = np.array([float(r["lat_x_m"]), float(r["lat_y_m"]), float(r["lat_z_m"])])
        T_c = np.eye(4)
        T_c[:3, :3] = R_c @ rot_exp(e_rot)
        T_c[:3, 3] = t_c + lateral
        T_b = T_bs @ T_c @ np.linalg.inv(T_bs)
        times.append(t1)
        R_rel.append(T_b[:3, :3])
        t_rel.append(T_b[:3, 3])
    return VisionUpdate(t=np.array(times), R_rel=np.array(R_rel), t_rel=np.array(t_rel), name="replayed_front_end")


REPLAY_VARIANTS: dict[str, tuple[str, float]] = {
    "replay, anchor": ("anchor", 1.0),
    "replay, clone": ("clone", 1.0),
    "replay, clone, noise assumed x4": ("clone", 4.0),
}


def _origin(seq: Any) -> float:
    """The clock time where ``skip_s = 0`` starts a run: the later of the IMU's and the truth's first sample."""
    return max(float(seq.imu.t[0]), float(seq.truth.t[0]))


def _replay_window(
    seq: Any,
    cam: Camera,
    vo_rows: list[dict[str, Any]],
    start_s: float,
    duration_s: float,
    out_at_s: float,
    scales: tuple[tuple[str, str, float], ...],
    seeds: int,
) -> list[dict[str, Any]]:
    """The clone on one window, fed the measured errors of that window. Scales are ``(name, model, scale)``.

    The run starts exactly at ``start_s`` on the clock the frames use. (``skip_s`` is counted from the later of the
    IMU's and the ground truth's first sample, so the offset is taken off.)
    """
    inside = [
        r
        for r in vo_rows
        if r["sequence"] == seq.name
        and start_s <= float(r["t_s"])
        and float(r["t_s"]) + float(r["dt_s"]) <= start_s + duration_s
    ]
    one = [r for r in inside if int(r["gap_frames"]) == 1]
    stream = replay_stream(one, seq.truth, cam, start_s, start_s + duration_s)
    summ = summary(one, 1, FRAME_STEP_S)
    # A floor, so that a window with (almost) no measured error does not hand the filter a zero measurement noise.
    sigmas = (
        max(round(summ["rot_rms_deg"], 3), MIN_ROT_SIGMA_DEG),
        max(round(summ["lat_rms_m"], 4), MIN_TRANS_SIGMA_M),
    )
    rows: list[dict[str, Any]] = []
    for name, model, scale in scales:
        for seed in range(seeds):
            opts = RunOptions(
                seed=seed,
                skip_s=start_s - _origin(seq),
                duration_s=duration_s,
                outages=((out_at_s, duration_s - out_at_s),),
                vision=model,
                vision_noise_scale=scale,
                vision_sigmas=sigmas,
                **dict(CONFIGS["walk10"]),
            )
            rec = run_sequence(seq, opts, vision_override=stream)
            head = rec["headline"]
            err = np.asarray(rec["error_time_series"]["position_error_m"], dtype=float)
            rows.append(
                {
                    "variant": name,
                    "seed": seed,
                    "nees_mean": head["nees_mean"],
                    "coverage_2sigma": head["coverage"]["2sigma"],
                    "final_error_m": float(err[-1]),
                    "max_error_m": float(err.max()),
                    "claimed_sigma_m": head["claimed_sigma_p95_m"],
                }
            )
    return rows


def replay_rows(
    root: str | Path,
    sequence: str,
    vo_rows: list[dict[str, Any]],
    seeds: int = 5,
) -> list[dict[str, Any]]:
    """The clone fed the measured errors themselves. The filter assumes the window's measured sigmas times the scale."""
    seq = load_sequence(root, sequence)
    cam = camera_from_yaml(Path(root) / sequence / "mav0/cam0/sensor.yaml")
    start, duration, out_at = CLONE_WINDOW
    scales = tuple((name, model, scale) for name, (model, scale) in REPLAY_VARIANTS.items())
    return _replay_window(seq, cam, vo_rows, start, duration, out_at, scales, seeds)


#: The wider measurement, fixed before it was run: the windows are chosen by speed (:func:`pick_window`), the front
#: end is run at gaps of one and four frames, and the clone is replayed at these assumed-noise scales.
WIDE_SEQUENCES = ("MH_01_easy", "MH_02_easy", "MH_03_medium", "MH_04_difficult", "MH_05_difficult")
WIDE_GAPS = (1, 4)
WIDE_LENGTH_S = 30.0
WIDE_OUTAGE_AT_S = 10.0
WIDE_SEEDS = 3
WIDE_SCALES: tuple[tuple[str, str, float], ...] = (
    ("clone x1", "clone", 1.0),
    ("clone x2", "clone", 2.0),
    ("clone x4", "clone", 4.0),
    ("clone x8", "clone", 8.0),
    ("anchor x1", "anchor", 1.0),
)
WIDE_COLUMNS = ("sequence", "window_start_s", *CLONE_COLUMNS)


def wide_study(
    root: str | Path,
    sequences: tuple[str, ...] = WIDE_SEQUENCES,
    existing: list[dict[str, Any]] | None = None,
    seeds: int = WIDE_SEEDS,
    fetch: bool = True,
    earliest_s: float = 30.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Choose a window per sequence, fetch its frames, measure the front end, and replay the clone.

    ``existing`` are the front-end rows already measured: their windows are avoided and kept. Returns the new
    front-end rows and the replay rows, each replay row tagged with its sequence and window start.
    """
    from .io.euroc_fetch import fetch_images

    existing = existing or []
    new_rows: list[dict[str, Any]] = []
    replay: list[dict[str, Any]] = []
    for name in sequences:
        seq = load_sequence(root, name)
        avoid = tuple((a, b) for s_, a, b in windows(existing, 1.0) if s_ == name)
        start = pick_window(seq.truth, WIDE_LENGTH_S, earliest_s=earliest_s, avoid=avoid)
        # Frames are counted from the first IMU sample, which is also the clock of the ground truth here.
        if fetch:
            fetch_images(
                name,
                Path(root),
                start_s=start,
                stop_s=start + WIDE_LENGTH_S,
                full_download=True,
            )
        print(f"{name}: window {start:.0f} s to {start + WIDE_LENGTH_S:.0f} s", file=sys.stderr, flush=True)
        mine = measure(Path(root) / name, WIDE_GAPS, window=(start, start + WIDE_LENGTH_S))
        new_rows += mine
        cam = camera_from_yaml(Path(root) / name / "mav0/cam0/sensor.yaml")
        for r in _replay_window(seq, cam, mine, start, WIDE_LENGTH_S, WIDE_OUTAGE_AT_S, WIDE_SCALES, seeds):
            replay.append({"sequence": name, "window_start_s": start, **r})
    # The window measured first is replayed again with the same scales, and with the run aligned to its frames.
    for name, a, b in windows(existing, 1.0):
        seq = load_sequence(root, name)
        cam = camera_from_yaml(Path(root) / name / "mav0/cam0/sensor.yaml")
        for r in _replay_window(seq, cam, existing, a, b - a, WIDE_OUTAGE_AT_S, WIDE_SCALES, seeds):
            replay.append({"sequence": name, "window_start_s": a, **r})
    return new_rows, replay


def wide_windows(
    root: str | Path,
    rows: list[dict[str, Any]],
    sequences: tuple[str, ...] = WIDE_SEQUENCES,
    earliest_s: float = 30.0,
) -> list[tuple[str, float, float]]:
    """``(sequence, start, length)`` of every window the wider measurement replays, from measured rows alone.

    The windows depend only on the ground truth and on the window measured first, which is
    :data:`ORIGINAL_WINDOW`, so they can be recomputed without images. Raises ``ValueError`` if the rows hold no
    measurement for a window.
    """
    first = rows_in(rows, *ORIGINAL_WINDOW)
    out: list[tuple[str, float, float]] = []
    for name in sequences:
        seq = load_sequence(root, name)
        avoid = tuple((a, b) for s_, a, b in windows(first, 1.0) if s_ == name)
        start = pick_window(seq.truth, WIDE_LENGTH_S, earliest_s=earliest_s, avoid=avoid)
        if not rows_in(rows, name, start, start + WIDE_LENGTH_S):
            raise ValueError(f"{name}: no measured front-end rows in the window starting at {start:.1f} s")
        out.append((name, start, WIDE_LENGTH_S))
    out += [(name, a, b - a) for name, a, b in windows(first, 1.0)]
    return out


def wide_replay(
    root: str | Path,
    rows: list[dict[str, Any]],
    sequences: tuple[str, ...] = WIDE_SEQUENCES,
    seeds: int = WIDE_SEEDS,
) -> list[dict[str, Any]]:
    """Replay the wider measurement from front-end rows already measured: no images, no new measurement.

    This is :func:`wide_study` without the fetch and the measurement, so a change to the filter can be replayed
    over the same front-end errors.
    """
    replay: list[dict[str, Any]] = []
    for name, start, length in wide_windows(root, rows, sequences):
        seq = load_sequence(root, name)
        cam = camera_from_yaml(Path(root) / name / "mav0/cam0/sensor.yaml")
        for r in _replay_window(seq, cam, rows, start, length, WIDE_OUTAGE_AT_S, WIDE_SCALES, seeds):
            replay.append({"sequence": name, "window_start_s": start, **r})
    return replay


CLONE_WINDOW = (60.0, 30.0, 10.0)  # skip, duration, and the start of the GNSS outage that runs to the end


def clone_rows(
    root: str | Path, sequence: str, rot_sigma_deg: float, trans_sigma_m: float, corr_s: float, seeds: int = 5
) -> list[dict[str, Any]]:
    """The stochastic clone against a simulated front end that has the measured error size and correlation.

    GNSS is healthy for the first 10 s of a 30 s window and lost for the last 20 s, so that the filter's biases have
    settled before the outage. NEES and coverage are over the whole window, which includes the 10 aided seconds.
    """
    seq = load_sequence(root, sequence)
    skip, duration, out_at = CLONE_WINDOW
    base = dict(CONFIGS["walk10"])
    rows: list[dict[str, Any]] = []
    for name, (model, corr_mult, scale) in CLONE_VARIANTS.items():
        for seed in range(seeds):
            opts = RunOptions(
                seed=seed,
                skip_s=skip,
                duration_s=duration,
                outages=((out_at, duration - out_at),),
                vision=model,
                vision_corr_s=corr_s * corr_mult,
                vision_noise_scale=scale,
                vision_sigmas=(rot_sigma_deg, trans_sigma_m) if model else None,
                **base,
            )
            rec = run_sequence(seq, opts)
            head = rec["headline"]
            err = np.asarray(rec["error_time_series"]["position_error_m"], dtype=float)
            rows.append(
                {
                    "variant": name,
                    "seed": seed,
                    "nees_mean": head["nees_mean"],
                    "coverage_2sigma": head["coverage"]["2sigma"],
                    "final_error_m": float(err[-1]),
                    "max_error_m": float(err.max()),
                    "claimed_sigma_m": head["claimed_sigma_p95_m"],
                }
            )
    return rows


def clone_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Variant | Runs | Median mean NEES | Median 2-sigma coverage | Median final error m | Median claimed sigma m "
        "| Meets the gate (NEES < 10, coverage > 90%) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name in [*CLONE_VARIANTS, *REPLAY_VARIANTS]:
        sel = [r for r in rows if r["variant"] == name]
        if not sel:
            continue
        nees = float(np.median([float(r["nees_mean"]) for r in sel]))
        cov = float(np.median([float(r["coverage_2sigma"]) for r in sel]))
        ok = "yes" if nees < 10.0 and cov > 0.9 else "no"
        lines.append(
            f"| {name} | {len(sel)} | {nees:.1f} | {100 * cov:.0f}% | "
            f"{np.median([float(r['final_error_m']) for r in sel]):.2f} | "
            f"{np.median([float(r['claimed_sigma_m']) for r in sel]):.2f} | {ok} |"
        )
    return "\n".join(lines)


def write_wide_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=WIDE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def passes(nees: float, coverage: float) -> bool:
    """The Track B gate: mean NEES below 10 and 2-sigma coverage above 90%."""
    return nees < 10.0 and coverage > 0.9


def wide_markdown(rows: list[dict[str, Any]]) -> str:
    """Per window and assumed-noise scale: the median over seeds, and whether it meets the gate."""
    names = [n for n, _, _ in WIDE_SCALES]
    keys = sorted({(r["sequence"], float(r["window_start_s"])) for r in rows})
    lines = [
        "| Sequence | Window start s | " + " | ".join(f"{n}: NEES / coverage" for n in names) + " |",
        "|---|---:|" + "---|" * len(names),
    ]
    verdict: dict[str, list[bool]] = {n: [] for n in names}
    for seq, start in keys:
        cells = []
        for n in names:
            sel = [
                r for r in rows if r["sequence"] == seq and float(r["window_start_s"]) == start and r["variant"] == n
            ]
            if not sel:
                cells.append("-")
                continue
            nees = float(np.median([float(r["nees_mean"]) for r in sel]))
            cov = float(np.median([float(r["coverage_2sigma"]) for r in sel]))
            ok = passes(nees, cov)
            verdict[n].append(ok)
            cells.append(f"{nees:.3g} / {100 * cov:.0f}%{' ok' if ok else ''}")
        lines.append(f"| {seq} | {start:.0f} | " + " | ".join(cells) + " |")
    total = len(keys)
    lines.append(
        "| **Windows meeting the gate** | | " + " | ".join(f"{sum(verdict[n])} of {total}" for n in names) + " |"
    )
    return "\n".join(lines)


def write_clone_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CLONE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


#: The window measured first (all five gaps), which the first tables of the page describe.
ORIGINAL_WINDOW = ("MH_01_easy", 60.0, 90.0)


def rows_in(rows: list[dict[str, Any]], sequence: str, start_s: float, stop_s: float) -> list[dict[str, Any]]:
    """The rows of one sequence whose pair lies inside ``[start_s, stop_s]``."""
    return [
        r
        for r in rows
        if r["sequence"] == sequence and start_s <= float(r["t_s"]) and float(r["t_s"]) + float(r["dt_s"]) <= stop_s
    ]


def rows_in_window(rows: list[dict[str, Any]], sequence: str, start_s: float, length_s: float) -> list[dict[str, Any]]:
    """The rows of one sequence whose pair starts in ``[start_s, start_s + length_s - one frame)``.

    Two windows can touch (90.005 s ends where the next begins), so a window is defined by where its pairs start, and
    a pair that straddles the boundary belongs to neither.
    """
    return [
        r
        for r in rows
        if r["sequence"] == sequence and start_s - 1e-6 <= float(r["t_s"]) < start_s + length_s - FRAME_STEP_S - 1e-6
    ]


def windows_markdown(
    rows: list[dict[str, Any]], wide_rows: list[dict[str, Any]], gaps: tuple[int, ...] = WIDE_GAPS
) -> str:
    """The front end's errors in every window of the wider measurement, at the gaps it used."""
    lines = [
        "| Sequence | Window start s | Gap, frames | Pairs | Rotation RMS deg | Lateral RMS m | Outlier share "
        "| Rotation correlation time s | Lateral correlation time s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    keys = sorted({(r["sequence"], float(r["window_start_s"])) for r in wide_rows})
    for seq, start in keys:
        sel = rows_in_window(rows, seq, start, WIDE_LENGTH_S)
        for gap in gaps:
            if not any(int(r["gap_frames"]) == gap for r in sel):
                continue
            s = summary(sel, gap, FRAME_STEP_S)
            lines.append(
                f"| {seq} | {start:.0f} | {gap} | {s['pairs']:.0f} | {s['rot_rms_deg']:.2f} | {s['lat_rms_m']:.3f} | "
                f"{100 * s['outlier_share']:.0f}% | {s['rot_corr_time_s']:.2f} | {s['lat_corr_time_s']:.2f} |"
            )
    return "\n".join(lines)


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def summary_markdown(rows: list[dict[str, Any]], frame_step_s: float = 0.05) -> str:
    lines = [
        "| Gap, frames | Pairs | Median baseline m | Rotation RMS deg | Lateral RMS m | Median direction error deg "
        "| Outlier share | Rotation lag-1 autocorrelation | Lateral lag-1 autocorrelation "
        "| Rotation correlation time s | Lateral correlation time s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for gap in sorted({int(r["gap_frames"]) for r in rows}):
        s = summary(rows, gap, frame_step_s)
        lines.append(
            f"| {gap} | {s['pairs']:.0f} | {s['baseline_m']:.3f} | {s['rot_rms_deg']:.2f} | {s['lat_rms_m']:.3f} | "
            f"{s['dir_median_deg']:.1f} | {100 * s['outlier_share']:.0f}% | {s['rot_acf_lag1']:.2f} | "
            f"{s['lat_acf_lag1']:.2f} | {s['rot_corr_time_s']:.2f} | {s['lat_corr_time_s']:.2f} |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit euroc vo", description="Measure the errors of the two-view front end on fetched frames."
    )
    p.add_argument("--sequence", default="MH_01_easy")
    p.add_argument("--root", default="data/raw/euroc")
    p.add_argument("--gaps", default=",".join(str(g) for g in GAPS))
    p.add_argument("--csv", default=None, help="write one row per pair")
    p.add_argument("--from-csv", default=None, help="print the summary of a saved --csv file; no images needed")
    p.add_argument(
        "--clone", action="store_true", help="also run the clone against the measured errors (a few minutes)"
    )
    p.add_argument("--clone-csv", default=None, help="write (with --clone) or read the clone check's runs")
    p.add_argument("--page", default=None, help="fill the vo-errors and vo-clone blocks of this Markdown page")
    p.add_argument(
        "--wide",
        action="store_true",
        help="the wider measurement: pick a window per Machine Hall sequence, fetch its frames from the whole "
        "archive on disk, measure, and replay the clone at several assumed-noise scales (an hour or more)",
    )
    p.add_argument("--wide-csv", default="docs/data/vo_wide.csv", help="the replay runs of --wide")
    p.add_argument(
        "--wide-replay",
        action="store_true",
        help="replay the wider measurement from the front-end rows of --from-csv: no images, no new measurement",
    )
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def read_clone_csv(path: str | Path) -> list[dict[str, Any]]:
    return read_csv(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.wide_replay:
        if not args.from_csv:
            print("error: --wide-replay needs --from-csv", file=sys.stderr)
            return 1
        try:
            replay = wide_replay(args.root, read_csv(args.from_csv))
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        write_wide_csv(args.wide_csv, replay)
        print(wide_markdown(replay))
        return 0
    if args.wide:
        existing = read_csv(args.csv) if args.csv and Path(args.csv).is_file() else []
        try:
            new_rows, replay = wide_study(args.root, WIDE_SEQUENCES, existing)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.csv:
            write_csv(args.csv, existing + new_rows)
        write_wide_csv(args.wide_csv, replay)
        print(wide_markdown(replay))
        return 0
    if args.from_csv:
        rows = read_csv(args.from_csv)
    else:
        gaps = tuple(int(g) for g in args.gaps.split(","))
        try:
            rows = measure(Path(args.root) / args.sequence, gaps)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.csv:
        write_csv(args.csv, rows)
        print(f"wrote {args.csv}", file=sys.stderr)
    first = rows_in(rows, *ORIGINAL_WINDOW)
    clone = None
    if args.clone:
        one = summary(first, 1, FRAME_STEP_S)
        sigmas = (round(one["rot_rms_deg"], 3), round(one["lat_rms_m"], 4))
        corr = round(one["lat_corr_time_s"], 2)
        root, seq = args.root, args.sequence
        clone = clone_rows(root, seq, *sigmas, corr_s=corr) + replay_rows(root, seq, first)
        if args.clone_csv:
            write_clone_csv(args.clone_csv, clone)
            print(f"wrote {args.clone_csv}", file=sys.stderr)
    elif args.clone_csv and Path(args.clone_csv).is_file():
        clone = read_clone_csv(args.clone_csv)
    if args.page:
        try:
            write_block(args.page, "vo-errors", summary_markdown(first))
            if clone is not None:
                write_block(args.page, "vo-clone", clone_markdown(clone))
            if Path(args.wide_csv).is_file():
                wide = read_csv(args.wide_csv)
                write_block(args.page, "vo-wide-errors", windows_markdown(rows, wide))
                write_block(args.page, "vo-wide-clone", wide_markdown(wide))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.markdown or not (args.csv or args.page):
        print(summary_markdown(first))
        if clone is not None:
            print("\n" + clone_markdown(clone))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
