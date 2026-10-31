"""The pre-registered tuning run of the Gauss-Markov visual error model: ADR-0034.

    navkit gate tune-gm --csv docs/data/gm_tuning.csv --page docs/calibration.md

The procedure is the paragraph "How the parameters are chosen" of ADR-0034, and nothing here departs from it.

1. The grid is ``tau`` in {0.25, 0.5, 1, 2} seconds and ``rho`` in {0.5, 0.75, 0.9}: twelve points and no others. A
   point is the stochastic clone with the Gauss-Markov model on, and no noise preset and no adaptive scale.
2. Each point goes through the candidate gate of ADR-0030 in both scenarios on seeds 0 to 24. A point *qualifies* if the
   gate passes in both.
3. The margin of a condition is its distance from its threshold in units of the threshold, positive when the condition
   holds. The *score* of a point is its smallest margin over all six conditions in both scenarios. Among qualifying
   points the largest score is chosen. Ties go to the smaller ``tau``, then the smaller ``rho``. A tie is an exact
   equality of the two scores.
4. The chosen point must pass the gate in both scenarios on seeds 25 to 49, 50 to 74 and 75 to 99. If no point
   qualifies, or the chosen point fails a block, the candidate is recorded as failed on development seeds. It is not
   repaired, no grid point is added, and it is not taken to a held-out block.

The margin functions, the seed refusal and the seed blocks are those of the earlier tuning run
(:mod:`navkit.scale_tuning`) and are imported, not copied. The point, the tie rule and the CSV differ, so they are here.

A DIAGNOSTIC runs after the decision and outside it. For the chosen point (or, if none qualified, the point with the
highest score) it evaluates the gate in the S2-like scenario at visual-error correlation times of 0, 0.25, 0.5, 1 and
2 seconds, on seeds 25 to 49. It shows whether the point is robust to a correlation time it was not tuned for. It is not
a pass or fail, it is never read by the selection, and its rows are in a file of their own.

Only development seeds (0 to 99) are run. The command takes no seed, and :func:`check_seeds` refuses any seed from 100
up before anything runs, in every stage, the diagnostic included. No option can widen that.

The loop knows the gate only through evaluators, functions ``(point, seeds) -> PointResult`` and ``(point, corr_time,
seeds) -> RobustnessResult``. The real ones run the cases of :mod:`navkit.candidate_gate`; the tests give the loop a
table instead, so that no case is run.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import itertools
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import candidate_gate as _gate
from .b1_gate import format_seeds
from .eval.candidate_gate import CANDIDATE_GATE_UPPER_QUANTILE, ScenarioGateResult, evaluate_scenario_gate
from .report.page import splice_block
from .scale_tuning import (
    CONFIRMATION_BLOCKS,
    GRID_SEEDS,
    SCENARIOS,
    check_seeds,
    condition_margin,
    scenario_margin,
)

#: ADR-0034: "tau in {0.25, 0.5, 1, 2} seconds and rho in {0.5, 0.75, 0.9}: twelve points, and no others".
GRID_TAU_S = (0.25, 0.5, 1.0, 2.0)
GRID_RHO = (0.5, 0.75, 0.9)
#: The diagnostic: visual-error correlation times of the S2-like scenario, on seeds 25 to 49. Outside the decision.
ROBUSTNESS_CORR_TIMES_S = (0.0, 0.25, 0.5, 1.0, 2.0)
ROBUSTNESS_SEEDS = range(25, 50)
S2_CASE = "outage_visual_clone_correlated"

START, END = "<!-- gm-tuning:start -->", "<!-- gm-tuning:end -->"
ROB_START, ROB_END = "<!-- gm-tuning-robustness:start -->", "<!-- gm-tuning-robustness:end -->"

CSV_FIELDS = (
    "stage",
    "tau_s",
    "rho",
    "scenario",
    "seeds",
    "condition",
    "relation",
    "value",
    "threshold",
    "margin",
    "holds",
    "score",
    "qualifies",
    "chosen",
)
ROBUSTNESS_CSV_FIELDS = (
    "stage",
    "basis",
    "tau_s",
    "rho",
    "corr_time_s",
    "seeds",
    "condition",
    "relation",
    "value",
    "threshold",
    "margin",
    "holds",
    "scenario_passed",
)
_TEXT_FIELDS = {"stage", "basis", "scenario", "seeds", "condition", "relation"}
_BOOL_FIELDS = {"holds", "qualifies", "chosen", "scenario_passed"}
DIAGNOSTIC = "DIAGNOSTIC"


# ------------------------------------------------------------------------------------------- the grid


@dataclass(frozen=True)
class GridPoint:
    """One setting of the two parameters."""

    tau_s: float
    rho: float

    @property
    def label(self) -> str:
        return f"tau={self.tau_s:g} s, rho={self.rho:g}"

    def estimator(self) -> dict[str, Any]:
        """The estimator settings of the point: the clone with the model on, no noise preset, no adaptive scale."""
        return {
            "vision_model": "clone",
            "vision_gm_error": True,
            "vision_gm_tau_s": self.tau_s,
            "vision_gm_rho": self.rho,
        }


GRID: tuple[GridPoint, ...] = tuple(GridPoint(tau, rho) for tau, rho in itertools.product(GRID_TAU_S, GRID_RHO))


# ---------------------------------------------------------------------------------------- the results


def _rows_of(
    result: ScenarioGateResult, stage: str, point: GridPoint, scenario: str, seeds: str, score: float, chosen: bool
) -> list[dict[str, Any]]:
    qualifies = result.passed
    return [
        {
            "stage": stage,
            "tau_s": float(point.tau_s),
            "rho": float(point.rho),
            "scenario": scenario,
            "seeds": seeds,
            "condition": c.name,
            "relation": c.relation,
            "value": float(c.value),
            "threshold": float(c.threshold),
            "margin": condition_margin(c),
            "holds": bool(c.passed),
            "score": score,
            "qualifies": qualifies,
            "chosen": chosen,
        }
        for c in result.conditions
    ]


@dataclass(frozen=True)
class PointResult:
    """The gate result of one grid point in both scenarios on one block of seeds."""

    point: GridPoint
    seeds: tuple[int, ...]
    s1: ScenarioGateResult
    s2: ScenarioGateResult

    @property
    def score(self) -> float:
        """The smallest margin over all conditions in both scenarios. Not the largest, not the mean."""
        return min(scenario_margin(self.s1), scenario_margin(self.s2))

    @property
    def qualifies(self) -> bool:
        return self.s1.passed and self.s2.passed

    def rows(self, stage: str, chosen: bool) -> list[dict[str, Any]]:
        """One row per scenario and condition. Score and qualification are those of the point, over both scenarios."""
        seeds = format_seeds(list(self.seeds))
        out: list[dict[str, Any]] = []
        for scenario, result in zip(SCENARIOS, (self.s1, self.s2), strict=True):
            for row in _rows_of(result, stage, self.point, scenario, seeds, self.score, chosen):
                row["qualifies"] = self.qualifies
                out.append(row)
        return out


@dataclass(frozen=True)
class RobustnessResult:
    """The gate result of the S2-like scenario at one correlation time. A diagnostic, not a decision."""

    point: GridPoint
    corr_time_s: float
    seeds: tuple[int, ...]
    scenario: ScenarioGateResult

    def rows(self, basis: str) -> list[dict[str, Any]]:
        seeds = format_seeds(list(self.seeds))
        return [
            {
                "stage": DIAGNOSTIC,
                "basis": basis,
                "tau_s": float(self.point.tau_s),
                "rho": float(self.point.rho),
                "corr_time_s": float(self.corr_time_s),
                "seeds": seeds,
                "condition": c.name,
                "relation": c.relation,
                "value": float(c.value),
                "threshold": float(c.threshold),
                "margin": condition_margin(c),
                "holds": bool(c.passed),
                "scenario_passed": bool(self.scenario.passed),
            }
            for c in self.scenario.conditions
        ]


def _rank(r: PointResult) -> tuple[float, float, float]:
    """Largest score first, then the smaller tau, then the smaller rho. A tie is an exact equality of scores."""
    return (-r.score, r.point.tau_s, r.point.rho)


def select_point(results: Sequence[PointResult]) -> PointResult | None:
    """The qualifying point with the largest score, ties to the smaller tau and then the smaller rho."""
    qualifying = [r for r in results if r.qualifies]
    return min(qualifying, key=_rank) if qualifying else None


def highest_score(results: Sequence[PointResult]) -> PointResult:
    """The point with the highest score whether or not it qualifies, with the same tie rule. For the diagnostic only."""
    return min(results, key=_rank)


# ---------------------------------------------------------------------------------------- the decision


@dataclass(frozen=True)
class Outcome:
    """Qualified and confirmed, or failed on development seeds."""

    passed: bool
    chosen: GridPoint | None
    failed_blocks: tuple[str, ...]

    @property
    def kind(self) -> str:
        if self.chosen is None:
            return "no_point_qualified"
        return "failed_confirmation" if self.failed_blocks else "qualified_and_confirmed"


def decide(results: Sequence[PointResult], confirmations: Mapping[str, PointResult] | None) -> Outcome:
    """Apply ADR-0034's rule: no qualifying point, or a chosen point that fails a block, is a failure."""
    chosen = select_point(results)
    if chosen is None:
        return Outcome(False, None, ())
    given = dict(confirmations or {})
    missing = [label for label in CONFIRMATION_BLOCKS if label not in given]
    if missing:
        raise ValueError(f"the chosen point {chosen.point.label} has no result for: {', '.join(missing)}")
    for label in CONFIRMATION_BLOCKS:
        if given[label].point != chosen.point:
            raise ValueError(f"{label} is not the chosen point {chosen.point.label}")
    failed = tuple(label for label in CONFIRMATION_BLOCKS if not given[label].qualifies)
    return Outcome(not failed, chosen.point, failed)


