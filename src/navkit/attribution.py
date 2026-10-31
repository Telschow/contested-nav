"""Where the error of a GNSS outage comes from, tested by removing and inflating one source at a time.

    navkit sweep attribution --csv docs/data/attribution.csv --page docs/attribution.md

The repository's mechanism library says the outage error "accumulates from accelerometer bias and unmodelled
dynamics", and gives two tests: run the outage with the bias removed and see whether the peak drift changes, and
look at how the error grows with the length of the outage. This runs those tests, on the ``outage_control`` case
(GNSS lost from 5 s, no vision), and one more that the limitations list asks for: a bias fault, to see whether
anything notices it.

Three experiments, all on the synthetic fixture and all reporting the **peak position error inside the outage**:

* **Ablation and escalation.** Remove each inertial error source (accelerometer bias, gyroscope bias, each white
  noise), all of them together, or make the filter's starting state exact; and scale each source up. The generator
  and the filter are told the same noise, so this removes a source from the data and from the filter's model alone.
* **Growth with outage length.** The peak error against the outage duration, and the exponent of the power law fitted
  to it. Textbook errors grow as a known power of time: a constant accelerometer bias as ``t^2``, a constant
  gyroscope bias as ``t^3`` (through gravity), accelerometer white noise as ``t^1.5``, gyroscope white noise as
  ``t^2.5``, and an error in the velocity at the outage's start as ``t``.
* **A bias fault.** A step in the accelerometer bias at the outage's start, of several sizes: does the peak error
  change, is the healthy GNSS receiver rejected when it returns, and where is the error a few seconds later?

The metric is the peak *inside* the outage. The error at the outage's last instant is not: the first fix after the
outage collapses it, so it measures the recovery and not the denial.

Recovery is measured over a window, not at one instant: the median and the maximum of the position error from 2 s to
6 s after the outage ends (``recovery_median_m``, ``recovery_max_m``). The single value 4 s after the end
(``error_after_return_m``) is kept as the legacy column. It moves a lot when a recovery happens a little earlier or
later, with no change in where the run ends up.
"""

from __future__ import annotations

import argparse
import copy
import csv
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .benchmark import default_config_path, run_case
from .io.imu import DEFAULT_NOISE
from .report.runner import Flags, Study, run_study
from .report.runner import build_parser as runner_parser
from .report.table import Column, Table
from .types import ImuSample

CASE = "outage_control"
OUTAGE_START_S = 5.0
OUTAGE_S = 15.0

CSV_COLUMNS = (
    "experiment",
    "arm",
    "param",
    "seed",
    "peak_error_m",
    "gnss_rejected",
    "gnss_faulted",
    "error_after_return_m",
    "recovery_median_m",
    "recovery_max_m",
)

_BASE = DEFAULT_NOISE.as_dict()
SOURCES: dict[str, tuple[str, ...]] = {
    "accelerometer bias": ("accel_bias_sigma", "accel_bias_rw"),
    "gyroscope bias": ("gyro_bias_sigma", "gyro_bias_rw"),
    "accelerometer white noise": ("accel_noise_density",),
    "gyroscope white noise": ("gyro_noise_density",),
}
ALL_IMU_KEYS = tuple(k for keys in SOURCES.values() for k in keys)
START_KNOWN = {"initial_pos_sigma_m": 0.0, "initial_vel_sigma_m_s": 0.0, "initial_rot_sigma_deg": 0.0}

#: The recovery window, in seconds after the outage ends: half-open, [2, 6). It has the same 4 s centre as the legacy
#: single instant.
RECOVERY_WINDOW_S = (2.0, 6.0)
#: The fewest epochs the window may hold. The benchmark's series has 200 epochs a second, so a full window holds
#: 800. Ten is far below that and is the least for which a median and a maximum are more than a single reading: it
#: stops only a series that ends inside the window or is sampled far too sparsely, which would otherwise quietly
#: fall back to the single instant this window replaces.
RECOVERY_MIN_EPOCHS = 10

ESCALATION_SCALES = (3.0, 10.0, 30.0, 100.0)
#: The scale at which each source is inflated for the growth test. Chosen to make that source clearly the largest.
GROWTH_ARMS: dict[str, dict[str, float]] = {
    "baseline": {},
    "no inertial errors": dict.fromkeys(ALL_IMU_KEYS, 0.0),
    "accelerometer bias x100": dict.fromkeys(SOURCES["accelerometer bias"], 100.0),
    "gyroscope bias x300": dict.fromkeys(SOURCES["gyroscope bias"], 300.0),
    "accelerometer white noise x100": dict.fromkeys(SOURCES["accelerometer white noise"], 100.0),
    "gyroscope white noise x30": dict.fromkeys(SOURCES["gyroscope white noise"], 30.0),
}
GROWTH_DURATIONS_S = (5.0, 15.0, 45.0, 90.0)
GROWTH_SCALE = 4  # a fixture four times as long (120 s), with the same motion
FAULT_SIZES = (0.0, 0.05, 0.2, 1.0)  # m/s^2

