"""The B1 gate of ADR-0028: run the candidate and its control over seeds, apply the gate, write the table.

    navkit gate b1 --seeds 0-24 --csv docs/data/b1_gate_dev.csv --page docs/calibration.md

The candidate is the ``outage_visual`` scenario of ``configs/benchmark.yaml`` with ``vision_model: clone`` and
``vision_noise_preset: measured-front-end`` (ADR-0024). Its paired control is ``outage_control`` on the same seed. Both
run through :func:`navkit.benchmark.run_case`, so the start draw of ADR-0027 applies. The arrays are cut to the
GNSS-outage window with the same half-open mask as the calibration report, and :func:`navkit.eval.gate.evaluate_b1_gate`
applies the conditions.

Seeds 100 to 124 are the held-out set. ADR-0028 allows one evaluation of it. The command refuses them unless
``--held-out`` is given, and so does :func:`run_gate`.

Two further rows use the same function on the development seeds and are labelled DIAGNOSTIC: the single-anchor
``outage_visual`` (the gate has to be able to say no) and the plain clone ``outage_visual_clone``. They are not gate
decisions and they are never computed for the held-out set.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import default_config_path, run_case
from .eval.calibration import window_mask
from .eval.gate import B1GateResult, evaluate_b1_gate
from .report.page import splice_block

#: The held-out set of ADR-0028, single use.
HELD_OUT_SEEDS = range(100, 125)
#: The gate is decided on this many seeds.
GATE_RUNS = 25
CANDIDATE_ESTIMATOR = {"vision_model": "clone", "vision_noise_preset": "measured-front-end"}
CONTROL = "outage_control"

CSV_FIELDS = (
    "role",
    "subject",
    "seeds",
    "n_runs",
    "n_epochs",
    "dof",
    "sum_n_eff",
    "degrees_of_freedom",
    "n_truncated",
    "condition",
    "relation",
    "value",
    "threshold",
    "passed",
    "subject_passed",
)
_INT_FIELDS = {"n_runs", "n_epochs", "dof", "degrees_of_freedom", "n_truncated"}
_TEXT_FIELDS = {"role", "subject", "seeds", "condition", "relation"}
_BOOL_FIELDS = {"passed", "subject_passed"}

CONDITION_LABELS = {
    "nees_upper": "Grand mean NEES, at most the upper edge of the band",
    "nees_lower": "Grand mean NEES, at least the lower bound",
    "coverage": "Pooled 2-sigma per-axis coverage",
    "ate_better": "Runs where the candidate has the lower ATE",
    "ate_median": "Median ATE ratio, candidate over control",
    "ate_worst": "Largest ATE ratio",
}

START, END = "<!-- b1-gate-dev:start -->", "<!-- b1-gate-dev:end -->"


# ------------------------------------------------------------------------------------------------ seeds


def parse_seeds(text: str) -> list[int]:
    """``"0-24"`` is seeds 0 to 24 inclusive. ``"1,4,2"`` is those seeds, in that order."""
    if not text or text != text.strip():
        raise ValueError(f"cannot read seeds from {text!r}")
    try:
        if "," not in text and "-" in text:
            lo, hi = text.split("-", 1)
            first, last = int(lo), int(hi)
            if first < 0 or last < first or lo.startswith("+") or hi.startswith("+"):
                raise ValueError
            return list(range(first, last + 1))
        seeds = [int(part) for part in text.split(",")]
    except ValueError:
        raise ValueError(f"cannot read seeds from {text!r}: use A-B or a comma list of non-negative integers") from None
    if any(s < 0 for s in seeds):
        raise ValueError(f"seeds must not be negative, got {text!r}")
    return seeds


def format_seeds(seeds: list[int]) -> str:
    """The inverse of :func:`parse_seeds` for a consecutive run, and a comma list otherwise."""
    if len(seeds) > 1 and seeds == list(range(seeds[0], seeds[0] + len(seeds))):
        return f"{seeds[0]}-{seeds[-1]}"
    return ",".join(str(s) for s in seeds)


def _touches_held_out(seeds: list[int]) -> bool:
    return any(s in HELD_OUT_SEEDS for s in seeds)


# --------------------------------------------------------------------------------------------- the runs


@dataclass(frozen=True)
class Subject:
    role: str  # "candidate" or "DIAGNOSTIC"
    name: str
    case: dict[str, Any]


def _document() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text(encoding="utf-8")) or {}


def candidate_case(cases: dict[str, Any]) -> dict[str, Any]:
    """The ``outage_visual`` case with the clone and the measured-front-end preset, as ADR-0028 states it."""
    base = copy.deepcopy(cases["outage_visual"])
    estimator = {**base.get("estimator", {}), **CANDIDATE_ESTIMATOR}
    if not estimator.get("vision_fuse"):
        raise ValueError("outage_visual no longer fuses vision; the candidate of ADR-0028 is not what the config has")
    base["estimator"] = estimator
    return base


def subjects(cases: dict[str, Any], diagnostics: bool) -> list[Subject]:
    out = [Subject("candidate", "outage_visual+clone+measured-front-end", candidate_case(cases))]
    if diagnostics:
        out.append(Subject("DIAGNOSTIC", "outage_visual", cases["outage_visual"]))
        out.append(Subject("DIAGNOSTIC", "outage_visual_clone", cases["outage_visual_clone"]))
    return out


def window_arrays(box: dict[str, Any]) -> dict[str, np.ndarray]:
    """The NEES, error and sigma of one run cut to the GNSS-outage window, and the ATE over it (no alignment)."""
    if "squared" not in box or not box.get("windows"):
        raise ValueError("the run has no covariance or no GNSS outage window")
    mask = window_mask(box["t"], box["windows"])
    error = np.asarray(box["error"], float)[mask]
    return {
        "nees": np.asarray(box["squared"], float)[mask],
        "error": error,
        "sigma": np.asarray(box["sigma"], float)[mask],
        "ate": np.asarray(float(np.sqrt(np.mean(np.sum(error**2, axis=1))))),
    }


def _stack(runs: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    return {k: np.stack([r[k] for r in runs]) for k in runs[0]}


def run_arrays(name: str, case: dict[str, Any], defaults: dict[str, Any], seeds: list[int]) -> dict[str, np.ndarray]:
    runs = []
    for seed in seeds:
        box: dict[str, Any] = {}
        run_case(name, case, defaults, seed=seed, nees_out=box)
        runs.append(window_arrays(box))
    return _stack(runs)


def run_gate(seeds: list[int], held_out: bool = False, diagnostics: bool = True) -> list[dict[str, Any]]:
    """Run the candidate, its control and (on development seeds) the two diagnostics, and return the CSV rows."""
    if _touches_held_out(seeds) and not held_out:
        raise ValueError("seeds 100 to 124 are the held-out set of ADR-0028 and need held_out=True")
    if len(seeds) < 2:
        raise ValueError("the gate needs at least two seeds")
    doc = _document()
    cases, defaults = doc["cases"], doc.get("defaults", {})
    control = run_arrays(CONTROL, cases[CONTROL], defaults, seeds)
    rows: list[dict[str, Any]] = []
    for subject in subjects(cases, diagnostics and not held_out):
        arrays = run_arrays(subject.name, subject.case, defaults, seeds)
        result = evaluate_b1_gate(arrays["nees"], arrays["error"], arrays["sigma"], arrays["ate"], control["ate"])
        rows.extend(result_rows(subject, seeds, result))
    return rows


def result_rows(subject: Subject, seeds: list[int], result: B1GateResult) -> list[dict[str, Any]]:
    """One row per condition of one subject."""
    return [
        {
            "role": subject.role,
            "subject": subject.name,
            "seeds": format_seeds(seeds),
            "n_runs": result.n_runs,
            "n_epochs": result.n_epochs,
            "dof": result.dof,
            "sum_n_eff": result.sum_n_eff,
            "degrees_of_freedom": result.degrees_of_freedom,
            "n_truncated": result.n_truncated,
            "condition": c.name,
            "relation": c.relation,
            "value": c.value,
            "threshold": c.threshold,
            "passed": c.passed,
            "subject_passed": result.passed,
        }
        for c in result.conditions
    ]


# ------------------------------------------------------------------------------------------- CSV, page


def csv_text(rows: list[dict[str, Any]]) -> str:
    """The rows as CSV text. Floats are written with ``repr`` (shortest round trip), so the bytes are deterministic."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in rows:
        out = []
        for k in CSV_FIELDS:
            v = row[k]
            if k in _BOOL_FIELDS:
                out.append("true" if v else "false")
            elif k in _INT_FIELDS or k in _TEXT_FIELDS:
                out.append(v)
            else:
                out.append(repr(float(v)))
        writer.writerow(out)
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    """The inverse of :func:`csv_text`."""
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        row: dict[str, Any] = {}
        for k in CSV_FIELDS:
            if k in _BOOL_FIELDS:
                row[k] = raw[k] == "true"
            elif k in _INT_FIELDS:
                row[k] = int(raw[k])
            elif k in _TEXT_FIELDS:
                row[k] = raw[k]
            else:
                row[k] = float(raw[k])
        rows.append(row)
    return rows


