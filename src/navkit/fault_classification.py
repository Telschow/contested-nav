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
import math
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np

from .euroc_compare import _ALL_CONFIGS
from .euroc_eval import RunOptions, dataset_loader, list_sequence_dirs, run_sequence
from .report.page import write_block
from .report.table import Column, Table

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
#: The confirmation run: fault sizes the model never saw (between and beyond the training ones), and seeds it never
#: saw. Fixed here, and committed, before the run. The model is the one fitted on the whole training CSV, unchanged.
CONFIRM_CASES: tuple[tuple[str, str, float], ...] = (
    ("control", "none", 0.0),
    ("multipath", "multipath", 5.0),
    ("multipath", "multipath", 20.0),
    ("spoofing", "ramp", 0.75),
    ("spoofing", "ramp", 1.5),
    ("spoofing", "ramp", 3.0),
    ("spoofing", "ramp", 10.0),
    ("spoofing", "step", 5.0),
    ("spoofing", "step", 20.0),
    ("spoofing", "step", 100.0),
    ("degradation", "accel_bias", 0.4),
    ("degradation", "accel_bias", 0.7),
    ("degradation", "accel_bias", 2.0),
    ("degradation", "gyro_bias", 0.02),
    ("degradation", "gyro_bias", 0.1),
)
CONFIRM_FAULT_SEEDS = (2, 3)
CONFIRM_CONTROL_SEEDS = (2, 3, 4, 5)  # more controls: the false-alarm rate needs them
TRAIN_CSV = "docs/data/fault_classification.csv"
SETTINGS = {"euroc": "walk10", "tumvi": "file-walk10"}
#: The first five features of the original study, then the ones added to see whether richer innovations help.
BASE_FEATURES = ("nis", "mean_shift", "drift_m_s", "bias_accel", "bias_gyro")
EXTRA_FEATURES = ("ac1", "axis_conc", "decay", "bias_accel_30", "bias_gyro_30")
FEATURES = BASE_FEATURES + EXTRA_FEATURES
LONG_WINDOW_S = 30.0
EDGE_S = 5.0
CSV_COLUMNS = ("dataset", "sequence", "seed", "cls", "kind", "level", *FEATURES)
TREE_DEPTH = 3
#: Stage 1 rules. ``max`` is the first one: the largest value of each feature on the training controls.
#: ``bound`` is a one-sided upper bound from a distribution fitted to those controls, at ``ALPHA_PER_FEATURE`` per
#: feature. 0.005 is a total budget of 5% shared over the ten features (Bonferroni), fixed before the unseen controls
#: were scored. It is not a tuned value.
STAGE1_RULES = ("max", "bound")
ALPHA_PER_FEATURE = 0.005
FA_CONFIDENCE = 0.95
#: Every feature is positive except the lag-1 autocorrelation, so the others are fitted on the log scale.
LINEAR_FEATURES = ("ac1",)


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
    first, last_s = d2[t < t[0] + EDGE_S], d2[t >= t[-1] - EDGE_S]
    moment = (r.T @ r) / n
    long_bias = [b for b in bias if onset_abs <= b[0] < onset_abs + LONG_WINDOW_S]
    last_long = long_bias[-1] if long_bias else last
    return {
        "ac1": float((z[:-1] * z[1:]).sum() / max(float((z * z).sum()), 1e-12)),
        "axis_conc": float(np.linalg.eigvalsh(moment)[-1] / max(float(np.trace(moment)), 1e-12)),
        "decay": float(last_s.mean() / max(float(first.mean()), 1e-12)),
        "bias_accel_30": float(np.linalg.norm(last_long[2] - ref[2])),
        "bias_gyro_30": float(np.linalg.norm(last_long[1] - ref[1])),
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
    for name in list_sequence_dirs(root):
        seq = loader(root, name)
        for seed in range(seeds):
            for case in CASES:
                row = run_case(seq, SETTINGS[dataset], seed, case)
                if row is not None:
                    rows.append(row)
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


def confirm_sweep(dataset: str, root: str | Path) -> list[dict[str, Any]]:
    """Runs of the confirmation design on one dataset."""
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in list_sequence_dirs(root):
        seq = loader(root, name)
        for case in CONFIRM_CASES:
            seeds = CONFIRM_CONTROL_SEEDS if case[0] == "control" else CONFIRM_FAULT_SEEDS
            for seed in seeds:
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


def _matrix(rows: list[dict[str, Any]], feats: tuple[str, ...] = FEATURES) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(r[f]) for f in feats] for r in rows])
    y = np.array([CLASSES.index(r["cls"]) for r in rows])
    return x, y


