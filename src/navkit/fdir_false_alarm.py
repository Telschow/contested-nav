"""How often the FDIR chi-square gate rejects a healthy GNSS update, and how outcomes move with three constants.

``navkit.fdir.gating`` states that the gate rejects a healthy update with probability ``alpha`` when the innovation
covariance is right. This module measures that, and reports it. It does not change any ``FdirConfig`` default.

    navkit sweep fdir rate --csv docs/data/fdir_false_alarm.csv --page docs/faults.md
    navkit sweep fdir sensitivity --csv docs/data/fdir_sensitivity.csv --page docs/faults.md

Part A, ``rate``. Cases ``gnss_only`` (healthy GNSS throughout) and ``outage_control`` (healthy GNSS outside a 15 s
outage), seeds 0 to 24. For every GNSS update the filter gated, the squared Mahalanobis distance of the innovation
is recomputed from the ``(residual, S)`` the filter recorded before it decided, and compared with the same
threshold the gate uses. That is the per-update test, not a fault declaration. On ``outage_control`` the updates
inside the outage do not exist, and the updates in the first ``SETTLE_S`` seconds after the return are reported
apart, because rejecting them is the gate working. Seeds 100 and up are reserved for the B1 gate (ADR-0028) and are
refused here.

Part B, ``sensitivity``. The fault matrix of :mod:`navkit.fault_matrix`, seeds 0 to 4, with one of
``max_consecutive_rejections``, ``reacq_consecutive_rejections`` and ``reacq_sigma_m`` at half and at double its
default, the others at their defaults. Per cell: in how many seeds the gate rejected a measurement and in how many a
channel was declared faulty. The control rows are the no-fault false-alarm counts.

Both CSVs are synthetic evidence from a known-answer fixture, not field measurements.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import default_config_path, run_case
from .eval.calibration import wilson_interval
from .eval.statistics import autocorrelation_estimate, chi2_cdf
from .fault_matrix import BASES, BY_ID, GnssHook, detection_stats
from .fdir.config import FdirConfig
from .fdir.gating import chi2_threshold, mahalanobis_sq
from .report.page import write_block

__all__ = ["main"]

#: Degrees of freedom of a GNSS position innovation.
DOF = 3
#: The gate's false-alarm probability on a healthy update, as the default config states it.
ALPHA = FdirConfig().alpha
#: Seconds after a GNSS outage ends that are reported apart from the false-alarm count. Chosen before the first run.
#: Rejecting the first fixes after an outage is the gate doing its job on a filter that has drifted, so counting
#: them as false alarms would measure the outage and not the gate.
SETTLE_S = 5.0
#: The development seeds of the ensemble (PR #140). Seeds from 100 are the B1 gate's held-out set (ADR-0028).
SEEDS = tuple(range(25))
RESERVED_SEED_START = 100
#: The fault matrix runs five seeds, and so does the sensitivity sweep, to stay comparable with it.
SENSITIVITY_SEEDS = 5

#: Part A cases, in table order.
CASES = ("gnss_only", "outage_control")
#: The constants moved one at a time in part B.
CONSTANTS = ("max_consecutive_rejections", "reacq_consecutive_rejections", "reacq_sigma_m")

PAGE_BLOCKS = {"rate": "fdir-false-alarm", "sensitivity": "fdir-sensitivity"}

RATE_FIELDS = (
    "case",
    "scope",
    "seed",
    "updates",
    "rejections",
    "rate",
    "mean_nis",
    "ess",
    "ess_defined",
    "nis_ess",
    "eff_rejections",
    "wilson_lo",
    "wilson_hi",
    "eff_wilson_lo",
    "eff_wilson_hi",
    "alpha",
    "threshold",
    "c",
    "predicted_rate",
)
SENSITIVITY_FIELDS = (
    "constant",
    "setting",
    "value",
    "fault",
    "base",
    "level",
    "unit",
    "n_seeds",
    "detected_n",
    "declared_n",
)
_RATE_TEXT = ("case", "scope")
_RATE_INT = ("updates", "rejections", "ess_defined")
_SENS_TEXT = ("constant", "setting", "fault", "base", "unit")
_SENS_INT = ("n_seeds", "detected_n", "declared_n")


# --- seeds, the gate, the counting -----------------------------------------------------------


def check_seeds(seeds: Iterable[int]) -> None:
    """Refuse any seed from the B1 gate's reserved range."""
    bad = sorted(s for s in seeds if s >= RESERVED_SEED_START)
    if bad:
        raise ValueError(f"seeds {bad} are reserved for the B1 gate (ADR-0028, seeds {RESERVED_SEED_START} and up)")


