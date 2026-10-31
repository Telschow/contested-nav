"""How the receiver's own fix errors behave in time, against the reference, written to a CSV the page is built from.

    navkit urbannav fixerrors --sequence tunnel1 --csv docs/data/urbannav_fix_errors.csv --page docs/urbannav.md
    navkit urbannav fixerrors --sequence deepurban1 --csv docs/data/urbannav_fix_errors.csv --page docs/urbannav.md

The question is whether the receiver's fix errors are independent from one second to the next, as a filter that takes
each fix as a separate measurement assumes. No filter is involved: these are the fixes and the reference only.

* **The error** of a fix is its east and north position minus the reference interpolated to the fix time. The mean over
  the sequence (the offset) is removed first, so what is measured is the change of the error and not a constant bias.
* **The correlation at a lag** is the sum of products of the centred errors over all pairs of fixes whose time
  difference is within :data:`LAG_TOLERANCE_S` of the lag, divided by the square root of the two sums of squares of
  the same pairs. It is given per axis and pooled over both. It is the usual sample correlation, so a few large errors
  dominate it in a short sequence.
* **The effective sample size** per axis is ``navkit.eval.statistics.autocorrelation_estimate`` on the centred series
  in time order, one value per valid fix. A sequence with an outage has its fixes joined across the gap, which is not
  a regular series, and the number is then rough. The ``truncated`` flag says whether the window rule was met.

The reference is an estimate whose own error is not known, so some of a correlated difference could be in the
reference and not in the receiver. These are differences between two solutions, as in ``urbannav_check``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import urbannav_data as ud
from .eval.statistics import autocorrelation_estimate
from .recorded import SequenceError
from .report.page import write_block as _write_page_block

CSV_COLUMNS = ("sequence", "quantity", "value", "unit")
DEFAULT_ROOT = "data/raw/urbannav"
LAGS_S = (1, 10, 30, 60)
#: Pairs of fixes count for a lag when their time difference is within this many seconds of it (the epochs are 1 Hz).
LAG_TOLERANCE_S = 0.5
AXES = ("east", "north")


def fix_errors(root: str | Path, seq_name: str) -> tuple[np.ndarray, np.ndarray]:
    """``(t, error)``: the valid fixes' times on the IMU clock and their east and north error, shape ``(n, 2)``."""
    seq = ud.load_sequence(root, seq_name)
    fixes = ud.load_gga(root, seq_name)
    valid = (fixes.quality > 0) & np.isfinite(fixes.lat_deg) & np.isfinite(fixes.lon_deg)
    enu, _ = ud.llh_to_enu(fixes.lat_deg[valid], fixes.lon_deg[valid], fixes.height_m[valid], origin=seq.origin_llh)
    t = fixes.utc_s[valid] - seq.epoch_unix_s
    ref = np.column_stack([np.interp(t, seq.truth_t, seq.truth_enu[:, k]) for k in range(2)])
    return t, enu[:, :2] - ref


def lag_pairs(t: np.ndarray, lag_s: float, tolerance_s: float = LAG_TOLERANCE_S) -> tuple[np.ndarray, np.ndarray]:
    """Indices ``(i, j)`` of the pairs whose time difference ``t[j] - t[i]`` is within ``tolerance_s`` of ``lag_s``."""
    dt = t[None, :] - t[:, None]
    i, j = np.nonzero(np.abs(dt - lag_s) < tolerance_s)
    return i, j


def pair_correlation(centred: np.ndarray, i: np.ndarray, j: np.ndarray) -> float:
    """Sample correlation over the pairs ``(i, j)`` of a centred series (one axis, or both axes pooled)."""
    a, b = centred[i], centred[j]
    denom = float(np.sqrt(np.sum(a**2) * np.sum(b**2)))
    return float(np.sum(a * b) / denom) if denom > 0.0 else float("nan")


