"""Timing evidence from a recorded sequence: timestamp regularity, and the ground truth's offset from the IMU.

    navkit euroc timing --dataset tumvi --csv docs/data/timing.csv

Two measurements, both from the data and neither assumed.

* **Interval statistics.** The spacing of the IMU and ground-truth timestamps: the mean, the spread (jitter), the
  longest gap, and how many gaps are more than half again the nominal one. The filter treats the IMU as a
  uniformly sampled stream and integrates over whatever spacing the timestamps give.
* **The offset between the ground truth and the IMU.** The ground truth and the IMU are recorded by different
  systems. If they are not on one clock, the simulated GNSS (generated from the ground truth) and the scoring
  reference are displaced in time from the inertial data. The offset is estimated by matching the angular rate
  the ground-truth attitude implies against the gyroscope. The primary method (``vector``) compares the rate
  vectors axis by axis after removing each axis's mean, which removes a constant gyroscope bias exactly; it
  assumes the ground truth is expressed in the IMU frame, which both datasets state. The cross-check
  (``magnitude``) compares the size of the rate and needs no frame, but a gyroscope bias adds a cross-term that
  shifts its peak by a few milliseconds, so it is a check on the order of magnitude and not the figure.

The offset ``offset_s`` is the shift ``dt`` for which ``truth.time_offset(dt)`` best matches the IMU, so applying it
to the ground truth removes the displacement. A positive value means the ground-truth timestamps are early.

Limits. The estimate needs the platform to rotate: a rig that does not turn gives a flat correlation and the
sequence reports ``correlation_peak`` near zero, in which case the offset means nothing. The ground truth of the
EuRoC Machine Hall sequences is itself a filtered estimate built from the inertial data, so its offset from the IMU
is small by construction and is not an independent check of the clock. Resolution is a fraction of a millisecond
with a parabolic refinement, and the real uncertainty is larger and not estimated here.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .euroc_compare import fetched_sequences
from .euroc_eval import dataset_loader
from .recorded import EurocSequence, SequenceError
from .types import ImuSample, Trajectory, rot_log_batch

CSV_COLUMNS = (
    "sequence",
    "dataset",
    "imu_rate_hz",
    "imu_jitter_ms",
    "imu_max_gap_ms",
    "imu_long_gaps",
    "truth_rate_hz",
    "truth_jitter_ms",
    "truth_max_gap_ms",
    "truth_gap_fraction",
    "offset_ms",
    "offset_magnitude_ms",
    "correlation_peak",
    "correlation_at_zero",
    "median_speed_m_s",
    "offset_displacement_mm",
)

MAX_LAG_S = 0.15
LAG_STEP_S = 0.001
TRIM_S = 1.0
#: A gap longer than this many nominal intervals counts as a long gap.
LONG_GAP_FACTOR = 1.5
#: A ground-truth gap longer than this (s) counts as a dropout when its share of the recording is reported.
DROPOUT_S = 0.1


@dataclass
class IntervalStats:
    rate_hz: float
    jitter_ms: float
    max_gap_ms: float
    long_gaps: int


def interval_stats(t: np.ndarray) -> IntervalStats:
    """Mean rate, jitter (standard deviation of the spacing), longest gap and the number of long gaps."""
    t = np.asarray(t, float)
    if len(t) < 3:
        raise ValueError("need at least three timestamps")
    d = np.diff(t)
    nominal = float(np.median(d))
    return IntervalStats(
        rate_hz=float(1.0 / d.mean()),
        jitter_ms=float(1e3 * d.std()),
        max_gap_ms=float(1e3 * d.max()),
        long_gaps=int(np.sum(d > LONG_GAP_FACTOR * nominal)),
    )


def dropout_fraction(t: np.ndarray, gap_s: float = DROPOUT_S) -> float:
    """The share of the recording's span that lies inside gaps longer than ``gap_s``.

    The simulated GNSS and the scoring reference are interpolated from the ground truth, so inside such a gap
    they follow a straight line between the two samples.
    """
    t = np.asarray(t, float)
    d = np.diff(t)
    span = float(t[-1] - t[0])
    return float(d[d > gap_s].sum() / span) if span > 0 else 0.0


def truth_rate_vector(truth: Trajectory) -> tuple[np.ndarray, np.ndarray]:
    """The body-frame angular rate of the ground-truth attitude, by a central difference over the neighbouring poses.

    Returns the times of the interior poses and the rate at each, shape ``(n, 3)``, in rad/s.
    """
    R = truth.rotations
    dt = truth.t[2:] - truth.t[:-2]
    rel = np.einsum("nji,njk->nik", R[:-2], R[2:])  # R_{k-1}^T R_{k+1}
    w = rot_log_batch(rel)
    out = np.zeros_like(w)
    ok = dt > 0
    out[ok] = w[ok] / dt[ok, None]
    return truth.t[1:-1], out


def truth_rate_magnitude(truth: Trajectory) -> tuple[np.ndarray, np.ndarray]:
    """``|w|`` of the ground-truth attitude, in rad/s, at the times of the interior poses."""
    t, w = truth_rate_vector(truth)
    return t, np.linalg.norm(w, axis=1)


def _normalised(x: np.ndarray) -> np.ndarray:
    """Remove each column's mean, then scale the whole array to unit norm (columns share one scale)."""
    x = x - x.mean(axis=0)
    n = float(np.linalg.norm(x))
    return x / n if n > 0 else x


