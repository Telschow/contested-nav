"""How much do the development-seed numbers move when GNSS and visual noise stop sharing a stream? (issue #259)

    navkit sweep shared-stream --csv docs/data/shared_stream_effect.csv --page docs/calibration.md

This is a measurement on development seeds, synthetic. It decides nothing. Whether to change the streams, and what
ADR-0010 says about it, stay with the maintainer in issue #251. No default seeding, table or golden is touched.

At equal seeds the GNSS noise and the visual rotation noise both start from ``np.random.default_rng(seed)``, so they are
one normal sequence (audit finding CN-01). The benchmark sets both seeds to the case seed. This study runs four cases of
``configs/benchmark.yaml`` on the development seeds 0 to 9 twice:

* ``shared``: as :func:`navkit.benchmark.run_case` does it, both seeds are the case seed.
* ``independent``: the GNSS seed stays the case seed and the vision seed is drawn from
  ``np.random.SeedSequence([seed, VISION_STREAM])``. The study sets ``scenario.vision.seed`` itself, through the case
  block, so ``sensors/models.py`` and the default path are unchanged.

The file has one row per (case, seed): ATE RMSE (alignment none), mean NEES, 2-sigma coverage and the number of FDIR
events, under both seedings, and their difference (independent minus shared). The single-anchor overconfident case
``outage_visual`` is among the cases, and so is ``outage_control``, which has no vision.

A side effect of the method: :func:`navkit.degrade.inject._derive_seed` hashes both the GNSS and the vision seed, so
changing the vision seed also changes the IMU noise draw of every case, ``outage_control`` included. The difference
``independent`` minus ``shared`` is therefore the effect of the new vision seed on the vision noise and on the IMU
noise together. It is not the effect of the vision rotation noise alone.

``streams_only`` separates the two (post-remediation audit, CN-AUD-01). It uses the seeds of ``independent`` and, for
the duration of one run, pins the IMU noise draws to the ones ``shared`` has, by answering the two IMU channels of
``_derive_seed`` with the hash of the shared seeds. Nothing in ``src/navkit/degrade`` changes, and the pin is
undone after the run. Then:

* ``streams_only`` minus ``shared`` is the effect of the GNSS/vision stream relationship alone, with the IMU fixed;
* ``independent`` minus ``streams_only`` is the effect of redrawing the IMU alone.

On ``outage_control``, which has no vision, ``streams_only`` equals ``shared`` exactly: a known answer the tests check.

Seeds from 100 are refused through :func:`navkit.seed_policy.require_development`. The output is deterministic.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import importlib
import io
import math
import statistics
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import yaml

from . import seed_policy
from .b1_gate import parse_seeds
from .benchmark import default_config_path, run_case
from .ensemble import COMPARE_RTOL
from .report.runner import Flags, Study
from .report.runner import build_parser as runner_parser
from .report.runner import run_study as runner_run_study
from .report.table import Column, Table

CASES = ("outage_visual", "vision_only", "outage_visual_clone", "outage_control")
SINGLE_ANCHOR = "outage_visual"
SEEDINGS = ("shared", "independent")
#: ``independent``'s seeds with the IMU noise pinned to the ``shared`` draw. The third column, not in ``SEEDINGS``.
STREAMS_ONLY = "streams_only"
#: ``navkit.degrade`` re-exports a function named ``inject``, so ``from .degrade import inject`` gives the function.
inject: Any = importlib.import_module("navkit.degrade.inject")
IMU_CHANNELS = ("imu", "imu_bias0")
DEFAULT_SEEDS = range(0, 10)
#: The second entry of the ``SeedSequence`` that gives the vision stream its own seed. After 1013 and 1014 in models.py.
VISION_STREAM = 1015
METRICS = ("ate_rmse_m", "nees_mean", "coverage_2sigma", "fdir_events")
LABELS = {
    "ate_rmse_m": "ATE RMSE",
    "nees_mean": "mean NEES",
    "coverage_2sigma": "2-sigma coverage",
    "fdir_events": "FDIR events",
}
#: The first fourteen columns are the ones of the original study, unchanged. The ``streams_only`` ones follow.
CSV_FIELDS = (
    "case",
    "seed",
    *(f"{m}_{s}" for m in METRICS for s in ("shared", "independent", "diff")),
    *(f"{m}_{s}" for m in METRICS for s in (STREAMS_ONLY, "diff_streams")),
)
TABLE = Table(
    (Column("case"), Column("seed", int), *(Column(f, float) for f in CSV_FIELDS[2:])),
    key="case",
)
START, END = "<!-- shared-stream:start -->", "<!-- shared-stream:end -->"
LABEL = "development seeds, synthetic"


def stream_seeds(seed: int, seeding: str) -> tuple[int, int]:
    """The (GNSS, vision) seeds for a case seed. ``shared`` is what the benchmark does."""
    if seeding == "shared":
        return seed, seed
    if seeding in ("independent", STREAMS_ONLY):
        vision = int(np.random.SeedSequence([seed, VISION_STREAM]).generate_state(1)[0])
        return seed, vision
    raise ValueError(f"seeding must be one of {', '.join((*SEEDINGS, STREAMS_ONLY))}, got {seeding!r}")


def _metrics(rec: dict[str, Any]) -> dict[str, float]:
    head = rec["headline"]
    return {
        "ate_rmse_m": float(head["ate_rmse_m"]),
        "nees_mean": float(head["nees_mean"]),
        "coverage_2sigma": float(head["coverage"]["2sigma"]),
        "fdir_events": float(rec["stats"].get("fdir_events", 0.0)),
    }


@contextlib.contextmanager
def imu_pinned_to_shared(seed: int) -> Iterator[None]:
    """Answer the IMU channels of ``_derive_seed`` as if the GNSS and vision seeds were both ``seed``, then undo it."""
    original = inject._derive_seed

    def pinned(scenario: Any, channel: str) -> int:
        if channel in IMU_CHANNELS:
            scenario = SimpleNamespace(
                name=scenario.name, gnss=SimpleNamespace(seed=seed), vision=SimpleNamespace(seed=seed)
            )
        return original(scenario, channel)

    inject._derive_seed = pinned
    try:
        yield
    finally:
        inject._derive_seed = original


def _run_one(name: str, case: dict[str, Any], defaults: dict[str, Any], seed: int, seeding: str) -> dict[str, float]:
    if seeding == STREAMS_ONLY:
        with imu_pinned_to_shared(seed):
            return _run_one(name, case, defaults, seed, "independent")
    if seeding == "shared":
        return _metrics(run_case(name, copy.deepcopy(case), defaults, seed=seed))
    gnss, vision = stream_seeds(seed, seeding)
    block = copy.deepcopy(case)
    sc = block["scenario"]
    sc.setdefault("gnss", {})["seed"] = gnss
    if "vision" in sc:
        sc["vision"]["seed"] = vision
    if "camera_drop" in sc:
        sc["camera_drop"]["seed"] = seed
    return _metrics(run_case(name, block, defaults, seed=None))


def run_study(doc: dict[str, Any], seeds: list[int] | None = None) -> list[dict[str, Any]]:
    """One row per (case, seed), in a fixed order."""
    use = list(DEFAULT_SEEDS) if seeds is None else list(seeds)
    seed_policy.require_development(use)
    defaults, cases = doc.get("defaults", {}), doc.get("cases", {})
    rows: list[dict[str, Any]] = []
    for name in CASES:
        for seed in use:
            by = {s: _run_one(name, cases[name], defaults, seed, s) for s in (*SEEDINGS, STREAMS_ONLY)}
            row: dict[str, Any] = {"case": name, "seed": seed}
            for m in METRICS:
                row[f"{m}_shared"] = by["shared"][m]
                row[f"{m}_independent"] = by["independent"][m]
                row[f"{m}_diff"] = by["independent"][m] - by["shared"][m]
                row[f"{m}_{STREAMS_ONLY}"] = by[STREAMS_ONLY][m]
                row[f"{m}_diff_streams"] = by[STREAMS_ONLY][m] - by["shared"][m]
            rows.append(row)
    return rows


def csv_text(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for r in rows:
        writer.writerow([r["case"], r["seed"], *(repr(r[f]) for f in CSV_FIELDS[2:])])
    return buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, Any]]:
    return [
        {"case": r["case"], "seed": int(r["seed"]), **{f: float(r[f]) for f in CSV_FIELDS[2:]}}
        for r in csv.DictReader(io.StringIO(text))
    ]


def compare(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> list[str]:
    """Differences between two row lists: text and seeds exactly, floats to the relative tolerance of ADR-0009."""
    if len(new) != len(old):
        return [f"{len(new)} rows against {len(old)}"]
    problems: list[str] = []
    for a, b in zip(new, old, strict=True):
        for key in CSV_FIELDS:
            x, y = a[key], b[key]
            same = x == y if key in ("case", "seed") else math.isclose(x, y, rel_tol=COMPARE_RTOL, abs_tol=1e-12)
            if not same:
                problems.append(f"{a['case']} seed {a['seed']} {key}: {x!r} against {y!r}")
    return problems


def median_of(rows: list[dict[str, Any]], case: str, field: str) -> float:
    return statistics.median(r[field] for r in rows if r["case"] == case)


def largest_change(rows: list[dict[str, Any]], seeding: str = "independent") -> tuple[str, str, float]:
    """The (case, metric, relative change of the median against ``shared``) with the largest absolute change."""
    best = ("", "", 0.0)
    for case in CASES:
        for m in ("ate_rmse_m", "nees_mean"):
            base = median_of(rows, case, f"{m}_shared")
            rel = (median_of(rows, case, f"{m}_{seeding}") - base) / base
            if abs(rel) > abs(best[2]):
                best = (case, m, rel)
    return best


def _fmt(m: str, v: float) -> str:
    if m == "ate_rmse_m":
        return f"{v:.2f} m"
    if m == "coverage_2sigma":
        return f"{v:.3f}"
    return f"{v:.1f}"


def _change_sentence(rows: list[dict[str, Any]], seeding: str, what: str) -> str:
    case, metric, rel = largest_change(rows, seeding)
    return (
        f"With {what}, the largest change of a median against the shared stream is in `{case}`, {LABELS[metric]}: "
        f"{abs(rel) * 100:.1f} percent {'lower' if rel < 0 else 'higher'}."
    )


def markdown_section(rows: list[dict[str, Any]]) -> str:
    """The generated section of ``docs/calibration.md``: a table and two sentences, all from the rows."""
    n = len({r["seed"] for r in rows})
    columns = (*SEEDINGS, STREAMS_ONLY)
    lines = [
        f"**What the shared noise stream changes ({LABEL}; MEASUREMENT).** At equal seeds the GNSS noise and the "
        "visual rotation noise are one normal sequence. Each case below was run over "
        f"{n} seeds three times: with that shared stream; with the vision seed derived from the case seed and a "
        "stream id (independent), which also redraws the IMU noise, because the IMU seed is hashed from both seeds; "
        "and with the same independent seeds but the IMU noise pinned to its shared draw (streams only). The table "
        "gives the median over the seeds. This measures the difference and decides nothing.",
        "",
        "| Case | Metric | Shared | Independent | Streams only (IMU fixed) |",
        "|---|---|---:|---:|---:|",
    ]
    for c in CASES:
        for m in METRICS:
            a, b, d = (median_of(rows, c, f"{m}_{s}") for s in columns)
            lines.append(f"| `{c}` | {LABELS[m]} | {_fmt(m, a)} | {_fmt(m, b)} | {_fmt(m, d)} |")
    lines += [
        "",
        _change_sentence(rows, STREAMS_ONLY, "only the stream relationship changed (IMU fixed)")
        + " "
        + _change_sentence(rows, "independent", "the streams and the IMU draw both changed"),
        "The no-vision control `outage_control` has no vision stream, so its streams-only column equals the shared "
        "one. The single-anchor control `outage_visual` is in the table. The medians are over "
        f"{n} development seeds of {len(CASES)} cases, not a test of significance.",
        "",
        "The rows are in `docs/data/shared_stream_effect.csv`, written by `navkit sweep shared-stream`, and the "
        "page section is checked against them by `tests/test_shared_stream_effect.py`.",
    ]
    return "\n".join(lines)


def _add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the packaged benchmark.yaml)")
    ap.add_argument("--csv", type=Path, required=True, help="write the rows here")
    ap.add_argument("--seeds", default="0-9", help="development seeds, A-B or a comma list; from 100 are refused")


def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    try:
        seeds = parse_seeds(args.seeds)
        seed_policy.require_development(seeds)
    except ValueError as exc:
        build_parser().error(str(exc))
    doc = yaml.safe_load((args.config or default_config_path()).read_text()) or {}
    return run_study(doc, seeds)


STUDY = Study(
    table=TABLE,
    run_args=_run,
    render=markdown_section,
    page_name="shared-stream",
    flags=Flags(page=True, compare=True),
    add_arguments=_add_arguments,
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    help={
        "page": "also write the section between the markers of this page",
        "compare": "exit 1 if the rows differ from this committed CSV",
    },
    compare_rows=compare,
)


def build_parser() -> argparse.ArgumentParser:
    return runner_parser(STUDY)


def main(argv: list[str] | None = None) -> int:
    return runner_run_study(STUDY, argv)