#: Exponent of the textbook power law for each source, for the page. The first two are not sources of error in the
#: inertial unit but errors in the state the filter has when GNSS is lost.
THEORY = {
    "velocity error at the start": 1.0,
    "accelerometer white noise": 1.5,
    "accelerometer bias": 2.0,
    "attitude error at the start": 2.0,
    "gyroscope white noise": 2.5,
    "gyroscope bias": 3.0,
}


def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = yaml.safe_load(default_config_path().read_text(encoding="utf-8"))
    return cfg["defaults"], cfg["cases"]


def _longer(defaults: dict[str, Any], factor: int) -> dict[str, Any]:
    """The defaults with a fixture ``factor`` times as long and the same motion (cycle counts scale with it)."""
    out = copy.deepcopy(defaults)
    s = out["synthetic"]
    s.update(
        duration_s=s["duration_s"] * factor,
        circles=s["circles"] * factor,
        sway_cycles=s["sway_cycles"] * factor,
        yaw_cycles=s["yaw_cycles"] * factor,
    )
    return out


def recovery_window(t: np.ndarray, outage_end_s: float) -> np.ndarray:
    """The epochs with ``end + 2 <= t < end + 6``: a boolean mask over ``t``."""
    lo, hi = RECOVERY_WINDOW_S
    return (t >= outage_end_s + lo) & (t < outage_end_s + hi)


def recovery_stats(
    t: np.ndarray, err: np.ndarray, outage_end_s: float, min_epochs: int = RECOVERY_MIN_EPOCHS
) -> tuple[float, float]:
    """The median and the maximum of ``err`` over the recovery window. Raises ``ValueError`` on too few epochs."""
    window = err[recovery_window(t, outage_end_s)]
    if len(window) < min_epochs:
        lo, hi = RECOVERY_WINDOW_S
        raise ValueError(
            f"the recovery window [{outage_end_s + lo:g}, {outage_end_s + hi:g}) s holds {len(window)} epochs, "
            f"fewer than the minimum of {min_epochs}"
        )
    return float(np.median(window)), float(window.max())


def run_arm(
    seed: int,
    *,
    outage_s: float = OUTAGE_S,
    noise_scale: dict[str, float] | None = None,
    gnss_sigma_m: float | None = None,
    estimator: dict[str, float] | None = None,
    imu_hook: Callable[[ImuSample], ImuSample] | None = None,
    fixture_factor: int = 1,
) -> dict[str, float]:
    """One run of the outage case with the changes given. Returns the figures the experiments report."""
    defaults, cases = _load()
    case = copy.deepcopy(cases[CASE])
    noise = dict(_BASE)
    for key, factor in (noise_scale or {}).items():
        noise[key] = _BASE[key] * factor
    case["scenario"]["imu_noise"] = noise
    case["scenario"]["gnss_outages"] = [
        {"start_s": OUTAGE_START_S, "duration_s": float(outage_s), "reason": "contested"}
    ]
    if gnss_sigma_m is not None:
        case["scenario"]["gnss"]["sigma_m"] = gnss_sigma_m
    case.setdefault("estimator", {}).update(estimator or {})
    record = run_case(
        CASE, case, _longer(defaults, fixture_factor) if fixture_factor != 1 else defaults, seed=seed, imu_hook=imu_hook
    )
    ts = record["error_time_series"]
    t, e = np.asarray(ts["t"]), np.asarray(ts["position_error_m"])
    end = OUTAGE_START_S + outage_s
    inside = (t >= OUTAGE_START_S) & (t < end)
    after = float(e[min(int(np.searchsorted(t, end + 4.0)), len(e) - 1)])
    median, window_max = recovery_stats(t, e, end)
    stats = record["stats"]
    return {
        "peak_error_m": float(e[inside].max()),
        "gnss_rejected": float(stats["gnss_updates_rejected"]),
        "gnss_faulted": float(stats.get("fdir_gnss_faulted", 0.0)),
        "error_after_return_m": after,
        "recovery_median_m": median,
        "recovery_max_m": window_max,
    }


def bias_step_hook(size: float) -> Callable[[ImuSample], ImuSample]:
    """An accelerometer bias of ``size`` m/s^2 on the x axis from the start of the outage."""

    def hook(imu: ImuSample) -> ImuSample:
        accel = imu.accel.copy()
        accel[imu.t >= OUTAGE_START_S, 0] += size
        return ImuSample(
            t=imu.t, accel=accel, gyro=imu.gyro, accel_cov=imu.accel_cov, gyro_cov=imu.gyro_cov, name=imu.name
        )

    return hook