Evaluator = Callable[[GridPoint, Sequence[int]], PointResult]
RobustnessEvaluator = Callable[[GridPoint, float, Sequence[int]], RobustnessResult]


@dataclass(frozen=True)
class TuningRun:
    grid: tuple[PointResult, ...]
    confirmations: dict[str, PointResult]
    outcome: Outcome
    robustness: tuple[RobustnessResult, ...] = ()
    robustness_basis: str = "chosen"

    def rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for r in self.grid:
            rows.extend(r.rows("grid", chosen=self.outcome.chosen == r.point))
        for label, r in self.confirmations.items():
            rows.extend(r.rows(label, chosen=True))
        return rows

    def robustness_rows(self) -> list[dict[str, Any]]:
        return [row for r in self.robustness for row in r.rows(self.robustness_basis)]


# --------------------------------------------------------------------------------------- the evaluators


def with_correlation_time(doc: dict[str, Any], corr_time_s: float) -> dict[str, Any]:
    """A copy of the benchmark document with ``vision.noise_corr_s`` of the S2 block set. ``doc`` is not changed."""
    if not (math.isfinite(corr_time_s) and corr_time_s >= 0.0):
        raise ValueError(f"the correlation time must be finite and not negative, got {corr_time_s!r} (a negative one)")
    out = copy.deepcopy(doc)
    out["cases"][S2_CASE]["scenario"]["vision"]["noise_corr_s"] = float(corr_time_s)
    return out


