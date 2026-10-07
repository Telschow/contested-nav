"""Sweep how wrong the filter's noise model is: tell it a sensor is better or worse than it is.

Every calibrated result in the benchmark has the filter told the true sensor noise. That is
the easiest possible case for a Kalman filter, and a real filter never gets it. This sweep
generates the data once with the scenario's true noise and filters it with the assumed
GNSS and vision sigmas multiplied by a factor. A factor below 1 makes the filter trust the
sensor more than it should; above 1, less.

    navkit sweep mismatch
    navkit sweep mismatch --scales 0.5 1 2 --seeds 5 --markdown
    navkit sweep mismatch --csv docs/data/mismatch_sweep.csv --figure docs/figures/mismatch-sweep.png \
        --page docs/mismatch.md

Each cell is one (case, factor) repeated over N noise seeds; the table reports the mean
with a percentile-bootstrap 95% interval. Only the filter's assumed noise changes, so a
difference between cells is a difference in the mismatch.

The output is synthetic. A sweep over a known-answer fixture does not make it a field
measurement, so the payload carries the same disclaimer and ``claim_type`` as
``results/benchmark.json``. With few seeds the interval is a rough guide, not a guarantee:
``n`` and ``n_distinct`` are reported beside it.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import MEASUREMENT, _config_label, _jsonable, default_config_path, run_case
from .outage_sweep import METRICS, _collect, _interval, summarise_cell

DEFAULT_CASES = ("gnss_only", "outage_control")
DEFAULT_SCALES = (0.25, 0.5, 0.7, 0.8, 0.9, 1.0, 1.25, 2.0, 4.0)
CHANNELS = ("gnss", "vision", "both")

#: Coverage band used to say where a filter stops being usable. It is an analyst's choice
#: and is printed with every result that uses it; it is not derived from the data.
DEFAULT_MIN_COVERAGE_PCT = 90.0

#: Column order of the CSV: one row per (case, factor).
CSV_FIELDS = (
    "case",
    "scale",
    "channel",
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
    "gnss_rejected_pct_mean",
    "gnss_rejected_pct_lo",
    "gnss_rejected_pct_hi",
    "verdicts",
)


def collect(record: dict[str, Any]) -> dict[str, Any]:
    """One run's metrics: the sweep metrics plus the share of GNSS fixes the filter rejected."""
    row = _collect(record)
    stats = record["stats"]
    seen = stats.get("gnss_fixes_seen", 0.0)
    row["gnss_rejected_pct"] = None if not seen else 100.0 * stats.get("gnss_updates_rejected", 0.0) / seen
    return row


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """:func:`summarise_cell` plus the interval of the GNSS rejection share."""
    out = summarise_cell(rows)
    values = [r["gnss_rejected_pct"] for r in rows if r["gnss_rejected_pct"] is not None]
    out["gnss_rejected_pct"] = _interval(values) if values else None
    return out