def _row(experiment: str, arm: str, param: float | str, seed: int, out: dict[str, float]) -> dict[str, Any]:
    return {"experiment": experiment, "arm": arm, "param": param, "seed": seed, **out}


def ablation_rows(seeds: int) -> list[dict[str, Any]]:
    arms: dict[str, dict[str, Any]] = {"baseline": {}}
    for name, keys in SOURCES.items():
        arms[f"no {name}"] = {"noise_scale": dict.fromkeys(keys, 0.0)}
    arms["no inertial errors"] = {"noise_scale": dict.fromkeys(ALL_IMU_KEYS, 0.0)}
    arms["start known exactly"] = {"estimator": START_KNOWN}
    arms["start known exactly, no inertial errors"] = {
        "estimator": START_KNOWN,
        "noise_scale": dict.fromkeys(ALL_IMU_KEYS, 0.0),
    }
    arms["GNSS noise x0.5"] = {"gnss_sigma_m": 0.4}
    arms["GNSS noise x0.1"] = {"gnss_sigma_m": 0.08}
    return [_row("ablation", name, "", s, run_arm(s, **kw)) for name, kw in arms.items() for s in range(seeds)]


def escalation_rows(seeds: int) -> list[dict[str, Any]]:
    return [
        _row("escalation", name, scale, s, run_arm(s, noise_scale=dict.fromkeys(keys, scale)))
        for name, keys in SOURCES.items()
        for scale in ESCALATION_SCALES
        for s in range(seeds)
    ]


def growth_rows(
    seeds: int,
    durations: tuple[float, ...] = GROWTH_DURATIONS_S,
    arms: tuple[str, ...] | None = None,
    scale: int = GROWTH_SCALE,
) -> list[dict[str, Any]]:
    chosen = {k: v for k, v in GROWTH_ARMS.items() if arms is None or k in arms}
    return [
        _row("growth", name, d, s, run_arm(s, outage_s=d, noise_scale=mult or None, fixture_factor=scale))
        for name, mult in chosen.items()
        for d in durations
        for s in range(seeds)
    ]


def fault_rows(seeds: int, sizes: tuple[float, ...] = FAULT_SIZES) -> list[dict[str, Any]]:
    return [
        _row("fault", "accelerometer bias step", size, s, run_arm(s, imu_hook=bias_step_hook(size) if size else None))
        for size in sizes
        for s in range(seeds)
    ]


# ------------------------------------------------------------------ summaries


def _mean(rows: list[dict[str, Any]], experiment: str, arm: str, param: Any = "", field: str = "peak_error_m") -> float:
    sel = [
        float(r[field])
        for r in rows
        if r["experiment"] == experiment and r["arm"] == arm and str(r["param"]) == str(param)
    ]
    if not sel:
        raise KeyError((experiment, arm, param))
    return float(np.mean(sel))


def exponent(rows: list[dict[str, Any]], arm: str) -> float:
    """The slope of log(peak error) against log(outage length) for one growth arm."""
    durations = sorted({float(r["param"]) for r in rows if r["experiment"] == "growth" and r["arm"] == arm})
    peaks = [_mean(rows, "growth", arm, d) for d in durations]
    return float(np.polyfit(np.log(durations), np.log(peaks), 1)[0])


def _pct(ratio: float) -> str:
    """A change as a signed whole percent, with a zero written as 0 and not -0."""
    return f"{int(round(100 * (ratio - 1))):+d}%"


def ablation_markdown(rows: list[dict[str, Any]]) -> str:
    base = _mean(rows, "ablation", "baseline")
    lines = [
        "| What changes | Peak error inside the outage, m | Change from baseline |",
        "|---|---:|---:|",
    ]
    arms = list(dict.fromkeys(r["arm"] for r in rows if r["experiment"] == "ablation"))
    for arm in arms:
        v = _mean(rows, "ablation", arm)
        lines.append(f"| {arm} | {v:.2f} | {_pct(v / base)} |")
    return "\n".join(lines)


