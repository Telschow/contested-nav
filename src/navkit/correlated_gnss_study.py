"""Is the innovation gate blind to a slow, time-correlated GNSS error? (issue #183)

    navkit sweep correlated-gnss --csv docs/data/correlated_gnss.csv --page docs/urbannav.md

On Deep-Urban-1 the gate rejected none of the fixes while the mean NIS stayed far below its level, and the receiver's
fix errors were correlated over tens of seconds. The page calls the link between the two an interpretation. This study
builds the same situation on synthetic data, where the cause is known, and reports the result either way.

Three cases of ``configs/benchmark.yaml``, each over the development seeds 0 to 9:

* ``independent``: ``gnss_only``, GNSS fixes with independent noise. The control.
* ``correlated``: the same case plus a first-order Gauss-Markov error on the fixes, with the size and correlation time
  below. They were declared before the study was run. One exploratory run of seed 1 with a size of 3 m preceded the
  declaration and is not a row.
* ``single_anchor``: ``outage_visual``, the overconfident single-anchor control row, kept as in every study here.

The criteria for "the gate is blind" are declared below too: the Wilson upper bound of the rejection rate is under
``BLIND_REJECTION_UPPER``, the mean NIS is under the gate level, and the mean NEES is at least ``BLIND_NEES_FACTOR``
times its expected value. The Wilson interval treats the fixes of a run as independent trials, which under correlated
error they are not, so it understates the uncertainty. The output is synthetic and deterministic. Seeds from 100 are
the held-out set of ADR-0028 and are refused.
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

import yaml

from .benchmark import default_config_path, run_case
from .eval.calibration import wilson_interval
from .fdir.config import FdirConfig
from .fdir.gating import chi2_threshold
from .report.page import splice_block

#: Declared before the study was run.
CORR_SIGMA_M = 1.5
CORR_TAU_S = 30.0
BLIND_REJECTION_UPPER = 0.05
BLIND_NEES_FACTOR = 3.0

CASES = ("independent", "correlated", "single_anchor")
DEFAULT_SEEDS = range(0, 10)
#: Seeds from here are the held-out set of ADR-0028.
HELD_OUT_FROM = 100
#: The position update has three degrees of freedom; the gate is the chi-square threshold at the default alpha.
DOF = 3
GATE_LEVEL = chi2_threshold(DOF, FdirConfig().alpha)
CSV_FIELDS = ("case", "seed", "fixes_seen", "fixes_rejected", "mean_nis", "nees_mean", "ate_rmse_m")
START, END = "<!-- correlated-gnss:start -->", "<!-- correlated-gnss:end -->"
COMPARE_RTOL = 1e-6


def case_definition(doc: dict[str, Any], name: str) -> dict[str, Any]:
    """A copy of the benchmark case that one row of the study runs."""
    cases = doc["cases"]
    if name == "single_anchor":
        return copy.deepcopy(cases["outage_visual"])
    case = copy.deepcopy(cases["gnss_only"])
    case["name"] = case["scenario"]["name"] = f"gnss_{name}"
    if name == "correlated":
        case["scenario"]["gnss"].update(multipath_sigma_m=CORR_SIGMA_M, multipath_tau_s=CORR_TAU_S)
    elif name != "independent":
        raise ValueError(f"unknown case {name!r}")
    return case


def refuse_held_out(seeds: list[int]) -> None:
    if any(s >= HELD_OUT_FROM for s in seeds):
        raise ValueError(f"seeds from {HELD_OUT_FROM} are the held-out set of ADR-0028; this study uses 0 to 9 only")


def run_study(doc: dict[str, Any], seeds: list[int] | None = None) -> list[dict[str, Any]]:
    """One row per (case, seed), in a fixed order."""
    use = list(DEFAULT_SEEDS) if seeds is None else list(seeds)
    refuse_held_out(use)
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for seed in use:
            rec = run_case(case, case_definition(doc, case), doc.get("defaults", {}), seed=seed)
            stats, head = rec["stats"], rec["headline"]
            rows.append(
                {
                    "case": case,
                    "seed": seed,
                    "fixes_seen": int(stats["gnss_fixes_seen"]),
                    "fixes_rejected": int(stats["gnss_updates_rejected"]),
                    "mean_nis": float(stats["fdir_gnss_mean_nis"]),
                    "nees_mean": float(head["nees_mean"]),
                    "ate_rmse_m": float(head["ate_rmse_m"]),
                }
            )
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per case: pooled counts with the Wilson interval, and the means over the seeds."""
    out: dict[str, dict[str, Any]] = {}
    for case in CASES:
        mine = [r for r in rows if r["case"] == case]
        if not mine:
            continue
        seen = sum(r["fixes_seen"] for r in mine)
        rejected = sum(r["fixes_rejected"] for r in mine)
        low, high = wilson_interval(rejected, seen)
        out[case] = {
            "seeds": len(mine),
            "seen": seen,
            "rejected": rejected,
            "rate": rejected / seen if seen else 0.0,
            "rate_low": low,
            "rate_high": high,
            "mean_nis": statistics.fmean(r["mean_nis"] for r in mine),
            "nees_mean": statistics.fmean(r["nees_mean"] for r in mine),
            "nees_expected": float(DOF),
        }
    return out


