"""Measure the fault modes the simulator can inject, against a clean control.

The FMEA-lite table in ``docs/MODEL.md`` lists every fault the injection layer can produce and,
until this sweep, marked most of them "unit-tested only": the code path is tested, the effect
on accuracy and calibration is not measured. This runs each one on a benchmark case over several
noise seeds and puts it next to the same case with no fault.

    navkit sweep faults
    navkit sweep faults --faults gnss_spoof_sustained gnss_time_offset --seeds 5 --markdown
    navkit sweep faults --csv docs/data/fault_matrix.csv --page docs/faults.md

What is measured for each cell, over N seeds:

* the usual error and calibration numbers (ATE, mean NEES, 2-sigma coverage, claimed sigma);
* **detected**: in how many seeds the gate rejected at least one measurement;
* **declared**: in how many seeds the FDIR layer isolated a channel as faulty (the strict test,
  and the one a downstream consumer could act on);
* the share of measurements rejected.

The same three are measured on each fault's control (the base case with no fault), and on the
control they are the **false-alarm** measures. A gate that rejects a healthy fix is a false
alarm, so a control that is rejected from is reported as such rather than excluded.

The output is synthetic. A sweep over a known-answer fixture is not a field measurement, so the
payload carries the same disclaimer and ``claim_type`` as ``results/benchmark.json``.
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import MEASUREMENT, _config_label, _jsonable, default_config_path, run_case
from .fdir.status import STATUS_REACCEPTED_WITH_INFLATION, STATUS_SENSOR_FAULT
from .outage_sweep import METRICS, _collect, _interval, summarise_cell
from .types import GnssFix

GnssHook = Callable[[GnssFix], GnssFix]

PAGE_START, PAGE_END = "<!-- faults:start -->", "<!-- faults:end -->"

#: The fault window used by the spoofing and spike faults, seconds into the 30 s scenario.
SPOOF_START_S, SPOOF_END_S = 10.0, 20.0
SPIKE_AT_S = 15.0
#: The post-outage spoof starts where the benchmark's outage ends.
POST_OUTAGE_S = 20.0


def offset_window(start_s: float, end_s: float, offset_m: float) -> GnssHook:
    """A hook that adds ``offset_m`` metres east to the fixes with ``start_s <= t < end_s``.

    Fixes that were removed by an outage stay removed: the offset is applied only where the fix is
    available, so the window means what it says.
    """

    def hook(fixes: GnssFix) -> GnssFix:
        positions = fixes.positions.copy()
        hit = (fixes.t >= start_s) & (fixes.t < end_s)
        if fixes.available is not None:
            hit &= fixes.available
        positions[hit, 0] += offset_m
        return GnssFix(
            t=fixes.t.copy(),
            positions=positions,
            cov=None if fixes.cov is None else fixes.cov.copy(),
            available=None if fixes.available is None else fixes.available.copy(),
            name=fixes.name + "_offset",
        )

    return hook


def _scenario_edit(**changes: Any) -> Callable[[dict[str, Any], float], dict[str, Any]]:
    """An edit that sets scenario keys, with ``{level}`` standing for the level."""

    def edit(case: dict[str, Any], level: float) -> dict[str, Any]:
        out = copy.deepcopy(case)
        scen = out.setdefault("scenario", {})
        for key, value in changes.items():
            scen[key] = _fill(value, level)
        return out

    return edit


def _fill(value: Any, level: float) -> Any:
    if value == "{level}":
        return level
    if isinstance(value, dict):
        return {k: _fill(v, level) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, level) for v in value]
    return value


@dataclass(frozen=True)
class Fault:
    """One fault mode: where it runs, what it is called and how a level turns into a run."""

    id: str
    label: str
    base: str
    unit: str
    levels: tuple[float, ...]
    fmea: str
    edit: Callable[[dict[str, Any], float], dict[str, Any]] | None = None
    hook: Callable[[float], GnssHook] | None = None
    #: When the fault begins, for faults that have a start. Detection latency is measured from it.
    onset_s: float | None = None

    def build(self, case: dict[str, Any], level: float) -> tuple[dict[str, Any], GnssHook | None]:
        out = self.edit(case, level) if self.edit is not None else copy.deepcopy(case)
        return out, None if self.hook is None else self.hook(level)


def _gnss_multipath(case: dict[str, Any], level: float) -> dict[str, Any]:
    out = copy.deepcopy(case)
    out.setdefault("scenario", {}).setdefault("gnss", {})["multipath_sigma_m"] = level
    return out


FAULTS: tuple[Fault, ...] = (
    Fault(
        "gnss_spoof_sustained",
        "GNSS spoof, sustained offset",
        "gnss_only",
        "m",
        (3.0, 10.0, 40.0),
        "GNSS spoofing, large sustained offset",
        hook=lambda m: offset_window(SPOOF_START_S, SPOOF_END_S, m),
        onset_s=SPOOF_START_S,
    ),
    Fault(
        "gnss_multipath_spike",
        "GNSS single spike",
        "gnss_only",
        "m",
        (20.0,),
        "GNSS multipath, single spike",
        hook=lambda m: offset_window(SPIKE_AT_S - 0.1, SPIKE_AT_S + 0.1, m),
        onset_s=SPIKE_AT_S,
    ),
    Fault(
        "gnss_slow_bias",
        "GNSS slow bias",
        "gnss_only",
        "m (1 sigma)",
        (1.0, 3.0),
        "GNSS slow bias",
        edit=_gnss_multipath,
    ),
    Fault(
        "gnss_time_offset",
        "GNSS timestamp offset",
        "gnss_only",
        "s",
        (0.05, 0.2, 0.5),
        "Timestamp offset (IMU, GNSS, vision)",
        edit=_scenario_edit(gnss_time_offset_s="{level}"),
    ),
    Fault(
        "imu_sample_loss",
        "IMU sample loss",
        "gnss_only",
        "s lost at 10 s",
        (0.5, 2.0),
        "IMU sample loss",
        edit=_scenario_edit(imu_outages=[{"start_s": 10.0, "duration_s": "{level}", "reason": "fault"}]),
        onset_s=10.0,
    ),
    Fault(
        "gnss_spoof_after_outage",
        "GNSS spoof after an outage",
        "outage_visual",
        "m",
        (3.0, 10.0, 22.0),
        "GNSS spoofing, modest offset after an outage",
        hook=lambda m: offset_window(POST_OUTAGE_S, 1e9, m),
        onset_s=POST_OUTAGE_S,
    ),
    Fault(
        "vision_time_offset",
        "Vision timestamp offset",
        "vision_only",
        "s",
        (0.05, 0.2),
        "Timestamp offset (IMU, GNSS, vision)",
        edit=_scenario_edit(vision_time_offset_s="{level}"),
    ),
    Fault(
        "vision_outage",
        "Vision outage",
        "vision_only",
        "s lost at 10 s",
        (2.0, 5.0),
        "Camera frame loss",
        edit=_scenario_edit(vision_outages=[{"start_s": 10.0, "duration_s": "{level}", "reason": "fault"}]),
        onset_s=10.0,
    ),
)
BY_ID = {f.id: f for f in FAULTS}
#: Order in which bases appear in the table.
BASES = ("gnss_only", "outage_visual", "vision_only")

CSV_FIELDS = (
    "fault",
    "base",
    "level",
    "unit",
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
    "detected_n",
    "declared_n",
    "granted_n",
    "latency_s_mean",
    "declared_channels",
    "rejected_pct_mean",
    "rejected_pct_lo",
    "rejected_pct_hi",
)
TEXT_FIELDS = ("fault", "base", "unit", "declared_channels")
INT_FIELDS = ("n_seeds", "detected_n", "declared_n", "granted_n")


def detection_stats(record: dict[str, Any], onset_s: float | None = None) -> dict[str, Any]:
    """What the gate and the FDIR layer did in one run.

    ``declared`` comes from the FDIR event log, not from the end-of-run flag: a channel that was
    declared faulty and later recovered would otherwise read as never declared. ``latency_s`` is
    the time from ``onset_s`` to the first declaration at or after it, when both exist.
    """
    s = record["stats"]
    rejected = float(s.get("gnss_updates_rejected", 0.0)) + float(s.get("vision_updates_rejected", 0.0))
    seen = float(s.get("gnss_fixes_seen", 0.0)) + float(s.get("vision_updates_used", 0.0))
    seen += float(s.get("vision_updates_rejected", 0.0))
    events = record.get("fdir_events", [])
    declared_at = [e["t_s"] for e in events if e["status"] == STATUS_SENSOR_FAULT]
    latency = None
    if onset_s is not None:
        after = [t for t in declared_at if t >= onset_s]
        latency = min(after) - onset_s if after else None
    return {
        "detected": rejected > 0.0,
        "declared": bool(declared_at),
        "declared_channels": sorted({e["sensor"] for e in events if e["status"] == STATUS_SENSOR_FAULT}),
        "granted": any(e["status"] == STATUS_REACCEPTED_WITH_INFLATION for e in events),
        "latency_s": latency,
        "rejected_pct": 0.0 if not seen else 100.0 * rejected / seen,
    }


def collect(record: dict[str, Any], onset_s: float | None = None) -> dict[str, Any]:
    return {**_collect(record), **detection_stats(record, onset_s)}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cell summary: the usual metrics, how many seeds detected and declared, and the rejection share."""
    out = summarise_cell(rows)
    out["detected_n"] = sum(1 for r in rows if r["detected"])
    out["declared_n"] = sum(1 for r in rows if r["declared"])
    out["granted_n"] = sum(1 for r in rows if r["granted"])
    out["declared_channels"] = ";".join(sorted({c for r in rows for c in r["declared_channels"]}))
    latencies = [r["latency_s"] for r in rows if r["latency_s"] is not None]
    out["latency_s"] = statistics.fmean(latencies) if latencies else None
    out["rejected_pct"] = _interval([r["rejected_pct"] for r in rows])
    return out


