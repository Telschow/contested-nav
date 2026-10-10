"""Can the GNSS gate tell an honest return after an outage from a spoofed one?

Until the first fix after an outage, the filter state is the same whether that fix is honest or spoofed.
A spoof that shifts the fix by ``delta`` metres therefore shifts that first innovation by ``delta``, and
nothing else. So one run per honest case gives the spoof statistic for every spoof size and direction:
``d2 = (r + delta u)' S^-1 (r + delta u)``, where ``r`` is the honest innovation and ``S`` its covariance.

The honest population is real-IMU outage runs (EuRoC, TUM VI) with simulated GNSS. The spoof population is
derived from it. Nothing is injected into a filter, so the result says what the first gate can do, not what
a full spoofing campaign does. Results must be quoted with that, and with the simulated GNSS.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .euroc_compare import _ALL_CONFIGS, DEFAULT_OUTAGE_S, DEFAULT_STARTS, fitting_starts
from .euroc_eval import RunOptions, dataset_loader, run_sequence
from .fdir.config import FdirConfig
from .fdir.gating import chi2_threshold

DOF = 3
#: Spoof sizes in metres, and how many evenly spread directions are tried per honest run.
SPOOF_SIZES_M = (5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
DIRECTIONS = 64
#: Honest false-alarm rate used to set a gate from the data.
MATCHED_ALPHA = 0.05
CSV_COLUMNS = (
    "dataset",
    "sequence",
    "config",
    "start_s",
    "seed",
    "rx",
    "ry",
    "rz",
    "sxx",
    "syy",
    "szz",
    "sxy",
    "sxz",
    "syz",
)
#: Which configurations are the "calibrated" and "default" ones, per dataset.
SETTINGS = {
    "euroc": ("default", "walk10"),
    "tumvi": ("file", "allan", "file-walk10"),
}


def shipped_gate() -> float:
    """The chi-square threshold the FDIR layer applies to a three-dimensional GNSS innovation."""
    return float(chi2_threshold(DOF, FdirConfig().alpha))


def honest_rows(
    dataset: str, root: str | Path, configs: tuple[str, ...], seeds: int, outage_s: float = DEFAULT_OUTAGE_S
) -> list[dict[str, Any]]:
    """The first GNSS innovation after each outage, one row per sequence, start, seed and configuration."""
    loader, _ = dataset_loader(dataset)
    names = sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir())
    rows: list[dict[str, Any]] = []
    for name in names:
        seq = loader(root, name)
        t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0]))
        window = float(min(seq.imu.t[-1], seq.truth.t[-1])) - t_start
        for start in fitting_starts(window, DEFAULT_STARTS, outage_s):
            for seed in range(seeds):
                for config in configs:
                    inn: list[tuple[float, np.ndarray, np.ndarray]] = []
                    opts = RunOptions(seed=seed, outages=((start, outage_s),), **_ALL_CONFIGS[config])
                    run_sequence(seq, opts, innovations_out=inn)
                    after = [i for i in inn if i[0] >= t_start + start + outage_s]
                    if not after:
                        continue
                    _, r, s = after[0]
                    rows.append(
                        {
                            "dataset": dataset,
                            "sequence": name,
                            "config": config,
                            "start_s": start,
                            "seed": seed,
                            "rx": r[0],
                            "ry": r[1],
                            "rz": r[2],
                            "sxx": s[0, 0],
                            "syy": s[1, 1],
                            "szz": s[2, 2],
                            "sxy": s[0, 1],
                            "sxz": s[0, 2],
                            "syz": s[1, 2],
                        }
                    )
    return rows


def _rs(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    f = {k: float(row[k]) for k in CSV_COLUMNS[5:]}
    r = np.array([f["rx"], f["ry"], f["rz"]])
    s = np.array([[f["sxx"], f["sxy"], f["sxz"]], [f["sxy"], f["syy"], f["syz"]], [f["sxz"], f["syz"], f["szz"]]])
    return r, s


def directions(n: int = DIRECTIONS) -> np.ndarray:
    """Evenly spread unit vectors (Fibonacci sphere), fixed so the table is reproducible."""
    k = np.arange(n) + 0.5
    z = 1.0 - 2.0 * k / n
    phi = np.pi * (1.0 + 5**0.5) * k
    rho = np.sqrt(1.0 - z * z)
    return np.stack([rho * np.cos(phi), rho * np.sin(phi), z], axis=1)


def honest_d2(row: dict[str, Any]) -> float:
    r, s = _rs(row)
    return float(r @ np.linalg.solve(s, r))


def sigma_m(row: dict[str, Any]) -> float:
    _, s = _rs(row)
    return float(np.sqrt(np.trace(s) / 3.0))


def spoof_d2(row: dict[str, Any], delta_m: float) -> np.ndarray:
    """Statistic for a spoof of ``delta_m`` metres in each of the fixed directions."""
    r, s = _rs(row)
    shifted = r[None, :] + delta_m * directions()
    return np.einsum("ij,ji->i", shifted, np.linalg.solve(s, shifted.T))


def detection_rate(rows: list[dict[str, Any]], delta_m: float, gate: float) -> float:
    hits = [np.mean(spoof_d2(r, delta_m) > gate) for r in rows]
    return float(np.mean(hits)) if hits else float("nan")


def matched_gate(rows: list[dict[str, Any]], alpha: float = MATCHED_ALPHA) -> float:
    """Gate that rejects ``alpha`` of these honest returns."""
    return float(np.quantile([honest_d2(r) for r in rows], 1.0 - alpha))


def select(rows: list[dict[str, Any]], dataset: str, config: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["dataset"] == dataset and r["config"] == config]


def min_detected_m(rows: list[dict[str, Any]], gate: float, rate: float = 0.9) -> float | None:
    """Smallest listed spoof size detected at least ``rate`` of the time, or None if none is."""
    for d in SPOOF_SIZES_M:
        if detection_rate(rows, d, gate) >= rate:
            return d
    return None


# --------------------------------------------------------------------- tables


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def honest_markdown(rows: list[dict[str, Any]]) -> str:
    gate = shipped_gate()
    lines = [
        "| Dataset | Setting | Honest returns | Median d² | 95th percentile d² | "
        f"Rejected by the shipped gate ({gate:.1f}) | Median claimed σ at return (m) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for ds, cfgs in SETTINGS.items():
        for c in cfgs:
            sel = select(rows, ds, c)
            if not sel:
                continue
            d2 = np.array([honest_d2(r) for r in sel])
            lines.append(
                f"| {ds} | {c} | {len(sel)} | {np.median(d2):.2f} | {np.percentile(d2, 95):.1f} | "
                f"{_pct(float(np.mean(d2 > gate)))} | {np.median([sigma_m(r) for r in sel]):.1f} |"
            )
    return "\n".join(lines)


def detection_markdown(rows: list[dict[str, Any]]) -> str:
    gate = shipped_gate()
    head = "| Dataset | Setting | " + " | ".join(f"{d:g} m" for d in SPOOF_SIZES_M) + " |"
    lines = [head, "|---|---|" + "---:|" * len(SPOOF_SIZES_M)]
    for ds, cfgs in SETTINGS.items():
        for c in cfgs:
            sel = select(rows, ds, c)
            if sel:
                cells = " | ".join(_pct(detection_rate(sel, d, gate)) for d in SPOOF_SIZES_M)
                lines.append(f"| {ds} | {c} | {cells} |")
    return "\n".join(lines)


def heldout_markdown(rows: list[dict[str, Any]]) -> str:
    """Set the gate on EuRoC at a 5% honest false-alarm rate; apply it to TUM VI."""
    lines = [
        "| Setting pair (EuRoC gate -> TUM VI) | Gate | EuRoC honest rejected | TUM VI honest rejected | "
        "Spoof size detected 90% (TUM VI) |",
        "|---|---:|---:|---:|---:|",
    ]
    for eu, tum in (("walk10", "file-walk10"),):
        a, b = select(rows, "euroc", eu), select(rows, "tumvi", tum)
        if not (a and b):
            continue
        g = matched_gate(a)
        far_a = float(np.mean([honest_d2(r) > g for r in a]))
        far_b = float(np.mean([honest_d2(r) > g for r in b]))
        m = min_detected_m(b, g)
        size = "none listed" if m is None else f"{m:g} m"
        lines.append(f"| {eu} -> {tum} | {g:.1f} | {_pct(far_a)} | {_pct(far_b)} | {size} |")
    return "\n".join(lines)


BLOCKS = {
    "separability-honest": honest_markdown,
    "separability-detection": detection_markdown,
    "separability-heldout": heldout_markdown,
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
        prog="navkit sweep separability",
        description="Honest returns after real-IMU outages against spoofs of several sizes, at the first GNSS gate.",
    )
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--csv", default=None, help="write one row per honest return")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the separability blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_csv:
        rows = rows_from_csv(args.from_csv)
    else:
        rows = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            print(f"{ds} ...", file=sys.stderr, flush=True)
            rows += honest_rows(ds, root, SETTINGS[ds], args.seeds)
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
