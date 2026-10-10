"""Does a second, independent source expose a slow-ramp GNSS spoof?

The slow-ramp study (ADR-0019) showed that an IMU and GNSS alone follow a ramp of 0.05 to 2 m/s. A visual relative
pose measures motion between frames, not absolute position, so a ramp whose velocity disagrees with it should show
as a growing GNSS innovation. This repeats the ramp runs with a simulated visual front end fused by the stochastic
clone (ADR-0017), and reads the same measures from the same runs.

Two front ends, both generated from the ground truth and never from images: independent errors, which is the case
the clone is calibrated for, and errors correlated over a second with the filter's assumed noise four times larger,
which is the setting ADR-0017 found by trial. ``vision_enabled`` stays False in the shipped configuration.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from . import slow_ramp as sr
from .euroc_eval import dataset_loader

FRONT_ENDS: dict[str, dict[str, Any]] = {
    "independent": {"vision": "clone", "vision_corr_s": 0.0, "vision_noise_scale": 1.0},
    "correlated": {"vision": "clone", "vision_corr_s": 1.0, "vision_noise_scale": 4.0},
}
SETTINGS = {"euroc": ("walk10",), "tumvi": ("file-walk10",)}
CSV_COLUMNS = ("front_end", *sr.CSV_COLUMNS)


def sweep_rows(dataset: str, root: str | Path, configs: tuple[str, ...], seeds: int) -> list[dict[str, Any]]:
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir()):
        seq = loader(root, name)
        for front, extra in FRONT_ENDS.items():
            for arm in sr.ARMS:
                for rate in sr.RATES_M_S:
                    for seed in range(seeds):
                        for config in configs:
                            row = sr.run_case(seq, config, arm, rate, seed, extra=extra)
                            if row is not None:
                                rows.append({"front_end": front, **row})
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


def select(rows: list[dict[str, Any]], front: str, dataset: str, arm: str, rate: float) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if r["front_end"] == front and r["dataset"] == dataset and float(r["rate_m_s"]) == rate and r["arm"] == arm
    ]


def vision_markdown(rows: list[dict[str, Any]], arm: str) -> str:
    lines = [
        "| Front end | Dataset | Ramp m/s | Runs | Over the gate | Declared faulty | Captured | "
        "First over the gate, s after onset (median) | Final error m (median) | Final offset m (median) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for front in FRONT_ENDS:
        for ds in SETTINGS:
            for rate in sr.RATES_M_S:
                sel = select(rows, front, ds, arm, rate)
                if not sel:
                    continue
                s = sr.stats(sel)
                lines.append(
                    f"| {front} | {ds} | {rate:g} | {s['runs']:.0f} | {sr._pct(s['over_gate'])} | "
                    f"{sr._pct(s['faulted'])} | {sr._pct(s['captured'])} | {sr._t(s['median_first_over_gate_s'])} | "
                    f"{s['median_final_error_m']:.1f} | {s['median_final_offset_m']:.1f} |"
                )
    return "\n".join(lines)


BLOCKS = {
    "vision-ramp-clean": lambda rows: vision_markdown(rows, "clean"),
    "vision-ramp-after-outage": lambda rows: vision_markdown(rows, "after_outage"),
}


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    import csv

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit sweep vision-ramp", description="Slow-ramp GNSS spoofs with a simulated visual second source."
    )
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--csv", default=None, help="write one row per run")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the vision-ramp blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_csv:
        rows = sr.rows_from_csv(args.from_csv)
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
                sr.write_block(args.page, name, text)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.markdown or not (args.csv or args.page):
        print("\n\n".join(tables.values()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
