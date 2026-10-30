"""The candidate gate of ADR-0030: run a candidate and its control in two scenarios over seeds, and apply the gate.

    navkit gate candidate --seeds 25-49 --csv docs/data/candidate_gate_dev.csv --page docs/calibration.md
    navkit gate n-eff-pool --csv docs/data/gate_n_eff_pool.csv

A candidate is a set of estimator settings. It runs against two scenarios with the same settings: S1, the scenario
block of ``outage_visual`` (independent visual errors), and S2, the scenario block of
``outage_visual_clone_correlated`` (visual errors correlated over time). The control is ``outage_control`` on the same
seeds. Both go through :func:`navkit.benchmark.run_case`, so the start draw of ADR-0027 applies, and the arrays are
cut to the GNSS-outage window as in :mod:`navkit.b1_gate`.

Seeds 0 to 99 are for development. Seeds 100 to 124 are spent (ADR-0028). From 125 the seeds are held-out blocks of 25:
the command refuses any of them without ``--held-out``, refuses a block that overlaps a row of
``docs/data/heldout_ledger.csv`` and any block that is not the next unused one. It never writes the ledger: a human
commits that row after the run.

The default candidate is the one of ADR-0028 (the stochastic clone with the measured-front-end noise preset), so that
the machinery can be exercised. It is not a new candidate, and nothing here evaluates one.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .b1_gate import CANDIDATE_ESTIMATOR, format_seeds, parse_seeds, window_arrays
from .benchmark import default_config_path, run_case
from .eval.calibration import effective_samples
from .eval.candidate_gate import (
    CANDIDATE_GATE_RUNS,
    CANDIDATE_GATE_UPPER_QUANTILE,
    ScenarioGateResult,
    evaluate_candidate_gate,
    evaluate_scenario_gate,
    parse_pool_csv,
    pool_csv_text,
)
from .report.page import splice_block

#: The two scenarios of ADR-0030: the cases whose scenario block each one uses.
SCENARIOS = {"S1": "outage_visual", "S2": "outage_visual_clone_correlated"}
CONTROL = "outage_control"
DEFAULT_ESTIMATOR: dict[str, Any] = dict(CANDIDATE_ESTIMATOR)

#: The first held-out block (ADR-0028) is spent. Later blocks start here and have this many seeds.
SPENT_SEEDS = range(100, 125)
FIRST_HELD_OUT_SEED = 125
BLOCK_SIZE = 25
#: The seeds whose effective sample sizes the pre-registered simulation draws from (ADR-0030).
POOL_SEEDS = list(range(25, 100))

LEDGER_PATH = Path(__file__).resolve().parents[2] / "docs" / "data" / "heldout_ledger.csv"
LEDGER_FIELDS = ("block", "seeds", "candidate", "commit", "date", "outcome")

CSV_FIELDS = (
    "role",
    "subject",
    "scenario",
    "seeds",
    "n_runs",
    "upper_quantile",
    "m",
    "condition",
    "relation",
    "value",
    "threshold",
    "passed",
    "scenario_passed",
    "subject_passed",
)
_INT_FIELDS = {"n_runs"}
_TEXT_FIELDS = {"role", "subject", "scenario", "seeds", "condition", "relation"}
_BOOL_FIELDS = {"passed", "scenario_passed", "subject_passed"}
CONDITION_ORDER = ("upper", "lower", "coverage", "better", "median_ratio", "worst_ratio")
CONDITION_LABELS = {
    "upper": "90th percentile of the per-run mean NEES, at most the upper edge",
    "lower": "Median of the per-run mean NEES, at least the lower bound",
    "coverage": "Pooled 2-sigma per-axis coverage",
    "better": "Runs where the candidate has the lower ATE",
    "median_ratio": "Median ATE ratio, candidate over control",
    "worst_ratio": "Largest ATE ratio",
}
START, END = "<!-- candidate-gate-dev:start -->", "<!-- candidate-gate-dev:end -->"


# ---------------------------------------------------------------------------------------- the ledger


def parse_ledger(text: str) -> list[dict[str, Any]]:
    """The held-out ledger. Each row is a block that was used, with the seeds as a list."""
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != LEDGER_FIELDS:
        raise ValueError(f"the ledger needs the columns {', '.join(LEDGER_FIELDS)}")
    rows = []
    for raw in reader:
        rows.append(
            {
                "block": int(raw["block"]),
                "seeds": parse_seeds(raw["seeds"]),
                "candidate": raw["candidate"],
                "commit": raw["commit"],
                "date": raw["date"],
                "outcome": raw["outcome"],
            }
        )
    return rows


def read_ledger(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    return parse_ledger(Path(path).read_text(encoding="utf-8"))


def next_block(ledger: list[dict[str, Any]]) -> list[int]:
    """The next unused block of 25 seeds: 125 to 149, then 150 to 174, and so on."""
    last = max((max(r["seeds"]) for r in ledger), default=FIRST_HELD_OUT_SEED - 1)
    start = max(last + 1, FIRST_HELD_OUT_SEED)
    return list(range(start, start + BLOCK_SIZE))


def check_seeds(seeds: list[int], held_out: bool, ledger: list[dict[str, Any]]) -> None:
    """Raise ``ValueError`` unless these seeds may be run. Runs no case."""
    if any(s in SPENT_SEEDS for s in seeds):
        raise ValueError("seeds 100 to 124 are spent: the first held-out block was used once (ADR-0028)")
    if any(s >= FIRST_HELD_OUT_SEED for s in seeds) and not held_out:
        raise ValueError(
            "seeds from 125 are held-out blocks (ADR-0030); give --held-out to evaluate the next one, once"
        )
    if held_out:
        used = {s for row in ledger for s in row["seeds"]}
        if used & set(seeds):
            raise ValueError("these seeds overlap a block in the held-out ledger (docs/data/heldout_ledger.csv)")
        expected = next_block(ledger)
        if list(seeds) != expected:
            raise ValueError(
                f"--held-out takes exactly the next unused block of {BLOCK_SIZE}: seeds {format_seeds(expected)}"
            )


# ---------------------------------------------------------------------------------------------- the runs


def _document() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text(encoding="utf-8")) or {}


def parse_estimator(text: str) -> dict[str, Any]:
    """``"k=v,k=v"`` as estimator settings. Values are read as YAML (numbers, booleans, words)."""
    if not text.strip():
        return {}
    out: dict[str, Any] = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        key = key.strip()
        if not sep or not key or not value.strip():
            raise ValueError(f"cannot read {part!r}: use key=value, comma separated")
        if key == "vision_fuse":
            raise ValueError("vision_fuse is on for a candidate and is not set here")
        out[key] = yaml.safe_load(value.strip())
    return out


def scenario_case(cases: dict[str, Any], key: str, estimator: dict[str, Any]) -> dict[str, Any]:
    """The case of scenario ``key`` ("S1" or "S2") with the candidate's estimator settings applied."""
    if key not in SCENARIOS:
        raise ValueError(f"unknown scenario {key!r}; known: {', '.join(SCENARIOS)}")
    case = copy.deepcopy(cases[SCENARIOS[key]])
    case["estimator"] = {"vision_fuse": True, **estimator}
    return case