def with_scale(case: dict[str, Any], scale: float, channel: str) -> dict[str, Any]:
    """Copy of ``case`` whose filter assumes noise multiplied by ``scale`` on ``channel``."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")
    if not scale > 0.0:
        raise ValueError(f"scale must be positive, got {scale!r}")
    out = copy.deepcopy(case)
    est = out.setdefault("estimator", {})
    if channel in ("gnss", "both"):
        est["gnss_sigma_scale"] = float(scale)
    if channel in ("vision", "both"):
        est["vision_sigma_scale"] = float(scale)
    return out


def cell_row(cell: dict[str, Any], channel: str) -> dict[str, Any]:
    """The flat record of one cell, as written to the CSV."""
    row: dict[str, Any] = {
        "case": cell["case"],
        "scale": cell["scale"],
        "channel": channel,
        "n_seeds": cell["n_seeds"],
        "verdicts": ";".join(f"{k}={v}" for k, v in cell["verdicts"].items()),
    }
    for metric in (*METRICS, "gnss_rejected_pct"):
        m = cell[metric]
        if metric == "claimed_sigma_p_m":
            row[f"{metric}_mean"] = None if m is None else m["mean"]
            continue
        for key in ("mean", "lo", "hi"):
            row[f"{metric}_{key}"] = None if m is None else m[key]
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, Any]]:
    """Read a CSV written by :func:`write_csv`; empty cells come back as ``None``."""
    with path.open(newline="", encoding="utf-8") as f:
        out = []
        for raw in csv.DictReader(f):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if key in ("case", "channel", "verdicts"):
                    row[key] = value
                elif key == "n_seeds":
                    row[key] = int(value)
                else:
                    row[key] = None if value == "" else float(value)
            out.append(row)
    return out


def compare_rows(
    got: list[dict[str, Any]], want: list[dict[str, Any]], rel_tol: float = 1e-6, abs_tol: float = 1e-9
) -> list[str]:
    """Differences between two CSV-shaped row lists; empty when they agree.

    Numbers are compared with a tolerance because two platforms can differ in the last bits
    (ADR-0009). Text, the row count and the order must match exactly.
    """
    if len(got) != len(want):
        return [f"row count {len(got)} != {len(want)}"]
    problems: list[str] = []
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        for key in CSV_FIELDS:
            a, b = g.get(key), w.get(key)
            if isinstance(a, float) and isinstance(b, float):
                if abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b))):
                    problems.append(f"row {i} {key}: {a!r} != {b!r}")
            elif a != b:
                problems.append(f"row {i} {key}: {a!r} != {b!r}")
    return problems


def _fmt(row: dict[str, Any], metric: str, digits: int) -> str:
    mean = row[f"{metric}_mean"]
    if mean is None:
        return "n/a"
    return f"{mean:.{digits}f} [{row[f'{metric}_lo']:.{digits}f}, {row[f'{metric}_hi']:.{digits}f}]"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """The table shown on the mismatch page, built from CSV-shaped rows."""
    columns = (
        "Case",
        "Assumed noise x",
        "ATE rmse m [95% CI]",
        "NEES mean [95% CI]",
        "Coverage @2σ % [95% CI]",
        "Claimed 1σ m",
        "GNSS fixes rejected % [95% CI]",
        "Verdicts",
    )
    lines = [
        "| " + " | ".join(columns) + " |",
        "|---|---:|---|---|---|---:|---|---|",
    ]
    for r in rows:
        claimed = r["claimed_sigma_p_m_mean"]
        claimed_s = "n/a" if claimed is None else f"{claimed:.3f}"
        verdicts = r["verdicts"].replace(";", ", ").replace("=", " x")
        lines.append(
            f"| {r['case']} | {r['scale']:g} | {_fmt(r, 'ate_rmse_m', 2)} | {_fmt(r, 'nees_mean', 1)} "
            f"| {_fmt(r, 'coverage_2sigma_pct', 1)} | {claimed_s} | {_fmt(r, 'gnss_rejected_pct', 1)} | {verdicts} |"
        )
    return "\n".join(lines)


PAGE_START, PAGE_END = "<!-- mismatch:start -->", "<!-- mismatch:end -->"


def splice_table(page: str, table: str) -> str:
    """Replace the generated block of the mismatch page with ``table``."""
    if PAGE_START not in page or PAGE_END not in page:
        raise ValueError(f"the page needs {PAGE_START} ... {PAGE_END} markers")
    head, rest = page.split(PAGE_START, 1)
    _, tail = rest.split(PAGE_END, 1)
    return f"{head}{PAGE_START}\n\n{table}\n\n{PAGE_END}{tail}"


def tolerance(rows: list[dict[str, Any]], min_coverage_pct: float) -> dict[str, dict[str, list[float]]]:
    """Per case, the factors whose mean 2-sigma coverage is at or above the band, and those below."""
    out: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        entry = out.setdefault(r["case"], {"within": [], "outside": []})
        cov = r["coverage_2sigma_pct_mean"]
        key = "within" if cov is not None and cov >= min_coverage_pct else "outside"
        entry[key].append(r["scale"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="navkit sweep mismatch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=Path("results") / "mismatch_sweep.json")
    ap.add_argument("--csv", type=Path, default=None, help="also write one row per (case, factor) to this CSV")
    ap.add_argument("--figure", type=Path, default=None, help="also render the sweep figure to this PNG")
    ap.add_argument("--page", type=Path, default=None, help="rewrite the generated table block in this page")
    ap.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES), help="cases to run (default: two GNSS cases)")
    ap.add_argument(
        "--scales", nargs="+", type=float, default=list(DEFAULT_SCALES), help="factors on the assumed noise"
    )
    ap.add_argument(
        "--channel",
        choices=CHANNELS,
        default="both",
        help="which sensor's assumed noise to scale (a channel a case does not use has no effect)",
    )
    ap.add_argument("--seeds", type=int, default=5, help="noise seeds per cell, starting at 0")
    ap.add_argument(
        "--min-coverage",
        type=float,
        default=DEFAULT_MIN_COVERAGE_PCT,
        help="2-sigma coverage band, %% (an analyst's choice, printed with the result)",
    )
    ap.add_argument("--markdown", action="store_true", help="print a summary table")
    ap.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="after the run, exit 1 unless the result matches this committed CSV (numbers within 1e-6)",
    )
    args = ap.parse_args(argv)
    config_given = args.config is not None
    if args.config is None:
        args.config = default_config_path()

    if args.seeds < 2:
        raise SystemExit("a spread needs at least 2 seeds")
    if any(not s > 0 for s in args.scales):
        raise SystemExit("scales must be positive")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    unknown = [c for c in args.cases if c not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    cells: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for name in args.cases:
        for scale in args.scales:
            case = with_scale(cases[name], scale, args.channel)
            rows = []
            t0 = time.perf_counter()
            for seed in range(args.seeds):
                row = collect(run_case(name, case, defaults, seed=seed))
                rows.append(row)
                runs.append({"case": name, "scale": scale, **row})
            cells.append({"case": name, "scale": scale, **summarise(rows)})
            print(
                f"ran {name} with assumed noise x{scale:g} over {args.seeds} seeds ({time.perf_counter() - t0:.1f} s)",
                file=sys.stderr,
                flush=True,
            )

    flat = [cell_row(c, args.channel) for c in cells]
    payload = {
        "schema": "navkit-mismatch-sweep/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "Synthetic fixture with the filter's assumed sensor noise varied. A mismatch sweep over a known-answer "
            "fixture is not a field measurement and must not be presented as real-sensor performance."
        ),
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "config_file": _config_label(args.config, config_given),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "n_seeds": args.seeds,
        "channel": args.channel,
        "scales": args.scales,
        "varies": "the sensor noise the filter assumes (the generator keeps the true noise), and the noise seed",
        "does_not_vary": (
            "Trajectory, outage window, IMU noise, the camera, or the filter's IMU noise model: only the assumed "
            "GNSS and vision sigmas are scaled. Everything is one synthetic path."
        ),
        "min_coverage_pct": args.min_coverage,
        "min_coverage_note": "an analyst's choice, not derived from the data",
        "tolerance": tolerance(flat, args.min_coverage),
        "summary": cells,
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    if args.csv is not None:
        write_csv(args.csv, flat)
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        page_text = splice_table(args.page.read_text(encoding="utf-8"), markdown_table(flat))
        args.page.write_text(page_text, encoding="utf-8")
        print(f"wrote {args.page}", file=sys.stderr)
    if args.figure is not None:
        from .figures import fig_mismatch_sweep

        made = fig_mismatch_sweep(cells, args.figure)
        print(f"wrote {made}", file=sys.stderr)
    for case_name, band in payload["tolerance"].items():
        print(
            f"{case_name}: mean 2-sigma coverage at or above {args.min_coverage:g}% for assumed noise x"
            f"{', x'.join(f'{s:g}' for s in band['within']) or 'none'}; below it for x"
            f"{', x'.join(f'{s:g}' for s in band['outside']) or 'none'}",
            file=sys.stderr,
        )
    if args.markdown:
        print()
        print(markdown_table(flat))
    if args.compare is not None:
        # Compare what a reader of the CSV would see, so a number that survives the round
        # trip through text is the one that is checked.
        tmp = args.out.with_suffix(".compare.csv")
        write_csv(tmp, flat)
        try:
            problems = compare_rows(read_csv(tmp), read_csv(args.compare))
        finally:
            tmp.unlink(missing_ok=True)
        if problems:
            print(f"result differs from {args.compare}:", file=sys.stderr)
            for p in problems[:10]:
                print(f"  {p}", file=sys.stderr)
            return 1
        print(f"result matches {args.compare}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
