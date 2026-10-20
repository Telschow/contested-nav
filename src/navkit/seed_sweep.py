"""Repeat a benchmark across independent seeds and report the spread.

Every number in README.md and docs/ comes from a single draw. ``configs/benchmark.yaml``
pins each case to ``seed: 0``, so a result like the seed-0 mean NEES of an anchor row is one sample of a
stochastic process, with one start draw (ADR-0027), not a measured property of the filter. This script re-runs the
selected cases over N seeds and reports the distribution, so the difference between
"this configuration overconfidently collapses coverage" and "this one fixture
happened to" is settled by measurement rather than assumed either way.

    navkit sweep seeds --seeds 10
    navkit sweep seeds --seeds 10 --only outage_visual --markdown

It reuses ``run_case`` from :mod:`navkit.benchmark` rather than reimplementing the
pipeline, so the sweep cannot drift away from what the committed benchmark
measures. The baseline seed is still included by default: the committed numbers
must remain reproducible, and a sweep that silently dropped the published draw
would make the comparison harder, not easier.

The output is still synthetic. More seeds do not make a known-answer fixture into
a field measurement, so the payload carries the same disclaimer and ``claim_type``
as ``results/benchmark.json`` and must never be cited as real-sensor performance.
"""

from __future__ import annotations

import argparse
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
from .ensemble import Collector, compare_rows, csv_text, markdown_table, parse_csv, splice_table

# Fields worth spreading. ATE and NEES and coverage are the three the docs quote,
# and they fail differently: ATE is a physical error, NEES is calibration, and
# coverage is the claim the consumer actually acts on.
METRICS = ("ate_rmse_m", "nees_mean", "coverage_2sigma_pct")


def _collect(record: dict[str, Any]) -> dict[str, Any]:
    head = record["headline"]
    # dead_reckoning has no covariance, and the benchmark then omits the key
    # entirely (``coverage`` is None, not {}), so absent has to be handled as
    # "not measured" rather than dereferenced.
    cov = (head.get("coverage") or {}).get("2sigma")
    verdict = head.get("calibration_verdict")
    return {
        "seed": record["seed"],
        "config_hash": record["config_hash"],
        "ate_rmse_m": head["ate_rmse_m"],
        "nees_mean": head.get("nees_mean"),
        "coverage_2sigma_pct": None if cov is None else cov * 100.0,
        "verdict": verdict or "n/a",
    }


