"""Can the GNSS innovations tell multipath, spoofing and sensor degradation apart?

Track A asks for more than "this channel is faulty". This is a feasibility study on real recorded IMU data (EuRoC,
TUM VI) with simulated GNSS. One fault is injected 35 s into each recording, in four classes:

* **multipath**: extra white noise on every GNSS fix for 20 s (no mean shift);
* **spoofing**: a slow ramp or a step offset on the GNSS positions (a consistent, moving or shifted track);
* **degradation**: a constant added to the accelerometer or the gyroscope (the IMU is wrong, the GNSS is healthy);
* **control**: nothing.

Five features are read from the 20 s of GNSS innovations after the onset: their normalised size (NIS), the whitened
mean (mean shift), the slope of the innovation over time (drift), and how far the filter's bias estimates moved.
A small decision tree is cross-validated leaving one sequence out. The point is to find which causes the
innovations can separate, and at which fault sizes, not to ship a detector. Simulated GNSS, injected faults, two
datasets, the calibrated bias-walk setting.
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

ONSET_S = 35.0
WINDOW_S = 20.0
MIN_FIXES = 20
CLASSES = ("control", "multipath", "spoofing", "degradation")
#: (class, kind, level, unit)
CASES: tuple[tuple[str, str, float], ...] = (
    ("control", "none", 0.0),
    ("multipath", "multipath", 3.0),
    ("multipath", "multipath", 10.0),
    ("multipath", "multipath", 30.0),
    ("spoofing", "ramp", 0.5),
    ("spoofing", "ramp", 1.0),
    ("spoofing", "ramp", 2.0),
    ("spoofing", "ramp", 5.0),
    ("spoofing", "step", 10.0),
    ("spoofing", "step", 50.0),
    ("degradation", "accel_bias", 0.2),
    ("degradation", "accel_bias", 1.0),
    ("degradation", "gyro_bias", 0.01),
    ("degradation", "gyro_bias", 0.05),
)
SETTINGS = {"euroc": "walk10", "tumvi": "file-walk10"}
FEATURES = ("nis", "mean_shift", "drift_m_s", "bias_accel", "bias_gyro")
CSV_COLUMNS = ("dataset", "sequence", "seed", "cls", "kind", "level", *FEATURES)
TREE_DEPTH = 3


def features(inn: list[Any], bias: list[Any], onset_abs: float) -> dict[str, float] | None:
    """The five features of the innovations in the 20 s after the onset, or None if there are too few fixes."""
    sel = [i for i in inn if onset_abs <= i[0] < onset_abs + WINDOW_S]
    if len(sel) < MIN_FIXES:
        return None
    t = np.array([i[0] for i in sel])
    r = np.stack([i[1] for i in sel])
    d2 = np.array([float(i[1] @ np.linalg.solve(i[2], i[1])) for i in sel])
    z = np.stack([np.linalg.solve(np.linalg.cholesky(i[2]), i[1]) for i in sel])
    n = len(sel)
    tc = t - t.mean()
    slope = (tc[:, None] * (r - r.mean(axis=0))).sum(axis=0) / float((tc**2).sum())
    before = [b for b in bias if b[0] < onset_abs]
    inside = [b for b in bias if onset_abs <= b[0] < onset_abs + WINDOW_S]
    ref = before[-1] if before else inside[0]
    last = inside[-1]
    return {
        "nis": float(d2.mean() / 3.0),
        "mean_shift": float(np.linalg.norm(z.mean(axis=0)) * np.sqrt(n)),
        "drift_m_s": float(np.linalg.norm(slope)),
        "bias_accel": float(np.linalg.norm(last[2] - ref[2])),
        "bias_gyro": float(np.linalg.norm(last[1] - ref[1])),
    }


def run_case(seq: Any, config: str, seed: int, case: tuple[str, str, float]) -> dict[str, Any] | None:
    cls, kind, level = case
    t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0]))
    duration = float(min(seq.imu.t[-1], seq.truth.t[-1])) - t_start
    if duration < ONSET_S + WINDOW_S + 5.0:
        return None
    fault = None if kind == "none" else (kind, ONSET_S, level)
    inn: list[Any] = []
    bias: list[Any] = []
    run_sequence(seq, RunOptions(seed=seed, fault=fault, **_ALL_CONFIGS[config]), innovations_out=inn, bias_out=bias)
    f = features(inn, bias, t_start + ONSET_S)
    if f is None:
        return None
    return {"dataset": seq.slug, "sequence": seq.name, "seed": seed, "cls": cls, "kind": kind, "level": level, **f}


def sweep_rows(dataset: str, root: str | Path, seeds: int) -> list[dict[str, Any]]:
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir()):
        seq = loader(root, name)
        for seed in range(seeds):
            for case in CASES:
                row = run_case(seq, SETTINGS[dataset], seed, case)
                if row is not None:
                    rows.append(row)
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


# ------------------------------------------------------------------ classifier
#
# Two stages, because one tree over all four classes learns the class sizes. The control is a twelfth of the runs,
# and a weak fault looks like it, so a single tree calls the control a spoof. Stage 1 asks only "is anything wrong":
# a feature must exceed its largest value on the training controls, which makes the false-alarm rate on the training
# controls zero. The rate on held-out sequences is what is reported, and it is not zero.
# Stage 2 names the cause of the runs that stage 1 flagged,
# with a small tree trained on faults only and weighted so that each class counts equally.


def _wgini(y: np.ndarray, w: np.ndarray, k: int) -> float:
    total = w.sum()
    if total <= 0.0:
        return 0.0
    p = np.bincount(y, weights=w, minlength=k) / total
    return float(1.0 - (p**2).sum())


def fit_tree(x: np.ndarray, y: np.ndarray, w: np.ndarray, k: int, depth: int = TREE_DEPTH) -> dict[str, Any]:
    """A small weighted CART tree on raw features: ``{"leaf": class}`` or ``{"f", "thr", "lo", "hi"}``."""
    weights = np.bincount(y, weights=w, minlength=k)
    leaf = {"leaf": int(np.argmax(weights))}
    if depth == 0 or (weights > 0).sum() <= 1:
        return leaf
    best: tuple[float, int | None, float] = (_wgini(y, w, k), None, 0.0)
    for f in range(x.shape[1]):
        vals = np.unique(x[:, f])
        for thr in (vals[:-1] + vals[1:]) / 2.0:
            lo = x[:, f] <= thr
            wl, wh = w[lo].sum(), w[~lo].sum()
            score = (wl * _wgini(y[lo], w[lo], k) + wh * _wgini(y[~lo], w[~lo], k)) / (wl + wh)
            if score < best[0] - 1e-12:
                best = (score, f, float(thr))
    if best[1] is None:
        return leaf
    f, thr = best[1], best[2]
    lo = x[:, f] <= thr
    return {
        "f": f,
        "thr": thr,
        "lo": fit_tree(x[lo], y[lo], w[lo], k, depth - 1),
        "hi": fit_tree(x[~lo], y[~lo], w[~lo], k, depth - 1),
    }


def predict(tree: dict[str, Any], row: np.ndarray) -> int:
    while "leaf" not in tree:
        tree = tree["lo"] if row[tree["f"]] <= tree["thr"] else tree["hi"]
    return int(tree["leaf"])


FAULT_CLASSES = CLASSES[1:]


def _matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(r[f]) for f in FEATURES] for r in rows])
    y = np.array([CLASSES.index(r["cls"]) for r in rows])
    return x, y


def _balanced(y: np.ndarray, k: int) -> np.ndarray:
    counts = np.bincount(y, minlength=k).astype(float)
    return 1.0 / counts[y]


def fit_detector(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stage 1 thresholds (the largest value of each feature on the controls) and the stage 2 tree."""
    x, y = _matrix(rows)
    ctrl = y == 0
    faults = ~ctrl
    yf = y[faults] - 1
    tree = fit_tree(x[faults], yf, _balanced(yf, len(FAULT_CLASSES)), len(FAULT_CLASSES))
    return {"threshold": x[ctrl].max(axis=0), "tree": tree}


