"""What the fetched UrbanNav files contain, measured and written to a CSV the documentation page is built from.

    navkit urbannav check --sequence tunnel1 --csv docs/data/urbannav_data.csv --page docs/urbannav.md

The dataset is not vendored (constraint S2), so CI cannot read it. It can check that the page is the table the
committed CSV produces. The CSV holds aggregate quantities only: counts, rates, intervals and error summaries.

Two measurements need a word.

* **The clock offset.** The reference and the IMU are on different systems. The offset is the shift that makes the
  reference's heading change in each second match the integral of the Xsens yaw rate over the same second. It
  uses only the z axis of the gyroscope, which is up in both frames, so it needs no rotation between the two units.
  It is fitted by a grid search at 0.01 s steps, so it cannot resolve less than that, and the 1 Hz reference limits
  how sharp the answer can be. :func:`clock_offset` is tested by shifting a synthetic reference by known amounts.
* **The fix errors.** A receiver fix is compared with the reference at the same instant. The reference is an
  estimate, not a truth, and the antenna offsets between the receiver, the reference unit and the IMU are not known.
  So these are differences between two solutions, not receiver accuracy.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import urbannav_data as ud
from .recorded import SequenceError
from .report.page import write_block as _write_page_block

CSV_COLUMNS = ("sequence", "quantity", "value", "unit")
DEFAULT_ROOT = "data/raw/urbannav"
OFFSET_GRID_STEP_S = 0.01
OFFSET_SEARCH_S = 1.5
#: Epochs compared on each side of an outage when looking at the fixes next to it.
EDGE_BEFORE = 10
EDGE_AFTER = 3


def clock_offset(seq: ud.UrbanNavSequence) -> float:
    """The shift to add to the reference times to put them on the IMU clock, in seconds.

    Positive means the reference clock runs early. See the module docstring for the method and its limits.
    """
    imu, ref = seq.imu, seq.reference
    gz = imu.gyro[:, 2]
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (gz[1:] + gz[:-1]) * np.diff(imu.t))])
    heading = np.unwrap(np.radians(ref.rpy_deg[:, 2]))
    dh = np.diff(heading)
    t0, t1 = seq.truth_t[:-1], seq.truth_t[1:]
    best, best_cost = 0.0, np.inf
    for d in np.arange(-OFFSET_SEARCH_S, OFFSET_SEARCH_S + 1e-9, OFFSET_GRID_STEP_S):
        ok = (t0 + d > imu.t[0]) & (t1 + d < imu.t[-1])
        if ok.sum() < 10:
            continue
        # The Xsens z axis is up, so counter-clockwise yaw is positive. Heading is clockwise from north.
        pred = -(np.interp(t1[ok] + d, imu.t, cum) - np.interp(t0[ok] + d, imu.t, cum))
        r = dh[ok] - pred
        r = r - r.mean()  # a constant gyroscope bias drops out
        cost = float(np.mean(r**2))
        if cost < best_cost:
            best, best_cost = float(d), cost
    if not np.isfinite(best_cost):
        raise SequenceError(f"{seq.name}: too little overlap between the reference and the IMU to fit an offset")
    return round(best / OFFSET_GRID_STEP_S) * OFFSET_GRID_STEP_S + 0.0


def _round(x: float) -> str:
    return f"{x:.4g}"


def measure(root: str | Path, seq_name: str) -> list[dict[str, Any]]:
    """All the quantities, as CSV rows."""
    seq = ud.load_sequence(root, seq_name)
    fixes = ud.load_gga(root, seq_name)
    rows: list[dict[str, Any]] = []

    def add(quantity: str, value: float | int | str, unit: str) -> None:
        rows.append({"sequence": seq_name, "quantity": quantity, "value": value, "unit": unit})

    dt = np.diff(seq.imu.t)
    add("imu_samples", len(seq.imu), "count")
    add("imu_span", _round(float(seq.imu.t[-1])), "s")
    add("imu_rate_median", _round(float(1.0 / np.median(dt))), "Hz")
    add("imu_longest_gap", _round(float(dt.max() * 1e3)), "ms")
    add("reference_epochs", len(seq.reference), "count")
    add("reference_spacing_median", _round(float(np.median(np.diff(seq.reference.utc_s)))), "s")
    add("reference_quality_codes", len(np.unique(seq.reference.quality)), "count")
    add("clock_offset", _round(clock_offset(seq)), "s")
    add("clock_offset_grid_step", OFFSET_GRID_STEP_S, "s")

    spans = ud.outage_intervals(fixes)
    denied = (fixes.quality == 0) | ~np.isfinite(fixes.lat_deg)
    add("gnss_epochs", len(fixes), "count")
    add("gnss_denied_epochs", int(denied.sum()), "count")
    add("gnss_outages", len(spans), "count")
    if spans:
        a, b = spans[0]
        add("outage_start", _round(a - seq.epoch_unix_s), "s")
        add("outage_end", _round(b - seq.epoch_unix_s), "s")
        add("outage_length", _round(b - a), "s")

    valid = ~denied
    enu, _ = ud.llh_to_enu(fixes.lat_deg[valid], fixes.lon_deg[valid], fixes.height_m[valid], origin=seq.origin_llh)
    tv = fixes.utc_s[valid]
    ref = np.column_stack([np.interp(tv - seq.epoch_unix_s, seq.truth_t, seq.truth_enu[:, k]) for k in range(3)])
    err = enu - ref
    horiz = np.linalg.norm(err[:, :2], axis=1)
    add("fix_horizontal_error_median", _round(float(np.median(horiz))), "m")
    add("fix_horizontal_error_p95", _round(float(np.quantile(horiz, 0.95))), "m")
    add("fix_horizontal_error_max", _round(float(horiz.max())), "m")
    if spans:
        a, b = spans[0]
        before, after = np.flatnonzero(tv < a), np.flatnonzero(tv >= b)
        if before.size >= EDGE_BEFORE and after.size >= EDGE_AFTER:
            add("fix_error_last_valid_before_outage", _round(float(horiz[before[-1]])), "m")
            add("fix_error_max_last_valid_before_outage", _round(float(horiz[before[-EDGE_BEFORE:]].max())), "m")
            add("fix_error_first_valid_after_outage", _round(float(horiz[after[0]])), "m")
            add("fix_error_max_first_valid_after_outage", _round(float(horiz[after[:EDGE_AFTER]].max())), "m")
            add("fix_vertical_bias_before_outage", _round(float(err[before, 2].mean())), "m")
            add("fix_vertical_bias_after_outage", _round(float(err[after, 2].mean())), "m")
    return rows


# ---------------------------------------------------------------------- output

LABELS = {
    "imu_samples": "IMU samples",
    "imu_span": "IMU time span",
    "imu_rate_median": "IMU rate, median",
    "imu_longest_gap": "IMU longest gap",
    "reference_epochs": "Reference epochs",
    "reference_spacing_median": "Reference spacing, median",
    "reference_quality_codes": "Distinct reference quality codes",
    "clock_offset": "Reference-to-IMU clock offset",
    "clock_offset_grid_step": "Offset search step",
    "gnss_epochs": "F9P fixes (GGA sentences)",
    "gnss_denied_epochs": "Epochs with no fix",
    "gnss_outages": "Outages by the rule",
    "outage_start": "First outage, start (IMU clock)",
    "outage_end": "First outage, end (IMU clock)",
    "outage_length": "First outage, length",
    "fix_horizontal_error_median": "Fix horizontal difference from the reference, median",
    "fix_horizontal_error_p95": "Fix horizontal difference, 95th percentile",
    "fix_horizontal_error_max": "Fix horizontal difference, largest",
    "fix_error_last_valid_before_outage": "Last valid fix before the outage, difference",
    "fix_error_max_last_valid_before_outage": "Largest difference in the last valid fixes before the outage",
    "fix_error_first_valid_after_outage": "First valid fix after the outage, difference",
    "fix_error_max_first_valid_after_outage": "Largest difference in the first valid fixes after the outage",
    "fix_vertical_bias_before_outage": "Mean fix height minus reference height, before the outage",
    "fix_vertical_bias_after_outage": "Mean fix height minus reference height, after the outage",
}


def table_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Sequence | Quantity | Value | Unit |", "|---|---|---:|---|"]
    for r in rows:
        lines.append(f"| {r['sequence']} | {LABELS.get(r['quantity'], r['quantity'])} | {r['value']} | {r['unit']} |")
    return "\n".join(lines)


BLOCKS = {"urbannav-data": table_markdown}


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write ``rows`` to ``path``, replacing the rows of those sequences and keeping the rows of any other."""
    ud.csv_table(CSV_COLUMNS).merge(path, rows)


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_block(path: str | Path, name: str, block: str) -> None:
    """Replace the text between a block's markers in a Markdown page."""
    _write_page_block(path, name, block)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit urbannav check", description="Measure what the fetched UrbanNav files contain."
    )
    p.add_argument("--root", default=DEFAULT_ROOT, help="where `navkit urbannav fetch` wrote (default: %(default)s)")
    p.add_argument("--sequence", "-s", default="tunnel1")
    p.add_argument(
        "--csv", default=None, help="write the quantities to this CSV; other sequences' rows in the file are kept"
    )
    p.add_argument("--from-csv", default=None, help="rebuild the tables from a saved CSV; reads no dataset files")
    p.add_argument(
        "--page",
        default=None,
        help="fill the urbannav blocks of this Markdown page from the CSV (needs --csv or --from-csv, so that every "
        "sequence is filled from one file)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.page and not (args.csv or args.from_csv):
        print(
            "error: --page needs --csv or --from-csv, so that every block is filled from the same file", file=sys.stderr
        )
        return 2
    try:
        rows = rows_from_csv(args.from_csv) if args.from_csv else measure(args.root, args.sequence)
    except SequenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.csv:
        try:
            write_csv(args.csv, rows)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.page:
        page_rows = rows_from_csv(args.csv or args.from_csv)
        try:
            for name, fn in BLOCKS.items():
                write_block(args.page, name, fn(page_rows))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if not (args.csv or args.page):
        print(table_markdown(rows))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