def _spread(values: list[float]) -> dict[str, float]:
    """Summary of a sample. A stddev over 10 draws is weak, so the range is
    reported too: it is the number a reader can check by eye."""
    ordered = sorted(values)
    out: dict[str, float] = {
        "mean": statistics.fmean(values),
        "min": ordered[0],
        "max": ordered[-1],
        "median": statistics.median(values),
    }
    if len(values) > 1:
        out["stdev"] = statistics.stdev(values)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=Path("results") / "seed_sweep.json")
    ap.add_argument("--seeds", type=int, default=10, help="number of seeds, starting at 0")
    ap.add_argument("--only", nargs="*", default=None, help="run only these case names")
    ap.add_argument("--markdown", action="store_true", help="print a summary table")
    ap.add_argument(
        "--ensemble-csv",
        type=Path,
        default=None,
        help="also write the ensemble NEES over the seeds, with its chi-square band, to this CSV (navkit.ensemble)",
    )
    ap.add_argument(
        "--ensemble-page",
        type=Path,
        default=None,
        help="with --ensemble-csv: write the table between the ensemble markers of this page",
    )
    ap.add_argument(
        "--ensemble-compare",
        type=Path,
        default=None,
        help="exit 1 if the ensemble differs from this committed CSV (text and integers exactly, floats to 1e-6)",
    )
    args = ap.parse_args(argv)
    config_given = args.config is not None
    if args.config is None:
        args.config = default_config_path()

    if args.seeds < 2:
        raise SystemExit("a spread needs at least 2 seeds")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    selected = args.only or list(cases)
    unknown = [k for k in selected if k not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    per_case: dict[str, list[dict[str, Any]]] = {}
    collector = Collector()
    for name in selected:
        rows: list[dict[str, Any]] = []
        for seed in range(args.seeds):
            t0 = time.perf_counter()
            nees_box: dict[str, Any] = {}
            rec = run_case(name, cases[name], defaults, seed=seed, nees_out=nees_box)
            collector.add(name, nees_box)
            row = _collect(rec)
            row["wall_s"] = round(time.perf_counter() - t0, 3)
            rows.append(row)
            # dead_reckoning reports no covariance, so NEES and coverage are
            # genuinely absent rather than zero. Print n/a so a reader can tell
            # "not measured" from "measured and tiny".
            nees_v = row["nees_mean"]
            nees_s = "n/a" if nees_v is None else f"{nees_v:.4g}"
            cov_pct = row["coverage_2sigma_pct"]
            cov_s = "n/a" if cov_pct is None else f"{cov_pct:.1f}%"
            print(
                f"  {name} seed={seed}  ate={row['ate_rmse_m']:.3f} m  "
                f"nees={nees_s}  cov@2s={cov_s}  verdict={row['verdict']}",
                file=sys.stderr,
                flush=True,
            )
        per_case[name] = rows
        print(f"ran {name} over {len(rows)} seeds", file=sys.stderr, flush=True)

    summary: dict[str, Any] = {}
    for name, rows in per_case.items():
        entry: dict[str, Any] = {}
        for metric in METRICS:
            vals = [r[metric] for r in rows if r[metric] is not None]
            if vals:
                entry[metric] = _spread(vals)
        verdicts: dict[str, int] = {}
        for r in rows:
            verdicts[r["verdict"] or "n/a"] = verdicts.get(r["verdict"] or "n/a", 0) + 1
        entry["verdict_counts"] = verdicts
        # The single most useful stability question: did the calibration verdict
        # flip across seeds? A mean NEES that is stable but a verdict that flips
        # means the number alone would mislead a reader.
        entry["verdict_stable"] = len(verdicts) == 1
        # The seed-0 config hash, so a reader can line the sweep's first draw up
        # against the single-draw benchmark. It is a label, not a verification.
        entry["seed0_config_hash"] = rows[0]["config_hash"]
        summary[name] = entry

    payload = {
        "schema": "navkit-seed-sweep/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "Synthetic fixture repeated across seeds. Multiple seeds do not make a "
            "known-answer fixture a field measurement; these are not real-sensor "
            "performance and must not be presented as such."
        ),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "config_file": _config_label(args.config, config_given),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "n_seeds": args.seeds,
        "seeds": list(range(args.seeds)),
        "varies": (
            "Sensor noise realisations only: GNSS, vision and camera-drop streams. "
            "The reference trajectory is the analytic one in synthetic.py, which takes "
            "no seed, so every seed replays the same 30 s motion. These numbers therefore "
            "bound sensitivity to noise on ONE scene, and say nothing about whether the "
            "result generalises to different motions, paths or outage timings."
        ),
        "does_not_vary": (
            "Trajectory geometry, manoeuvre amplitudes, timing and duration of the GNSS "
            "outage, and estimator tuning. Generalising N10 to multiple synthetic scenes "
            "still needs a scene parameter sweep."
        ),
        "summary": summary,
        "runs": per_case,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}", file=sys.stderr)
    if args.ensemble_csv is not None:
        args.ensemble_csv.parent.mkdir(parents=True, exist_ok=True)
        args.ensemble_csv.write_text(csv_text(collector.rows()), encoding="utf-8")
        print(f"wrote {args.ensemble_csv}", file=sys.stderr)
        if args.ensemble_page is not None:
            page = args.ensemble_page.read_text(encoding="utf-8")
            args.ensemble_page.write_text(splice_table(page, markdown_table(collector.rows())), encoding="utf-8")
            print(f"wrote the ensemble table into {args.ensemble_page}", file=sys.stderr)
    if args.ensemble_compare is not None:
        problems = compare_rows(collector.rows(), parse_csv(args.ensemble_compare.read_text(encoding="utf-8")))
        if problems:
            print(f"the ensemble differs from {args.ensemble_compare}:", file=sys.stderr)
            for line in problems[:20]:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"the ensemble matches {args.ensemble_compare}", file=sys.stderr)

    if args.markdown:
        print()
        print(as_markdown(summary))
    return 0


def as_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "| Case | NEES mean | NEES range | ATE rmse range | Coverage @2σ | Verdict stable |",
        "|---|---:|---|---:|---|---|",
    ]
    for name, e in summary.items():
        nees = e.get("nees_mean", {})
        ate = e.get("ate_rmse_m", {})
        cov = e.get("coverage_2sigma_pct", {})
        verdict = "yes" if e["verdict_stable"] else f"NO {e['verdict_counts']}"
        lines.append(
            f"| {name} | {nees.get('mean', float('nan')):.1f} | "
            f"{nees.get('min', float('nan')):.1f}–{nees.get('max', float('nan')):.1f} | "
            f"{ate.get('min', float('nan')):.2f}–{ate.get('max', float('nan')):.2f} m | "
            f"{cov.get('min', float('nan')):.0f}–{cov.get('max', float('nan')):.0f}% | {verdict} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
