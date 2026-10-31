"""The pre-registered tuning run of the adaptive visual scale: ADR-0031, amended by ADR-0032.

    navkit gate tune-scale --csv docs/data/adaptive_scale_tuning.csv --page docs/calibration.md

The procedure is the paragraph "How the parameters are chosen" of ADR-0031, and nothing here departs from it.

1. The grid is ``tau`` in {2, 5, 10} seconds, ``s_min`` in {0.25, 0.5} and ``s_max`` in {8, 16}: twelve points and no
   others. A point is the stochastic clone with the adaptive scale on and no noise preset.
2. Each point goes through the candidate gate of ADR-0030 in both scenarios on seeds 0 to 24. A point *qualifies* if the
   gate passes in both.
3. The margin of a condition is its distance from its threshold in units of the threshold, positive when the condition
   holds. The *score* of a point is its smallest margin over all six conditions in both scenarios. Among qualifying
   points the largest score is chosen. Ties go to the smaller ``tau``, then the larger ``s_min``, then the smaller
   ``s_max``. A tie is an exact equality of the two scores.
4. The chosen point must pass the gate in both scenarios on seeds 25 to 49, 50 to 74 and 75 to 99. If no point
   qualifies, or the chosen point fails a block, the candidate is recorded as failed on development seeds. It is not
   repaired, no grid point is added, and it is not taken to a held-out block.

Only development seeds (0 to 99) are run. The command takes no seed, and :func:`check_seeds` refuses any seed from 100
up before anything runs, in every stage. No option can widen that: seeds 100 to 124 are spent (ADR-0028) and from 125
the seeds are held-out blocks, which are for the one evaluation that ADR-0031 puts after this run.

A margin that is not defined (a threshold that is zero, negative or not finite, or a value that is not finite) is an
error and not a number: there is no rule for it in the ADR, so the run stops.

The loop knows the gate only through an evaluator, a function ``(point, seeds) -> PointResult``. The real one runs the
cases of :mod:`navkit.candidate_gate`; the tests give the loop a table instead, so that no case is run.
"""

from __future__ import annotations

import argparse
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
from .eval.gate import Condition
from .report.page import splice_block

#: ADR-0031: "tau in {2, 5, 10} seconds, s_min in {0.25, 0.5}, s_max in {8, 16}: twelve points, and no others".
GRID_TAU_S = (2.0, 5.0, 10.0)
GRID_S_MIN = (0.25, 0.5)
GRID_S_MAX = (8.0, 16.0)
#: ADR-0031: "each point is evaluated ... in both scenarios on seeds 0 to 24".
GRID_SEEDS = range(0, 25)
#: ADR-0031: "the chosen point must also pass the gate on seeds 25 to 49, 50 to 74 and 75 to 99".
CONFIRMATION_BLOCKS: dict[str, range] = {
    "confirm 25-49": range(25, 50),
    "confirm 50-74": range(50, 75),
    "confirm 75-99": range(75, 100),
}
#: The first seed this module will not run. Seeds 100 to 124 are spent (ADR-0028); from 125 they are held-out blocks.
SEED_LIMIT = 100
SCENARIOS = ("S1", "S2")

START, END = "<!-- scale-tuning:start -->", "<!-- scale-tuning:end -->"

