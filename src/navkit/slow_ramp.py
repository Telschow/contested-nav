"""Does a slow-ramp GNSS spoof drag the filter along before anything reacts?

The separability study (ADR-0018) covers the first fix after an outage. This one covers a spoof that starts small
and grows: from the onset, every simulated GNSS position is shifted along world x by ``rate * (t - onset)``. The run
is a real recorded IMU (EuRoC, TUM VI) with simulated GNSS, in two arms: GNSS healthy until the onset, and a 20 s
outage ending at the onset. Rate 0 is the control for each case.

For every run it records when the first fix passed the chi-square gate's threshold, when the channel was declared
faulty, when the filter re-accepted GNSS with inflation (a loosening, so a possible capture), the position error
against the truth, and the spoof offset at each of those times. All of it is simulated GNSS on two datasets, and a
ramp along one axis.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .euroc_compare import _ALL_CONFIGS
from .euroc_eval import RunOptions, dataset_loader, run_sequence
from .fdir.status import STATUS_REACCEPTED_WITH_INFLATION, STATUS_SENSOR_FAULT
from .separability import shipped_gate

RATES_M_S = (0.0, 0.05, 0.2, 0.5, 1.0, 2.0)
ONSET_S = 35.0
OUTAGE = (15.0, 20.0)  # the outage arm: ends at the onset
ARMS = ("clean", "after_outage")
SETTINGS = {"euroc": ("default", "walk10"), "tumvi": ("file", "file-walk10")}
#: A run is "captured" when the final error exceeds this share of the final spoof offset.
CAPTURE_SHARE = 0.5
#: Shortest recording after the onset, so that a ramp has time to act.
MIN_AFTER_S = 30.0
CSV_COLUMNS = (
    "dataset",
    "sequence",
    "config",
    "arm",
    "rate_m_s",
    "seed",
    "after_onset_s",
    "first_over_gate_s",
    "fault_s",
    "reaccept_s",
    "final_error_m",
    "max_error_m",
    "final_offset_m",
)


def _first(times: list[float]) -> str:
    return f"{min(times):.3f}" if times else ""


def run_case(
    seq: Any, config: str, arm: str, rate: float, seed: int, extra: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0]))
    duration = float(min(seq.imu.t[-1], seq.truth.t[-1])) - t_start
    if duration < ONSET_S + MIN_AFTER_S:
        return None
    outages = (OUTAGE,) if arm == "after_outage" else ()
    spoof = (ONSET_S, rate) if rate > 0.0 else None
    inn: list[tuple[float, np.ndarray, np.ndarray]] = []
    events: list[dict[str, Any]] = []
    opts = RunOptions(seed=seed, outages=outages, spoof=spoof, **{**_ALL_CONFIGS[config], **(extra or {})})
    rec = run_sequence(seq, opts, innovations_out=inn, events_out=events)
    onset = t_start + ONSET_S
    gate = shipped_gate()
    over = [t - onset for t, r, s in inn if t >= onset and float(r @ np.linalg.solve(s, r)) > gate]
    gnss = [e for e in events if e["sensor"] == "gnss" and e["t_s"] >= onset]
    fault = [e["t_s"] - onset for e in gnss if e["status"] == STATUS_SENSOR_FAULT]
    reacc = [e["t_s"] - onset for e in gnss if e["status"] == STATUS_REACCEPTED_WITH_INFLATION]
    ts = np.asarray(rec["error_time_series"]["t"], dtype=float)
    err = np.asarray(rec["error_time_series"]["position_error_m"], dtype=float)
    since = ts - (t_start - float(seq.imu.t[0]) + ONSET_S)
    after = since >= 0.0
    return {
        "dataset": seq.slug,
        "sequence": seq.name,
        "config": config,
        "arm": arm,
        "rate_m_s": rate,
        "seed": seed,
        "after_onset_s": float(since[-1]),
        "first_over_gate_s": _first(over),
        "fault_s": _first(fault),
        "reaccept_s": _first(reacc),
        "final_error_m": float(err[-1]),
        "max_error_m": float(err[after].max()),
        "final_offset_m": rate * float(since[-1]),
    }


def sweep_rows(dataset: str, root: str | Path, configs: tuple[str, ...], seeds: int) -> list[dict[str, Any]]:
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir()):
        seq = loader(root, name)
        for arm in ARMS:
            for rate in RATES_M_S:
                for seed in range(seeds):
                    for config in configs:
                        row = run_case(seq, config, arm, rate, seed)
                        if row is not None:
                            rows.append(row)
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


# --------------------------------------------------------------------- tables


def _num(v: Any) -> float | None:
    return float(v) if v not in ("", None) else None


def select(rows: list[dict[str, Any]], dataset: str, config: str, arm: str, rate: float) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if r["dataset"] == dataset and r["config"] == config and r["arm"] == arm and float(r["rate_m_s"]) == rate
    ]


def captured(row: dict[str, Any]) -> bool:
    return float(row["final_error_m"]) > CAPTURE_SHARE * float(row["final_offset_m"]) > 0.0


def stats(sel: list[dict[str, Any]]) -> dict[str, float]:
    """Shares of runs, and medians over the runs where the event happened."""
    n = len(sel)
    gate = [_num(r["first_over_gate_s"]) for r in sel]
    fault = [_num(r["fault_s"]) for r in sel]
    reacc = [_num(r["reaccept_s"]) for r in sel]
    seen = [g for g in gate if g is not None]
    return {
        "runs": float(n),
        "over_gate": len(seen) / n,
        "faulted": sum(f is not None for f in fault) / n,
        "reaccepted": sum(x is not None for x in reacc) / n,
        "captured": sum(captured(r) for r in sel) / n,
        "median_first_over_gate_s": float(np.median(seen)) if seen else float("nan"),
        "median_final_error_m": float(np.median([float(r["final_error_m"]) for r in sel])),
        "median_final_offset_m": float(np.median([float(r["final_offset_m"]) for r in sel])),
    }


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _t(x: float) -> str:
    return "-" if x != x else f"{x:.0f}"


def ramp_markdown(rows: list[dict[str, Any]], arm: str) -> str:
    lines = [
        "| Dataset | Setting | Ramp m/s | Runs | Over the gate | Declared faulty | Re-accepted | Captured | "
        "First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ds, cfgs in SETTINGS.items():
        for c in cfgs:
            for rate in RATES_M_S:
                sel = select(rows, ds, c, arm, rate)
                if not sel:
                    continue
                s = stats(sel)
                lines.append(
                    f"| {ds} | {c} | {rate:g} | {s['runs']:.0f} | {_pct(s['over_gate'])} | {_pct(s['faulted'])} | "
                    f"{_pct(s['reaccepted'])} | {_pct(s['captured'])} | {_t(s['median_first_over_gate_s'])} | "
                    f"{s['median_final_error_m']:.1f} | {s['median_final_offset_m']:.1f} |"
                )
    return "\n".join(lines)


BLOCKS = {
    "ramp-clean": lambda rows: ramp_markdown(rows, "clean"),
    "ramp-after-outage": lambda rows: ramp_markdown(rows, "after_outage"),
}

# ------------------------------------------------------------------------- I/O


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_block(path: str | Path, name: str, block: str) -> None:
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text or text.index(start) > text.index(end):
        raise ValueError(f"{page} needs the lines {start} and {end}, in that order")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    page.write_text(f"{head}{start}\n\n{block}\n\n{end}{tail}", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit sweep ramp",
        description="Slow-ramp GNSS spoofs on real recorded IMU data.",
    )
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--csv", default=None, help="write one row per run")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the ramp blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_csv:
        rows = rows_from_csv(args.from_csv)
    else:
        rows = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            rows += sweep_rows(ds, root, SETTINGS[ds], args.seeds)
    if args.csv:
        write_csv(args.csv, rows)
        print(f"wrote {args.csv}", file=sys.stderr)
    tables = {name: fn(rows) for name, fn in BLOCKS.items()}
    if args.page:
        try:
            for name, text in tables.items():
                write_block(args.page, name, text)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.markdown or not (args.csv or args.page):
        print("\n\n".join(tables.values()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
