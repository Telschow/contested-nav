"""Three sanity checks on the UrbanNav runs, as rows of a CSV written through the merge writer (issue #182).

    navkit urbannav sanity --sequence tunnel1 --csv docs/data/urbannav_sanity.csv
    navkit urbannav sanity --sequence deepurban1 --csv docs/data/urbannav_sanity.csv

The dataset is not vendored (constraint S2), so CI runs the checks on the made-up sequence only. Each setting is
declared here as a constant and is not changed after a run.

* **Clock-shift sensitivity.** The aided run is repeated with the IMU clock moved by minus and plus
  :data:`CLOCK_SHIFT_S` against the reference and the fixes, the declared variant and seed 0. It reports the horizontal
  mean NEES and the ATE RMSE of each. It applies to a sequence without an outage only: with one, the outage window
  would have to move with the clock, and the aided run is what the shift is read against.
* **The dead-reckoning bound.** The accelerometer is integrated alone for :data:`DEAD_RECKONING_S` from the first IMU
  sample, with the reference attitude (``urbannav_run.accel_only_error_m``). That is the drift the filter could not beat
  with an IMU-only stretch of that length, and it is read against the aided run's horizontal RMSE.
* **The spread of the lag-10 correlation.** The correlation of the receiver's fix errors :data:`FIX_LAG_S` seconds apart
  under several estimators (pair tolerance, centring), and the largest minus the smallest. The estimator of
  ``urbannav_fix_errors`` is one of them.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import urbannav_data as ud
from . import urbannav_fix_errors as fe
from . import urbannav_run as ur
from .recorded import EurocSequence, SequenceError

CSV_COLUMNS = ("sequence", "quantity", "value", "unit")
DEFAULT_ROOT = "data/raw/urbannav"
#: The clock shift of the sensitivity check, in seconds, applied with both signs.
CLOCK_SHIFT_S = 0.26
#: Length of the IMU-only stretch, in seconds.
DEAD_RECKONING_S = 60.0
#: The lag of the fix-error correlation, in seconds, and the pair tolerances tried (the third is the study's own).
FIX_LAG_S = 10
LAG_TOLERANCES_S = (0.25, fe.LAG_TOLERANCE_S, 1.0)
SEED = 0


def shift_imu_clock(seq: EurocSequence, shift_s: float) -> EurocSequence:
    """A copy of ``seq`` whose IMU timestamps are ``shift_s`` later. The input is not changed."""
    return dataclasses.replace(seq, imu=dataclasses.replace(seq.imu, t=seq.imu.t + shift_s))


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def clock_shift_rows(
    seq: EurocSequence, gnss: Any, spans: list[tuple[float, float]], info: dict[str, Any]
) -> list[dict[str, Any]]:
    """NEES and ATE of the aided run at shifts of ``-CLOCK_SHIFT_S``, 0 and ``+CLOCK_SHIFT_S``. Empty with an outage."""
    if spans:
        return []
    rows: list[dict[str, Any]] = []
    for name, shift in (("minus", -CLOCK_SHIFT_S), ("zero", 0.0), ("plus", CLOCK_SHIFT_S)):
        res = ur.run_once(shift_imu_clock(seq, shift), gnss, spans, info, SEED, "declared")
        rows.append({"quantity": f"clock_shift_{name}_hor_nees_mean", "value": _fmt(res["hor_nees_mean"]), "unit": ""})
        rows.append({"quantity": f"clock_shift_{name}_ate_rmse", "value": _fmt(res["ate_rmse_m"]), "unit": "m"})
    rows.insert(0, {"quantity": "clock_shift", "value": CLOCK_SHIFT_S, "unit": "s"})
    return rows


def dead_reckoning_rows(
    seq: EurocSequence, gnss: Any, spans: list[tuple[float, float]], info: dict[str, Any]
) -> list[dict[str, Any]]:
    """The accelerometer-only drift over the first ``DEAD_RECKONING_S`` against the aided horizontal RMSE."""
    t0 = float(seq.imu.t[0])
    if float(seq.imu.t[-1]) - t0 < DEAD_RECKONING_S:
        raise SequenceError(f"{seq.name}: shorter than the {DEAD_RECKONING_S:g} s dead-reckoning window")
    drift = ur.accel_only_error_m(seq, (t0, t0 + DEAD_RECKONING_S))
    aided = ur.run_once(seq, gnss, spans, info, SEED, "declared")["hor_rmse_m"]
    return [
        {"quantity": "dead_reckoning_window", "value": DEAD_RECKONING_S, "unit": "s"},
        {"quantity": "dead_reckoning_accel_only_hor_err", "value": _fmt(drift), "unit": "m"},
        {"quantity": "dead_reckoning_aided_hor_rmse", "value": _fmt(aided), "unit": "m"},
        {"quantity": "dead_reckoning_to_aided_ratio", "value": _fmt(drift / aided), "unit": ""},
    ]


def correlation_estimates(t: np.ndarray, err: np.ndarray, lag_s: float = FIX_LAG_S) -> dict[str, float]:
    """The lag correlation of the ``(n, 2)`` fix errors under each estimator, by name. Empty without pairs."""
    centred = err - err.mean(axis=0)
    out: dict[str, float] = {}
    for tol in LAG_TOLERANCES_S:
        i, j = fe.lag_pairs(t, lag_s, tol)
        if len(i) < 2:
            continue
        out[f"pooled_tol{tol:g}"] = fe.pair_correlation(centred, i, j)
        if tol == fe.LAG_TOLERANCE_S:
            out["mean_of_axes"] = float(np.mean([fe.pair_correlation(centred[:, k], i, j) for k in range(2)]))
            # Each side of the pairs is centred on its own mean instead of the mean of the whole series.
            a, b = err[i] - err[i].mean(axis=0), err[j] - err[j].mean(axis=0)
            denom = float(np.sqrt(np.sum(a**2) * np.sum(b**2)))
            if denom > 0.0:
                out["pooled_pair_centred"] = float(np.sum(a * b) / denom)
    return out


def fix_correlation_rows(t: np.ndarray, err: np.ndarray) -> list[dict[str, Any]]:
    est = correlation_estimates(t, err)
    if not est:
        raise SequenceError(f"no pairs of fixes {FIX_LAG_S} s apart")
    rows: list[dict[str, Any]] = [{"quantity": "fix_corr_lag", "value": FIX_LAG_S, "unit": "s"}]
    rows += [{"quantity": f"fix_corr_lag{FIX_LAG_S}s_{k}", "value": _fmt(v), "unit": ""} for k, v in est.items()]
    vals = list(est.values())
    rows.append({"quantity": f"fix_corr_lag{FIX_LAG_S}s_min", "value": _fmt(min(vals)), "unit": ""})
    rows.append({"quantity": f"fix_corr_lag{FIX_LAG_S}s_max", "value": _fmt(max(vals)), "unit": ""})
    rows.append({"quantity": f"fix_corr_lag{FIX_LAG_S}s_spread", "value": _fmt(max(vals) - min(vals)), "unit": ""})
    return rows


def measure(root: str | Path, seq_name: str) -> list[dict[str, Any]]:
    """All three checks as CSV rows."""
    seq, gnss, spans, info = ur.build(root, seq_name)
    t, err = fe.fix_errors(root, seq_name)
    rows = clock_shift_rows(seq, gnss, spans, info) + dead_reckoning_rows(seq, gnss, spans, info)
    rows += fix_correlation_rows(t, err)
    return [{"sequence": seq_name, **r} for r in rows]


TABLE = ud.csv_table(CSV_COLUMNS)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit urbannav sanity", description="Clock-shift, dead-reckoning and correlation sanity checks."
    )
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--sequence", "-s", default="tunnel1")
    p.add_argument("--csv", default=None, help="write the rows here; other sequences' rows in the file are kept")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = measure(args.root, args.sequence)
    except SequenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.csv:
        try:
            TABLE.merge(args.csv, rows)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.csv}", file=sys.stderr)
    else:
        print("\n".join(f"{r['sequence']},{r['quantity']},{r['value']},{r['unit']}" for r in rows))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
