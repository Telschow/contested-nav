"""How small a multipath fault does the signature catch, and does it call anything else?

The thresholds of :mod:`navkit.fdir.multipath` were fixed before this study. This evaluates them on runs the
fault-classification study never used for the thresholds: its confirmation runs (544, unseen fault sizes and seeds),
plus new runs here: multipath at 0.5 to 2 m, to find the floor, and extra control runs, on seeds 6 and 7.

Simulated GNSS, injected faults, two datasets, the calibrated bias-walk setting.
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
from .fault_classification import ONSET_S, SETTINGS, WINDOW_S, rows_from_csv
from .fdir import multipath as mp

FLOOR_LEVELS_M = (0.5, 1.0, 1.5, 2.0)
SEEDS = (6, 7)
CONFIRM_CSV = "docs/data/fault_classification_confirm.csv"
CSV_COLUMNS = ("dataset", "sequence", "seed", "kind", "level", "nis", "ac1", "multipath")


def run_case(seq: Any, config: str, seed: int, level: float) -> dict[str, Any] | None:
    """One run: multipath of ``level`` metres (0 for a control), and the signature of the window after the onset."""
    t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0]))
    if float(min(seq.imu.t[-1], seq.truth.t[-1])) - t_start < ONSET_S + WINDOW_S + 5.0:
        return None
    fault = ("multipath", ONSET_S, level) if level > 0 else None
    inn: list[Any] = []
    run_sequence(seq, RunOptions(seed=seed, fault=fault, **_ALL_CONFIGS[config]), innovations_out=inn)
    onset = t_start + ONSET_S
    sig = mp.signature([i for i in inn if onset <= i[0] < onset + WINDOW_S])
    if sig is None:
        return None
    return {
        "dataset": seq.slug,
        "sequence": seq.name,
        "seed": seed,
        "kind": "multipath" if level > 0 else "none",
        "level": level,
        "nis": sig.nis,
        "ac1": sig.ac1,
        "multipath": sig.multipath,
    }


def sweep_rows(dataset: str, root: str | Path) -> list[dict[str, Any]]:
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir()):
        seq = loader(root, name)
        for level in (0.0, *FLOOR_LEVELS_M):
            for seed in SEEDS:
                row = run_case(seq, SETTINGS[dataset], seed, level)
                if row is not None:
                    rows.append(row)
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


# --------------------------------------------------------------------- tables


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _called(row: dict[str, Any]) -> bool:
    return str(row["multipath"]) in ("True", "true", "1")


def upper_bound(n: int) -> float:
    """The rule of three: with no events in ``n`` trials, the 95% upper bound on the rate is about ``3 / n``."""
    return 3.0 / n


def confirm_rows(path: str | Path = CONFIRM_CSV) -> list[dict[str, Any]]:
    """The confirmation runs of the fault-classification study, with the call recomputed from the stored features."""
    out = []
    for r in rows_from_csv(path):
        nis, ac1 = float(r["nis"]), float(r["ac1"])
        out.append({**r, "multipath": nis >= mp.NIS_MIN and ac1 <= mp.AC1_MAX})
    return out


def confirm_markdown(rows: list[dict[str, Any]]) -> str:
    cr = confirm_rows()
    lines = ["| Class | Runs | Called multipath |", "|---|---:|---:|"]
    for cls in ("control", "multipath", "spoofing", "degradation"):
        sel = [r for r in cr if r["cls"] == cls]
        lines.append(f"| {cls} | {len(sel)} | {_pct(sum(_called(r) for r in sel) / len(sel))} |")
    return "\n".join(lines)


def floor_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Multipath m | Runs | Called multipath | Median NIS | Median lag-1 autocorrelation |",
        "|---:|---:|---:|---:|---:|",
    ]
    for level in (0.0, *FLOOR_LEVELS_M):
        sel = [r for r in rows if float(r["level"]) == level]
        if sel:
            lines.append(
                f"| {level:g} | {len(sel)} | {_pct(sum(_called(r) for r in sel) / len(sel))} | "
                f"{np.median([float(r['nis']) for r in sel]):.2f} | {np.median([float(r['ac1']) for r in sel]):.2f} |"
            )
    return "\n".join(lines)


def false_alarm_markdown(rows: list[dict[str, Any]]) -> str:
    cr = [r for r in confirm_rows() if r["cls"] == "control"]
    new = [r for r in rows if float(r["level"]) == 0.0]
    lines = [
        "| Control runs | Runs | Called multipath | 95% upper bound on the false-alarm rate |",
        "|---|---:|---:|---:|",
    ]
    for label, sel in (("confirmation", cr), ("new", new), ("both", cr + new)):
        hits = sum(_called(r) for r in sel)
        bound = _pct(upper_bound(len(sel))) if hits == 0 else "see the count"
        lines.append(f"| {label} | {len(sel)} | {hits} | {bound} |")
    return "\n".join(lines)


BLOCKS = {
    "multipath-confirm": confirm_markdown,
    "multipath-floor": floor_markdown,
    "multipath-false-alarms": false_alarm_markdown,
}

# ------------------------------------------------------------------------- I/O


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


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
    p = argparse.ArgumentParser(prog="navkit sweep multipath", description="Evaluate the multipath signature.")
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--csv", default=None, help="write one row per new run")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the multipath blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_csv:
        with Path(args.from_csv).open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    else:
        rows = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            rows += sweep_rows(ds, root)
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
