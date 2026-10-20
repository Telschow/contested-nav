"""The ensemble NEES over seeded runs, as rows and as a CSV.

After ADR-0027 each seed draws its own start error from the filter's declared prior, and a single run where absolute
position is unobservable is close to one sample. This module runs a case for seeds ``0 .. N - 1`` through the same
:func:`navkit.benchmark.run_case` path as ``navkit sweep seeds`` and keeps the per-epoch NEES the calibration report
scores. :func:`navkit.eval.calibration.ensemble_nees` turns the ``(N, K)`` series into the ensemble mean and its
chi-square band.

    navkit sweep seeds --seeds 25 --ensemble-csv docs/data/ensemble_nees.csv --ensemble-page docs/calibration.md

Each case gives a ``full`` row over every epoch, and for a case with a GNSS outage an ``outage`` row over the epochs
inside the half-open outage windows (the same mask the calibration report uses). A case with no covariance
(dead reckoning) has no NEES and is skipped. This only adds output: it changes no verdict, no record and no existing
number. Whether and how it becomes a gate is a separate decision.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .benchmark import run_case
from .eval.calibration import ensemble_nees, window_mask

CSV_FIELDS = (
    "case",
    "scope",
    "n_runs",
    "dof",
    "n_epochs",
    "grand_mean",
    "band_low",
    "band_high",
    "fraction_inside",
    "fraction_below",
    "fraction_above",
    "ensemble_mean_min",
    "ensemble_mean_max",
)
_INT_FIELDS = {"n_runs", "dof", "n_epochs"}
_TEXT_FIELDS = {"case", "scope"}


def window_epochs(box: dict[str, Any]) -> int:
    """How many epochs of one collected run lie inside its outage windows (zero when it has none)."""
    if not box.get("windows"):
        return 0
    return int(window_mask(box["t"], box["windows"]).sum())


class Collector:
    """Per-epoch NEES from runs of the same cases, kept until the ensemble is scored."""

    def __init__(self) -> None:
        self._full: dict[str, list[np.ndarray]] = {}
        self._window: dict[str, list[np.ndarray]] = {}
        self._dof: dict[str, int] = {}

    def add(self, case: str, box: dict[str, Any]) -> None:
        """Keep one run. `box` is what `run_case(..., nees_out=box)` filled; an empty one (no covariance) is ignored."""
        if "squared" not in box:
            return
        squared = np.asarray(box["squared"], dtype=float)
        runs = self._full.setdefault(case, [])
        if runs and runs[0].shape != squared.shape:
            raise ValueError(f"{case}: runs differ in length ({runs[0].shape[0]} and {squared.shape[0]} epochs)")
        runs.append(squared)
        self._dof[case] = int(box["dof"])
        if box.get("windows"):
            self._window.setdefault(case, []).append(squared[window_mask(box["t"], box["windows"])])

    def rows(self) -> list[dict[str, Any]]:
        """One row per case and scope, in the order the cases were added."""
        out: list[dict[str, Any]] = []
        for case, runs in self._full.items():
            scopes = [("full", runs)]
            if case in self._window:
                scopes.append(("outage", self._window[case]))
            for scope, series in scopes:
                result = ensemble_nees(np.vstack(series), dof=self._dof[case])
                out.append(
                    {
                        "case": case,
                        "scope": scope,
                        "n_runs": result.n_runs,
                        "dof": result.dof,
                        "n_epochs": result.n_epochs,
                        "grand_mean": result.grand_mean,
                        "band_low": result.low,
                        "band_high": result.high,
                        "fraction_inside": result.fraction_inside,
                        "fraction_below": result.fraction_below,
                        "fraction_above": result.fraction_above,
                        "ensemble_mean_min": float(result.mean.min()),
                        "ensemble_mean_max": float(result.mean.max()),
                    }
                )
        return out


def run_ensemble(
    names: list[str], cases: dict[str, Any], defaults: dict[str, Any], n_runs: int
) -> list[dict[str, Any]]:
    """Run each named case for seeds ``0 .. n_runs - 1`` and score the ensemble."""
    collector = Collector()
    for name in names:
        for seed in range(n_runs):
            box: dict[str, Any] = {}
            run_case(name, cases[name], defaults, seed=seed, nees_out=box)
            collector.add(name, box)
    return collector.rows()


def csv_text(rows: list[dict[str, Any]]) -> str:
    """The rows as CSV text. Floats are written with ``repr`` (shortest round trip), so the bytes are deterministic."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in rows:
        writer.writerow([row[k] if k in _INT_FIELDS or k in _TEXT_FIELDS else repr(float(row[k])) for k in CSV_FIELDS])
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    """The inverse of :func:`csv_text`."""
    out: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        out.append(
            {
                k: (raw[k] if k in _TEXT_FIELDS else int(raw[k]) if k in _INT_FIELDS else float(raw[k]))
                for k in CSV_FIELDS
            }
        )
    return out


# -------------------------------------------------------------------------------------------------------- page

START, END = "<!-- ensemble:start -->", "<!-- ensemble:end -->"
#: Floats are compared to this relative tolerance across platforms (ADR-0009); integers and text must match exactly.
COMPARE_RTOL = 1e-6


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """The generated block of the calibration page: the band, then one line per case and scope."""
    if not rows:
        raise ValueError("no rows to tabulate")
    first = rows[0]
    lines = [
        f"Band for the ensemble mean over N = {first['n_runs']} runs with {first['dof']} degrees of freedom: "
        f"{first['band_low']:.3f} to {first['band_high']:.3f}. Shares are of the scored epochs.",
        "",
        "| Case | Scope | Scored epochs | Grand mean NEES | Inside the band | Below | Above |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['scope']} | {r['n_epochs']} | {r['grand_mean']:.4g} | "
            f"{100.0 * r['fraction_inside']:.1f}% | {100.0 * r['fraction_below']:.1f}% | "
            f"{100.0 * r['fraction_above']:.1f}% |"
        )
    return "\n".join(lines)


def splice_table(page: str, table: str) -> str:
    """``page`` with the text between the ensemble markers replaced by ``table``."""
    if START not in page or END not in page or page.index(START) > page.index(END):
        raise ValueError(f"the page needs the lines {START} and {END}, in that order")
    head, rest = page.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n\n{table}\n\n{END}{tail}"


def compare_rows(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> list[str]:
    """Differences between two row lists: text and integers exactly, floats to :data:`COMPARE_RTOL`."""
    if len(new) != len(old):
        return [f"{len(new)} rows against {len(old)}"]
    problems: list[str] = []
    for a, b in zip(new, old, strict=True):
        for key in CSV_FIELDS:
            x, y = a[key], b[key]
            same = (
                x == y
                if key in _TEXT_FIELDS or key in _INT_FIELDS
                else math.isclose(x, y, rel_tol=COMPARE_RTOL, abs_tol=1e-12)
            )
            if not same:
                problems.append(f"{a['case']} {a['scope']} {key}: {x!r} against {y!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """``python -m navkit.ensemble --csv FILE --page FILE``: write the page table from a committed CSV."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--page", type=Path, required=True)
    args = ap.parse_args(argv)
    rows = parse_csv(args.csv.read_text(encoding="utf-8"))
    page = args.page.read_text(encoding="utf-8")
    args.page.write_text(splice_table(page, markdown_table(rows)), encoding="utf-8")
    print(f"wrote the ensemble table into {args.page}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