def gate_threshold() -> float:
    """The threshold the gate compares a three-dof innovation with, at the default ``alpha``."""
    return chi2_threshold(DOF, ALPHA)


def rejection_indicator(nis: np.ndarray, threshold: float) -> np.ndarray:
    """1.0 where the gate rejects (``d2 > threshold``, as ``FdirManager`` accepts ``d2 <= threshold``), else 0.0."""
    return (np.asarray(nis, dtype=float) > threshold).astype(float)


def count_rejections(nis: np.ndarray, threshold: float) -> int:
    return int(rejection_indicator(nis, threshold).sum())


def scope_masks(t: np.ndarray, windows: list[tuple[float, float]], settle_s: float) -> dict[str, np.ndarray]:
    """Which updates fall in an outage, in a settling period after it, or in neither (``counted``).

    All intervals are half-open: the outage is ``[start, end)``, as ``docs/MODEL.md`` defines it, and the settling
    period after it is ``[end, end + settle_s)``. A fix at ``end + settle_s`` is counted.
    """
    times = np.asarray(t, dtype=float)
    outage = np.zeros(times.shape, dtype=bool)
    settling = np.zeros(times.shape, dtype=bool)
    for start, end in windows:
        outage |= (times >= start) & (times < end)
        settling |= (times >= end) & (times < end + settle_s)
    settling &= ~outage
    return {"outage": outage, "settling": settling, "counted": ~(outage | settling)}


def scale_factor(nis: np.ndarray, dof: int) -> float:
    """``c``: the mean distance over its expectation ``dof``. One means the covariance is the right size."""
    return float(np.mean(nis)) / dof


def predicted_rate(c: float, threshold: float, dof: int) -> float:
    """``P(chi2_dof > threshold / c)``: the rejection rate if the innovation covariance is too small by ``c``."""
    if not c > 0.0:
        raise ValueError(f"c must be positive, got {c}")
    return 1.0 - chi2_cdf(threshold / c, dof)


def series_ess(x: np.ndarray) -> tuple[float, bool]:
    """Effective sample size of a series (the rejection indicator, or the NIS), and whether it could be estimated.

    A series with no rejection is constant and a series of fewer than ten values is too short, and the
    autocorrelation of either is undefined. Such a series counts as ``len(x)`` independent samples and is flagged,
    which is the generous reading: it can only make an interval narrower than the data allow.
    """
    arr = np.asarray(x, dtype=float)
    try:
        est = autocorrelation_estimate(arr)
    except ValueError:
        return float(arr.size), False
    return est.effective_sample_size, True


# --- one run, and the rows ---------------------------------------------------------------------


def outage_windows(case: dict[str, Any]) -> list[tuple[float, float]]:
    """The half-open GNSS outage windows of a benchmark case."""
    outages = case.get("scenario", {}).get("gnss_outages", []) or []
    return [(float(o["start_s"]), float(o["start_s"]) + float(o["duration_s"])) for o in outages]


def _scopes(windows: list[tuple[float, float]]) -> tuple[str, ...]:
    return ("counted", "settling") if windows else ("all",)


