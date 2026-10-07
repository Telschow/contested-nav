"""Sweep the GNSS outage window: when it starts and how long it lasts.

The benchmark has one outage (5 s to 20 s). Everything it says about visual aiding
through a denial is therefore a statement about a 15 s outage that begins 5 s in. This
sweep asks whether the headline finding, that vision improves position error but the
filter's reported uncertainty collapses, holds when the outage is shorter, longer or
later, and whether the no-vision control stays calibrated across the same grid.

    navkit sweep outages
    navkit sweep outages --starts 5 10 --durations 5 10 15 20 --seeds 5 --markdown
    navkit sweep outages --csv results/outage_sweep.csv --figure docs/figures/outage-sweep.png

Each cell of the grid is one (case, outage start, outage duration) and is repeated over
N noise seeds; the table reports the mean with a percentile-bootstrap 95% interval. Only
the outage window changes, so a difference between cells is a difference in the outage.
Combinations whose window runs past the end of the scenario are skipped and listed.

The output is synthetic. A sweep over a known-answer fixture does not make it a field
measurement, so the payload carries the same disclaimer and ``claim_type`` as
``results/benchmark.json``. With few seeds the bootstrap interval is a rough guide, not
a guarantee: ``n`` and ``n_distinct`` are reported beside it so that is visible.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import MEASUREMENT, _config_label, _jsonable, default_config_path, run_case
from .scene_sweep import bootstrap_ci

DEFAULT_CASES = ("outage_control", "outage_visual")
DEFAULT_STARTS = (5.0, 10.0)
DEFAULT_DURATIONS = (5.0, 10.0, 15.0, 20.0)
METRICS = ("ate_rmse_m", "nees_mean", "coverage_2sigma_pct", "claimed_sigma_p_m")

#: Column order of the CSV: one row per grid cell.
CSV_FIELDS = (
    "case",
    "start_s",
    "duration_s",
    "end_s",
    "n_seeds",
    "ate_rmse_m_mean",
    "ate_rmse_m_lo",
    "ate_rmse_m_hi",
    "nees_mean_mean",
    "nees_mean_lo",
    "nees_mean_hi",
    "coverage_2sigma_pct_mean",
    "coverage_2sigma_pct_lo",
    "coverage_2sigma_pct_hi",
    "claimed_sigma_p_m_mean",
    "verdicts",
)


def _collect(record: dict[str, Any]) -> dict[str, Any]:
    head = record["headline"]
    cov = (head.get("coverage") or {}).get("2sigma")
    return {
        "seed": record["seed"],
        "config_hash": record["config_hash"],
        "ate_rmse_m": head["ate_rmse_m"],
        "nees_mean": head.get("nees_mean"),
        "coverage_2sigma_pct": None if cov is None else cov * 100.0,
        "claimed_sigma_p_m": head.get("claimed_sigma_p_m"),
        "verdict": head.get("calibration_verdict") or "n/a",
    }


def _interval(values: list[float]) -> dict[str, Any]:
    ci = bootstrap_ci(values)
    return {
        "mean": statistics.fmean(values),
        "lo": ci["lo"],
        "hi": ci["hi"],
        "n": ci["n"],
        "n_distinct": ci["n_distinct"],
    }


def summarise_cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse the per-seed rows of one grid cell into mean, interval and verdict counts."""
    out: dict[str, Any] = {"n_seeds": len(rows)}
    for metric in METRICS:
        values = [r[metric] for r in rows if r[metric] is not None]
        out[metric] = _interval(values) if values else None
    verdicts: dict[str, int] = {}
    for r in rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    out["verdicts"] = dict(sorted(verdicts.items()))
    return out


def plan_grid(
    cases: list[str], starts: list[float], durations: list[float], scenario_duration_s: float
) -> tuple[list[tuple[str, float, float]], list[tuple[float, float]]]:
    """Return the cells to run and the (start, duration) pairs skipped for overrunning the scenario."""
    windows = [(s, d) for s in starts for d in durations]
    skipped = [(s, d) for s, d in windows if s + d > scenario_duration_s]
    kept = [(c, s, d) for c in cases for s, d in windows if s + d <= scenario_duration_s]
    return kept, skipped


def with_outage(case: dict[str, Any], start_s: float, duration_s: float) -> dict[str, Any]:
    """Copy of ``case`` whose only GNSS outage is the given window."""
    out = copy.deepcopy(case)
    out.setdefault("scenario", {})["gnss_outages"] = [
        {"start_s": float(start_s), "duration_s": float(duration_s), "reason": "contested"}
    ]
    return out