def estimate_offset(
    imu: ImuSample,
    truth: Trajectory,
    max_lag_s: float = MAX_LAG_S,
    step_s: float = LAG_STEP_S,
    method: str = "vector",
) -> dict[str, float]:
    """The shift of the ground-truth timestamps that best matches the IMU, from the angular rate.

    ``method="vector"`` compares the rate vectors per axis after removing each axis mean (assumes the ground truth
    is in the IMU frame); ``"magnitude"`` compares ``|w|`` (no frame, but biased by a gyroscope bias). Returns
    ``offset_s``, ``correlation_peak`` and ``correlation_at_zero``, the correlation of the two series at the best
    shift and at none. A peak near zero means the rig did not turn and the offset means nothing.
    """
    if method not in ("vector", "magnitude"):
        raise ValueError(f"method must be 'vector' or 'magnitude', got {method!r}")
    t_w, w_vec = truth_rate_vector(truth)
    w_truth = w_vec if method == "vector" else np.linalg.norm(w_vec, axis=1)
    lo = max(float(imu.t[0]), float(t_w[0])) + TRIM_S + max_lag_s
    hi = min(float(imu.t[-1]), float(t_w[-1])) - TRIM_S - max_lag_s
    if hi - lo < 5.0:
        raise ValueError("the IMU and the ground truth share too little time to estimate an offset")
    sel = (imu.t >= lo) & (imu.t <= hi)
    t_g = imu.t[sel]
    g = imu.gyro[sel] if method == "vector" else np.linalg.norm(imu.gyro[sel], axis=1)
    gyro = _normalised(g)
    lags = np.arange(-max_lag_s, max_lag_s + 0.5 * step_s, step_s)
    corr = np.empty(len(lags))
    for i, dt in enumerate(lags):
        # Shifting the truth timestamps by dt makes the value at time t the old value at t - dt.
        if method == "vector":
            shifted = np.stack([np.interp(t_g - dt, t_w, w_truth[:, k]) for k in range(3)], axis=1)
        else:
            shifted = np.interp(t_g - dt, t_w, w_truth)
        corr[i] = float(np.sum(gyro * _normalised(shifted)))
    k = int(np.argmax(corr))
    offset = float(lags[k])
    if 0 < k < len(lags) - 1:  # parabolic refinement through the peak and its neighbours
        a, b, c = corr[k - 1], corr[k], corr[k + 1]
        denom = a - 2.0 * b + c
        if denom < 0.0:
            offset += 0.5 * step_s * (a - c) / denom
    zero = int(np.argmin(np.abs(lags)))
    return {"offset_s": offset, "correlation_peak": float(corr[k]), "correlation_at_zero": float(corr[zero])}