def _gate_arrays(
    state: dict[str, Any], controls: dict[tuple[int, ...], np.ndarray], seed_list: list[int]
) -> tuple[dict[str, Any], tuple[int, ...]]:
    check_seeds(seed_list)
    if len(seed_list) < 2:
        raise ValueError("the gate needs at least two seeds")
    if state["doc"] is None:
        state["doc"] = _gate._document()
    key = tuple(seed_list)
    if key not in controls:
        controls[key] = _gate.run_control("S1", seed_list, state["doc"])["ate"]
    return state["doc"], key


def _evaluate_scenario(
    scenario: str, estimator: dict[str, Any], seeds: list[int], doc: dict[str, Any], control: np.ndarray
) -> ScenarioGateResult:
    a = _gate.run_scenario(scenario, estimator, seeds, doc)
    return evaluate_scenario_gate(
        a["y"], a["n_eff"], a["err"], a["sigma"], a["ate"], control, upper_quantile=CANDIDATE_GATE_UPPER_QUANTILE
    )


def make_evaluator(doc: dict[str, Any] | None = None) -> Evaluator:
    """The real evaluator: run both scenarios and the control through :mod:`navkit.candidate_gate` and apply the gate.

    The control (``outage_control``) has no vision, so it is run once per list of seeds and shared by all points.
    """
    state: dict[str, Any] = {"doc": doc or None}
    controls: dict[tuple[int, ...], np.ndarray] = {}

    def evaluate(point: GridPoint, seeds: Sequence[int]) -> PointResult:
        seed_list = list(seeds)
        document, key = _gate_arrays(state, controls, seed_list)
        results = {s: _evaluate_scenario(s, point.estimator(), seed_list, document, controls[key]) for s in SCENARIOS}
        return PointResult(point, key, results["S1"], results["S2"])

    return evaluate