def call(model: dict[str, Any], row: np.ndarray) -> str:
    if not np.any(row > model["threshold"]):
        return "control"
    return FAULT_CLASSES[predict(model["tree"], row)]


def cross_validate(rows: list[dict[str, Any]]) -> list[str]:
    """The called class per row, each from a model fitted without that row's sequence."""
    x, _ = _matrix(rows)
    seqs = np.array([f"{r['dataset']}/{r['sequence']}" for r in rows])
    out = [""] * len(rows)
    for s in np.unique(seqs):
        test = seqs == s
        model = fit_detector([r for r, t in zip(rows, test, strict=True) if not t])
        for i in np.flatnonzero(test):
            out[i] = call(model, x[i])
    return out


def with_predictions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "predicted": p} for r, p in zip(rows, cross_validate(rows), strict=True)]


def model_text(rows: list[dict[str, Any]]) -> str:
    model = fit_detector(rows)

    def walk(t: dict[str, Any], pad: str) -> list[str]:
        if "leaf" in t:
            return [f"{pad}-> {FAULT_CLASSES[t['leaf']]}"]
        name = FEATURES[t["f"]]
        return [
            f"{pad}{name} <= {t['thr']:.4g}:",
            *walk(t["lo"], pad + "  "),
            f"{pad}{name} > {t['thr']:.4g}:",
            *walk(t["hi"], pad + "  "),
        ]

    head = [
        "stage 1: a fault if any feature exceeds its control maximum: "
        + str({n: round(float(v), 4) for n, v in zip(FEATURES, model["threshold"], strict=True)})
    ]
    return "\n".join([*head, "stage 2:", *walk(model["tree"], "  ")])