CSV_FIELDS = (
    "stage",
    "tau_s",
    "s_min",
    "s_max",
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
_TEXT_FIELDS = {"stage", "scenario", "seeds", "condition", "relation"}
_BOOL_FIELDS = {"holds", "qualifies", "chosen"}


# ------------------------------------------------------------------------------------------- the grid


@dataclass(frozen=True)
class GridPoint:
    """One setting of the three parameters."""

    tau_s: float
    s_min: float
    s_max: float

    @property
    def label(self) -> str:
        return f"tau={self.tau_s:g} s, s_min={self.s_min:g}, s_max={self.s_max:g}"

    def estimator(self) -> dict[str, Any]:
        """The estimator settings of the point: the clone with the scale on, and no noise preset."""
        return {
            "vision_model": "clone",
            "vision_adaptive_scale": True,
            "vision_scale_tau_s": self.tau_s,
            "vision_scale_min": self.s_min,
            "vision_scale_max": self.s_max,
        }


GRID: tuple[GridPoint, ...] = tuple(
    GridPoint(tau, lo, hi) for tau, lo, hi in itertools.product(GRID_TAU_S, GRID_S_MIN, GRID_S_MAX)
)


# ----------------------------------------------------------------------------------------- the seeds


def check_seeds(seeds: Sequence[int]) -> None:
    """Raise ``ValueError`` unless every seed is a development seed. Runs no case."""
    for s in seeds:
        if s < 0:
            raise ValueError(f"seed {s} is negative")
        if s >= SEED_LIMIT:
            raise ValueError(
                f"seed {s} is not a development seed: the tuning run takes seeds 0 to {SEED_LIMIT - 1} only "
                "(seeds 100 to 124 are spent and from 125 they are held-out blocks, ADR-0028 and ADR-0030)"
            )


# ---------------------------------------------------------------------------------------- the margins


def condition_margin(c: Condition) -> float:
    """The distance of a condition from its threshold in units of the threshold: positive when it holds.

    ``(threshold - value) / threshold`` for an "at most" condition and ``(value - threshold) / threshold`` for an "at
    least" one. For the count condition that is ``(count - 20) / 20`` and for coverage ``(value - 0.95) / 0.95``.
    """
    if c.relation not in ("<=", ">="):
        raise ValueError(f"unknown relation {c.relation!r} for the condition {c.name}")
    if not (math.isfinite(c.threshold) and c.threshold > 0.0):
        raise ValueError(
            f"the margin of {c.name} is undefined: the threshold must be finite and positive, got {c.threshold!r}. "
            "ADR-0031 has no rule for it; stop and ask"
        )
    if not math.isfinite(c.value):
        raise ValueError(f"the margin of {c.name} is undefined: the value is not finite, got {c.value!r}")
    if c.relation == "<=":
        return (c.threshold - c.value) / c.threshold
    return (c.value - c.threshold) / c.threshold


def scenario_margin(result: ScenarioGateResult) -> float:
    """The smallest margin of the six conditions of one scenario."""
    return min(condition_margin(c) for c in result.conditions)


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
        """One row per scenario and condition."""
        seeds = format_seeds(list(self.seeds))
        out = []
        for scenario, result in zip(SCENARIOS, (self.s1, self.s2), strict=True):
            for c in result.conditions:
                out.append(
                    {
                        "stage": stage,
                        "tau_s": float(self.point.tau_s),
                        "s_min": float(self.point.s_min),
                        "s_max": float(self.point.s_max),
                        "scenario": scenario,
                        "seeds": seeds,
                        "condition": c.name,
                        "relation": c.relation,
                        "value": float(c.value),
                        "threshold": float(c.threshold),
                        "margin": condition_margin(c),
                        "holds": bool(c.passed),
                        "score": self.score,
                        "qualifies": self.qualifies,
                        "chosen": chosen,
                    }
                )
        return out


def select_point(results: Sequence[PointResult]) -> PointResult | None:
    """The qualifying point with the largest score, ties to the smaller tau, the larger s_min, the smaller s_max."""
    qualifying = [r for r in results if r.qualifies]
    if not qualifying:
        return None
    return min(qualifying, key=lambda r: (-r.score, r.point.tau_s, -r.point.s_min, r.point.s_max))


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
    """Apply ADR-0031's rule: no qualifying point, or a chosen point that fails a block, is a failure."""
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


@dataclass(frozen=True)
class TuningRun:
    grid: tuple[PointResult, ...]
    confirmations: dict[str, PointResult]
    outcome: Outcome

    def rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for r in self.grid:
            rows.extend(r.rows("grid", chosen=self.outcome.chosen == r.point))
        for label, r in self.confirmations.items():
            rows.extend(r.rows(label, chosen=True))
        return rows


def make_evaluator(doc: dict[str, Any] | None = None) -> Evaluator:
    """The real evaluator: run both scenarios and the control through :mod:`navkit.candidate_gate` and apply the gate.

    The control (``outage_control``) has no vision, so it is run once per list of seeds and shared by all points.
    """
    state: dict[str, Any] = {"doc": doc or None}
    controls: dict[tuple[int, ...], np.ndarray] = {}

    def evaluate(point: GridPoint, seeds: Sequence[int]) -> PointResult:
        seed_list = list(seeds)
        check_seeds(seed_list)
        if len(seed_list) < 2:
            raise ValueError("the gate needs at least two seeds")
        if state["doc"] is None:
            state["doc"] = _gate._document()
        key = tuple(seed_list)
        if key not in controls:
            controls[key] = _gate.run_control("S1", seed_list, state["doc"])["ate"]
        results = {}
        for scenario in SCENARIOS:
            a = _gate.run_scenario(scenario, point.estimator(), seed_list, state["doc"])
            results[scenario] = evaluate_scenario_gate(
                a["y"],
                a["n_eff"],
                a["err"],
                a["sigma"],
                a["ate"],
                controls[key],
                upper_quantile=CANDIDATE_GATE_UPPER_QUANTILE,
            )
        return PointResult(point, key, results["S1"], results["S2"])

    return evaluate


def run_tuning(
    evaluate: Evaluator | None = None,
    progress: Callable[[str], None] | None = None,
    doc: dict[str, Any] | None = None,
) -> TuningRun:
    """The whole procedure, once: the grid, the choice, the confirmation of the chosen point, the outcome."""
    for seeds in (GRID_SEEDS, *CONFIRMATION_BLOCKS.values()):
        check_seeds(seeds)  # every stage is checked before the first case runs
    run_one = evaluate if evaluate is not None else make_evaluator(doc)
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
    return TuningRun(tuple(grid), confirmations, decide(grid, confirmations if chosen is not None else None))


# ------------------------------------------------------------------------------------------------ CSV


def csv_text(rows: list[dict[str, Any]]) -> str:
    """The rows as CSV text. Floats are written with ``repr``, so the bytes are deterministic."""
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
            else:
                row[k] = float(raw[k])
        rows.append(row)
    return rows


def outcome_from_rows(rows: list[dict[str, Any]]) -> Outcome:
    """The outcome that a set of rows states, from the rows alone."""
    keys = sorted({(r["tau_s"], r["s_min"], r["s_max"]) for r in rows if r["stage"] == "grid" and r["chosen"]})
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
    return f"tau = {p.tau_s:g} s, s_min = {p.s_min:g}, s_max = {p.s_max:g}"


def _groups(rows: list[dict[str, Any]], stage: str) -> list[list[dict[str, Any]]]:
    order: list[tuple[float, float, float]] = []
    for r in rows:
        key = (r["tau_s"], r["s_min"], r["s_max"])
        if r["stage"] == stage and key not in order:
            order.append(key)
    return [[r for r in rows if r["stage"] == stage and (r["tau_s"], r["s_min"], r["s_max"]) == key] for key in order]


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
        f"Grid, development seeds {grid_seeds}. The score is the smallest margin of a point, and the last column "
        "names the condition that gives it.",
        "",
        "| tau (s) | s_min | s_max | S1 holds | S2 holds | Score | Smallest margin is | Qualifies | Chosen |",
        "|---:|---:|---:|---|---|---:|---|---|---|",
    ]
    for g in grid:
        low = min(g, key=lambda r: r["margin"])
        chosen = "chosen" if g[0]["chosen"] else ""
        lines.append(
            f"| {g[0]['tau_s']:g} | {g[0]['s_min']:g} | {g[0]['s_max']:g} | {_holds(g, 'S1')} | {_holds(g, 'S2')} | "
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


def splice_section(page: str, text: str) -> str:
    """``page`` with the text between the tuning markers replaced by ``text``."""
    return splice_block(page, "scale-tuning", text)


# ------------------------------------------------------------------------------------------ command


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="navkit gate tune-scale",
        description="The pre-registered tuning run of the adaptive visual scale (ADR-0031). The grid and the seeds are "
        "fixed, development seeds only; no option takes a seed.",
    )
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--page", type=Path, default=None, help="write the tables between the scale-tuning markers")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()

    def progress(msg: str) -> None:
        print(f"[{time.perf_counter() - started:7.1f} s] {msg}", file=sys.stderr, flush=True)

    run = run_tuning(progress=progress)
    rows = run.rows()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_section(page, markdown_section(rows)), encoding="utf-8")
        print(f"wrote the tables into {args.page}", file=sys.stderr)
    print(f"{run.outcome.kind}; elapsed {time.perf_counter() - started:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