def escalation_markdown(rows: list[dict[str, Any]]) -> str:
    scales = sorted({float(r["param"]) for r in rows if r["experiment"] == "escalation"})
    base = _mean(rows, "ablation", "baseline")
    head = "| Source scaled up | " + " | ".join(f"x{s:g}" for s in scales) + " |"
    lines = [head, "|---|" + "---:|" * len(scales)]
    for name in SOURCES:
        cells = [
            f"{_mean(rows, 'escalation', name, s):.2f} ({100 * (_mean(rows, 'escalation', name, s) / base - 1):+.0f}%)"
            for s in scales
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def growth_markdown(rows: list[dict[str, Any]]) -> str:
    durations = sorted({float(r["param"]) for r in rows if r["experiment"] == "growth"})
    head = "| Case | " + " | ".join(f"{d:g} s" for d in durations) + " | Fitted exponent |"
    lines = [head, "|---|" + "---:|" * (len(durations) + 1)]
    for arm in dict.fromkeys(r["arm"] for r in rows if r["experiment"] == "growth"):
        cells = [f"{_mean(rows, 'growth', arm, d):.1f}" for d in durations]
        lines.append(f"| {arm} | " + " | ".join(cells) + f" | {exponent(rows, arm):.2f} |")
    lines += ["", "Textbook exponents: " + ", ".join(f"{k} {v:g}" for k, v in THEORY.items()) + "."]
    return "\n".join(lines)


def fault_markdown(rows: list[dict[str, Any]]) -> str:
    sizes = sorted({float(r["param"]) for r in rows if r["experiment"] == "fault"})
    base = _mean(rows, "fault", "accelerometer bias step", sizes[0])
    lines = [
        "| Bias step, m/s² | Peak error inside the outage, m | Change | GNSS fixes rejected after the outage | "
        "Runs with the GNSS channel declared faulty | Median error 2 to 6 s after the outage, m | "
        "Largest error 2 to 6 s after the outage, m | Error at 4 s after the outage (legacy, one instant), m |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in sizes:
        arm = "accelerometer bias step"
        peak = _mean(rows, "fault", arm, s)
        faulted = _mean(rows, "fault", arm, s, "gnss_faulted")
        rejected = _mean(rows, "fault", arm, s, "gnss_rejected")
        after = _mean(rows, "fault", arm, s, "error_after_return_m")
        median = _mean(rows, "fault", arm, s, "recovery_median_m")
        window_max = _mean(rows, "fault", arm, s, "recovery_max_m")
        change = _pct(peak / base)
        lines.append(
            f"| {s:g} | {peak:.1f} | {change} | {rejected:.0f} | {100 * faulted:.0f}% | "
            f"{median:.1f} | {window_max:.1f} | {after:.1f} |"
        )
    return "\n".join(lines)


BLOCKS: dict[str, Callable[[list[dict[str, Any]]], str]] = {
    "attribution-ablation": ablation_markdown,
    "attribution-escalation": escalation_markdown,
    "attribution-growth": growth_markdown,
    "attribution-fault": fault_markdown,
}


# ----------------------------------------------------------------------- I/O


# The committed CSV has CRLF line ends.
TABLE = Table(tuple(Column(n, str, optional=True) for n in CSV_COLUMNS), key="case", lineterminator="\r\n")


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--seeds", type=int, default=8, help="seeds for the ablation and escalation (default: %(default)s)")
    p.add_argument("--growth-seeds", type=int, default=5, help="seeds for the growth test (default: %(default)s)")
    p.add_argument("--fault-seeds", type=int, default=6, help="seeds for the bias fault (default: %(default)s)")
    p.add_argument("--only", action="append", choices=("ablation", "escalation", "growth", "fault"), default=[])


def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    wanted = args.only or ["ablation", "escalation", "growth", "fault"]
    rows: list[dict[str, Any]] = []
    steps: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "ablation": lambda: ablation_rows(args.seeds),
        "escalation": lambda: escalation_rows(args.seeds),
        "growth": lambda: growth_rows(args.growth_seeds),
        "fault": lambda: fault_rows(args.fault_seeds),
    }
    for name in wanted:
        print(f"{name} ...", file=sys.stderr, flush=True)
        rows += steps[name]()
    return rows


def _blocks(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, str]:
    have = {r["experiment"] for r in rows}
    needs = {
        "attribution-ablation": "ablation",
        "attribution-escalation": "escalation",
        "attribution-growth": "growth",
        "attribution-fault": "fault",
    }
    return {
        name: BLOCKS[name](rows)
        for name, exp in needs.items()
        if exp in have and (exp != "escalation" or "ablation" in have)
    }


STUDY = Study(
    table=TABLE,
    run_args=_run,
    blocks=_blocks,
    flags=Flags(csv=True, page=True, markdown=True, from_csv=True, print_default=True),
    add_arguments=_add_arguments,
    read=rows_from_csv,
    prog="navkit sweep attribution",
    description="Where the error of a GNSS outage comes from: remove, inflate and grow each inertial source.",
    help={
        "csv": "write one row per run",
        "from_csv": "rebuild the tables and page from a saved --csv file; no runs",
        "page": "fill the attribution blocks of this Markdown page",
        "markdown": "print the tables",
    },
)


def build_parser() -> argparse.ArgumentParser:
    return runner_parser(STUDY)


def main(argv: list[str] | None = None) -> int:
    return run_study(STUDY, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
