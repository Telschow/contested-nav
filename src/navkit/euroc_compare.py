"""Compare filter settings across fetched EuRoC sequences, one GNSS outage at a time.

    navkit euroc compare --markdown
    navkit euroc compare --csv docs/data/euroc_compare.csv --page docs/euroc.md
    navkit euroc compare --sequence MH_01_easy --sequence V1_01_easy --starts 15,35 --seeds 2 \\
        --csv results/euroc_compare.csv --json results/euroc_compare.json

For every sequence found under the data root, every outage start that fits, every seed and every
configuration, this runs :func:`navkit.euroc_eval.run_sequence` once and records what happened. It
exists so that a statement such as "the preset loses fewer runs" can be regenerated and cited from a
file instead of typed. The data is not vendored (S2): fetch it first with ``navkit euroc fetch``.

What is counted. A run is **lost** when the filter rejects more than ``--lost-threshold`` (default a
fifth) of the GNSS fixes it sees. That is a measure of the outcome. The FDIR layer's "channel faulted"
flag is reported next to it and is not used for the count: some runs reject hundreds of fixes and are
never declared faulty, so the flag alone understates the failures (ADR-0014).

Configurations are fixed and named: ``default`` (the filter as shipped), ``preset`` (the
``adis16448`` preset of :mod:`navkit.euroc_eval`) and ``legacy`` (the earlier process-noise form).

Every record carries ``data_class: real_imu_simulated_gnss`` and the caveats of ADR-0013. GNSS is
simulated from the ground truth, so nothing here is GNSS-denied performance in the field. Results
quoted from this output must state the simulated GNSS, the preset, and the runs that still fail.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__
from .euroc_eval import (
    CAVEATS,
    DATA_CLASS,
    PRESETS,
    EurocSequence,
    RunOptions,
    SequenceError,
    dataset_loader,
    run_sequence,
)
from .io import tumvi_fetch
from .io.euroc_fetch import IMU_CSV, SEQUENCES, TRUTH_CSV

#: Named settings. Each maps to keyword arguments of :class:`RunOptions`.
CONFIGS: dict[str, dict[str, Any]] = {
    "default": {},
    "preset": {"preset": "adis16448", **PRESETS["adis16448"]},
    "legacy": {"process_noise": "legacy"},
    "walk10": {"preset": "adis16448-walk", **PRESETS["adis16448-walk"]},
}

#: TUM VI: ``file`` is the dataset's own figures (inflated by its authors: white noise x2, bias random walk
#: x10), ``allan`` the raw figures from their Allan plots, ``file-walk10`` the file's figures with the bias
#: walks multiplied by a further 10. All declare a bias prior, because the start bias is only estimated.
TUMVI_CONFIGS: dict[str, dict[str, Any]] = {
    "file": {"bias_sigma": 0.05},
    "allan": {"noise_source": "allan", "bias_sigma": 0.05},
    "file-walk10": {"bias_sigma": 0.05, "bias_walk_scale": 10.0},
}

DEFAULT_CONFIGS = ("default", "preset")
DEFAULT_TUMVI_CONFIGS = ("file", "allan")
_ALL_CONFIGS = {**CONFIGS, **TUMVI_CONFIGS}


def configs_for(dataset: str) -> dict[str, dict[str, Any]]:
    return TUMVI_CONFIGS if dataset == "tumvi" else CONFIGS


DEFAULT_STARTS = (15.0, 35.0, 60.0, 90.0)
DEFAULT_OUTAGE_S = 20.0
DEFAULT_LOST_THRESHOLD = 0.2

#: Seconds of GNSS that must remain after the outage, and unused at the end of the recording.
_TAIL_S = 5.0
_MARGIN_S = 2.0

CSV_COLUMNS = (
    "sequence",
    "group",
    "config",
    "start_s",
    "outage_s",
    "seed",
    "gnss_fixes_seen",
    "gnss_rejected",
    "rejected_fraction",
    "lost",
    "fdir_faulted",
    "nees_mean",
    "coverage_2sigma",
    "ate_rmse_m",
    "max_position_error_m",
)


class CompareError(ValueError):
    """The comparison cannot run as asked. The message says what to change."""


def group_of(sequence: str) -> str:
    """The recording environment, from the sequence name."""
    if sequence.startswith("MH_"):
        return "Machine Hall"
    if sequence.startswith(("V1_", "V2_")):
        return "Vicon room"
    if sequence.startswith("room"):
        return "TUM VI room"
    return "other"


def fetched_sequences(root: str | Path, dataset: str = "euroc") -> list[str]:
    """Known sequences whose IMU and ground-truth files are under ``root``, in dataset order."""
    base = Path(root)
    if dataset == "tumvi":
        names, imu, truth = tumvi_fetch.SEQUENCES, tumvi_fetch.IMU_CSV, tumvi_fetch.TRUTH_CSV
    else:
        names, imu, truth = tuple(SEQUENCES), IMU_CSV, TRUTH_CSV
    return [name for name in names if (base / name / imu).is_file() and (base / name / truth).is_file()]


def fitting_starts(duration_s: float, starts: tuple[float, ...], outage_s: float) -> list[float]:
    """Outage starts that leave GNSS time after the outage and some recording unused at the end."""
    return [s for s in starts if s + outage_s + _TAIL_S < duration_s - _MARGIN_S]


@dataclass
class Row:
    sequence: str
    config: str
    start_s: float
    outage_s: float
    seed: int
    gnss_fixes_seen: float
    gnss_rejected: float
    rejected_fraction: float
    lost: bool
    fdir_faulted: bool
    nees_mean: float
    coverage_2sigma: float
    ate_rmse_m: float
    max_position_error_m: float

    def as_dict(self) -> dict[str, Any]:
        out = {"group": group_of(self.sequence), **self.__dict__}
        return {k: out[k] for k in CSV_COLUMNS}


def run_one(seq: EurocSequence, config: str, start_s: float, outage_s: float, seed: int, threshold: float) -> Row:
    kwargs = dict(_ALL_CONFIGS[config])
    record = run_sequence(seq, RunOptions(seed=seed, outages=((start_s, outage_s),), **kwargs))
    stats = record["stats"]
    seen = float(stats["gnss_fixes_seen"])
    rejected = float(stats["gnss_updates_rejected"])
    fraction = rejected / seen if seen > 0 else 0.0
    errors = np.asarray(record["error_time_series"]["position_error_m"], dtype=float)
    head = record["headline"]
    return Row(
        sequence=seq.name,
        config=config,
        start_s=start_s,
        outage_s=outage_s,
        seed=seed,
        gnss_fixes_seen=seen,
        gnss_rejected=rejected,
        rejected_fraction=fraction,
        lost=fraction > threshold,
        fdir_faulted=float(stats.get("fdir_gnss_faulted", 0.0)) > 0.0,
        nees_mean=float(head["nees_mean"]),
        coverage_2sigma=float(head["coverage"]["2sigma"]),
        ate_rmse_m=float(head["ate_rmse_m"]),
        max_position_error_m=float(errors.max()),
    )


def compare(
    root: str | Path,
    sequences: list[str],
    configs: tuple[str, ...],
    starts: tuple[float, ...],
    outage_s: float,
    seeds: int,
    threshold: float,
    log: Any = None,
    first_seed: int = 0,
    dataset: str = "euroc",
) -> tuple[list[Row], dict[str, str]]:
    """Run every combination. Returns the rows and a ``{sequence: reason}`` map of what was skipped."""
    table = configs_for(dataset)
    unknown = [c for c in configs if c not in table]
    if unknown:
        raise CompareError(f"unknown configuration {unknown[0]!r} for {dataset}; known: {', '.join(table)}")
    if seeds < 1 or outage_s <= 0 or not 0.0 <= threshold < 1.0:
        raise CompareError("need --seeds >= 1, --outage > 0 and 0 <= --lost-threshold < 1")
    loader, _ = dataset_loader(dataset)
    rows: list[Row] = []
    skipped: dict[str, str] = {}
    for name in sequences:
        seq = loader(root, name)
        window = float(min(seq.imu.t[-1], seq.truth.t[-1]) - max(seq.imu.t[0], seq.truth.t[0]))
        usable = fitting_starts(window, starts, outage_s)
        if not usable:
            skipped[name] = f"no outage start fits in its {window:.0f} s window"
            continue
        for start in usable:
            for seed in range(first_seed, first_seed + seeds):
                for config in configs:
                    rows.append(run_one(seq, config, start, outage_s, seed, threshold))
        if log:
            log(f"{name}: {len(usable)} starts x {seeds} seeds x {len(configs)} configs")
    if not rows:
        raise CompareError("nothing ran: " + "; ".join(f"{k}: {v}" for k, v in skipped.items()))
    return rows, skipped


def _stats(sel: list[Row]) -> dict[str, float]:
    return {
        "runs": float(len(sel)),
        "lost": float(sum(r.lost for r in sel)),
        "faulted_flag": float(sum(r.fdir_faulted for r in sel)),
        "median_nees": float(np.median([r.nees_mean for r in sel])),
        "mean_coverage_2sigma": float(np.mean([r.coverage_2sigma for r in sel])),
        "median_max_error_m": float(np.median([r.max_position_error_m for r in sel])),
    }


def breakdown(rows: list[Row]) -> list[dict[str, Any]]:
    """Statistics for every (scope, config): all sequences, each group, each sequence."""
    configs = list(dict.fromkeys(r.config for r in rows))
    scopes: list[tuple[str, list[Row]]] = [("all", rows)]
    groups = list(dict.fromkeys(group_of(r.sequence) for r in rows))
    for g in groups if len(groups) > 1 else []:  # a lone environment would only repeat the "all" row
        scopes.append((g, [r for r in rows if group_of(r.sequence) == g]))
    for s in dict.fromkeys(r.sequence for r in rows):
        scopes.append((s, [r for r in rows if r.sequence == s]))
    out = []
    for scope, sel in scopes:
        for c in configs:
            part = [r for r in sel if r.config == c]
            if part:
                out.append({"scope": scope, "config": c, **_stats(part)})
    return out


def as_markdown(rows: list[Row], threshold: float) -> str:
    """A table from the rows. Every figure comes from the data; none is typed here."""
    lines = [
        f"Lost = more than {100 * threshold:g}% of GNSS fixes rejected. Flag = FDIR declared the channel faulty.",
        "",
        "| Scope | Config | Runs | Lost | Flag | Median NEES (expected 3) | Mean 2σ coverage | Median max error m |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for b in breakdown(rows):
        lines.append(
            f"| {b['scope']} | {b['config']} | {b['runs']:.0f} | {b['lost']:.0f} | {b['faulted_flag']:.0f} | "
            f"{b['median_nees']:.2f} | {100 * b['mean_coverage_2sigma']:.1f}% | {b['median_max_error_m']:.1f} |"
        )
    return "\n".join(lines)


def rows_from_csv(path: str | Path) -> list[Row]:
    """Read the per-run CSV written by ``--csv``. Used to check a page against the committed copy."""
    rows: list[Row] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            rows.append(
                Row(
                    sequence=rec["sequence"],
                    config=rec["config"],
                    start_s=float(rec["start_s"]),
                    outage_s=float(rec["outage_s"]),
                    seed=int(rec["seed"]),
                    gnss_fixes_seen=float(rec["gnss_fixes_seen"]),
                    gnss_rejected=float(rec["gnss_rejected"]),
                    rejected_fraction=float(rec["rejected_fraction"]),
                    lost=rec["lost"] == "True",
                    fdir_faulted=rec["fdir_faulted"] == "True",
                    nees_mean=float(rec["nees_mean"]),
                    coverage_2sigma=float(rec["coverage_2sigma"]),
                    ate_rmse_m=float(rec["ate_rmse_m"]),
                    max_position_error_m=float(rec["max_position_error_m"]),
                )
            )
    return rows


def failing_runs_markdown(rows: list[Row], config: str = "preset") -> str:
    """The runs of one configuration that were lost. Listing them is part of quoting the result."""
    lost = [r for r in rows if r.config == config and r.lost]
    if not lost:
        return f"No run was lost with `{config}`."
    lines = [
        f"Runs still lost with `{config}`:",
        "",
        "| Sequence | Outage start s | Seed | GNSS fixes rejected | Max position error m |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in lost:
        rejected = f"{100 * r.rejected_fraction:.0f}%"
        lines.append(f"| {r.sequence} | {r.start_s:g} | {r.seed} | {rejected} | {r.max_position_error_m:.1f} |")
    return "\n".join(lines)


def page_block(rows: list[Row], threshold: float) -> str:
    """What goes between the ``euroc`` markers of ``docs/euroc.md``."""
    configs = list(dict.fromkeys(r.config for r in rows))
    tail = [
        failing_runs_markdown(rows, c)
        for c in configs
        if c not in BASELINE_CONFIGS and any(r.lost for r in rows if r.config == c)
    ]
    return "\n\n".join([as_markdown(rows, threshold), *tail])


def validation_block(rows: list[Row], threshold: float) -> str:
    """The checks run after the settings were chosen: one line per outage length and configuration."""
    lines = [
        f"Lost = more than {100 * threshold:g}% of GNSS fixes rejected.",
        "",
        "| Outage s | Config | Runs | Lost | Median NEES (expected 3) | Mean 2σ coverage |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for length in sorted({r.outage_s for r in rows}):
        for c in dict.fromkeys(r.config for r in rows):
            sel = [r for r in rows if r.outage_s == length and r.config == c]
            if sel:
                s = _stats(sel)
                lines.append(
                    f"| {length:g} | {c} | {s['runs']:.0f} | {s['lost']:.0f} | {s['median_nees']:.2f} | "
                    f"{100 * s['mean_coverage_2sigma']:.1f}% |"
                )
    return "\n".join(lines)


PAGE_BLOCKS = ("euroc", "euroc-validation", "tumvi")
#: Configurations whose lost runs are counted in a table but not listed under it: the as-shipped baseline.
BASELINE_CONFIGS = ("default", "file")
PAGE_MARKERS = ("<!-- euroc:start -->", "<!-- euroc:end -->")


def markers(name: str) -> tuple[str, str]:
    return (f"<!-- {name}:start -->", f"<!-- {name}:end -->")


def write_page(path: str | Path, block: str, name: str = "euroc") -> None:
    """Replace the text between a block's markers. Refuses a page without them."""
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    start, end = markers(name)
    if start not in text or end not in text or text.index(start) > text.index(end):
        raise CompareError(f"{page} needs the lines {start} and {end}, in that order")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    page.write_text(f"{head}{start}\n\n{block}\n\n{end}{tail}", encoding="utf-8")


