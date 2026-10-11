"""How small a multipath fault does the signature catch, and does it call anything else?

:mod:`navkit.fdir.multipath` has two rules, fixed before they were tested on fresh runs: ``sensitive`` (NIS at least 2)
and ``specific`` (NIS at least 6), both with a lag-1 autocorrelation of at most 0.8.

Three sets of runs, none of them used to set a threshold except where stated:

* the **floor** runs: multipath of 0.5 to 2 m and extra controls, seeds 6 and 7;
* the **confirmation** runs of the fault-classification study (unseen sizes and seeds), read from its CSV;
* the **fresh** runs: new seeds (8 and 9), with the mixed set of cases listed in ``FRESH_CASES``. The criteria for
  shipping a rule were written before this set was run (``CRITERIA``).

The 6 in the specific rule came from the classification tree's training runs, so the training runs are not evidence for
it. The floor and confirmation runs were seen before the fresh set was designed. Only the fresh set is a clean test of
the rule that is chosen. Simulated GNSS, injected faults, two datasets, the calibrated bias-walk setting.
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
FLOOR_SEEDS = (6, 7)
FRESH_SEEDS = (8, 9)
#: (kind, level). ``none`` is the control.
FRESH_CASES: tuple[tuple[str, float], ...] = (
    ("none", 0.0),
    ("multipath", 1.0),
    ("multipath", 2.0),
    ("multipath", 3.0),
    ("multipath", 5.0),
    ("step", 5.0),
    ("step", 10.0),
    ("ramp", 3.0),
    ("ramp", 5.0),
    ("accel_bias", 0.7),
    ("gyro_bias", 0.02),
)
#: Written before the fresh runs: a rule is shipped only if, on the fresh runs, it calls at least this share of the
#: multipath runs of 3 m and above, and calls no more than this share of the runs of every other kind.
CRITERIA = {"recall_at_3m_and_above": 0.95, "false_call_rate_other": 0.02}
CLASS_OF = {
    "none": "control",
    "multipath": "multipath",
    "ramp": "spoofing",
    "step": "spoofing",
    "accel_bias": "degradation",
    "gyro_bias": "degradation",
}
CONFIRM_CSV = "docs/data/fault_classification_confirm.csv"
CSV_COLUMNS = ("dataset", "sequence", "seed", "kind", "level", "nis", "ac1")


def run_case(seq: Any, config: str, seed: int, kind: str, level: float) -> dict[str, Any] | None:
    """One run: the fault (``none`` for a control) and the two statistics of the window after the onset."""
    t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0]))
    if float(min(seq.imu.t[-1], seq.truth.t[-1])) - t_start < ONSET_S + WINDOW_S + 5.0:
        return None
    fault = None if kind == "none" else (kind, ONSET_S, level)
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
        "kind": kind,
        "level": level,
        "nis": sig.nis,
        "ac1": sig.ac1,
    }


def sweep_rows(
    dataset: str, root: str | Path, cases: tuple[tuple[str, float], ...], seeds: tuple[int, ...]
) -> list[dict[str, Any]]:
    loader, _ = dataset_loader(dataset)
    rows: list[dict[str, Any]] = []
    for name in sorted(d for d in os.listdir(root) if (Path(root) / d).is_dir()):
        seq = loader(root, name)
        for kind, level in cases:
            for seed in seeds:
                row = run_case(seq, SETTINGS[dataset], seed, kind, level)
                if row is not None:
                    rows.append(row)
        print(f"{dataset} {name}", file=sys.stderr, flush=True)
    return rows


def floor_cases() -> tuple[tuple[str, float], ...]:
    return (("none", 0.0), *(("multipath", lv) for lv in FLOOR_LEVELS_M))


# --------------------------------------------------------------------- tables


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def called(row: dict[str, Any], rule: str) -> bool:
    return mp.call(float(row["nis"]), float(row["ac1"]), rule)


def cls_of(row: dict[str, Any]) -> str:
    return CLASS_OF[row["kind"]]


def upper_bound(n: int) -> float:
    """The rule of three: with no events in ``n`` trials, the 95% upper bound on the rate is about ``3 / n``."""
    return 3.0 / n


def confirm_rows(path: str | Path = CONFIRM_CSV) -> list[dict[str, Any]]:
    """The confirmation runs of the fault-classification study, as rows of this study."""
    kind_of = {"none": "none"}
    return [{**r, "kind": kind_of.get(r["kind"], r["kind"])} for r in rows_from_csv(path)]


def _share(sel: list[dict[str, Any]], rule: str) -> float:
    return sum(called(r, rule) for r in sel) / len(sel) if sel else float("nan")


def floor_markdown(floor: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> str:
    lines = [
        "| Multipath m | Runs | Sensitive rule calls | Specific rule calls | Median NIS "
        "| Median lag-1 autocorrelation |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for level in (0.0, *FLOOR_LEVELS_M):
        sel = [r for r in floor if float(r["level"]) == level]
        if sel:
            lines.append(
                f"| {level:g} | {len(sel)} | {_pct(_share(sel, 'sensitive'))} | {_pct(_share(sel, 'specific'))} | "
                f"{np.median([float(r['nis']) for r in sel]):.2f} | {np.median([float(r['ac1']) for r in sel]):.2f} |"
            )
    return "\n".join(lines)


def confirm_markdown(floor: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> str:
    cr = confirm_rows()
    lines = [
        "| Class | Runs | Sensitive rule calls multipath | Specific rule calls multipath |",
        "|---|---:|---:|---:|",
    ]
    for cls in ("control", "multipath", "spoofing", "degradation"):
        sel = [r for r in cr if cls_of(r) == cls]
        lines.append(f"| {cls} | {len(sel)} | {_pct(_share(sel, 'sensitive'))} | {_pct(_share(sel, 'specific'))} |")
    return "\n".join(lines)


def fresh_markdown(floor: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> str:
    lines = [
        "| Class | Fault | Level | Runs | Sensitive rule calls multipath | Specific rule calls multipath |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for kind, level in FRESH_CASES:
        sel = [r for r in fresh if r["kind"] == kind and float(r["level"]) == level]
        if sel:
            lines.append(
                f"| {CLASS_OF[kind]} | {kind} | {level:g} | {len(sel)} | {_pct(_share(sel, 'sensitive'))} | "
                f"{_pct(_share(sel, 'specific'))} |"
            )
    return "\n".join(lines)


def criteria_results(fresh: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The fresh-run recall and false-call rate of each rule, and whether the criteria are met."""
    out: dict[str, dict[str, Any]] = {}
    big = [r for r in fresh if r["kind"] == "multipath" and float(r["level"]) >= 3.0]
    other = [r for r in fresh if r["kind"] != "multipath"]
    for rule in mp.RULES:
        recall, false_rate = _share(big, rule), _share(other, rule)
        out[rule] = {
            "recall": recall,
            "false_call_rate": false_rate,
            "met": recall >= CRITERIA["recall_at_3m_and_above"] and false_rate <= CRITERIA["false_call_rate_other"],
        }
    return out