def cell_row(cell: dict[str, Any]) -> dict[str, Any]:
    """The flat record of one cell, as written to the CSV."""
    keys = ("fault", "base", "level", "unit", "n_seeds", "detected_n", "declared_n", "granted_n")
    row: dict[str, Any] = {k: cell[k] for k in keys}
    row["latency_s_mean"] = cell["latency_s"]
    row["declared_channels"] = cell["declared_channels"]
    for metric in (*METRICS, "rejected_pct"):
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
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if key in TEXT_FIELDS:
                    row[key] = value
                elif key in INT_FIELDS:
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
    (ADR-0009). Text, counts, the row count and the order must match exactly.
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
    """The table on the fault page: each base case, its control first, then its faults."""
    columns = (
        "Case",
        "Fault",
        "Level",
        "ATE rmse m [95% CI]",
        "NEES mean [95% CI]",
        "Coverage @2σ % [95% CI]",
        "Gate rejected",
        "Fault declared",
        "Declared channel",
        "Latency s",
        "Inflation grant",
        "Measurements rejected % [95% CI]",
    )
    lines = [
        "| " + " | ".join(columns) + " |",
        "|---|---|---:|---|---|---|---:|---:|---|---:|---:|---|",
    ]
    order = {fid: i for i, fid in enumerate(["control", *BY_ID])}
    for base in BASES:
        group = sorted((r for r in rows if r["base"] == base), key=lambda r: (order[r["fault"]], r["level"]))
        for r in group:
            if r["fault"] == "control":
                name, level = "none (control)", ""
            else:
                name, level = BY_ID[r["fault"]].label, f"{r['level']:g} {r['unit']}"
            n = r["n_seeds"]
            lines.append(
                f"| {base} | {name} | {level} | {_fmt(r, 'ate_rmse_m', 2)} | {_fmt(r, 'nees_mean', 1)} "
                f"| {_fmt(r, 'coverage_2sigma_pct', 1)} | {r['detected_n']}/{n} | {r['declared_n']}/{n} "
                f"| {r['declared_channels'] or 'none'} "
                f"| {'n/a' if r['latency_s_mean'] is None else format(r['latency_s_mean'], '.1f')} "
                f"| {r['granted_n']}/{n} | {_fmt(r, 'rejected_pct', 1)} |"
            )
    return "\n".join(lines)