def _balanced(y: np.ndarray, k: int) -> np.ndarray:
    counts = np.bincount(y, minlength=k).astype(float)
    return 1.0 / counts[y]


def bound_threshold(controls: np.ndarray, feats: tuple[str, ...], alpha: float = ALPHA_PER_FEATURE) -> np.ndarray:
    """A one-sided upper bound per feature from a normal fitted to the controls (log scale for positive features).

    With 34 controls the largest value is a poor estimate of a tail: it is exceeded by about 1 in 35 unseen runs per
    feature, and ten features give ten chances. A fitted bound has a stated level per feature. The spread is widened by
    ``sqrt(1 + 1/n)`` for the uncertainty of the fitted mean.
    """
    z = NormalDist().inv_cdf(1.0 - alpha)
    out = np.empty(controls.shape[1])
    for i, name in enumerate(feats):
        log = name not in LINEAR_FEATURES
        v = np.log(controls[:, i]) if log else controls[:, i]
        n = len(v)
        edge = v.mean() + z * v.std(ddof=1) * math.sqrt(1.0 + 1.0 / n)
        out[i] = math.exp(edge) if log else edge
    return out


def fit_detector(rows: list[dict[str, Any]], feats: tuple[str, ...] = FEATURES, stage1: str = "max") -> dict[str, Any]:
    """Stage 1 thresholds (see ``STAGE1_RULES``) and the stage 2 tree."""
    if stage1 not in STAGE1_RULES:
        raise ValueError(f"stage1 must be one of {STAGE1_RULES}, not {stage1!r}")
    x, y = _matrix(rows, feats)
    ctrl = y == 0
    faults = ~ctrl
    yf = y[faults] - 1
    tree = fit_tree(x[faults], yf, _balanced(yf, len(FAULT_CLASSES)), len(FAULT_CLASSES))
    threshold = x[ctrl].max(axis=0) if stage1 == "max" else bound_threshold(x[ctrl], feats)
    return {"threshold": threshold, "tree": tree, "features": feats, "stage1": stage1}


def call(model: dict[str, Any], row: np.ndarray) -> str:
    if not np.any(row > model["threshold"]):
        return "control"
    return FAULT_CLASSES[predict(model["tree"], row)]


def cross_validate(rows: list[dict[str, Any]], feats: tuple[str, ...] = FEATURES, stage1: str = "max") -> list[str]:
    """The called class per row, each from a model fitted without that row's sequence."""
    x, _ = _matrix(rows, feats)
    seqs = np.array([f"{r['dataset']}/{r['sequence']}" for r in rows])
    out = [""] * len(rows)
    for s in np.unique(seqs):
        test = seqs == s
        model = fit_detector([r for r, t in zip(rows, test, strict=True) if not t], feats, stage1)
        for i in np.flatnonzero(test):
            out[i] = call(model, x[i])
    return out


def frozen_predictions(
    train: list[dict[str, Any]], test: list[dict[str, Any]], stage1: str = "max"
) -> list[dict[str, Any]]:
    """The calls of one model fitted on ``train`` alone, on rows it never saw."""
    model = fit_detector(train, FEATURES, stage1)
    x, _ = _matrix(test, FEATURES)
    return [{**r, "predicted": call(model, x[i])} for i, r in enumerate(test)]


def with_predictions(
    rows: list[dict[str, Any]], feats: tuple[str, ...] = FEATURES, stage1: str = "max"
) -> list[dict[str, Any]]:
    return [{**r, "predicted": p} for r, p in zip(rows, cross_validate(rows, feats, stage1), strict=True)]