def make_robustness_evaluator(doc: dict[str, Any] | None = None) -> RobustnessEvaluator:
    """The real evaluator of the diagnostic: the S2-like scenario at one correlation time, through the same gate."""
    state: dict[str, Any] = {"doc": doc or None}
    controls: dict[tuple[int, ...], np.ndarray] = {}

    def evaluate(point: GridPoint, corr_time_s: float, seeds: Sequence[int]) -> RobustnessResult:
        seed_list = list(seeds)
        document, key = _gate_arrays(state, controls, seed_list)
        shifted = with_correlation_time(document, corr_time_s)
        result = _evaluate_scenario("S2", point.estimator(), seed_list, shifted, controls[key])
        return RobustnessResult(point, float(corr_time_s), key, result)

    return evaluate


def run_tuning(
    evaluate: Evaluator | None = None,
    robustness: RobustnessEvaluator | None = None,
    progress: Callable[[str], None] | None = None,
    doc: dict[str, Any] | None = None,
) -> TuningRun:
    """The whole procedure, once: the grid, the choice, the confirmation, the outcome, then the diagnostic."""
    for seeds in (GRID_SEEDS, *CONFIRMATION_BLOCKS.values(), ROBUSTNESS_SEEDS):
        check_seeds(seeds)  # every stage is checked before the first case runs
    run_one = evaluate if evaluate is not None else make_evaluator(doc)
    run_rob = robustness if robustness is not None else make_robustness_evaluator(doc)
    say = progress if progress is not None else (lambda _msg: None)
    grid: list[PointResult] = []
    for point in GRID:
        result = run_one(point, list(GRID_SEEDS))
        grid.append(result)
        say(f"grid {point.label}: score {result.score:.4g}, qualifies {result.qualifies}")
    chosen = select_point(grid)
    confirmations: dict[str, PointResult] = {}
    if chosen is not None:
        for label, seeds in CONFIRMATION_BLOCKS.items():
            confirmations[label] = run_one(chosen.point, list(seeds))
            say(
                f"{label} {chosen.point.label}: score {confirmations[label].score:.4g}, "
                f"qualifies {confirmations[label].qualifies}"
            )
    outcome = decide(grid, confirmations if chosen is not None else None)
    # The diagnostic comes after the decision and nothing in it is read by the decision.
    subject = chosen if chosen is not None else highest_score(grid)
    basis = "chosen" if chosen is not None else "highest_score"
    robust: list[RobustnessResult] = []
    for corr_time in ROBUSTNESS_CORR_TIMES_S:
        r = run_rob(subject.point, corr_time, list(ROBUSTNESS_SEEDS))
        robust.append(r)
        say(f"{DIAGNOSTIC} {subject.point.label}, correlation time {corr_time:g} s: gate passes {r.scenario.passed}")
    return TuningRun(tuple(grid), confirmations, outcome, tuple(robust), basis)


# ------------------------------------------------------------------------------------------------ CSV