def run_one(name: str, seed: int, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One run of ``name``: a per-run record for each scope, keyed ``"<case>/<scope>"``."""
    check_seeds([seed])
    case = doc["cases"][name]
    windows = outage_windows(case)
    box: list[tuple[float, np.ndarray, np.ndarray]] = []
    run_case(name, case, doc["defaults"], seed=seed, innovations_out=box)
    t = np.array([b[0] for b in box], dtype=float)
    nis = np.array([mahalanobis_sq(r, s) for _, r, s in box], dtype=float)
    threshold = gate_threshold()
    masks = scope_masks(t, windows, SETTLE_S)
    out: dict[str, dict[str, Any]] = {}
    for scope in _scopes(windows):
        mask = np.ones(t.shape, dtype=bool) if scope == "all" else masks[scope]
        x = nis[mask]
        indicator = rejection_indicator(x, threshold)
        ess, defined = series_ess(indicator)
        nis_ess, _ = series_ess(x)
        n = int(x.size)
        k = int(indicator.sum())
        out[f"{name}/{scope}"] = {
            "case": name,
            "scope": scope,
            "seed": seed,
            "updates": n,
            "rejections": k,
            "rate": k / n if n else 0.0,
            "mean_nis": float(np.mean(x)) if n else 0.0,
            "ess": ess,
            "ess_defined": int(defined),
            "nis_ess": nis_ess,
            "eff_rejections": k * ess / n if n else 0.0,
        }
    return out


def pooled_row(case: str, scope: str, per_run: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """The row over all runs of one case and scope.

    The raw interval treats the ``N`` updates as independent. The effective interval replaces ``N`` by the sum of
    the per-run effective sample sizes and the rejection count by ``sum(k_i * ess_i / n_i)``, which keeps each
    run's own rate and shrinks its weight by its own autocorrelation.
    """
    n = sum(int(r["updates"]) for r in per_run)
    k = sum(int(r["rejections"]) for r in per_run)
    ess = float(sum(float(r["ess"]) for r in per_run))
    eff_k = float(sum(float(r["rejections"]) * float(r["ess"]) / float(r["updates"]) for r in per_run if r["updates"]))
    mean_nis = sum(float(r["mean_nis"]) * int(r["updates"]) for r in per_run) / n
    c = mean_nis / DOF
    lo, hi = wilson_interval(k, n)
    elo, ehi = wilson_interval(eff_k, ess)
    return {
        "case": case,
        "scope": scope,
        "seed": "all",
        "updates": n,
        "rejections": k,
        "rate": k / n,
        "mean_nis": mean_nis,
        "ess": ess,
        "ess_defined": sum(int(r["ess_defined"]) for r in per_run),
        "nis_ess": float(sum(float(r["nis_ess"]) for r in per_run)),
        "eff_rejections": eff_k,
        "wilson_lo": lo,
        "wilson_hi": hi,
        "eff_wilson_lo": elo,
        "eff_wilson_hi": ehi,
        "alpha": ALPHA,
        "threshold": threshold,
        "c": c,
        "predicted_rate": predicted_rate(c, threshold, DOF),
    }


def _load_doc(config: Path | None = None) -> dict[str, Any]:
    doc = yaml.safe_load((config or default_config_path()).read_text(encoding="utf-8")) or {}
    return doc


def rate_rows(seeds: list[int] | tuple[int, ...] = SEEDS, doc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Part A: per-seed rows, then a pooled row, for each case and scope."""
    check_seeds(seeds)
    doc = _load_doc() if doc is None else doc
    threshold = gate_threshold()
    runs: dict[str, list[dict[str, Any]]] = {}
    for case in CASES:
        for seed in seeds:
            for key, rec in run_one(case, seed, doc).items():
                runs.setdefault(key, []).append(rec)
    rows: list[dict[str, Any]] = []
    for key, per_run in runs.items():
        case, scope = key.split("/")
        rows.extend({f: r.get(f) for f in RATE_FIELDS} for r in per_run)
        rows.append(pooled_row(case, scope, per_run, threshold))
    return rows


# --- CSV ---------------------------------------------------------------------------------------


def rate_csv_text(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=RATE_FIELDS, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r[k]) for k in RATE_FIELDS})
    return buf.getvalue()


def parse_rate_csv(text: str) -> list[dict[str, Any]]:
    out = []
    for raw in csv.DictReader(io.StringIO(text)):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if key in _RATE_TEXT:
                row[key] = value
            elif key == "seed":
                row[key] = value if value == "all" else int(value)
            elif key in _RATE_INT:
                row[key] = int(value)
            else:
                row[key] = None if value == "" else float(value)
        out.append(row)
    return out


def _differ(a: Any, b: Any, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b)))
    return bool(a != b)