def gate_is_blind(summary: dict[str, Any]) -> bool:
    """The declared criteria: few rejections, a mean NIS under the gate level, and a large error against the claim."""
    return bool(
        summary["rate_high"] < BLIND_REJECTION_UPPER
        and summary["mean_nis"] < GATE_LEVEL
        and summary["nees_mean"] >= BLIND_NEES_FACTOR * summary["nees_expected"]
    )


def csv_text(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for r in rows:
        writer.writerow(
            [
                r["case"],
                r["seed"],
                r["fixes_seen"],
                r["fixes_rejected"],
                repr(r["mean_nis"]),
                repr(r["nees_mean"]),
                repr(r["ate_rmse_m"]),
            ]
        )
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    return [
        {
            "case": r["case"],
            "seed": int(r["seed"]),
            "fixes_seen": int(r["fixes_seen"]),
            "fixes_rejected": int(r["fixes_rejected"]),
            "mean_nis": float(r["mean_nis"]),
            "nees_mean": float(r["nees_mean"]),
            "ate_rmse_m": float(r["ate_rmse_m"]),
        }
        for r in csv.DictReader(io.StringIO(text))
    ]


def compare(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> list[str]:
    """Differences between two row lists: text and counts exactly, floats to the relative tolerance of ADR-0009."""
    if len(new) != len(old):
        return [f"{len(new)} rows against {len(old)}"]
    problems: list[str] = []
    for a, b in zip(new, old, strict=True):
        for key in CSV_FIELDS:
            x, y = a[key], b[key]
            same = math.isclose(x, y, rel_tol=COMPARE_RTOL) if isinstance(x, float) else x == y
            if not same:
                problems.append(f"{a['case']} seed {a['seed']} {key}: {x!r} against {y!r}")
    return problems


LABELS = {
    "independent": "Independent noise (control)",
    "correlated": f"Correlated error, {CORR_SIGMA_M:g} m, {CORR_TAU_S:g} s",
    "single_anchor": "Single anchor with an outage (control)",
}


def markdown_section(rows: list[dict[str, Any]]) -> str:
    """The generated section of ``docs/urbannav.md``: a table, and sentences the page test checks against the rows."""
    s = summarise(rows)
    missing = [c for c in CASES if c not in s]
    if missing:
        raise ValueError(f"the rows have no case {', '.join(missing)}")
    n = s["independent"]["seeds"]
    lines = [
        "**Is the gate blind to a slow, correlated GNSS error? Synthetic, not the real receiver (MEASUREMENT).** "
        f"Each case was run over {n} development seeds. The correlated case adds a first-order Gauss-Markov error "
        f"with a standard deviation of {CORR_SIGMA_M:g} m and a correlation time of {CORR_TAU_S:g} s to the fixes, "
        "both declared before the run. The rejection column pools the fixes of all seeds with a Wilson 95% interval "
        "that treats them as independent trials, which they are not under correlated error, so it is too narrow. "
        f"The gate level is {GATE_LEVEL:.2f} (three degrees of freedom).",
        "",
        "| Case | Fixes | Rejected (Wilson 95%) | Mean NIS (expected 3) | Mean NEES (expected 3) |",
        "|---|---:|---:|---:|---:|",
    ]
    for case in CASES:
        c = s[case]
        lines.append(
            f"| {LABELS[case]} | {c['seen']} | {c['rejected']} ({c['rate_low']:.1%} to {c['rate_high']:.1%}) "
            f"| {c['mean_nis']:.2f} | {c['nees_mean']:.1f} |"
        )
    c, i = s["correlated"], s["independent"]
    met = gate_is_blind(c)
    lines += [
        "",
        f'The criteria for "blind" were declared first: an upper Wilson bound of the rejection rate under '
        f"{BLIND_REJECTION_UPPER:.0%}, a mean NIS under the gate level, and a mean NEES at least "
        f"{BLIND_NEES_FACTOR:g} times its expected value. In the correlated case the gate rejected {c['rejected']} of "
        f"{c['seen']} fixes, the mean NIS was {c['mean_nis']:.2f} against {i['mean_nis']:.2f} for independent noise, "
        f"and the mean NEES was {c['nees_mean']:.1f}. The criteria were "
        f"{'met' if met else 'not met'}.",
        "",
        "What this shows: the rows, for this scenario. What it does not show: that the real receiver's errors follow "
        "this model, why Deep-Urban-1 behaved as it did, or what a correlated-error model in the filter would change. "
        "The run is 30 s long, the same length as the correlation time, so the error is close to one slow wave. "
        "The single-anchor row is the overconfident control and is not a GNSS-error case.",
        "",
        "The rows are in `docs/data/correlated_gnss.csv`, written by `navkit sweep correlated-gnss`, and the sentences "
        "above are checked against them by `tests/test_correlated_gnss_page.py`.",
    ]
    return "\n".join(lines)


def splice_section(page: str, text: str) -> str:
    return splice_block(page, "correlated-gnss", text)


def parse_seeds(text: str) -> list[int]:
    if "-" in text and "," not in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",") if x]


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
    # The committed rows are read before the new ones are written, so that --csv and --compare may name one file.
    committed = parse_csv(args.compare.read_text(encoding="utf-8")) if args.compare is not None else None
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}: {len(rows)} rows", file=sys.stderr)
    if committed is not None:
        problems = compare(rows, committed)
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        if problems:
            print(f"{len(problems)} difference(s) from {args.compare}", file=sys.stderr)
            return 1
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_section(page, markdown_section(rows)), encoding="utf-8")
    return 0