def provenance(root: str | Path, sequences: list[str]) -> dict[str, Any]:
    """The input hashes of every sequence used, read from the fetch manifest when it has them."""
    path = Path(root) / "MANIFEST.json"
    hashes: dict[str, Any] = {}
    if path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        for name in sequences:
            files = manifest.get("sequences", {}).get(name, {}).get("files", [])
            hashes[name] = {f["path"]: f["sha256"] for f in files}
    return {"manifest": str(path), "sha256": hashes}


def build_record(
    rows: list[Row],
    skipped: dict[str, str],
    root: str | Path,
    args: dict[str, Any],
    threshold: float,
    dataset: str = "euroc",
) -> dict[str, Any]:
    sequences = list(dict.fromkeys(r.sequence for r in rows))
    return {
        "claim_type": "MEASUREMENT",
        "data_class": DATA_CLASS,
        "caveats": list(CAVEATS),
        "navkit_version": __version__,
        "dataset": "TUM VI" if dataset == "tumvi" else "EuRoC MAV",
        "options": args,
        "lost_threshold": threshold,
        "configs": {name: _ALL_CONFIGS[name] for name in dict.fromkeys(r.config for r in rows)},
        "inputs": provenance(root, sequences),
        "skipped": skipped,
        "summary": breakdown(rows),
        "runs": [r.as_dict() for r in rows],
    }