def compare_rate_rows(
    got: list[dict[str, Any]], want: list[dict[str, Any]], rel_tol: float = 1e-6, abs_tol: float = 1e-9
) -> list[str]:
    """Differences between a run and the committed CSV; empty when they agree.

    Per-seed rows are compared for the seeds in ``got``, so a reduced run (fewer seeds) can be checked against the
    full file. The pooled rows are compared only when ``got`` has the same seeds as ``want``. Floats are compared to
    1e-6 relative (ADR-0009); text and counts must match exactly.
    """
    index = {(r["case"], r["scope"], r["seed"]): r for r in want}
    seeds_got = {r["seed"] for r in got if r["seed"] != "all"}
    seeds_want = {r["seed"] for r in want if r["seed"] != "all"}
    problems: list[str] = []
    for r in got:
        key = (r["case"], r["scope"], r["seed"])
        if r["seed"] == "all" and seeds_got != seeds_want:
            continue
        ref = index.get(key)
        if ref is None:
            problems.append(f"{key}: not in the committed file")
            continue
        for f in RATE_FIELDS:
            if _differ(r.get(f), ref.get(f), rel_tol, abs_tol):
                problems.append(f"{key} {f}: {r.get(f)!r} != {ref.get(f)!r}")
    return problems


def sensitivity_csv_text(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SENSITIVITY_FIELDS, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        out = {k: ("" if r.get(k) is None else r[k]) for k in SENSITIVITY_FIELDS}
        if r.get("value") is not None:
            out["value"] = format(r["value"], "g")  # 3 and 3.0 are the same setting; one spelling survives a round trip
        writer.writerow(out)
    return buf.getvalue()


def parse_sensitivity_csv(text: str) -> list[dict[str, Any]]:
    out = []
    for raw in csv.DictReader(io.StringIO(text)):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if key in _SENS_TEXT:
                row[key] = value
            elif key in _SENS_INT:
                row[key] = int(value)
            else:
                row[key] = None if value == "" else float(value)
        out.append(row)
    return out


def compare_sensitivity_rows(
    got: list[dict[str, Any]], want: list[dict[str, Any]], rel_tol: float = 1e-6, abs_tol: float = 1e-9
) -> list[str]:
    """Each row of ``got`` must exist in ``want`` with the same counts, so a reduced grid can check the full file."""
    index = {(r["constant"], r["setting"], r["fault"], r["base"], r["level"]): r for r in want}
    problems: list[str] = []
    for r in got:
        key = (r["constant"], r["setting"], r["fault"], r["base"], r["level"])
        ref = index.get(key)
        if ref is None:
            problems.append(f"{key}: not in the committed file")
            continue
        for f in SENSITIVITY_FIELDS:
            if _differ(r.get(f), ref.get(f), rel_tol, abs_tol):
                problems.append(f"{key} {f}: {r.get(f)!r} != {ref.get(f)!r}")
    return problems


# --- part B ------------------------------------------------------------------------------------


def scaled_value(default: int | float, factor: float) -> int | float:
    """``default * factor``. An integer is rounded half up (5 halved is 2.5, which becomes 3) and stays an integer."""
    if isinstance(default, bool):
        raise TypeError("a boolean is not a scalable constant")
    if isinstance(default, int):
        return int(math.floor(default * factor + 0.5))
    return float(default * factor)


def sensitivity_settings(constants: list[str] | tuple[str, ...] = CONSTANTS) -> list[tuple[str, str, Any]]:
    """``(constant, setting, value)``: the default first, then half and double of each constant."""
    cfg = FdirConfig()
    out: list[tuple[str, str, Any]] = [("default", "default", None)]
    for name in constants:
        base = getattr(cfg, name)
        out.append((name, "half", scaled_value(base, 0.5)))
        out.append((name, "double", scaled_value(base, 2.0)))
    return out


def _cell_counts(
    base: str,
    case: dict[str, Any],
    hook: GnssHook | None,
    defaults: dict[str, Any],
    seeds: int,
    onset_s: float | None,
    overrides: dict[str, Any] | None,
) -> tuple[int, int]:
    detected = declared = 0
    for seed in range(seeds):
        record = run_case(base, case, defaults, seed=seed, gnss_hook=hook, fdir_events=True, fdir_overrides=overrides)
        stats = detection_stats(record, onset_s)
        detected += int(stats["detected"])
        declared += int(stats["declared"])
    return detected, declared


def sensitivity_rows(
    faults: list[str] | None = None,
    constants: list[str] | None = None,
    seeds: int = SENSITIVITY_SEEDS,
    doc: dict[str, Any] | None = None,
    progress: bool = False,
) -> list[dict[str, Any]]:
    """Part B: for the default and each setting, the detected and declared counts of every fault-matrix cell."""
    check_seeds(range(seeds))
    doc = _load_doc() if doc is None else doc
    defaults, cases = doc.get("defaults", {}), doc.get("cases", {})
    chosen = list(BY_ID) if faults is None else faults
    unknown = [f for f in chosen if f not in BY_ID]
    if unknown:
        raise ValueError(f"unknown fault(s): {', '.join(unknown)}; known: {', '.join(BY_ID)}")
    names = list(CONSTANTS) if constants is None else constants
    bad = [c for c in names if c not in CONSTANTS]
    if bad:
        raise ValueError(f"unknown constant(s): {', '.join(bad)}; known: {', '.join(CONSTANTS)}")
    selected = [BY_ID[f] for f in chosen]
    bases = [b for b in BASES if any(f.base == b for f in selected)]

    rows: list[dict[str, Any]] = []
    for constant, setting, value in sensitivity_settings(names):
        overrides = None if value is None else {constant: value}
        t0 = time.perf_counter()
        cells: list[tuple[str, str, float, str, dict[str, Any], GnssHook | None, float | None]] = []
        for base in bases:
            cells.append(("control", base, 0.0, "", cases[base], None, None))
        for fault in selected:
            for level in fault.levels:
                case, hook = fault.build(cases[fault.base], level)
                cells.append((fault.id, fault.base, level, fault.unit, case, hook, fault.onset_s))
        for fault_id, base, level, unit, case, hook, onset in cells:
            detected, declared = _cell_counts(base, case, hook, defaults, seeds, onset, overrides)
            rows.append(
                {
                    "constant": constant,
                    "setting": setting,
                    "value": value,
                    "fault": fault_id,
                    "base": base,
                    "level": level,
                    "unit": unit,
                    "n_seeds": seeds,
                    "detected_n": detected,
                    "declared_n": declared,
                }
            )
        if progress:
            print(f"ran {constant} {setting} ({time.perf_counter() - t0:.1f} s)", file=sys.stderr, flush=True)
    return rows


# --- the page ----------------------------------------------------------------------------------


def _pct(x: float, digits: int = 3) -> str:
    return f"{100.0 * x:.{digits}f}%"


def _interval(lo: float, hi: float) -> str:
    return f"[{_pct(lo)}, {_pct(hi)}]"


def _inside(x: float, lo: float, hi: float) -> str:
    return "inside" if lo <= x <= hi else "outside"


def _pooled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["seed"] == "all"]


