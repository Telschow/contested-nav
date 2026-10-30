"""The mismatch sweep as an ensemble over seeds, as rows and as a CSV.

Since ADR-0029 a single run's verdict uses the effective sample size, so five seeds and single-run verdicts cannot
resolve a mild mismatch (``docs/mismatch.md``). This module does for the mismatch sweep what :mod:`navkit.ensemble`
does for the benchmark cases. For each case and each factor on the filter's assumed noise it runs ``n_runs`` seeds
through the same :func:`navkit.benchmark.run_case` path as ``navkit sweep mismatch``, keeps the per-epoch NEES the
calibration report scores, and scores the ensemble with :func:`navkit.eval.calibration.ensemble_nees`.

    navkit sweep mismatch --ensemble-csv docs/data/mismatch_ensemble.csv --ensemble-page docs/mismatch.md

Each (case, factor) gives a ``full`` row over every epoch, and for a case with a GNSS outage an ``outage`` row over the
epochs inside the half-open outage windows. The statistics are the ones ``docs/calibration.md`` defines for the
ensemble: the grand mean and the shares of scored epochs inside, below and above the band for ``n_runs`` runs and the
case's degrees of freedom. This only adds output: it changes no verdict, no record and no existing number.
"""

from __future__ import annotations

import csv
import io
import itertools
import math
import sys
import time
from pathlib import Path
from typing import Any

from .benchmark import run_case
from .ensemble import Collector
from .report.page import splice_block

#: The ensemble runs the development seeds of ADR-0030, 25 to 49. The single-run sweep uses seeds 0 to 4, so the two
#: tables do not share a draw. The held-out seeds (100 and up) are never used here.
FIRST_SEED = 25
N_RUNS = 25

CSV_FIELDS = (
    "case",
    "factor",
    "scope",
    "n_runs",
    "dof",
    "epochs",
    "grand_mean",
    "band_low",
    "band_high",
    "fraction_inside",
    "fraction_below",
    "fraction_above",
)
_INT_FIELDS = {"n_runs", "dof", "epochs"}
_TEXT_FIELDS = {"case", "scope"}
#: Floats are compared to this relative tolerance across platforms (ADR-0009); integers and text must match exactly.
COMPARE_RTOL = 1e-6


