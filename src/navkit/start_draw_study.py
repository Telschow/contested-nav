"""Which part of the start draw does the single anchor fail on? (issue #168)

    navkit sweep start-draw --csv docs/data/start_draw_study.csv --page docs/results.md

Every ESKF case starts at the truth plus an error drawn from the filter's declared prior (ADR-0027): position,
velocity and attitude. This study runs four cases of ``configs/benchmark.yaml`` on the development seeds 0 to 9, each in
three variants of the same draw:

* ``full``: the draw as it is.
* ``no_attitude``: the attitude part is set to zero, the position and velocity parts stay.
* ``attitude_only``: the position and velocity parts are set to zero, the attitude part stays.

The draw is made first, on its own stream, and :func:`navkit.benchmark.run_case` takes the variant through its
``start_hook``, so every variant of a seed sees the same draw. The file has one row per (case, variant, seed): the ATE
RMSE with alignment ``none`` over the full run, and the mean NEES over the full run. It holds no verdicts.

Seeds from 100 are the held-out set of ADR-0028 and are refused. The output is synthetic and deterministic.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .b1_gate import parse_seeds
from .benchmark import StartError, default_config_path, run_case
from .ensemble import COMPARE_RTOL
from .report.page import splice_block

CASES = ("outage_visual", "vision_only", "outage_visual_clone", "outage_control")
SINGLE_ANCHOR = ("outage_visual", "vision_only")
CLONE = "outage_visual_clone"
VARIANTS = ("full", "no_attitude", "attitude_only")
DEFAULT_SEEDS = range(0, 10)
#: Seeds from here are the held-out set of ADR-0028.
HELD_OUT_FROM = 100
CSV_FIELDS = ("case", "variant", "seed", "ate_rmse_m", "nees_mean")
START, END = "<!-- start-draw:start -->", "<!-- start-draw:end -->"
#: The clone's ATE and mean NEES may differ across the three variants of one seed by this fraction of their mean.
CLONE_TOLERANCE = 0.25
#: "Close to the full-draw median" means within this fraction of it.
CLOSE = 0.25
#: "Several times larger" means at least this ratio.
SEVERAL = 3.0


def zero_attitude(err: StartError) -> StartError:
    return StartError(dp=err.dp, dv=err.dv, dtheta=np.zeros(3))


def attitude_only(err: StartError) -> StartError:
    return StartError(dp=np.zeros(3), dv=np.zeros(3), dtheta=err.dtheta)


def keep(err: StartError) -> StartError:
    return err


HOOKS = {"full": keep, "no_attitude": zero_attitude, "attitude_only": attitude_only}


def refuse_held_out(seeds: list[int]) -> None:
    if any(s >= HELD_OUT_FROM for s in seeds):
        raise ValueError(f"seeds from {HELD_OUT_FROM} are the held-out set of ADR-0028; this study uses 0 to 9 only")


def run_study(doc: dict[str, Any], seeds: list[int] | None = None) -> list[dict[str, Any]]:
    """One row per (case, variant, seed), in a fixed order."""
    use = list(DEFAULT_SEEDS) if seeds is None else list(seeds)
    refuse_held_out(use)
    defaults, cases = doc.get("defaults", {}), doc.get("cases", {})
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for variant in VARIANTS:
            for seed in use:
                rec = run_case(case, copy.deepcopy(cases[case]), defaults, seed=seed, start_hook=HOOKS[variant])
                head = rec["headline"]
                rows.append(
                    {
                        "case": case,
                        "variant": variant,
                        "seed": seed,
                        "ate_rmse_m": float(head["ate_rmse_m"]),
                        "nees_mean": float(head["nees_mean"]),
                    }
                )
    return rows


def csv_text(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for r in rows:
        writer.writerow([r["case"], r["variant"], r["seed"], repr(r["ate_rmse_m"]), repr(r["nees_mean"])])
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    return [
        {
            "case": r["case"],
            "variant": r["variant"],
            "seed": int(r["seed"]),
            "ate_rmse_m": float(r["ate_rmse_m"]),
            "nees_mean": float(r["nees_mean"]),
        }
        for r in csv.DictReader(io.StringIO(text))
    ]


def series(rows: list[dict[str, Any]], case: str, variant: str, key: str = "ate_rmse_m") -> dict[int, float]:
    """The values of one (case, variant) by seed."""
    return {r["seed"]: r[key] for r in rows if r["case"] == case and r["variant"] == variant}


def median_ate(rows: list[dict[str, Any]], case: str, variant: str) -> float:
    return statistics.median(series(rows, case, variant).values())


def larger_with_attitude(rows: list[dict[str, Any]], case: str) -> tuple[int, int]:
    """In how many seeds the ATE of ``full`` is larger than that of ``no_attitude``, and of how many."""
    full, without = series(rows, case, "full"), series(rows, case, "no_attitude")
    seeds = sorted(set(full) & set(without))
    return sum(full[s] > without[s] for s in seeds), len(seeds)


def clone_spread(rows: list[dict[str, Any]], key: str) -> float:
    """The largest relative difference across variants of the clone, over the seeds, for ``key``."""
    by_variant = [series(rows, CLONE, v, key) for v in VARIANTS]
    worst = 0.0
    for s in by_variant[0]:
        vals = [b[s] for b in by_variant]
        worst = max(worst, (max(vals) - min(vals)) / abs(statistics.fmean(vals)))
    return worst


def compare(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> list[str]:
    """Differences between two row lists: text and seeds exactly, floats to the relative tolerance of ADR-0009."""
    if len(new) != len(old):
        return [f"{len(new)} rows against {len(old)}"]
    problems: list[str] = []
    for a, b in zip(new, old, strict=True):
        for key in CSV_FIELDS:
            x, y = a[key], b[key]
            same = x == y if key in ("case", "variant", "seed") else math.isclose(x, y, rel_tol=COMPARE_RTOL)
            if not same:
                problems.append(f"{a['case']} {a['variant']} seed {a['seed']} {key}: {x!r} against {y!r}")
    return problems


def _m(value: float) -> str:
    return f"{value:.2f} m"


def markdown_section(rows: list[dict[str, Any]]) -> str:
    """The generated section of ``docs/results.md``: a table, and sentences the page test checks against the rows."""
    n = len({r["seed"] for r in rows})
    lines = [
        "**The anchor model does not recover from a start attitude error inside its own prior (MEASUREMENT).** "
        f"Each case below was run over {n} seeds in three variants of the same start draw: the full draw, the draw "
        "with the attitude part set to zero, and the draw with only the attitude part kept. The table gives the "
        "median ATE (alignment none, full run) over the seeds and, in the last column, in how many seeds the ATE with "
        "the full draw is larger than without the attitude draw.",
        "",
        "| Case | Full draw | Attitude zeroed | Attitude only | Seeds with a larger ATE when the attitude is drawn |",
        "|---|---:|---:|---:|---:|",
    ]
    for case in CASES:
        k, total = larger_with_attitude(rows, case)
        cells = " | ".join(_m(median_ate(rows, case, v)) for v in VARIANTS)
        lines.append(f"| `{case}` | {cells} | {k} of {total} |")
    lines += [
        "",
        "For both single-anchor cases (`outage_visual` and `vision_only`) the median ATE is several times larger with "
        "the attitude drawn than without it, and with only the attitude drawn it is close to the full-draw median. "
        "The attitude prior is 2 degrees per axis, so the anchor model does not recover from a start attitude error "
        "inside its own declared prior.",
        "",
        "Without vision (`outage_control`) the attitude draw moves the median ATE by less than a factor of two. "
        "The clone (`outage_visual_clone`) does not follow the attitude draw: its ATE and its mean NEES stay within a "
        "quarter of their mean across the three variants in every seed. "
        "The count in the last column says little for the clone, whose differences are small.",
        "",
        "Why the anchor model fails is a HYPOTHESIS and was not tested here: gravity leakage from the start tilt "
        "error plus absolute information that the anchor model invents.",
        "",
        "The rows are in `docs/data/start_draw_study.csv`, written by `navkit sweep start-draw`, and the sentences "
        "above are checked against them by `tests/test_start_draw_page.py`.",
    ]
    return "\n".join(lines)


def splice_section(page: str, text: str) -> str:
    return splice_block(page, "start-draw", text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--page", type=Path, default=None, help="also write the section between the markers of this page")
    ap.add_argument("--compare", type=Path, default=None, help="exit 1 if the rows differ from this committed CSV")
    ap.add_argument("--seeds", default="0-9", help="development seeds, A-B or a comma list; from 100 are refused")
    args = ap.parse_args(argv)
    try:
        seeds = parse_seeds(args.seeds)
        refuse_held_out(seeds)
    except ValueError as exc:
        ap.error(str(exc))
    doc = yaml.safe_load((args.config or default_config_path()).read_text()) or {}
    rows = run_study(doc, seeds)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}: {len(rows)} rows", file=sys.stderr)
    if args.compare is not None:
        problems = compare(rows, parse_csv(args.compare.read_text(encoding="utf-8")))
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        if problems:
            print(f"{len(problems)} difference(s) from {args.compare}", file=sys.stderr)
            return 1
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_section(page, markdown_section(rows)), encoding="utf-8")
    return 0
