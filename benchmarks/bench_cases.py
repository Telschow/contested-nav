#!/usr/bin/env python
"""Time the benchmark scenarios, with the spread, so a speed claim has a number behind it.

For each case this runs ``run_case`` (the same code path as ``navkit run``) once as an
untimed warm-up and then ``--repeats`` times, and reports the wall time of the whole case
and the estimator's own run time. The estimator time is what the result record already
carries as ``runtime_s``; the rest of the wall time is trajectory synthesis, the sensor
models, the metrics and the calibration scoring.

    python benchmarks/bench_cases.py                      # all cases, 5 repeats
    python benchmarks/bench_cases.py --only outage_visual --repeats 10
    python benchmarks/bench_cases.py --out results/performance.json

What this does and does not say. Times are for one machine and one Python build, and the
JSON records both. Medians are reported with the minimum, maximum and standard deviation
because a single number hides the spread, and the spread on a shared or cloud machine is
not small. The numbers compare runs of this script on the same machine; they are not a
statement about any real-time target, which this project does not have.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_benchmark() -> Any:
    """Load ``scripts/run_benchmark.py`` by path, so this works from a source checkout."""
    spec = importlib.util.spec_from_file_location("run_benchmark", ROOT / "scripts" / "run_benchmark.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def _cpu_model() -> str:
    """The CPU model from ``/proc/cpuinfo`` where it exists, else what ``platform`` reports."""
    fallback = platform.processor() or "unknown"
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
    except OSError:
        return fallback  # not Linux, or /proc is not mounted
    for line in lines:
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return fallback


def environment() -> dict[str, Any]:
    """What the numbers were measured on."""
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu": _cpu_model(),
        "logical_cpus": os.cpu_count(),
        "blas_threads_env": {
            k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def time_case(run_case: Any, name: str, case: dict[str, Any], defaults: dict[str, Any], repeats: int) -> dict[str, Any]:
    """Time one case: an untimed warm-up, then ``repeats`` timed runs."""
    run_case(name, case, defaults)  # warm-up: imports, caches, allocator state
    wall: list[float] = []
    estimator: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        rec = run_case(name, case, defaults)
        wall.append(time.perf_counter() - t0)
        estimator.append(float(rec["runtime_s"]))
    wall_s = _summary(wall)
    est_s = _summary(estimator)
    return {
        "case": name,
        "repeats": repeats,
        "wall_s": wall_s,
        "estimator_s": est_s,
        "estimator_share_of_wall": est_s["median"] / wall_s["median"],
        "wall_samples_s": wall,
    }


def as_markdown(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Case | Wall median (s) | min to max (s) | stdev (s) | Estimator median (s) | Estimator share of wall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        w, e = r["wall_s"], r["estimator_s"]
        out.append(
            f"| {r['case']} | {w['median']:.3f} | {w['min']:.3f} to {w['max']:.3f} | {w['stdev']:.3f} "
            f"| {e['median']:.3f} | {r['estimator_share_of_wall']:.0%} |"
        )
    total = sum(r["wall_s"]["median"] for r in rows)
    out.append(f"| **all cases (sum of medians)** | **{total:.3f}** | | | | |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=5, help="timed runs per case after one warm-up (default 5)")
    ap.add_argument("--only", nargs="*", default=None, help="time only these cases")
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "benchmark.yaml")
    ap.add_argument("--out", type=Path, default=None, help="also write the full numbers as JSON")
    args = ap.parse_args(argv)
    if args.repeats < 2:
        raise SystemExit("--repeats must be at least 2 to report a spread")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults, cases = doc.get("defaults", {}), doc.get("cases", {})
    selected = args.only or list(cases)
    unknown = [k for k in selected if k not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    run_case = _load_benchmark().run_case
    rows = []
    for name in selected:
        print(f"timing {name} ...", file=sys.stderr, flush=True)
        rows.append(time_case(run_case, name, cases[name], defaults, args.repeats))

    print(as_markdown(rows))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"environment": environment(), "cases": rows}, indent=2) + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