def splice_table(page: str, table: str) -> str:
    """Replace the generated block of the fault page with ``table``."""
    if PAGE_START not in page or PAGE_END not in page:
        raise ValueError(f"the page needs {PAGE_START} ... {PAGE_END} markers")
    head, rest = page.split(PAGE_START, 1)
    _, tail = rest.split(PAGE_END, 1)
    return f"{head}{PAGE_START}\n\n{table}\n\n{PAGE_END}{tail}"


def _run_cell(
    fault_id: str,
    base: str,
    level: float,
    case: dict[str, Any],
    hook: GnssHook | None,
    defaults: dict[str, Any],
    seeds: int,
    onset_s: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for seed in range(seeds):
        record = run_case(base, case, defaults, seed=seed, gnss_hook=hook, fdir_events=True, force_inject=True)
        row = collect(record, onset_s)
        rows.append(row)
        runs.append({"fault": fault_id, "base": base, "level": level, **row})
    return rows, runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="navkit sweep faults", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=Path("results") / "fault_matrix.json")
    ap.add_argument("--csv", type=Path, default=None, help="also write one row per cell to this CSV")
    ap.add_argument("--page", type=Path, default=None, help="rewrite the generated table block in this page")
    ap.add_argument("--faults", nargs="+", default=None, help="fault ids to run (default: all); see --list")
    ap.add_argument("--list", action="store_true", help="list the fault ids and exit")
    ap.add_argument("--seeds", type=int, default=5, help="noise seeds per cell, starting at 0")
    ap.add_argument("--markdown", action="store_true", help="print the summary table")
    ap.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="after the run, exit 1 unless the result matches this committed CSV (numbers within 1e-6)",
    )
    args = ap.parse_args(argv)

    if args.list:
        for f in FAULTS:
            print(f"{f.id:<26} {f.base:<14} levels {', '.join(f'{lv:g}' for lv in f.levels)} {f.unit}")
        return 0
    config_given = args.config is not None
    if args.config is None:
        args.config = default_config_path()
    if args.seeds < 2:
        raise SystemExit("a spread needs at least 2 seeds")
    selected = list(BY_ID) if args.faults is None else args.faults
    unknown = [f for f in selected if f not in BY_ID]
    if unknown:
        raise SystemExit(f"unknown fault(s): {', '.join(unknown)}; known: {', '.join(BY_ID)}")

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    faults = [BY_ID[f] for f in selected]
    bases = [b for b in BASES if any(f.base == b for f in faults)]
    missing = [b for b in bases if b not in cases]
    if missing:
        raise SystemExit(f"the config has no case(s) {', '.join(missing)}")

    cells: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []

    def run(
        fault_id: str,
        base: str,
        level: float,
        unit: str,
        case: dict[str, Any],
        hook: GnssHook | None,
        onset_s: float | None = None,
    ) -> None:
        t0 = time.perf_counter()
        rows, cell_runs = _run_cell(fault_id, base, level, case, hook, defaults, args.seeds, onset_s)
        runs.extend(cell_runs)
        cells.append({"fault": fault_id, "base": base, "level": level, "unit": unit, **summarise(rows)})
        print(
            f"ran {base} {fault_id} {level:g} over {args.seeds} seeds ({time.perf_counter() - t0:.1f} s)",
            file=sys.stderr,
            flush=True,
        )

    for base in bases:
        run("control", base, 0.0, "", cases[base], None)
    for fault in faults:
        for level in fault.levels:
            case, hook = fault.build(cases[fault.base], level)
            run(fault.id, fault.base, level, fault.unit, case, hook, fault.onset_s)

    flat = [cell_row(c) for c in cells]
    payload = {
        "schema": "navkit-fault-matrix/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "Synthetic fixture with faults injected into the sensor streams. Detection and false-alarm rates "
            "over a known-answer fixture and a handful of seeds are not field measurements and must not be "
            "presented as real-sensor performance."
        ),
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "config_file": _config_label(args.config, config_given),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "n_seeds": args.seeds,
        "faults": {
            f.id: {"label": f.label, "base": f.base, "unit": f.unit, "levels": list(f.levels), "fmea": f.fmea}
            for f in faults
        },
        "definitions": {
            "detected": "the gate rejected at least one measurement in the run",
            "declared": "the FDIR layer declared a channel faulty at some point in the run (from its event log)",
            "granted": "the NIS monitor gave a channel one bounded covariance inflation (ADR-0006)",
            "latency_s": "mean time from the fault's onset to the first declaration, over the seeds that declared",
            "false_alarm": "the same two measures on the control (the base case with no fault)",
        },
        "varies": "one fault, one level at a time, and the noise seed",
        "does_not_vary": (
            "Trajectory, filter tuning, fault window and the sensors' noise models. Each fault is one window "
            "on one synthetic path. The fault is not part of the scenario hash for the position offsets, which are "
            "applied to the GNSS stream after the scenario; the fault id and level are recorded with every run."
        ),
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
    if args.markdown:
        print()
        print(markdown_table(flat))
    if args.compare is not None:
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
