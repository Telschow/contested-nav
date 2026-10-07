"""Sweep the *trajectory* rather than the sensor noise, and report a distribution.

`navkit sweep seeds` varies GNSS, vision, and camera-drop noise over N seeds. That
answers "is this filter overconfident under this noise", which is a narrower
question than it looks: the trajectory is held fixed at the one in
`configs/benchmark.yaml`, so every draw replays identical motion. A result that
was really an artefact of that particular path -- a long straight excursion, a
slow turn -- would be indistinguishable from a property of the estimator.

This script varies the scene instead, using `synthetic.seeded_scene`, and holds
the noise at the configured seed. The two axes are independent, so
`navkit sweep seeds` answers a robustness question and this one answers a
generalisation question; they are complements, not replacements.

    navkit sweep scenes --seeds 8
    navkit sweep scenes --seeds 8 --markdown
    navkit sweep scenes --seeds 8 --both-seeds   # full cross product

The strongest single number in the output is `verdict_stable`: whether the
calibration verdict holds in every scene. A mean NEES that is stable while the
verdict flips between scenes is a much weaker result than either alone, and the
per-verdict counts are reported so that case cannot be hidden in an average.

Confidence intervals are bootstrapped rather than taken from a standard
deviation. With 8-10 draws the normal approximation is not defensible, and the
min/max are reported alongside so a reader can check the interval by eye rather
than trusting it.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import MEASUREMENT, default_config_path, run_case

# Number of bootstrap resamples. Large enough that the 95th percentile of the
# endpoint distribution is stable to the reported precision, small enough to
# stay instant.
_BOOTSTRAP = 10_000
_BOOTSTRAP_SEED = 20260929


def _collect(record: dict[str, Any]) -> dict[str, Any]:
    """Reduce a benchmark record to the fields this sweep reports."""
    head = record["headline"]
    cov = (head.get("coverage") or {}).get("2sigma")
    return {
        "scene_seed": record.get("scene_seed"),
        "seed": record["seed"],
        "config_hash": record["config_hash"],
        "radius_m": record["synthetic"]["radius_m"],
        "path_length_m": record.get("summary", {}).get("path_length_m"),
        "ate_rmse_m": head["ate_rmse_m"],
        "nees_mean": head.get("nees_mean"),
        "coverage_2sigma_pct": None if cov is None else cov * 100.0,
        "verdict": head.get("calibration_verdict") or "n/a",
    }


def bootstrap_ci(values: list[float], statistic: Any = np.mean, level: float = 0.95) -> dict[str, float]:
    """Percentile bootstrap CI for ``statistic`` over ``values``.

    Returns the point estimate, the interval, and how many of the resamples
    were degenerate. With very small samples a bootstrap can put a large share
    of its mass on a single observed value; ``n_distinct`` reports how many
    unique values went in, so a reader can tell a tight interval over a
    genuinely repeated quantity from a tight interval over one repeated draw.
    """
    arr = np.asarray(values, dtype=float)
    n = arr.size
    point = float(statistic(arr))
    if n < 2:
        return {"point": point, "lo": point, "hi": point, "n": n, "n_distinct": 1}
    rng = np.random.default_rng(_BOOTSTRAP_SEED)
    idx = rng.integers(0, n, size=(_BOOTSTRAP, n))
    stats = np.array([float(statistic(row)) for row in arr[idx]], dtype=float)
    lo, hi = np.percentile(stats, [(1.0 - level) / 2 * 100.0, (1.0 + level) / 2 * 100.0])
    return {
        "point": point,
        "lo": float(lo),
        "hi": float(hi),
        "n": n,
        "n_distinct": int(np.unique(arr).size),
    }


def _spread(values: list[float]) -> dict[str, Any]:
    """Range plus a bootstrapped mean CI, for one metric over the scenes."""
    ordered = sorted(values)
    out: dict[str, Any] = {
        "mean": statistics.fmean(values),
        "min": ordered[0],
        "max": ordered[-1],
        "median": statistics.median(values),
        "ci95": bootstrap_ci(values),
    }
    if len(values) > 1:
        out["stdev"] = statistics.stdev(values)
    return out


def as_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "| Case | Scenes | NEES mean (95% CI) | ATE rmse m (95% CI) | Coverage @2σ (95% CI) | Verdict stable |",
        "|---|---:|---|---|---|---|",
    ]
    for name, e in summary.items():
        # n_runs, not the NEES sample count: an estimator that reports no
        # covariance (dead reckoning) has no NEES but did run in every scene.
        n = e.get("n_runs", 0)
        nees = e.get("nees_mean")
        ate = e["ate_rmse_m"]
        cov = e.get("coverage_2sigma_pct")
        nees_s = "n/a" if nees is None else f"{nees['mean']:.1f} [{nees['ci95']['lo']:.1f}, {nees['ci95']['hi']:.1f}]"
        ate_s = f"{ate['mean']:.2f} [{ate['ci95']['lo']:.2f}, {ate['ci95']['hi']:.2f}]"
        cov_s = "n/a" if cov is None else f"{cov['mean']:.1f} [{cov['ci95']['lo']:.1f}, {cov['ci95']['hi']:.1f}]"
        stable = "yes" if e["verdict_stable"] else f"NO {e['verdict_counts']}"
        lines.append(f"| {name} | {n} | {nees_s} | {ate_s} | {cov_s} | {stable} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=Path("results") / "scene_sweep.json")
    ap.add_argument("--seeds", type=int, default=8, help="number of scenes, starting at 0")
    ap.add_argument("--only", nargs="*", default=None, help="run only these case names")
    ap.add_argument("--markdown", action="store_true", help="print a summary table")
    ap.add_argument(
        "--both-seeds",
        action="store_true",
        help="also sweep the noise seed, giving the full cross product of scenes and noise draws",
    )
    args = ap.parse_args(argv)
    if args.config is None:
        args.config = default_config_path()

    if args.seeds < 2:
        raise SystemExit("a spread needs at least 2 scenes")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    selected = args.only or list(cases)
    unknown = [k for k in selected if k not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    if args.both_seeds:
        planned: list[tuple[str, int | None, int]] = [
            (n, s, k) for n in selected for s in range(args.seeds) for k in range(args.seeds)
        ]
    else:
        planned = [(n, None, s) for n in selected for s in range(args.seeds)]

    per_case: dict[str, list[dict[str, Any]]] = {}
    for name, noise_seed, scene_seed in planned:
        rows = per_case.setdefault(name, [])
        t0 = time.perf_counter()
        rec = run_case(name, cases[name], defaults, seed=noise_seed, scene_seed=scene_seed)
        row = _collect(rec)
        row["wall_s"] = round(time.perf_counter() - t0, 3)
        rows.append(row)
        nees = row["nees_mean"]
        nees_s = "n/a" if nees is None else f"{nees:.4g}"
        cov = row["coverage_2sigma_pct"]
        cov_s = "n/a" if cov is None else f"{cov:.1f}%"
        path = row["path_length_m"]
        path_s = "n/a" if path is None else f"{path:.1f}"
        print(
            f"  {name:32s} scene={scene_seed} noise={'-' if noise_seed is None else noise_seed}  "
            f"path={path_s} m  nees={nees_s}  cov@2s={cov_s}  "
            f"ate={row['ate_rmse_m']:.3f}  verdict={row['verdict']}",
            flush=True,
        )

    summary: dict[str, Any] = {}
    for name, rows in per_case.items():
        entry: dict[str, Any] = {"n_runs": len(rows)}
        for key in ("ate_rmse_m", "nees_mean", "coverage_2sigma_pct", "path_length_m"):
            vals = [r[key] for r in rows if r[key] is not None]
            # dead_reckoning reports no covariance, so NEES and coverage are
            # genuinely absent rather than zero. Print n/a so a reader can tell
            # "not measured" from "measured and tiny".
            entry[key] = _spread(vals) if vals else None
        verdicts: dict[str, int] = {}
        for r in rows:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        entry["verdict_counts"] = verdicts
        entry["verdict_stable"] = len(verdicts) == 1
        summary[name] = entry

    payload = {
        "schema": "navkit-scene-sweep/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "Synthetic fixture with the trajectory varied across scenes. Scenes do not make a "
            "known-answer fixture a field measurement; these are not real-sensor performance "
            "and must not be presented as such."
        ),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "config_sha256": __import__("hashlib").sha256(args.config.read_bytes()).hexdigest(),
        "n_scenes": args.seeds,
        "sweeps_noise_seed": bool(args.both_seeds),
        "varies": "trajectory motion parameters (radius, turning, sway, start offsets)",
        "fixed": "duration, sample rate, and the t=0 exact initial state",
        "bootstrap": {"resamples": _BOOTSTRAP, "seed": _BOOTSTRAP_SEED, "level": 0.95},
        "summary": summary,
        "rows": per_case,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    if args.markdown:
        print()
        print(as_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