def _per_seed(rows: list[dict[str, Any]], case: str, scope: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["case"] == case and r["scope"] == scope and r["seed"] != "all"]


def _label(row: dict[str, Any]) -> str:
    return {
        "all": "all updates",
        "counted": "outside the outage and its settling period",
        "settling": f"first {SETTLE_S:g} s after the return (reported apart)",
    }[row["scope"]]


def rate_tables(rows: list[dict[str, Any]]) -> str:
    """The three part A tables and the sentences that read them, generated from the CSV rows."""
    pooled = _pooled(rows)
    t1 = [
        "| Case | Updates counted | Updates | Rejections | Observed rate | 95% Wilson interval, raw count "
        + "| Summed effective updates | Effective rejections | 95% Wilson interval, effective count | Stated α |",
        "|---|---|---:|---:|---:|---|---:|---:|---|---:|",
    ]
    for r in pooled:
        t1.append(
            f"| {r['case']} | {_label(r)} | {r['updates']} | {r['rejections']} | {_pct(r['rate'])} "
            f"| {_interval(r['wilson_lo'], r['wilson_hi'])} | {r['ess']:.1f} | {r['eff_rejections']:.2f} "
            f"| {_interval(r['eff_wilson_lo'], r['eff_wilson_hi'])} | {_pct(r['alpha'])} |"
        )
    t2 = [
        f"| Case | Updates counted | Mean NIS (expected {DOF}) | c = mean NIS / {DOF} | Threshold "
        + "| Predicted rate P(χ²₃ > threshold / c) | Observed rate | Stated α |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in pooled:
        t2.append(
            f"| {r['case']} | {_label(r)} | {r['mean_nis']:.3f} | {r['c']:.3f} | {r['threshold']:g} "
            f"| {_pct(r['predicted_rate'])} | {_pct(r['rate'])} | {_pct(r['alpha'])} |"
        )
    t3 = [
        "| Case | Updates counted | Runs | Runs where the estimator returned a value for the indicator "
        + "| Indicator, per-run effective size, min / median / max "
        + "| NIS series, per-run effective size, min / median / max (diagnostic, in neither interval) "
        + "| Per-run updates, median |",
        "|---|---|---:|---:|---|---|---:|",
    ]
    for r in pooled:
        runs = _per_seed(rows, r["case"], r["scope"])
        ess = sorted(float(x["ess"]) for x in runs)
        nis_ess = sorted(float(x["nis_ess"]) for x in runs)
        ups = sorted(int(x["updates"]) for x in runs)
        t3.append(
            f"| {r['case']} | {_label(r)} | {len(runs)} | {r['ess_defined']} "
            f"| {ess[0]:.1f} / {float(np.median(ess)):.1f} / {ess[-1]:.1f} "
            f"| {nis_ess[0]:.1f} / {float(np.median(nis_ess)):.1f} / {nis_ess[-1]:.1f} "
            f"| {float(np.median(ups)):g} |"
        )
    lines = [
        *rate_setup(rows),
        "",
        "Per-update gate rejections of healthy GNSS fixes:",
        "",
        *t1,
        "",
        "Predicted rate from the scale factor c, next to the observed rate:",
        "",
        *t2,
        "",
        "Effective sample size of the rejection indicator, per run:",
        "",
        *t3,
        "",
        *rate_sentences(rows),
    ]
    return "\n".join(lines)


def rate_setup(rows: list[dict[str, Any]]) -> list[str]:
    """The run's own settings, read from the rows, so that no number in the prose is typed."""
    seeds = sorted({int(r["seed"]) for r in rows if r["seed"] != "all"})
    pooled = _pooled(rows)
    return [
        f"Seeds {seeds[0]} to {seeds[-1]} ({len(seeds)} runs per case). The stated α is {_pct(pooled[0]['alpha'])}, "
        f"which is a threshold of {pooled[0]['threshold']:g} for {DOF} degrees of freedom. The settling period after "
        f"an outage is {SETTLE_S:g} s, the half-open interval from the return to {SETTLE_S:g} s after it."
    ]


def rate_sentences(rows: list[dict[str, Any]]) -> list[str]:
    """What the numbers show, one bullet per case and scope. Each condition is computed, not typed."""
    out: list[str] = []
    for r in _pooled(rows):
        a = r["alpha"]
        pred = r["predicted_rate"]
        closer = "closer to" if abs(pred - r["rate"]) < abs(a - r["rate"]) else "farther from"
        out.append(
            f"- **{r['case']}, {_label(r)}.** The gate rejected {r['rejections']} of {r['updates']} updates, "
            f"{_pct(r['rate'])}. The stated α is {_pct(a)}, which is {_inside(a, r['wilson_lo'], r['wilson_hi'])} "
            f"the raw-count interval {_interval(r['wilson_lo'], r['wilson_hi'])} and "
            f"{_inside(a, r['eff_wilson_lo'], r['eff_wilson_hi'])} the effective-count interval "
            f"{_interval(r['eff_wilson_lo'], r['eff_wilson_hi'])}. The mean NIS is {r['mean_nis']:.3f}, so "
            f"c is {r['c']:.3f} and the predicted rate is {_pct(pred)}. The predicted rate is "
            f"{_inside(pred, r['wilson_lo'], r['wilson_hi'])} the raw-count interval and "
            f"{_inside(pred, r['eff_wilson_lo'], r['eff_wilson_hi'])} the effective-count interval, and it is "
            f"{closer} the observed rate than α is."
        )
    return out


def sensitivity_tables(rows: list[dict[str, Any]]) -> str:
    """Control declarations per setting, then one table per constant with the detected and declared count per cell."""
    seeds = rows[0]["n_seeds"]
    defaults = FdirConfig()
    settings: list[tuple[str, str, Any]] = []
    for r in rows:
        key = (r["constant"], r["setting"], r["value"])
        if key not in settings:
            settings.append(key)
    cells: list[tuple[str, str, float]] = []
    for r in rows:
        key3 = (r["fault"], r["base"], r["level"])
        if key3 not in cells:
            cells.append(key3)
    lookup = {(r["constant"], r["setting"], r["fault"], r["base"], r["level"]): r for r in rows}
    bases = [b for b in BASES if any(c[1] == b for c in cells)]

    def label(constant: str, setting: str, value: Any) -> str:
        if constant == "default":
            return "defaults"
        return f"{constant} = {value:g} ({setting}; default {getattr(defaults, constant):g})"

    t0 = [
        "| Setting | "
        + " | ".join(f"{b} control declared" for b in bases)
        + " | Cells whose detected count differs from the defaults"
        + " | Cells whose declared count differs from the defaults |",
        "|---|" + "---:|" * len(bases) + "---:|---:|",
    ]
    for constant, setting, value in settings:
        ctl = [lookup[(constant, setting, "control", b, 0.0)]["declared_n"] for b in bases]
        det = dec = 0
        for fault, base, level in cells:
            now = lookup[(constant, setting, fault, base, level)]
            ref = lookup[("default", "default", fault, base, level)]
            det += int(now["detected_n"] != ref["detected_n"])
            dec += int(now["declared_n"] != ref["declared_n"])
        t0.append(
            f"| {label(constant, setting, value)} | " + " | ".join(f"{c}/{seeds}" for c in ctl) + f" | {det} | {dec} |"
        )
    order = {fid: i for i, fid in enumerate(["control", *BY_ID])}
    cells_sorted = sorted(cells, key=lambda c: (bases.index(c[1]), order[c[0]], c[2]))
    per_constant: list[str] = []
    for constant in dict.fromkeys(s[0] for s in settings if s[0] != "default"):
        mine = [s for s in settings if s[0] == constant]
        head = (
            "| Case | Fault | Level | "
            + f"{constant} = {getattr(defaults, constant):g} (default) | "
            + " | ".join(f"{constant} = {v:g} ({s})" for _, s, v in mine)
            + " |"
        )
        table = [head, "|---|---|---:|" + "---|" * (1 + len(mine))]
        for fault, base, level in cells_sorted:
            if fault == "control":
                name, lv = "none (control)", ""
            else:
                name, lv = BY_ID[fault].label, f"{level:g} {BY_ID[fault].unit}"
            d = lookup[("default", "default", fault, base, level)]
            parts = [f"{d['detected_n']}/{d['declared_n']}"]
            for _, s, _ in mine:
                x = lookup[(constant, s, fault, base, level)]
                parts.append(f"{x['detected_n']}/{x['declared_n']}")
            table.append(f"| {base} | {name} | {lv} | " + " | ".join(parts) + " |")
        per_constant.extend([f"`{constant}`, detected / declared, out of {seeds} seeds:", "", *table, ""])
    lines = [
        *sensitivity_setup(rows),
        "",
        f"False alarms: seeds in which the no-fault control declared a channel faulty, out of {seeds}:",
        "",
        *t0,
        "",
        *per_constant,
        *sensitivity_sentences(rows),
    ]
    return "\n".join(lines).rstrip()


def _setting_label(constant: str, setting: str, value: Any) -> str:
    return "defaults" if constant == "default" else f"{constant} = {value:g} ({setting})"


def sensitivity_sentences(rows: list[dict[str, Any]]) -> list[str]:
    """What the counts show: the control declarations, and the cells whose counts differ from the defaults."""
    seeds = rows[0]["n_seeds"]
    lookup = {(r["constant"], r["setting"], r["fault"], r["base"], r["level"]): r for r in rows}
    settings: list[tuple[str, str, Any]] = []
    for r in rows:
        key = (r["constant"], r["setting"], r["value"])
        if key not in settings:
            settings.append(key)
    cells = list(dict.fromkeys((r["fault"], r["base"], r["level"]) for r in rows))
    bases = [b for b in BASES if any(c[1] == b for c in cells)]
    out = ["What the counts show:", ""]
    for base in bases:
        counts = sorted({lookup[(c, s, "control", base, 0.0)]["declared_n"] for c, s, _ in settings})
        where = (
            f"in {counts[0]} of {seeds} seeds at every setting"
            if len(counts) == 1
            else f"in between {counts[0]} and {counts[-1]} of {seeds} seeds across the settings"
        )
        out.append(f"- The `{base}` control declared a channel faulty {where}.")
    for constant, setting, value in settings:
        if constant == "default":
            continue
        changed = []
        for fault, base, level in cells:
            now = lookup[(constant, setting, fault, base, level)]
            ref = lookup[("default", "default", fault, base, level)]
            if (now["detected_n"], now["declared_n"]) != (ref["detected_n"], ref["declared_n"]):
                name = "control" if fault == "control" else f"{BY_ID[fault].label} {level:g} {BY_ID[fault].unit}"
                changed.append(
                    f"{base}, {name}: detected {ref['detected_n']} to {now['detected_n']}, "
                    f"declared {ref['declared_n']} to {now['declared_n']}"
                )
        label = _setting_label(constant, setting, value)
        if changed:
            out.append(
                f"- {label}: {len(changed)} cell(s) differ from the defaults ({'; '.join(changed)}; of {seeds} seeds)."
            )
        else:
            out.append(f"- {label}: no cell differs from the defaults in its detected or declared count.")
    return out


def sensitivity_setup(rows: list[dict[str, Any]]) -> list[str]:
    """The three constants at the defaults and at half and double, as the run used them."""
    defaults = FdirConfig()
    seeds = rows[0]["n_seeds"]
    table = ["| Constant | Default | Half | Double | Type |", "|---|---:|---:|---:|---|"]
    for name in dict.fromkeys(r["constant"] for r in rows if r["constant"] != "default"):
        value = {r["setting"]: r["value"] for r in rows if r["constant"] == name}
        base = getattr(defaults, name)
        kind = "integer, rounded half up" if isinstance(base, int) else "float"
        table.append(f"| `{name}` | {base:g} | {value['half']:g} | {value['double']:g} | {kind} |")
    return [
        f"Seeds 0 to {seeds - 1}, as the fault matrix above uses. The defaults are the ones in `FdirConfig`, and "
        "the table is read from them:",
        "",
        *table,
    ]


# --- command line ------------------------------------------------------------------------------


def _write_page(path: Path, part: str, block: str) -> None:
    write_block(path, PAGE_BLOCKS[part], block)
    print(f"wrote {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="navkit sweep fdir", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "part", choices=("rate", "sensitivity"), help="rate: per-update false alarms; sensitivity: constants"
    )
    ap.add_argument("--csv", type=Path, default=None, help="write the rows to this CSV")
    ap.add_argument("--page", type=Path, default=None, help="rewrite this part's generated block in this page")
    ap.add_argument(
        "--seeds",
        type=int,
        default=None,
        help=(
            f"seeds 0 .. N-1 (default {len(SEEDS)} for rate, {SENSITIVITY_SEEDS} for sensitivity; "
            f"never {RESERVED_SEED_START} and up)"
        ),
    )
    ap.add_argument("--faults", nargs="+", default=None, help="sensitivity only: fault ids (default: all)")
    ap.add_argument("--constants", nargs="+", default=None, help="sensitivity only: constants (default: all three)")
    ap.add_argument("--markdown", action="store_true", help="print the tables")
    ap.add_argument(
        "--compare", type=Path, default=None, help="exit 1 unless the run matches this committed CSV (1e-6 relative)"
    )
    args = ap.parse_args(argv)

    full = args.faults is None and args.constants is None
    if args.part == "rate":
        n = len(SEEDS) if args.seeds is None else args.seeds
        if n < 2:
            raise SystemExit("a spread needs at least 2 seeds")
        reduced = n != len(SEEDS)
    else:
        n = SENSITIVITY_SEEDS if args.seeds is None else args.seeds
        if n < 2:
            raise SystemExit("a spread needs at least 2 seeds")
        reduced = n != SENSITIVITY_SEEDS or not full
    if args.page is not None and reduced:
        raise SystemExit("--page needs the full grid: drop --seeds, --faults and --constants")
    try:
        if args.part == "rate":
            seeds = list(range(n))
            check_seeds(seeds)
            rows = rate_rows(seeds)
            text = rate_csv_text(rows)
            block = rate_tables(rows)
        else:
            check_seeds(range(n))
            srows = sensitivity_rows(args.faults, args.constants, n, progress=True)
            text = sensitivity_csv_text(srows)
            block = sensitivity_tables(srows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text(text, encoding="utf-8")
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        _write_page(args.page, args.part, block)
    if args.markdown:
        print(block)
    if args.compare is not None:
        committed = args.compare.read_text(encoding="utf-8")
        if args.part == "rate":
            problems = compare_rate_rows(parse_rate_csv(text), parse_rate_csv(committed))
        else:
            problems = compare_sensitivity_rows(parse_sensitivity_csv(text), parse_sensitivity_csv(committed))
        if problems:
            print(f"result differs from {args.compare}:", file=sys.stderr)
            for p in problems[:10]:
                print(f"  {p}", file=sys.stderr)
            return 1
        print(f"result matches {args.compare}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
