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
from .types import Trajectory, VisionUpdate, interpolate_trajectory
from .vo_frontend import Camera, camera_from_yaml, load_gray, motion_from_pair, relative_poses_along

GAPS = (1, 2, 4, 6, 10)
FRAME_STEP_S = 0.05  # the camera is 20 Hz
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
            images.pop(i - 2 * max(gaps) - 4, None)  # keep memory bounded
        return images[i]

    rows: list[dict[str, Any]] = []
    top = max(gaps)
    for i in range(0, len(frames) - top):
        window = [image(i + k) for k in range(top + 1)]
        found = relative_poses_along(window, gaps, cam, seed=i)
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


def replay_rows(
    root: str | Path,
    sequence: str,
    vo_rows: list[dict[str, Any]],
    rot_sigma_deg: float,
    trans_sigma_m: float,
    seeds: int = 5,
) -> list[dict[str, Any]]:
    """The clone fed the measured errors themselves. The filter assumes the measured sigmas times the scale."""
    seq = load_sequence(root, sequence)
    cam = camera_from_yaml(Path(root) / sequence / "mav0/cam0/sensor.yaml")
    skip, duration, out_at = CLONE_WINDOW
    t_from = skip + float(seq.imu.t[0])
    stream = replay_stream(vo_rows, seq.truth, cam, t_from, t_from + duration)
    rows: list[dict[str, Any]] = []
    for name, (model, scale) in REPLAY_VARIANTS.items():
        for seed in range(seeds):
            opts = RunOptions(
                seed=seed,
                skip_s=skip,
                duration_s=duration,
                outages=((out_at, duration - out_at),),
                vision=model,
                vision_noise_scale=scale,
                vision_sigmas=(rot_sigma_deg, trans_sigma_m),
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


def write_clone_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CLONE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


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
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def read_clone_csv(path: str | Path) -> list[dict[str, Any]]:
    return read_csv(path)


def write_block(path: str | Path, name: str, block: str) -> None:
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text or text.index(start) > text.index(end):
        raise ValueError(f"{page} needs the lines {start} and {end}, in that order")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    page.write_text(f"{head}{start}\n\n{block}\n\n{end}{tail}", encoding="utf-8")


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
    clone = None
    if args.clone:
        one = summary(rows, 1, FRAME_STEP_S)
        sigmas = (round(one["rot_rms_deg"], 3), round(one["lat_rms_m"], 4))
        corr = round(one["lat_corr_time_s"], 2)
        root, seq = args.root, args.sequence
        clone = clone_rows(root, seq, *sigmas, corr_s=corr) + replay_rows(root, seq, rows, *sigmas)
        if args.clone_csv:
            write_clone_csv(args.clone_csv, clone)
            print(f"wrote {args.clone_csv}", file=sys.stderr)
    elif args.clone_csv and Path(args.clone_csv).is_file():
        clone = read_clone_csv(args.clone_csv)
    if args.page:
        try:
            write_block(args.page, "vo-errors", summary_markdown(rows))
            if clone is not None:
                write_block(args.page, "vo-clone", clone_markdown(clone))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.markdown or not (args.csv or args.page):
        print(summary_markdown(rows))
        if clone is not None:
            print("\n" + clone_markdown(clone))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