def _format_value(condition: str, v: float) -> str:
    if condition == "coverage":
        return f"{100.0 * v:.2f}%"
    if condition == "ate_better":
        return str(int(v))
    return f"{v:.4g}"


def _format_threshold(condition: str, relation: str, v: float) -> str:
    return f"{relation} {_format_value(condition, v)}"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """The generated block: one line per subject, then one line per condition with its value and its threshold."""
    if not rows:
        raise ValueError("no rows to tabulate")
    subjects_seen: list[tuple[str, str]] = []
    for r in rows:
        key = (r["role"], r["subject"])
        if key not in subjects_seen:
            subjects_seen.append(key)
    head = [
        "| Role | Subject | Seeds | Runs | Window epochs | Sum of n_eff | Band degrees of freedom "
        "| Truncated runs | All conditions hold |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for role, name in subjects_seen:
        r = next(x for x in rows if (x["role"], x["subject"]) == (role, name))
        head.append(
            f"| {role} | {name} | {r['seeds']} | {r['n_runs']} | {r['n_epochs']} | {r['sum_n_eff']:.1f} | "
            f"{r['degrees_of_freedom']} | {r['n_truncated']} | {'yes' if r['subject_passed'] else 'no'} |"
        )
    body = [
        "| Role | Subject | Condition | Value | Threshold | Holds |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in rows:
        c = r["condition"]
        body.append(
            f"| {r['role']} | {r['subject']} | {CONDITION_LABELS[c]} | {_format_value(c, r['value'])} | "
            f"{_format_threshold(c, r['relation'], r['threshold'])} | {'yes' if r['passed'] else 'no'} |"
        )
    return "\n".join([*head, "", *body])


def splice_table(page: str, table: str) -> str:
    """``page`` with the text between the gate markers replaced by ``table``."""
    return splice_block(page, "b1-gate-dev", table)


# --------------------------------------------------------------------------------------------- command


class _Parser(argparse.ArgumentParser):
    """Refuses the held-out seeds unless ``--held-out`` is given, and says the set is single use when it is."""

    def parse_args(self, args: Any = None, namespace: Any = None) -> argparse.Namespace:  # type: ignore[override]
        ns = super().parse_args(args, namespace)
        if ns.held_out:
            print("warning: the held-out set (seeds 100 to 124) is single use per ADR-0028.", file=sys.stderr)
        elif _touches_held_out(ns.seeds):
            self.error("seeds 100 to 124 are the held-out set of ADR-0028; give --held-out to evaluate it (single use)")
        return ns


def _seeds_arg(text: str) -> list[int]:
    try:
        return parse_seeds(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="navkit gate b1", description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--seeds", type=_seeds_arg, required=True, help="A-B or a comma list; the gate uses exactly 25")
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--page", type=Path, default=None, help="write the table between the b1-gate-dev markers")
    ap.add_argument("--held-out", action="store_true", help="allow seeds 100 to 124 (single use, ADR-0028)")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if len(args.seeds) != GATE_RUNS:
        ap.error(f"the gate is decided on exactly {GATE_RUNS} seeds, got {len(args.seeds)}")
    rows = run_gate(args.seeds, held_out=args.held_out)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_table(page, markdown_table(rows)), encoding="utf-8")
        print(f"wrote the table into {args.page}", file=sys.stderr)
    for r in rows:
        if r["condition"] == "ate_worst":
            print(f"{r['role']:<10} {r['subject']:<40} all conditions hold: {r['subject_passed']}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