def write_csv(path: Path, cells: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for cell in cells:
            row: dict[str, Any] = {
                "case": cell["case"],
                "start_s": cell["start_s"],
                "duration_s": cell["duration_s"],
                "end_s": cell["start_s"] + cell["duration_s"],
                "n_seeds": cell["n_seeds"],
                "verdicts": ";".join(f"{k}={v}" for k, v in cell["verdicts"].items()),
            }
            for metric in METRICS:
                m = cell[metric]
                if metric == "claimed_sigma_p_m":
                    row[f"{metric}_mean"] = None if m is None else m["mean"]
                    continue
                for key in ("mean", "lo", "hi"):
                    row[f"{metric}_{key}"] = None if m is None else m[key]
            writer.writerow(row)


def as_markdown(cells: list[dict[str, Any]]) -> str:
    lines = [
        "| Case | Start s | Duration s | ATE rmse m [95% CI] | NEES mean [95% CI] "
        "| Coverage @2σ % [95% CI] | Verdicts |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for c in cells:
        ate, nees, cov = c["ate_rmse_m"], c["nees_mean"], c["coverage_2sigma_pct"]
        verdicts = ", ".join(f"{k} x{v}" for k, v in c["verdicts"].items())
        nees_s = "n/a" if nees is None else f"{nees['mean']:.1f} [{nees['lo']:.1f}, {nees['hi']:.1f}]"
        cov_s = "n/a" if cov is None else f"{cov['mean']:.1f} [{cov['lo']:.1f}, {cov['hi']:.1f}]"
        lines.append(
            f"| {c['case']} | {c['start_s']:g} | {c['duration_s']:g} | "
            f"{ate['mean']:.2f} [{ate['lo']:.2f}, {ate['hi']:.2f}] | {nees_s} | {cov_s} | {verdicts} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="navkit sweep outages", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=Path("results") / "outage_sweep.json")
    ap.add_argument("--csv", type=Path, default=None, help="also write one row per grid cell to this CSV")
    ap.add_argument("--figure", type=Path, default=None, help="also render the sweep figure to this PNG")
    ap.add_argument(
        "--cases", nargs="+", default=list(DEFAULT_CASES), help="cases to run (default: control and visual)"
    )
    ap.add_argument("--starts", nargs="+", type=float, default=list(DEFAULT_STARTS), help="outage start times, s")
    ap.add_argument("--durations", nargs="+", type=float, default=list(DEFAULT_DURATIONS), help="outage lengths, s")
    ap.add_argument("--seeds", type=int, default=5, help="noise seeds per cell, starting at 0")
    ap.add_argument("--markdown", action="store_true", help="print a summary table")
    args = ap.parse_args(argv)
    config_given = args.config is not None
    if args.config is None:
        args.config = default_config_path()

    if args.seeds < 2:
        raise SystemExit("a spread needs at least 2 seeds")
    if any(s < 0 for s in args.starts) or any(d <= 0 for d in args.durations):
        raise SystemExit("outage starts must be >= 0 and durations > 0")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    unknown = [c for c in args.cases if c not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    scenario_duration = float(defaults.get("synthetic", {}).get("duration_s", 30.0))
    grid, skipped = plan_grid(args.cases, args.starts, args.durations, scenario_duration)
    if not grid:
        raise SystemExit(f"every outage window overruns the {scenario_duration:g} s scenario")

    cells: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for name, start, duration in grid:
        case = with_outage(cases[name], start, duration)
        rows = []
        t0 = time.perf_counter()
        for seed in range(args.seeds):
            row = _collect(run_case(name, case, defaults, seed=seed))
            rows.append(row)
            runs.append({"case": name, "start_s": start, "duration_s": duration, **row})
        cell = {"case": name, "start_s": start, "duration_s": duration, **summarise_cell(rows)}
        cells.append(cell)
        print(
            f"ran {name} outage {start:g}+{duration:g} s over {args.seeds} seeds ({time.perf_counter() - t0:.1f} s)",
            file=sys.stderr,
            flush=True,
        )

    payload = {
        "schema": "navkit-outage-sweep/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "Synthetic fixture with the GNSS outage window varied. Multiple outage windows and seeds do not "
            "make a known-answer fixture a field measurement; these are not real-sensor performance and must "
            "not be presented as such."
        ),
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "config_file": _config_label(args.config, config_given),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "n_seeds": args.seeds,
        "scenario_duration_s": scenario_duration,
        "starts_s": args.starts,
        "durations_s": args.durations,
        "skipped_windows": [{"start_s": s, "duration_s": d} for s, d in skipped],
        "varies": "GNSS outage start time and duration, and the noise seed",
        "does_not_vary": (
            "Trajectory, scenario duration, sensor models, estimator tuning, and the camera: each case keeps the "
            "visual configuration it has in the benchmark. Everything is one synthetic path."
        ),
        "summary": cells,
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    if args.csv is not None:
        write_csv(args.csv, cells)
        print(f"wrote {args.csv}", file=sys.stderr)
    if skipped:
        listed = ", ".join(f"{s:g}+{d:g}" for s, d in skipped)
        print(f"skipped (window overruns the {scenario_duration:g} s scenario): {listed}", file=sys.stderr)
    if args.figure is not None:
        from .figures import fig_outage_sweep

        made = fig_outage_sweep(cells, args.figure)
        print(f"wrote {made}", file=sys.stderr)
    if args.markdown:
        print()
        print(as_markdown(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
