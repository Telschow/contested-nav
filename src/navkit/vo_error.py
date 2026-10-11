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

from .euroc_eval import load_sequence
from .geometry.rigid import rot_log
from .types import Trajectory, interpolate_trajectory
from .vo_frontend import Camera, camera_from_yaml, load_gray, motion_from_pair, relative_pose

GAPS = (1, 4, 10)
#: Below this true baseline the direction of the motion is undefined and the pair is skipped.
MIN_TRUE_BASELINE_M = 1e-3
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


def measure(seq_dir: Path, gaps: tuple[int, ...] = GAPS, min_baseline_m: float = 0.0) -> list[dict[str, Any]]:
    """Run the front end on every pair ``gap`` frames apart and return one row per pair that produced an estimate."""
    seq = load_sequence(seq_dir.parent, seq_dir.name)
    cam = camera_from_yaml(seq_dir / "mav0/cam0/sensor.yaml")
    frames = frame_list(seq_dir)
    if len(frames) < max(gaps) + 2:
        raise ValueError(f"{seq_dir.name}: {len(frames)} frames are not enough for gaps up to {max(gaps)}")
    images: dict[int, np.ndarray] = {}

    def image(i: int) -> np.ndarray:
        if i not in images:
            images[i] = load_gray(frames[i][1])
            images.pop(i - 3 * max(gaps) - 4, None)  # keep memory bounded
        return images[i]

    rows: list[dict[str, Any]] = []
    for gap in gaps:
        for i in range(0, len(frames) - gap):
            (t0, _), (t1, _) = frames[i], frames[i + gap]
            if not (seq.truth.t[0] <= t0 and t1 <= seq.truth.t[-1]):
                continue
            est = relative_pose(image(i), image(i + gap), cam, seed=i)
            if est is None:
                continue
            row = pair_row(seq_dir.name, gap, t0, t1, est, seq.truth, cam)
            if row is not None and row["baseline_m"] >= min_baseline_m:
                rows.append(row)
    return rows


# ------------------------------------------------------------------ statistics


def autocorrelation(x: np.ndarray, max_lag: int = MAX_LAG) -> np.ndarray:
    """Normalised autocorrelation at lags 0 to ``max_lag`` of a series (mean removed)."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    var = float(x @ x)
    if var <= 0.0 or len(x) <= max_lag:
        return np.full(max_lag + 1, np.nan)
    return np.array([float(x[: len(x) - k] @ x[k:]) / var for k in range(max_lag + 1)])


def correlation_time(acf: np.ndarray, step_s: float) -> float:
    """Seconds until the autocorrelation first falls below 1/e. Capped at the longest lag if it never does."""
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
    acf_rot = np.nanmean([autocorrelation(rot[:, k]) for k in range(3)], axis=0)
    acf_lat = np.nanmean([autocorrelation(lat[:, k]) for k in range(3)], axis=0)
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
    p.add_argument("--markdown", action="store_true", help="print the summary table")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    if args.markdown or not args.csv:
        print(summary_markdown(rows))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