def criteria_markdown(floor: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> str:
    res = criteria_results(fresh)
    lines = [
        f"| Rule | Recall, multipath of 3 m and above (needs {_pct(CRITERIA['recall_at_3m_and_above'])}) | "
        "Called multipath, all other runs including controls "
        f"(needs at most {_pct(CRITERIA['false_call_rate_other'])}) | Criteria met |",
        "|---|---:|---:|---|",
    ]
    for rule in mp.RULES:
        r = res[rule]
        lines.append(f"| {rule} | {_pct(r['recall'])} | {_pct(r['false_call_rate'])} | {'yes' if r['met'] else 'no'} |")
    return "\n".join(lines)


def false_alarm_markdown(floor: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> str:
    ctrl = {
        "floor": [r for r in floor if r["kind"] == "none"],
        "confirmation": [r for r in confirm_rows() if r["kind"] == "none"],
        "fresh": [r for r in fresh if r["kind"] == "none"],
    }
    lines = [
        "| Control runs | Runs | Sensitive rule calls | Specific rule calls "
        "| 95% upper bound on the specific rule's rate |",
        "|---|---:|---:|---:|---:|",
    ]
    everything = [r for sel in ctrl.values() for r in sel]
    for label, sel in (*ctrl.items(), ("all", everything)):
        s, p = (sum(called(r, rule) for r in sel) for rule in mp.RULES)
        bound = _pct(upper_bound(len(sel))) if p == 0 else "see the count"
        lines.append(f"| {label} | {len(sel)} | {s} | {p} | {bound} |")
    return "\n".join(lines)


BLOCKS = {
    "multipath-floor": floor_markdown,
    "multipath-confirm": confirm_markdown,
    "multipath-fresh": fresh_markdown,
    "multipath-criteria": criteria_markdown,
    "multipath-false-alarms": false_alarm_markdown,
}

# ------------------------------------------------------------------------- I/O


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: str | Path) -> list[dict[str, Any]]:
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
    p = argparse.ArgumentParser(prog="navkit sweep multipath", description="Evaluate the multipath signature.")
    p.add_argument("--euroc-root", default="data/raw/euroc")
    p.add_argument("--tumvi-root", default="data/raw/tumvi")
    p.add_argument("--set", choices=("floor", "fresh"), default=None, help="run one set and write it with --csv")
    p.add_argument("--csv", default=None, help="write one row per run of the set that was run")
    p.add_argument("--floor-csv", default="docs/data/multipath_detector.csv")
    p.add_argument("--fresh-csv", default="docs/data/multipath_fresh.csv")
    p.add_argument("--page", default=None, help="fill the multipath blocks of this Markdown page")
    p.add_argument("--markdown", action="store_true", help="print the tables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.set:
        cases = floor_cases() if args.set == "floor" else FRESH_CASES
        seeds = FLOOR_SEEDS if args.set == "floor" else FRESH_SEEDS
        rows: list[dict[str, Any]] = []
        for ds, root in (("euroc", args.euroc_root), ("tumvi", args.tumvi_root)):
            rows += sweep_rows(ds, root, cases, seeds)
        target = args.csv or (args.floor_csv if args.set == "floor" else args.fresh_csv)
        write_csv(target, rows)
        print(f"wrote {target}", file=sys.stderr)
        return 0
    floor, fresh = read_csv(args.floor_csv), read_csv(args.fresh_csv)
    tables = {name: fn(floor, fresh) for name, fn in BLOCKS.items()}
    if args.page:
        try:
            for name, text in tables.items():
                write_block(args.page, name, text)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.markdown or not args.page:
        print("\n\n".join(tables.values()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
