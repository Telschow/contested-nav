"""The usefulness diagnostic in scenario S2: ``navkit gate usefulness-s2``.

ADR-0034's tuning run found no point that passed the gate of ADR-0030 in both scenarios, and the best point held the
three NEES conditions in S2 but not the usefulness conditions (the candidate is not better than the no-vision control in
enough seeds, and in a few seeds it is much worse). This diagnostic asks whether a *more exact* model changes that. It
runs three subjects in S2 on development seeds and reports, next to the six conditions, how each compares with the
control seed by seed:

* the plain stochastic clone (no model of the correlated error);
* the Gauss-Markov model at the best point of the tuning run (tau 2 s, rho 0.9);
* the Gauss-Markov model at tau 2 s and rho 0.99, which is close to the generator's own error process (the generator's
  correlated error is a first-order autoregressive process with the same time constant and no white part; rho must be
  below one, because the white part of the measurement covariance would be singular).

It is a DIAGNOSTIC. It is not a gate decision, not a selection input and not a held-out evaluation. It uses
development seeds only; no option takes a seed, and a seed from 100 up is refused before any case runs.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import candidate_gate as _gate
from .b1_gate import format_seeds
from .eval.candidate_gate import CANDIDATE_GATE_UPPER_QUANTILE, evaluate_scenario_gate
from .report.page import splice_block
from .scale_tuning import check_seeds

SCENARIO = "S2"
#: The development seeds the ensemble and the robustness diagnostic use for S2.
SEEDS = range(25, 50)

START, END = "<!-- gm-s2-usefulness:start -->", "<!-- gm-s2-usefulness:end -->"
DIAGNOSTIC = "DIAGNOSTIC"
NEES_CONDITIONS = ("upper", "lower", "coverage")
USEFULNESS_CONDITIONS = ("better", "median_ratio", "worst_ratio")

CSV_FIELDS = (
    "subject",
    "scenario",
    "seeds",
    "runs",
    "control_ate_median_m",
    "candidate_ate_median_m",
    "better_count",
    "ratio_median",
    "ratio_p90",
    "ratio_max",
    "condition",
    "relation",
    "value",
    "threshold",
    "holds",
    "scenario_passed",
)
_TEXT_FIELDS = {"subject", "scenario", "seeds", "condition", "relation"}
_BOOL_FIELDS = {"holds", "scenario_passed"}
_INT_FIELDS = {"runs", "better_count"}


@dataclass(frozen=True)
class Subject:
    """One estimator setting and the words that name it."""

    label: str
    estimator: dict[str, Any]


#: The correlation time the model is given: the one of the generator's correlated error in S2.
MATCHING_TAU_S = 2.0


def _gauss_markov(rho: float) -> dict[str, Any]:
    """The clone with the Gauss-Markov model at the matching correlation time and the declared correlated share."""
    return {"vision_model": "clone", "vision_gm_error": True, "vision_gm_tau_s": MATCHING_TAU_S, "vision_gm_rho": rho}


SUBJECTS: tuple[Subject, ...] = (
    Subject("plain clone (no model)", {"vision_model": "clone"}),
    Subject("Gauss-Markov model, tau 2 s, rho 0.9", _gauss_markov(0.9)),
    Subject("Gauss-Markov model, tau 2 s, rho 0.99", _gauss_markov(0.99)),
)

Runner = Callable[[dict[str, Any], list[int]], dict[str, np.ndarray]]


# ------------------------------------------------------------------------------------------------- the run


def default_runner(doc: dict[str, Any] | None = None) -> Runner:
    """The real runner: the candidate in S2 through :mod:`navkit.candidate_gate`."""
    document = doc or _gate._document()

    def run(estimator: dict[str, Any], seeds: list[int]) -> dict[str, np.ndarray]:
        return _gate.run_scenario(SCENARIO, estimator, seeds, document)

    return run


def run_usefulness(
    runner: Runner | None = None,
    seeds: Sequence[int] = SEEDS,
    subjects: Sequence[Subject] = SUBJECTS,
    control_ate: np.ndarray | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """The rows of the diagnostic: for each subject the six conditions and its comparison with the control.

    ``runner`` and ``control_ate`` are injected by the tests; the defaults run the real cases. A seed from 100 up is
    refused before anything runs.
    """
    seed_list = list(seeds)
    check_seeds(seed_list)
    if len(seed_list) < 2:
        raise ValueError("the gate needs at least two seeds")
    say = progress or (lambda msg: None)
    if control_ate is None:
        say("control (no vision)")
        control_ate = _gate.run_control(SCENARIO, seed_list)["ate"]
    control = np.asarray(control_ate, float)
    if control.shape != (len(seed_list),) or not np.all(control > 0.0):
        raise ValueError("the control needs one positive window ATE per seed")
    run = runner or default_runner()
    span = format_seeds(seed_list)
    rows: list[dict[str, Any]] = []
    for subject in subjects:
        say(subject.label)
        a = run(subject.estimator, seed_list)
        result = evaluate_scenario_gate(
            a["y"], a["n_eff"], a["err"], a["sigma"], a["ate"], control, upper_quantile=CANDIDATE_GATE_UPPER_QUANTILE
        )
        ratio = np.asarray(a["ate"], float) / control
        summary = {
            "subject": subject.label,
            "scenario": SCENARIO,
            "seeds": span,
            "runs": len(seed_list),
            "control_ate_median_m": float(np.median(control)),
            "candidate_ate_median_m": float(np.median(a["ate"])),
            "better_count": int(np.sum(np.asarray(a["ate"], float) < control)),
            "ratio_median": float(np.median(ratio)),
            "ratio_p90": float(np.percentile(ratio, 90)),
            "ratio_max": float(np.max(ratio)),
        }
        for c in result.conditions:
            rows.append(
                {
                    **summary,
                    "condition": c.name,
                    "relation": c.relation,
                    "value": float(c.value),
                    "threshold": float(c.threshold),
                    "holds": bool(c.passed),
                    "scenario_passed": bool(result.passed),
                }
            )
    return rows


# ------------------------------------------------------------------------------------------------- the CSV


def csv_text(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in rows:
        out: list[Any] = []
        for k in CSV_FIELDS:
            v = row[k]
            if k in _BOOL_FIELDS:
                out.append("true" if v else "false")
            elif k in _TEXT_FIELDS:
                out.append(v)
            elif k in _INT_FIELDS:
                out.append(int(v))
            else:
                if not math.isfinite(float(v)):
                    raise ValueError(f"{k} must be finite, got {v!r}")
                out.append(repr(float(v)))
        writer.writerow(out)
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != CSV_FIELDS:
        raise ValueError(f"the file needs the columns {', '.join(CSV_FIELDS)}")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row: dict[str, Any] = {}
        for k in CSV_FIELDS:
            if k in _BOOL_FIELDS:
                row[k] = raw[k] == "true"
            elif k in _TEXT_FIELDS:
                row[k] = raw[k]
            elif k in _INT_FIELDS:
                row[k] = int(raw[k])
            else:
                row[k] = float(raw[k])
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------------------------ the page


def _groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["subject"], []).append(r)
    return out


def _failing(group: list[dict[str, Any]], names: tuple[str, ...]) -> list[str]:
    return [r["condition"] for r in group if r["condition"] in names and not r["holds"]]


def _list(items: list[str]) -> str:
    return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + items[-1] if items else ""


def _settings(label: str) -> str:
    """The settings part of a subject label: what follows the model name."""
    return label.split(", ", 1)[1] if ", " in label else label


def _hold_set(group: list[dict[str, Any]]) -> frozenset[str]:
    return frozenset(r["condition"] for r in group if r["holds"])


def sentences(rows: list[dict[str, Any]]) -> str:
    """What the rows show, in words. Every clause is chosen from the rows; none is fixed except the closing hedge."""
    groups = _groups(rows)
    parts: list[str] = []
    for label, group in groups.items():
        nees, useful = _failing(group, NEES_CONDITIONS), _failing(group, USEFULNESS_CONDITIONS)
        nees_text = (
            "the NEES conditions hold" if not nees else f"the NEES conditions do not all hold ({_list(nees)} fail)"
        )
        useful_text = (
            "the usefulness conditions are met"
            if not useful
            else f"the usefulness conditions are not met ({_list(useful)} fail)"
        )
        parts.append(f"In scenario S2, for the {label}: {nees_text}, and {useful_text}.")
    models = [label for label in groups if label.startswith("Gauss-Markov")]
    if len(models) >= 2:
        loose, exact = models[0], models[-1]
        same = _hold_set(groups[loose]) == _hold_set(groups[exact])
        parts.append(
            f"Making the model more exact ({_settings(exact)} instead of {_settings(loose)}) "
            + ("does not change which conditions hold." if same else "changes which conditions hold.")
        )
    runs = rows[0]["runs"]
    parts.append(
        f"This is one near-exact model on {runs} development seeds. It does not show that no estimator can meet the "
        "usefulness conditions in S2: it shows that these did not."
    )
    return " ".join(parts)


def markdown_section(rows: list[dict[str, Any]]) -> str:
    """The generated block: the comparison with the control, the six conditions per subject, and the sentences."""
    if not rows:
        raise ValueError("no rows to tabulate")
    groups = _groups(rows)
    first = rows[0]
    lines = [
        f"{DIAGNOSTIC}, outside every decision. Scenario S2 (visual errors correlated over time), development seeds "
        f"{first['seeds']}. The comparison with the no-vision control is seed by seed, over the GNSS-outage window.",
        "",
        "| Subject | Runs | Control window ATE, median (m) | Candidate window ATE, median (m) | "
        "Runs with the lower ATE | ATE ratio, median | ATE ratio, 90th percentile | ATE ratio, maximum |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, group in groups.items():
        g = group[0]
        lines.append(
            f"| {label} | {g['runs']} | {g['control_ate_median_m']:.4g} | {g['candidate_ate_median_m']:.4g} | "
            f"{g['better_count']} | {g['ratio_median']:.4g} | {g['ratio_p90']:.4g} | {g['ratio_max']:.4g} |"
        )
    lines += ["", "| Subject | Condition | Value | Threshold | Holds | All six hold |", "|---|---|---:|---:|---|---|"]
    for label, group in groups.items():
        for r in group:
            lines.append(
                f"| {label} | {r['condition']} | {r['value']:.4g} | {r['threshold']:.4g} | "
                f"{'yes' if r['holds'] else 'no'} | {'yes' if r['scenario_passed'] else 'no'} |"
            )
    lines += ["", sentences(rows)]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------- the command


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="navkit gate usefulness-s2",
        description="The usefulness diagnostic in scenario S2 (ADR-0036): three subjects on development seeds 25 to "
        "49. No option takes a seed.",
    )
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--page", type=Path, default=None, help="write the tables between the gm-s2-usefulness markers")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()

    def progress(msg: str) -> None:
        print(f"[{time.perf_counter() - started:7.1f} s] {msg}", file=sys.stderr, flush=True)

    rows = run_usefulness(progress=progress)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_block(page, "gm-s2-usefulness", markdown_section(rows)), encoding="utf-8")
        print(f"wrote the tables into {args.page}", file=sys.stderr)
    print(f"elapsed {time.perf_counter() - started:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