def rows_for(seq_name: str, t: np.ndarray, err: np.ndarray) -> list[dict[str, Any]]:
    """The quantities of one sequence, as CSV rows, from the fix times and their ``(n, 2)`` east and north errors."""
    offset = err.mean(axis=0)
    centred = err - offset
    rows: list[dict[str, Any]] = []

    def add(quantity: str, value: float | int, unit: str) -> None:
        shown = value if isinstance(value, int) else f"{value:.4g}"
        rows.append({"sequence": seq_name, "quantity": quantity, "value": shown, "unit": unit})

    add("fix_error_fixes", int(len(t)), "count")
    add("fix_error_lag_tolerance", LAG_TOLERANCE_S, "s")
    add("fix_error_offset_east", float(offset[0]), "m")
    add("fix_error_offset_north", float(offset[1]), "m")
    add("fix_error_rms_about_offset", float(np.sqrt(np.mean(np.sum(centred**2, axis=1)))), "m")
    for lag in LAGS_S:
        i, j = lag_pairs(t, lag)
        add(f"fix_error_pairs_lag{lag}s", int(len(i)), "count")
        if len(i) >= 2:
            for k, axis in enumerate(AXES):
                add(f"fix_error_corr_{axis}_lag{lag}s", pair_correlation(centred[:, k], i, j), "")
            add(f"fix_error_corr_pooled_lag{lag}s", pair_correlation(centred, i, j), "")
    for k, axis in enumerate(AXES):
        est = autocorrelation_estimate(centred[:, k])
        add(f"fix_error_ess_{axis}", est.effective_sample_size, "count")
        add(f"fix_error_ess_{axis}_truncated", int(est.truncated), "flag")
    return rows


def measure(root: str | Path, seq_name: str) -> list[dict[str, Any]]:
    t, err = fix_errors(root, seq_name)
    try:
        return rows_for(seq_name, t, err)
    except ValueError as exc:  # too few fixes, or a constant error series
        raise SequenceError(f"{seq_name}: {exc}") from exc


# ---------------------------------------------------------------------- output

LABELS = {
    "fix_error_fixes": "Valid fixes",
    "fix_error_lag_tolerance": "Pairs for a lag: time difference within this of the lag",
    "fix_error_offset_east": "Mean offset of the fixes from the reference, east",
    "fix_error_offset_north": "Mean offset of the fixes from the reference, north",
    "fix_error_rms_about_offset": "Horizontal root mean square of the difference about that offset",
    **{f"fix_error_pairs_lag{n}s": f"Pairs of fixes {n} s apart" for n in LAGS_S},
    **{
        f"fix_error_corr_{a}_lag{n}s": f"Correlation of the fix difference {n} s apart, {a}"
        for n in LAGS_S
        for a in (*AXES, "pooled")
    },
    **{f"fix_error_ess_{a}": f"Effective sample size of the fix difference, {a}" for a in AXES},
    **{f"fix_error_ess_{a}_truncated": f"That size is an upper bound, {a} (1 yes, 0 no)" for a in AXES},
}


def table_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Sequence | Quantity | Value | Unit |", "|---|---|---:|---|"]
    for r in rows:
        lines.append(f"| {r['sequence']} | {LABELS.get(r['quantity'], r['quantity'])} | {r['value']} | {r['unit']} |")
    return "\n".join(lines)


BLOCKS: dict[str, Callable[[list[dict[str, Any]]], str]] = {"urbannav-fix-errors": table_markdown}


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
        prog="navkit urbannav fixerrors", description="Measure how the receiver's fix errors behave in time."
    )
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--sequence", "-s", default="tunnel1")
    p.add_argument("--csv", default=None, help="write the quantities here; other sequences' rows in the file are kept")
    p.add_argument("--from-csv", default=None, help="rebuild the table from a saved CSV; reads no dataset files")
    p.add_argument("--page", default=None, help="fill the urbannav-fix-errors block (needs --csv or --from-csv)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.page and not (args.csv or args.from_csv):
        print("error: --page needs --csv or --from-csv, so that the block is filled from one file", file=sys.stderr)
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