def run_scenario(
    key: str, estimator: dict[str, Any], seeds: list[int], doc: dict[str, Any] | None = None
) -> dict[str, np.ndarray]:
    """Run the candidate in scenario ``key`` on ``seeds`` and return the arrays the evaluator needs."""
    doc = doc or _document()
    case = scenario_case(doc["cases"], key, estimator)
    ys, ns, errs, sigmas, ates = [], [], [], [], []
    for seed in seeds:
        box: dict[str, Any] = {}
        run_case(SCENARIOS[key], case, doc.get("defaults", {}), seed=seed, nees_out=box)
        w = window_arrays(box)
        n_eff, _ = effective_samples(w["nees"])
        if not math.isfinite(n_eff):
            raise ValueError(f"seed {seed}: the window series has no effective sample size")
        ys.append(float(np.mean(w["nees"])))
        ns.append(n_eff)
        errs.append(w["error"])
        sigmas.append(w["sigma"])
        ates.append(float(w["ate"]))
    return {
        "y": np.array(ys),
        "n_eff": np.array(ns),
        "err": np.stack(errs),
        "sigma": np.stack(sigmas),
        "ate": np.array(ates),
    }


def run_control(key: str, seeds: list[int], doc: dict[str, Any] | None = None) -> dict[str, np.ndarray]:
    """The no-vision control on ``seeds``. It has no vision, so it is the same in both scenarios; ``key`` is checked."""
    if key not in SCENARIOS:
        raise ValueError(f"unknown scenario {key!r}; known: {', '.join(SCENARIOS)}")
    doc = doc or _document()
    ates = []
    for seed in seeds:
        box: dict[str, Any] = {}
        run_case(CONTROL, doc["cases"][CONTROL], doc.get("defaults", {}), seed=seed, nees_out=box)
        ates.append(float(window_arrays(box)["ate"]))
    return {"ate": np.array(ates)}