def model_text(rows: list[dict[str, Any]], feats: tuple[str, ...] = FEATURES) -> str:
    model = fit_detector(rows, feats)

    def walk(t: dict[str, Any], pad: str) -> list[str]:
        if "leaf" in t:
            return [f"{pad}-> {FAULT_CLASSES[t['leaf']]}"]
        name = feats[t["f"]]
        return [
            f"{pad}{name} <= {t['thr']:.4g}:",
            *walk(t["lo"], pad + "  "),
            f"{pad}{name} > {t['thr']:.4g}:",
            *walk(t["hi"], pad + "  "),
        ]

    head = [
        "stage 1: a fault if any feature exceeds its control maximum: "
        + str({n: round(float(v), 4) for n, v in zip(feats, model["threshold"], strict=True)})
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


def compare_markdown(rows: list[dict[str, Any]]) -> str:
    """The same cross-validation with the original five features and with all ten."""
    lines = [
        "| Features | Control called a fault | Multipath called multipath | Spoofing called spoofing "
        "| Degradation called degradation | 10 m step called multipath | 0.5 m/s ramp detected |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, feats in (("original five", BASE_FEATURES), ("all ten", FEATURES)):
        sc = with_predictions(rows, feats)

        def share(pick: Any, called: Any, sc: list[dict[str, Any]] = sc) -> float:
            sel = [r for r in sc if pick(r)]
            return sum(called(r) for r in sel) / len(sel)

        def is_(kind: str, level: float) -> Any:
            return lambda r: r["kind"] == kind and float(r["level"]) == level

        cells = [
            share(lambda r: r["cls"] == "control", lambda r: r["predicted"] != "control"),
            share(lambda r: r["cls"] == "multipath", lambda r: r["predicted"] == "multipath"),
            share(lambda r: r["cls"] == "spoofing", lambda r: r["predicted"] == "spoofing"),
            share(lambda r: r["cls"] == "degradation", lambda r: r["predicted"] == "degradation"),
            share(is_("step", 10.0), lambda r: r["predicted"] == "multipath"),
            share(is_("ramp", 0.5), lambda r: r["predicted"] != "control"),
        ]
        lines.append(f"| {label} | " + " | ".join(_pct(c) for c in cells) + " |")
    return "\n".join(lines)


def _confirm_scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return frozen_predictions(rows_from_csv(TRAIN_CSV), rows)


def confirm_confusion_markdown(rows: list[dict[str, Any]]) -> str:
    return confusion_markdown(_confirm_scored(rows))


def confirm_levels_markdown(rows: list[dict[str, Any]]) -> str:
    scored = _confirm_scored(rows)
    lines = [
        "| Class | Fault | Level | Runs | Called correctly | Called control (missed) | Detected (any fault called) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for cls, kind, level in CONFIRM_CASES:
        sel = [r for r in scored if r["kind"] == kind and float(r["level"]) == level]
        if sel:
            ok = sum(r["predicted"] == cls for r in sel) / len(sel)
            miss = sum(r["predicted"] == "control" for r in sel) / len(sel)
            lines.append(
                f"| {cls} | {kind} | {level:g} | {len(sel)} | {_pct(ok)} | {_pct(miss)} | {_pct(1.0 - miss)} |"
            )
    return "\n".join(lines)


def confirm_compare_markdown(rows: list[dict[str, Any]]) -> str:
    """The cross-validated figures of the training runs next to the figures on the unseen runs."""
    train = rows_from_csv(TRAIN_CSV)
    sets = (
        ("cross-validated, training runs", with_predictions(train, FEATURES)),
        ("frozen model, unseen runs", _confirm_scored(rows)),
    )
    lines = [
        "| Figures | Runs | Control called a fault | Multipath called multipath | Spoofing called spoofing "
        "| Degradation called degradation |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, sc in sets:

        def share(cls: str, hit: Any, sc: list[dict[str, Any]] = sc) -> str:
            sel = [r for r in sc if r["cls"] == cls]
            return _pct(sum(hit(r) for r in sel) / len(sel))

        lines.append(
            f"| {label} | {len(sc)} | {share('control', lambda r: r['predicted'] != 'control')} "
            f"| {share('multipath', lambda r: r['predicted'] == 'multipath')} "
            f"| {share('spoofing', lambda r: r['predicted'] == 'spoofing')} "
            f"| {share('degradation', lambda r: r['predicted'] == 'degradation')} |"
        )
    return "\n".join(lines)


def upper_limit(k: int, n: int, confidence: float = FA_CONFIDENCE) -> float:
    """One-sided upper confidence limit of a rate seen as ``k`` events in ``n`` runs (Clopper-Pearson).

    With no false alarm in 68 runs the rate is not shown to be zero: it is shown to be below this.
    """
    if k >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        cdf = sum(math.comb(n, i) * mid**i * (1.0 - mid) ** (n - i) for i in range(k + 1))
        if cdf > 1.0 - confidence:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def stage1_markdown(rows: list[dict[str, Any]]) -> str:
    """The two stage 1 rules, each cross-validated on the training runs and frozen on the unseen runs."""
    train = rows_from_csv(TRAIN_CSV)
    sets = (
        ("training runs, cross-validated", lambda rule: with_predictions(train, FEATURES, rule)),
        ("unseen runs, frozen model", lambda rule: frozen_predictions(train, rows, rule)),
    )
    names = {"max": "control maximum", "bound": f"fitted bound, {ALPHA_PER_FEATURE:.1%} per feature"}
    header = (
        "| Runs | Stage 1 rule | Controls | False alarms | Rate, upper 95% limit | Multipath detected "
        "| Spoofing detected | Degradation detected |"
    )
    lines = [header, "|---|---|---:|---:|---:|---:|---:|---:|"]
    for label, scorer in sets:
        for rule in STAGE1_RULES:
            sc = scorer(rule)
            ctrl = [r for r in sc if r["cls"] == "control"]
            k = sum(r["predicted"] != "control" for r in ctrl)

            def seen(cls: str, sc: list[dict[str, Any]] = sc) -> str:
                sel = [r for r in sc if r["cls"] == cls]
                return _pct(sum(r["predicted"] != "control" for r in sel) / len(sel))

            rate = f"{_pct(k / len(ctrl))}, {_pct(upper_limit(k, len(ctrl)))}"
            lines.append(
                f"| {label} | {names[rule]} | {len(ctrl)} | {k} | {rate} "
                f"| {seen('multipath')} | {seen('spoofing')} | {seen('degradation')} |"
            )
    return "\n".join(lines)


BLOCKS = {
    "faultclass-compare": compare_markdown,
    "faultclass-features": lambda rows: feature_markdown(rows),
    "faultclass-confusion": lambda rows: confusion_markdown(with_predictions(rows)),
    "faultclass-levels": lambda rows: level_markdown(with_predictions(rows)),
}

CONFIRM_BLOCKS = {
    "faultclass-stage1": stage1_markdown,
    "faultclass-confirm-compare": confirm_compare_markdown,
    "faultclass-confirm-calls": confirm_confusion_markdown,
    "faultclass-confirm-levels": confirm_levels_markdown,
}

# ------------------------------------------------------------------------- I/O


# The committed CSV has CRLF line ends.
TABLE = Table(tuple(Column(n, str, optional=True) for n in CSV_COLUMNS), key="dataset", lineterminator="\r\n")


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit sweep faultclass", description="Can GNSS innovations separate multipath, spoofing and degradation?"
    )
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument(
        "--confirm",
        action="store_true",
        help="run (or with --from-csv, read) the confirmation design on unseen sizes and seeds, with the model frozen "
        "on the training CSV",
    )
    p.add_argument("--csv", default=None, help="write one row per run")
    p.add_argument("--from-csv", default=None, help="rebuild the tables and page from a saved --csv file; no runs")
    p.add_argument("--page", default=None, help="fill the faultclass blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    blocks = CONFIRM_BLOCKS if args.confirm else BLOCKS
    if args.from_csv:
        rows = rows_from_csv(args.from_csv)
    else:
        rows = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            rows += confirm_sweep(ds, root) if args.confirm else sweep_rows(ds, root, args.seeds)
    if args.csv:
        TABLE.write(args.csv, rows)
        print(f"wrote {args.csv}", file=sys.stderr)
    tables = {name: fn(rows) for name, fn in blocks.items()}
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
