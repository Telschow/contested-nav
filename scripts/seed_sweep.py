#!/usr/bin/env python
"""Repeat a benchmark across independent seeds and report the spread.

Every number in README.md and docs/ comes from a single draw. ``configs/benchmark.yaml``
pins each case to ``seed: 0``, so a result like mean NEES 419.4 is one sample of a
stochastic process, not a measured property of the filter. This script re-runs the
selected cases over N seeds and reports the distribution, so the difference between
"this configuration overconfidently collapses coverage" and "this one fixture
happened to" is settled by measurement rather than assumed either way.

    python scripts/seed_sweep.py --seeds 10
    python scripts/seed_sweep.py --seeds 10 --only outage_visual --markdown

It reuses ``run_case`` from ``run_benchmark.py`` rather than reimplementing the
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_benchmark import MEASUREMENT, ROOT, _jsonable, run_case

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
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "benchmark.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "seed_sweep.json")
    ap.add_argument("--seeds", type=int, default=10, help="number of seeds, starting at 0")
    ap.add_argument("--only", nargs="*", default=None, help="run only these case names")
    ap.add_argument("--markdown", action="store_true", help="print a summary table")
    args = ap.parse_args(argv)

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
    for name in selected:
        rows: list[dict[str, Any]] = []
        for seed in range(args.seeds):
            t0 = time.perf_counter()
            rec = run_case(name, cases[name], defaults, seed=seed)
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
        "config_file": str(args.config.relative_to(ROOT)),
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
    try:
        shown = args.out.relative_to(ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown}", file=sys.stderr)

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