def subject_name(estimator: dict[str, Any]) -> str:
    if estimator == DEFAULT_ESTIMATOR:
        return "outage_visual+clone+measured-front-end"
    return "outage_visual+" + ",".join(f"{k}={v}" for k, v in sorted(estimator.items()))


def result_rows(
    role: str, subject: str, scenario: str, seeds: list[int], result: ScenarioGateResult, subject_passed: bool
) -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "subject": subject,
            "scenario": scenario,
            "seeds": format_seeds(seeds),
            "n_runs": result.n_runs,
            "upper_quantile": result.upper_quantile,
            "m": result.m,
            "condition": c.name,
            "relation": c.relation,
            "value": c.value,
            "threshold": c.threshold,
            "passed": c.passed,
            "scenario_passed": result.passed,
            "subject_passed": subject_passed,
        }
        for c in result.conditions
    ]


def run_candidate_gate(
    seeds: list[int],
    estimator: dict[str, Any] | None = None,
    held_out: bool = False,
    diagnostics: bool = True,
    ledger: list[dict[str, Any]] | None = None,
    doc: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the candidate, the control and (on development seeds) two diagnostics in S1 and S2, and return CSV rows.

    The diagnostics are the plain clone and the single anchor. They are never run on a held-out block.
    """
    check_seeds(seeds, held_out, read_ledger() if ledger is None else ledger)
    if len(seeds) < 2:
        raise ValueError("the gate needs at least two seeds")
    doc = doc or _document()
    estimator = dict(DEFAULT_ESTIMATOR if estimator is None else estimator)
    subjects: list[tuple[str, str, dict[str, Any]]] = [("candidate", subject_name(estimator), estimator)]
    if diagnostics and not held_out:
        subjects.append(("DIAGNOSTIC", "outage_visual_clone", {"vision_model": "clone"}))
        subjects.append(("DIAGNOSTIC", "outage_visual", {}))
    control = run_control("S1", seeds, doc)
    rows: list[dict[str, Any]] = []
    for role, name, est in subjects:
        results = {}
        for key in SCENARIOS:
            a = run_scenario(key, est, seeds, doc)
            results[key] = evaluate_scenario_gate(
                a["y"],
                a["n_eff"],
                a["err"],
                a["sigma"],
                a["ate"],
                control["ate"],
                upper_quantile=CANDIDATE_GATE_UPPER_QUANTILE,
            )
        both = evaluate_candidate_gate(results["S1"], results["S2"]).passed
        for key, result in results.items():
            rows.extend(result_rows(role, name, key, seeds, result, both))
    return rows


# --------------------------------------------------------------------------------------------- CSV, page


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
            elif k in _INT_FIELDS or k in _TEXT_FIELDS:
                out.append(v)
            else:
                out.append(repr(float(v)))
        writer.writerow(out)
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
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


def compare_rows(new: list[dict[str, Any]], old: list[dict[str, Any]], rel_tol: float = 1e-6) -> list[str]:
    """Differences between two row lists: text, integers and flags exactly, floats to ``rel_tol``."""
    if len(new) != len(old):
        return [f"{len(new)} rows against {len(old)}"]
    problems = []
    for a, b in zip(new, old, strict=True):
        for k in CSV_FIELDS:
            x, y = a[k], b[k]
            same = math.isclose(x, y, rel_tol=rel_tol, abs_tol=1e-12) if isinstance(x, float) else x == y
            if not same:
                problems.append(f"{a['subject']} {a['scenario']} {a['condition']} {k}: {x!r} against {y!r}")
    return problems


def _format_value(condition: str, v: float) -> str:
    if condition == "coverage":
        return f"{100.0 * v:.2f}%"
    if condition == "better":
        return str(int(v))
    return f"{v:.4g}"


def _format_threshold(condition: str, relation: str, v: float) -> str:
    return f"{relation} {_format_value(condition, v)}"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """The generated block: one line per subject and scenario, then one line per condition."""
    if not rows:
        raise ValueError("no rows to tabulate")
    seen: list[tuple[str, str, str]] = []
    for r in rows:
        key = (r["role"], r["subject"], r["scenario"])
        if key not in seen:
            seen.append(key)
    head = [
        "| Role | Subject | Scenario | Seeds | Runs | Median n_eff (m) | Level of (U) "
        "| Holds in this scenario | Holds in both |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for role, subject, scenario in seen:
        r = next(x for x in rows if (x["role"], x["subject"], x["scenario"]) == (role, subject, scenario))
        head.append(
            f"| {role} | {subject} | {scenario} | {r['seeds']} | {r['n_runs']} | {r['m']:.1f} | "
            f"{r['upper_quantile']:g} | {'yes' if r['scenario_passed'] else 'no'} | "
            f"{'yes' if r['subject_passed'] else 'no'} |"
        )
    body = ["| Role | Subject | Scenario | Condition | Value | Threshold | Holds |", "|---|---|---|---|---:|---:|---|"]
    for r in rows:
        c = r["condition"]
        body.append(
            f"| {r['role']} | {r['subject']} | {r['scenario']} | {CONDITION_LABELS[c]} | "
            f"{_format_value(c, r['value'])} | "
            f"{_format_threshold(c, r['relation'], r['threshold'])} | {'yes' if r['passed'] else 'no'} |"
        )
    return "\n".join([*head, "", *body])


def splice_table(page: str, table: str) -> str:
    """``page`` with the text between the candidate-gate markers replaced by ``table``."""
    return splice_block(page, "candidate-gate-dev", table)


# ------------------------------------------------------------------------------------------- commands


class _Parser(argparse.ArgumentParser):
    """Refuses seeds that may not be run, before anything runs, and says a held-out block is single use."""

    def parse_args(self, args: Any = None, namespace: Any = None) -> argparse.Namespace:  # type: ignore[override]
        ns = super().parse_args(args, namespace)
        try:
            check_seeds(ns.seeds, ns.held_out, read_ledger(ns.ledger))
        except (ValueError, OSError) as exc:
            self.error(str(exc))
        if ns.held_out:
            print(
                f"warning: seeds {format_seeds(ns.seeds)} are a held-out block, single use per ADR-0030. "
                "Record the result in the ledger afterwards.",
                file=sys.stderr,
            )
        return ns


def _seeds_arg(text: str) -> list[int]:
    try:
        return parse_seeds(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _estimator_arg(text: str) -> dict[str, Any]:
    try:
        return parse_estimator(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="navkit gate candidate", description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument(
        "--seeds", type=_seeds_arg, required=True, help=f"A-B or a comma list; exactly {CANDIDATE_GATE_RUNS}"
    )
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--page", type=Path, default=None, help="write the table between the candidate-gate-dev markers")
    ap.add_argument("--estimator", type=_estimator_arg, default=None, help='candidate settings "k=v,k=v"')
    ap.add_argument("--held-out", action="store_true", help="evaluate the next unused held-out block (single use)")
    ap.add_argument("--ledger", type=Path, default=LEDGER_PATH, help="the held-out ledger (read, never written)")
    ap.add_argument("--compare", type=Path, default=None, help="exit 1 if the rows differ from this committed CSV")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if len(args.seeds) != CANDIDATE_GATE_RUNS:
        ap.error(f"the gate is decided on exactly {CANDIDATE_GATE_RUNS} seeds, got {len(args.seeds)}")
    rows = run_candidate_gate(
        args.seeds, estimator=args.estimator, held_out=args.held_out, ledger=read_ledger(args.ledger)
    )
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}", file=sys.stderr)
    if args.page is not None:
        page = args.page.read_text(encoding="utf-8")
        args.page.write_text(splice_table(page, markdown_table(rows)), encoding="utf-8")
        print(f"wrote the table into {args.page}", file=sys.stderr)
    for r in rows:
        if r["condition"] == "worst_ratio":
            print(
                f"{r['role']:<10} {r['subject']:<40} {r['scenario']}: scenario passes {r['scenario_passed']}, "
                f"both scenarios pass {r['subject_passed']}",
                file=sys.stderr,
            )
    if args.compare is not None:
        problems = compare_rows(rows, parse_csv(args.compare.read_text(encoding="utf-8")))
        if problems:
            print(f"the rows differ from {args.compare}:", file=sys.stderr)
            for line in problems[:20]:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"the rows match {args.compare}", file=sys.stderr)
    return 0


def run_pool(doc: dict[str, Any] | None = None) -> list[dict[str, float]]:
    """The effective sample size of the default candidate's window NEES in S1, on each of seeds 25 to 99."""
    arrays = run_scenario("S1", DEFAULT_ESTIMATOR, POOL_SEEDS, doc)
    return [{"seeds": s, "n_eff": float(n)} for s, n in zip(POOL_SEEDS, arrays["n_eff"], strict=True)]


def build_pool_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="navkit gate n-eff-pool",
        description="The per-run effective sample sizes that the simulated properties of ADR-0030 draw from "
        "(the default candidate in S1, seeds 25 to 99). The seeds are fixed; no option takes one.",
    )
    ap.add_argument("--csv", type=Path, required=True, help="write seeds,n_eff here")
    ap.add_argument("--compare", type=Path, default=None, help="exit 1 if the pool differs from this committed CSV")
    return ap


def main_pool(argv: list[str] | None = None) -> int:
    args = build_pool_parser().parse_args(argv)
    rows = run_pool()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text(pool_csv_text(rows), encoding="utf-8")
    print(f"wrote {args.csv}", file=sys.stderr)
    if args.compare is not None:
        old = parse_pool_csv(args.compare.read_text(encoding="utf-8"))
        problems = [] if len(old) == len(rows) else [f"{len(rows)} rows against {len(old)}"]
        for a, b in zip(rows, old, strict=False):
            if a["seeds"] != b["seeds"] or not math.isclose(a["n_eff"], b["n_eff"], rel_tol=1e-6, abs_tol=1e-12):
                problems.append(f"seed {a['seeds']}: {a['n_eff']!r} against {b['n_eff']!r}")
        if problems:
            print(f"the pool differs from {args.compare}:", file=sys.stderr)
            for line in problems[:20]:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"the pool matches {args.compare}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