def score_cell(case: str, factor: float, boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of one (case, factor): the ensemble over ``boxes``, one ``nees_out`` box per seed.

    A run with no covariance leaves its box empty and gives no row.
    """
    collector = Collector()
    for box in boxes:
        collector.add(case, box)
    rows = []
    for r in collector.rows():
        rows.append(
            {
                "case": r["case"],
                "factor": float(factor),
                "scope": r["scope"],
                "n_runs": r["n_runs"],
                "dof": r["dof"],
                "epochs": r["n_epochs"],
                "grand_mean": r["grand_mean"],
                "band_low": r["band_low"],
                "band_high": r["band_high"],
                "fraction_inside": r["fraction_inside"],
                "fraction_below": r["fraction_below"],
                "fraction_above": r["fraction_above"],
            }
        )
    return rows


def run_ensemble(
    cells: list[tuple[str, float, dict[str, Any]]],
    defaults: dict[str, Any],
    n_runs: int = N_RUNS,
    first_seed: int = FIRST_SEED,
) -> list[dict[str, Any]]:
    """Run each ``(name, factor, case)`` for seeds ``first_seed .. first_seed + n_runs - 1`` and score each cell.

    ``case`` is the case with the factor already applied (:func:`navkit.mismatch_sweep.with_scale`), so that the cell
    is the sweep's own and this module does not import the sweep.
    """
    rows: list[dict[str, Any]] = []
    for name, factor, case in cells:
        t0 = time.perf_counter()
        boxes = []
        for seed in range(first_seed, first_seed + n_runs):
            box: dict[str, Any] = {}
            run_case(name, case, defaults, seed=seed, nees_out=box)
            boxes.append(box)
        rows.extend(score_cell(name, factor, boxes))
        print(
            f"ensemble: {name} with assumed noise x{factor:g} over seeds {first_seed} to {first_seed + n_runs - 1} "
            f"({time.perf_counter() - t0:.1f} s)",
            file=sys.stderr,
            flush=True,
        )
    return rows


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
    return [
        {k: (raw[k] if k in _TEXT_FIELDS else int(raw[k]) if k in _INT_FIELDS else float(raw[k])) for k in CSV_FIELDS}
        for raw in csv.DictReader(io.StringIO(text))
    ]


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
                problems.append(f"{a['case']} x{a['factor']:g} {a['scope']} {key}: {x!r} against {y!r}")
    return problems


# -------------------------------------------------------------------------------------------------------- page

START, END = "<!-- mismatch-ensemble:start -->", "<!-- mismatch-ensemble:end -->"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    """The generated block of the mismatch page: the band, then one line per case, factor and scope."""
    if not rows:
        raise ValueError("no rows to tabulate")
    first = rows[0]
    lines = [
        f"Band for the ensemble mean over N = {first['n_runs']} runs with {first['dof']} degrees of freedom: "
        f"{first['band_low']:.3f} to {first['band_high']:.3f}. Shares are of the scored epochs.",
        "",
        "| Case | Assumed noise x | Scope | Scored epochs | Grand mean NEES | Inside the band | Below | Above |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['factor']:g} | {r['scope']} | {r['epochs']} | {r['grand_mean']:.4g} | "
            f"{100.0 * r['fraction_inside']:.1f}% | {100.0 * r['fraction_below']:.1f}% | "
            f"{100.0 * r['fraction_above']:.1f}% |"
        )
    return "\n".join(lines)


def splice_table(page: str, table: str) -> str:
    """``page`` with the text between the mismatch-ensemble markers replaced by ``table``."""
    return splice_block(page, "mismatch-ensemble", table)


# ------------------------------------------------------------------------------------------------------ sentences

#: The factors the page calls mild. They are my choice, like the 90% coverage band of the single-run sweep.
MILD = (0.8, 0.9, 1.25)
#: A mild factor is resolved by the ensemble when its mean is outside the band, on the side the mismatch predicts, for
#: more than this share of the scored epochs and for a larger share than at the true noise.
ENSEMBLE_MIN_SHARE = 0.5
#: It is resolved by one run when the bulk test reads the predicted way in at least this share of the seeds.
SINGLE_MIN_SHARE = 0.8


def bulk_count(verdicts: str, word: str) -> int:
    """How many seeds read ``word`` in the bulk, from the sweep CSV's ``name=count;name=count`` verdict string.

    A mixed verdict ``mixed(bulk=overconfident, tail=consistent)`` counts for its bulk word.
    """
    total = 0
    for item in verdicts.split(";"):
        name, count = item.rsplit("=", 1)
        bulk = name.split("bulk=", 1)[1].split(",", 1)[0].rstrip(")") if name.startswith("mixed(") else name
        if bulk == word:
            total += int(count)
    return total


def _predicted_share(row: dict[str, Any]) -> float:
    """The share of scored epochs outside the band on the side a wrong assumed noise predicts.

    Assumed noise below the truth gives a NEES above the band, assumed noise above it a NEES below.
    """
    return row["fraction_above"] if row["factor"] < 1.0 else row["fraction_below"]


def _by_scope(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[float, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[float, dict[str, Any]]] = {}
    for r in rows:
        out.setdefault((r["case"], r["scope"]), {})[r["factor"]] = r
    return out


def _ensemble_resolves(cell: dict[float, dict[str, Any]], factor: float) -> bool:
    share = _predicted_share(cell[factor])
    true_noise = cell.get(1.0)
    return share > ENSEMBLE_MIN_SHARE and (
        true_noise is None or share > _predicted_share({**true_noise, "factor": factor})
    )


def _single_resolves(row: dict[str, Any], factor: float) -> bool:
    word = "overconfident" if factor < 1.0 else "underconfident"
    return bulk_count(row["verdicts"], word) >= SINGLE_MIN_SHARE * row["n_seeds"]


def resolution(rows: list[dict[str, Any]], single_rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Which mild factors the ensemble and one run resolve, per case over the full run.

    ``both``, ``only_ensemble``, ``only_single`` and ``neither`` hold ``(case, factor)``. ``unresolved`` holds
    ``(case, scope, factor)`` for every scope the ensemble does not resolve, outage scope included.
    """
    singles = {(r["case"], r["scale"]): r for r in single_rows}
    out: dict[str, list[Any]] = {"both": [], "only_ensemble": [], "only_single": [], "neither": [], "unresolved": []}
    for (case, scope), cell in _by_scope(rows).items():
        for factor in (f for f in MILD if f in cell):
            ens = _ensemble_resolves(cell, factor)
            if not ens:
                out["unresolved"].append((case, scope, factor))
            if scope == "full" and (case, factor) in singles:
                one = _single_resolves(singles[(case, factor)], factor)
                key = ("both" if one else "only_ensemble") if ens else ("only_single" if one else "neither")
                out[key].append((case, factor))
    return out


def _pct(x: float) -> str:
    return f"{100.0 * x:.1f}%"


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _g(factors: list[float]) -> str:
    return _list([f"{f:g}" for f in factors])


def _direction(label: str, cell: dict[float, dict[str, Any]], below: bool) -> str | None:
    """One sentence for the factors below 1 (``below``) or above 1: the shares outside the band, predicted side."""
    factors = sorted(f for f in cell if (f < 1.0 if below else f > 1.0))
    if not factors:
        return None
    shares = [_predicted_share(cell[f]) for f in factors]
    side, where = ("above", "below") if below else ("below", "above")
    text = (
        f"{label}: with the assumed noise {where} the true noise, the ensemble mean is {side} the band for "
        f"{_list([_pct(x) for x in shares])} of the scored epochs at factors {_g(factors)}"
    )
    if len(shares) > 1:
        # The mismatch grows away from 1, so a share that grows with the size is non-decreasing in that order.
        by_size = shares[::-1] if below else shares
        if len(set(by_size)) == 1:
            text += ", a share that is level"
        elif all(a <= b for a, b in itertools.pairwise(by_size)):
            text += ", a share that rises or stays level as the mismatch grows"
        else:
            text += ", a share that does not keep rising as the mismatch grows"
    return text + "."


def findings(rows: list[dict[str, Any]], single_rows: list[dict[str, Any]]) -> list[str]:
    """The sentences of the page, each derived from the CSV rows and the single-run rows."""
    out: list[str] = []
    cells = _by_scope(rows)
    for (case, scope), cell in cells.items():
        label = case if scope == "full" else f"{case} ({scope} scope)"
        for below in (True, False):
            sentence = _direction(label, cell, below)
            if sentence:
                out.append(sentence)
        r = cell.get(1.0)
        if r is not None:
            text = (
                f"{label}: at the true noise (factor 1) the ensemble mean is inside the band for "
                f"{_pct(r['fraction_inside'])} of the scored epochs, below it for {_pct(r['fraction_below'])} and "
                f"above it for {_pct(r['fraction_above'])}."
            )
            if r["fraction_inside"] < 0.5:
                text += (
                    " That is not inside the band for most epochs, so for this case read the factors against each "
                    "other, not against the band."
                )
            out.append(text)
        mild = [f for f in MILD if f in cell]
        if mild:
            yes = [f for f in mild if _ensemble_resolves(cell, f)]
            no = [f for f in mild if f not in yes]
            if not yes:
                verdict = "the ensemble resolves none of them"
            elif not no:
                verdict = "the ensemble resolves all of them"
            else:
                verdict = f"the ensemble resolves {_g(yes)} and not {_g(no)}"
            out.append(f"{label}: of the mild factors {_g(mild)}, {verdict}.")
    got = resolution(rows, single_rows)
    for case in dict.fromkeys(c for c, _ in cells):
        parts = []
        for key, phrase in (
            ("both", "both resolve"),
            ("only_ensemble", "only the ensemble resolves"),
            ("only_single", "only one run resolves"),
            ("neither", "neither resolves"),
        ):
            factors = [f for c, f in got[key] if c == case]
            if factors:
                parts.append(f"{phrase} {_g(sorted(factors))}")
        if parts:
            out.append(f"Against the single-run table, {case}, mild factors: {'; '.join(parts)}.")
    if got["only_ensemble"]:
        out.append(
            "The ensemble resolves some mild mismatch that one run does not: "
            + "; ".join(_per_case([(c, "full", f) for c, f in got["only_ensemble"]]))
            + "."
        )
    if got["only_single"]:
        out.append(
            "One run resolves some mild mismatch that the ensemble does not: "
            + "; ".join(_per_case([(c, "full", f) for c, f in got["only_single"]]))
            + "."
        )
    if got["unresolved"]:
        out.append(
            "The ensemble does not resolve every mild mismatch: " + "; ".join(_per_case(got["unresolved"])) + "."
        )
    return out


def _per_case(items: list[tuple[str, str, float]]) -> list[str]:
    """``case at 0.8 and 0.9`` per case and scope, in the order first seen."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for case, scope, factor in items:
        grouped.setdefault((case, scope), []).append(factor)
    return [
        f"{case if scope == 'full' else f'{case} ({scope} scope)'} at {_g(sorted(factors))}"
        for (case, scope), factors in grouped.items()
    ]


def rules_text(single_rows: list[dict[str, Any]]) -> str:
    seeds = max((r["n_seeds"] for r in single_rows), default=0)
    need = math.ceil(SINGLE_MIN_SHARE * seeds)
    return (
        f"My rule for resolved, which is a choice and not a test: the mild factors are {_g(list(MILD))}. The ensemble "
        f"resolves one when its mean is outside the band, on the side the mismatch predicts, for more than "
        f"{_pct(ENSEMBLE_MIN_SHARE)} of the scored epochs and for a larger share than at the true noise. One run "
        f"resolves it when its bulk test reads the predicted way in at least {need} of {seeds} seeds."
    )


def page_block(rows: list[dict[str, Any]], single_rows: list[dict[str, Any]]) -> str:
    """The generated block of the mismatch page: the table, the rule for resolved, then one bullet per sentence."""
    parts = [markdown_table(rows)]
    sentences = findings(rows, single_rows)
    if sentences:
        parts += [rules_text(single_rows), "\n".join(f"- {line}" for line in sentences)]
    return "\n\n".join(parts)


def write_outputs(
    rows: list[dict[str, Any]], single_rows: list[dict[str, Any]], csv_path: Path, page_path: Path | None
) -> None:
    """Write the CSV and, when given, the table between the markers of the page."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(csv_text(rows), encoding="utf-8")
    print(f"wrote {csv_path}", file=sys.stderr)
    if page_path is not None:
        page = page_path.read_text(encoding="utf-8")
        page_path.write_text(splice_table(page, page_block(rows, single_rows)), encoding="utf-8")
        print(f"wrote the ensemble table into {page_path}", file=sys.stderr)