def _csv_text(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        out: list[Any] = []
        for k in fields:
            v = row[k]
            if k in _BOOL_FIELDS:
                out.append("true" if v else "false")
            elif k in _TEXT_FIELDS:
                out.append(v)
            else:
                if not math.isfinite(float(v)):
                    raise ValueError(f"{k} must be finite, got {v!r}")
                out.append(repr(float(v)))
        writer.writerow(out)
    return buffer.getvalue()


def _parse_csv(text: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != fields:
        raise ValueError(f"the file needs the columns {', '.join(fields)}")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row: dict[str, Any] = {}
        for k in fields:
            if k in _BOOL_FIELDS:
                row[k] = raw[k] == "true"
            elif k in _TEXT_FIELDS:
                row[k] = raw[k]
            else:
                row[k] = float(raw[k])
        rows.append(row)
    return rows


def csv_text(rows: list[dict[str, Any]]) -> str:
    """The rows as CSV text. Floats are written with ``repr``, so the bytes are deterministic."""
    return _csv_text(rows, CSV_FIELDS)


def parse_csv(text: str) -> list[dict[str, Any]]:
    return _parse_csv(text, CSV_FIELDS)


def robustness_csv_text(rows: list[dict[str, Any]]) -> str:
    return _csv_text(rows, ROBUSTNESS_CSV_FIELDS)


def parse_robustness_csv(text: str) -> list[dict[str, Any]]:
    return _parse_csv(text, ROBUSTNESS_CSV_FIELDS)


def outcome_from_rows(rows: list[dict[str, Any]]) -> Outcome:
    """The outcome that a set of rows states, from the rows alone."""
    keys = sorted({(r["tau_s"], r["rho"]) for r in rows if r["stage"] == "grid" and r["chosen"]})
    if not keys:
        return Outcome(False, None, ())
    if len(keys) != 1:
        raise ValueError("more than one grid point is marked as chosen")
    failed = []
    for label in CONFIRMATION_BLOCKS:
        block = [r for r in rows if r["stage"] == label]
        if not block:
            raise ValueError(f"the chosen point has no rows for {label}")
        if not all(r["qualifies"] for r in block):
            failed.append(label)
    return Outcome(not failed, GridPoint(*keys[0]), tuple(failed))


# ------------------------------------------------------------------------------------------------ page


def _span(seeds: str) -> str:
    lo, _, hi = seeds.partition("-")
    return f"{lo} to {hi}" if hi else lo


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _point_text(p: GridPoint) -> str:
    return f"tau = {p.tau_s:g} s, rho = {p.rho:g}"


def _groups(rows: list[dict[str, Any]], stage: str) -> list[list[dict[str, Any]]]:
    order: list[tuple[float, float]] = []
    for r in rows:
        key = (r["tau_s"], r["rho"])
        if r["stage"] == stage and key not in order:
            order.append(key)
    return [[r for r in rows if r["stage"] == stage and (r["tau_s"], r["rho"]) == key] for key in order]


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _holds(group: list[dict[str, Any]], scenario: str) -> str:
    return _yes(all(r["holds"] for r in group if r["scenario"] == scenario))


def markdown_section(rows: list[dict[str, Any]]) -> str:
    """The generated block: the grid table, the confirmation table, and the outcome in one sentence."""
    grid = _groups(rows, "grid")
    if not grid:
        raise ValueError("no grid rows to tabulate")
    out = outcome_from_rows(rows)
    grid_seeds = _span(grid[0][0]["seeds"])
    lines = [
        f"Grid, development seeds {grid_seeds}. The score is the smallest margin of a point, and the column "
        "'Smallest margin is' names the condition that gives it.",
        "",
        "| tau (s) | rho | S1 holds | S2 holds | Score | Smallest margin is | Qualifies | Chosen |",
        "|---:|---:|---|---|---:|---|---|---|",
    ]
    for g in grid:
        low = min(g, key=lambda r: r["margin"])
        chosen = "chosen" if g[0]["chosen"] else ""
        lines.append(
            f"| {g[0]['tau_s']:g} | {g[0]['rho']:g} | {_holds(g, 'S1')} | {_holds(g, 'S2')} | "
            f"{g[0]['score']:.4g} | {low['scenario']} {low['condition']} | {_yes(g[0]['qualifies'])} | {chosen} |"
        )
    if out.chosen is not None:
        lines += [
            "",
            f"Confirmation of the chosen point ({_point_text(out.chosen)}) on further development seeds.",
            "",
            "| Block | Seeds | S1 holds | S2 holds | Score | Holds in both |",
            "|---|---|---|---|---:|---|",
        ]
        for label in CONFIRMATION_BLOCKS:
            g = _groups(rows, label)[0]
            lines.append(
                f"| {label} | {g[0]['seeds']} | {_holds(g, 'S1')} | {_holds(g, 'S2')} | {g[0]['score']:.4g} | "
                f"{_yes(g[0]['qualifies'])} |"
            )
    lines += ["", _outcome_sentence(rows, out, grid_seeds)]
    return "\n".join(lines)


def _outcome_sentence(rows: list[dict[str, Any]], out: Outcome, grid_seeds: str) -> str:
    if out.chosen is None:
        return (
            "Outcome: failed on development seeds. No point of the grid passed the gate in both scenarios on seeds "
            f"{grid_seeds}, so none was chosen and none was confirmed."
        )
    spans = {label: _span(_groups(rows, label)[0][0]["seeds"]) for label in CONFIRMATION_BLOCKS}
    if out.failed_blocks:
        failed = _list([spans[b] for b in out.failed_blocks])
        return (
            f"Outcome: failed on development seeds. The chosen point ({_point_text(out.chosen)}) did not pass the "
            f"gate in both scenarios on seeds {failed}."
        )
    blocks = _list([spans[b] for b in CONFIRMATION_BLOCKS])
    return (
        f"Outcome: the point {_point_text(out.chosen)} qualified on the development seeds and passed the gate in "
        f"both scenarios on each confirmation block (seeds {blocks})."
    )


def robustness_markdown(rows: list[dict[str, Any]]) -> str:
    """The generated diagnostic block: one row per correlation time and condition, labelled as a diagnostic."""
    if not rows:
        raise ValueError("no diagnostic rows to tabulate")
    first = rows[0]
    point = GridPoint(first["tau_s"], first["rho"])
    why = (
        "the chosen point"
        if first["basis"] == "chosen"
        else "the point with the highest score, because no point qualified"
    )
    lines = [
        f"{DIAGNOSTIC}, outside the decision. The subject is {why} ({_point_text(point)}). The S2-like scenario is run "
        "with the visual-error correlation time set to each value below, on development seeds "
        f"{_span(first['seeds'])}, "
        "and the gate of ADR-0030 is evaluated for that scenario alone. This is not a pass or fail and not a "
        "selection input: it shows whether the point is robust to a correlation time it was not tuned for.",
        "",
        "| Correlation time (s) | Condition | Value | Threshold | Margin | Holds | All six hold |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['corr_time_s']:g} | {r['condition']} | {r['value']:.4g} | {r['threshold']:.4g} | "
            f"{r['margin']:.4g} | {_yes(r['holds'])} | {_yes(r['scenario_passed'])} |"
        )
    return "\n".join(lines)


def splice_section(page: str, text: str, start: str = START, end: str = END) -> str:
    """``page`` with the text between the two marker lines replaced by ``text``."""
    name = start.removeprefix("<!-- ").removesuffix(":start -->")
    return splice_block(page, name, text)


# ------------------------------------------------------------------------------------------ command


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="navkit gate tune-gm",
        description="The pre-registered tuning run of the Gauss-Markov visual error model (ADR-0034). The grid and the "
        "seeds are fixed, development seeds only; no option takes a seed.",
    )
    ap.add_argument("--csv", type=Path, required=True, help="write the rows of the decision here")
    ap.add_argument(
        "--robustness-csv",
        type=Path,
        default=None,
        help="write the DIAGNOSTIC rows here (default: next to --csv, with _robustness before the extension)",
    )
    ap.add_argument("--page", type=Path, default=None, help="write the tables between the gm-tuning markers")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rob_path = args.robustness_csv or args.csv.with_name(f"{args.csv.stem}_robustness{args.csv.suffix}")
    started = time.perf_counter()

    def progress(msg: str) -> None:
        print(f"[{time.perf_counter() - started:7.1f} s] {msg}", file=sys.stderr, flush=True)

    run = run_tuning(progress=progress)
    rows, rob_rows = run.rows(), run.robustness_rows()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    rob_path.write_text(robustness_csv_text(rob_rows), encoding="utf-8")
    print(f"wrote {args.csv} and {rob_path}", file=sys.stderr)
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        page = splice_section(page, markdown_section(rows), START, END)
        page = splice_section(page, robustness_markdown(rob_rows), ROB_START, ROB_END)
        args.page.write_text(page, encoding="utf-8")
        print(f"wrote the tables into {args.page}", file=sys.stderr)
    print(f"{run.outcome.kind}; elapsed {time.perf_counter() - started:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