def _floats(text: str) -> tuple[float, ...]:
    try:
        values = tuple(float(x) for x in text.split(",") if x.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected comma separated seconds, got {text!r}") from exc
    if not values:
        raise argparse.ArgumentTypeError("give at least one start time")
    return values


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit euroc compare",
        description=(
            "Run the filter with several settings on the fetched EuRoC sequences, one GNSS outage at a time, "
            "and count the runs that lose GNSS. GNSS is simulated from the ground truth."
        ),
    )
    p.add_argument("--dataset", choices=("euroc", "tumvi"), default="euroc", help="which dataset to compare on")
    p.add_argument(
        "--root", default=None, help="where the fetch command wrote the files (default: the dataset's folder)"
    )
    p.add_argument("--sequence", "-s", action="append", default=[], metavar="NAME", help="default: every fetched one")
    p.add_argument(
        "--configs",
        default=None,
        help=f"comma separated. EuRoC: {', '.join(CONFIGS)} (default {','.join(DEFAULT_CONFIGS)}). "
        f"TUM VI: {', '.join(TUMVI_CONFIGS)} (default {','.join(DEFAULT_TUMVI_CONFIGS)})",
    )
    p.add_argument("--starts", type=_floats, default=DEFAULT_STARTS, help="outage start times in s, comma separated")
    p.add_argument("--outage", type=float, default=DEFAULT_OUTAGE_S, help="outage length in s (default: %(default)s)")
    p.add_argument("--seeds", type=int, default=2, help="noise seeds per case (default: %(default)s)")
    p.add_argument("--first-seed", type=int, default=0, help="the seeds run are first-seed, first-seed + 1, ...")
    p.add_argument(
        "--lost-threshold",
        type=float,
        default=DEFAULT_LOST_THRESHOLD,
        help="fraction of GNSS fixes rejected above which a run counts as lost (default: %(default)s)",
    )
    p.add_argument("--from-csv", default=None, help="rebuild the table and page from a saved --csv file; no runs")
    p.add_argument("--csv", default=None, help="write one row per run")
    p.add_argument("--json", default=None, help="write the full record with provenance")
    p.add_argument("--page", default=None, help="fill a table between the markers of this Markdown page")
    p.add_argument(
        "--block",
        choices=PAGE_BLOCKS,
        default="euroc",
        help="which block --page fills: the main table, or the checks run after the settings were chosen",
    )
    p.add_argument("--markdown", action="store_true", help="print the summary table")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skipped: dict[str, str] = {}
    sequences: list[str] = []
    if args.from_csv:
        if args.json:
            print("error: --json needs a real run, not --from-csv", file=sys.stderr)
            return 1
        rows = rows_from_csv(args.from_csv)
        if not rows:
            print(f"error: {args.from_csv} has no rows", file=sys.stderr)
            return 1
        configs: tuple[str, ...] = ()
    else:
        _, default_root = dataset_loader(args.dataset)
        root = args.root or default_root
        sequences = args.sequence or fetched_sequences(root, args.dataset)
        if not sequences:
            hint = (
                "navkit tumvi fetch --sequence room1"
                if args.dataset == "tumvi"
                else "navkit euroc fetch --sequence MH_01_easy"
            )
            print(f"error: no sequences under {root}. Fetch some with: {hint}", file=sys.stderr)
            return 1
        defaults = DEFAULT_TUMVI_CONFIGS if args.dataset == "tumvi" else DEFAULT_CONFIGS
        configs = tuple(c.strip() for c in (args.configs or ",".join(defaults)).split(",") if c.strip())
        try:
            rows, skipped = compare(
                root,
                sequences,
                configs,
                args.starts,
                args.outage,
                args.seeds,
                args.lost_threshold,
                log=lambda m: print(m, file=sys.stderr, flush=True),
                first_seed=args.first_seed,
                dataset=args.dataset,
            )
        except (CompareError, SequenceError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    for name, reason in skipped.items():
        print(f"skipped {name}: {reason}", file=sys.stderr)
    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(r.as_dict() for r in rows)
        print(f"wrote {path}", file=sys.stderr)
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        options = {
            "sequences": sequences,
            "configs": list(configs),
            "starts_s": list(args.starts),
            "outage_s": args.outage,
            "seeds": args.seeds,
            "first_seed": args.first_seed,
        }
        path.write_text(
            json.dumps(build_record(rows, skipped, root, options, args.lost_threshold, args.dataset), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path}", file=sys.stderr)
    if args.page:
        try:
            build = validation_block if args.block == "euroc-validation" else page_block
            write_page(args.page, build(rows, args.lost_threshold), args.block)
        except CompareError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.page}", file=sys.stderr)
    if args.markdown or not (args.csv or args.json or args.page):
        print(as_markdown(rows, args.lost_threshold))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