def sequence_row(seq: EurocSequence) -> dict[str, Any]:
    """One CSV row of timing evidence for a loaded sequence."""
    imu_s, truth_s = interval_stats(seq.imu.t), interval_stats(seq.truth.t)
    est = estimate_offset(seq.imu, seq.truth)
    check = estimate_offset(seq.imu, seq.truth, method="magnitude")
    speed = float(np.median(np.linalg.norm(seq.velocity, axis=1)))
    return {
        "sequence": seq.name,
        "dataset": seq.dataset,
        "imu_rate_hz": imu_s.rate_hz,
        "imu_jitter_ms": imu_s.jitter_ms,
        "imu_max_gap_ms": imu_s.max_gap_ms,
        "imu_long_gaps": imu_s.long_gaps,
        "truth_rate_hz": truth_s.rate_hz,
        "truth_jitter_ms": truth_s.jitter_ms,
        "truth_max_gap_ms": truth_s.max_gap_ms,
        "truth_gap_fraction": dropout_fraction(seq.truth.t),
        "offset_ms": 1e3 * est["offset_s"],
        "offset_magnitude_ms": 1e3 * check["offset_s"],
        "correlation_peak": est["correlation_peak"],
        "correlation_at_zero": est["correlation_at_zero"],
        "median_speed_m_s": speed,
        "offset_displacement_mm": 1e3 * abs(est["offset_s"]) * speed,
    }


def table_markdown(rows: list[dict[str, Any]]) -> str:
    """The table for the specification page. Every figure comes from the rows."""
    lines = [
        "| Sequence | IMU Hz | IMU longest gap ms | Truth Hz | Truth longest gap ms | Truth time in dropouts | "
        "Offset ms | Magnitude check ms | Correlation (peak / at zero) | Offset x speed mm |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for r in rows:
        f = {k: float(v) for k, v in r.items() if k not in ("sequence", "dataset")}
        corr = f"{f['correlation_peak']:.3f} / {f['correlation_at_zero']:.3f}"
        lines.append(
            f"| {r['sequence']} | {f['imu_rate_hz']:.1f} | {f['imu_max_gap_ms']:.1f} | {f['truth_rate_hz']:.1f} | "
            f"{f['truth_max_gap_ms']:.0f} | {100 * f['truth_gap_fraction']:.1f}% | {f['offset_ms']:+.1f} | "
            f"{f['offset_magnitude_ms']:+.1f} | {corr} | {f['offset_displacement_mm']:.1f} |"
        )
    return "\n".join(lines)


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows({k: r[k] for k in CSV_COLUMNS} for r in rows)


def write_block(path: str | Path, block: str, name: str = "timing") -> None:
    """Replace the text between a block's markers in a Markdown page. Refuses a page without them."""
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text or text.index(start) > text.index(end):
        raise ValueError(f"{page} needs the lines {start} and {end}, in that order")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    page.write_text(f"{head}{start}\n\n{block}\n\n{end}{tail}", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit euroc timing",
        description="Timestamp regularity and the ground-truth-to-IMU time offset of the fetched sequences.",
    )
    p.add_argument("--dataset", action="append", choices=("euroc", "tumvi"), default=[], help="default: both")
    p.add_argument("--root", default=None, help="data root, for one dataset only (default: the dataset's folder)")
    p.add_argument("--sequence", "-s", action="append", default=[], metavar="NAME")
    p.add_argument("--csv", default=None, help="write the rows")
    p.add_argument("--from-csv", default=None, help="rebuild the table and page from a saved --csv file")
    p.add_argument("--page", default=None, help="fill the timing block of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the table")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows: list[dict[str, Any]]
    if args.from_csv:
        rows = rows_from_csv(args.from_csv)
    else:
        datasets = args.dataset or ["euroc", "tumvi"]
        if args.root and len(datasets) != 1:
            print("error: --root needs exactly one --dataset", file=sys.stderr)
            return 2
        rows = []
        for dataset in datasets:
            loader, default_root = dataset_loader(dataset)
            root = args.root or default_root
            names = [s for s in (args.sequence or fetched_sequences(root, dataset)) if _belongs(s, dataset)]
            for name in names:
                try:
                    rows.append(sequence_row(loader(root, name)))
                except (SequenceError, ValueError) as exc:
                    print(f"{name}: {exc}", file=sys.stderr)
                    continue
                print(f"{name}: done", file=sys.stderr, flush=True)
        if not rows:
            print(
                "error: no sequences found. Fetch some with `navkit euroc fetch` or `navkit tumvi fetch`.",
                file=sys.stderr,
            )
            return 1
    if args.csv:
        write_csv(args.csv, rows)
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.page:
        try:
            write_block(args.page, table_markdown(rows))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.page}", file=sys.stderr)
    if args.markdown or not (args.csv or args.page):
        print(table_markdown(rows))
    return 0


def _belongs(name: str, dataset: str) -> bool:
    return name.startswith("room") if dataset == "tumvi" else not name.startswith("room")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