# --------------------------------------------------------------------- tables


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def confusion_markdown(scored: list[dict[str, Any]]) -> str:
    lines = [
        "| True class | Runs | " + " | ".join(f"Called {c}" for c in CLASSES) + " |",
        "|---|---:|" + "---:|" * len(CLASSES),
    ]
    for c in CLASSES:
        sel = [r for r in scored if r["cls"] == c]
        cells = " | ".join(_pct(sum(r["predicted"] == p for r in sel) / len(sel)) for p in CLASSES)
        lines.append(f"| {c} | {len(sel)} | {cells} |")
    return "\n".join(lines)


def level_markdown(scored: list[dict[str, Any]]) -> str:
    lines = [
        "| Class | Fault | Level | Runs | Called correctly | Called control (missed) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for cls, kind, level in CASES:
        sel = [r for r in scored if r["kind"] == kind and float(r["level"]) == level]
        if not sel:
            continue
        ok = sum(r["predicted"] == cls for r in sel) / len(sel)
        miss = sum(r["predicted"] == "control" for r in sel) / len(sel)
        lines.append(f"| {cls} | {kind} | {level:g} | {len(sel)} | {_pct(ok)} | {_pct(miss)} | {_pct(1.0 - miss)} |")
    return "\n".join(lines)


def feature_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Fault | Level | " + " | ".join(FEATURES) + " |", "|---|---:|" + "---:|" * len(FEATURES)]
    for _cls, kind, level in CASES:
        sel = [r for r in rows if r["kind"] == kind and float(r["level"]) == level]
        if sel:
            cells = " | ".join(f"{np.median([float(r[f]) for r in sel]):.3g}" for f in FEATURES)
            lines.append(f"| {kind} | {level:g} | {cells} |")
    return "\n".join(lines)


BLOCKS = {
    "faultclass-features": lambda rows: feature_markdown(rows),
    "faultclass-confusion": lambda rows: confusion_markdown(with_predictions(rows)),
    "faultclass-levels": lambda rows: level_markdown(with_predictions(rows)),
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
        prog="navkit sweep faultclass", description="Can GNSS innovations separate multipath, spoofing and degradation?"
    )
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--csv", default=None, help="write one row per run")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the faultclass blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.from_csv:
        rows = rows_from_csv(args.from_csv)
    else:
        rows = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            rows += sweep_rows(ds, root, args.seeds)
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
