"""Reproducible benchmark for the 21-state ESKF.

Every number quoted in README.md and docs/ is produced by this module, from a YAML
scenario in ``configs/``, with a fixed seed. Nothing here is hand-entered. The point
is that a reader can rerun it and get the same digits:

    navkit run --out results/benchmark.json
    navkit run --only gnss_only outage_visual

The same code runs from a source checkout without installing anything:

    python scripts/run_benchmark.py --out results/benchmark.json

Design decisions worth stating, because they change the numbers:

* The reference trajectory is the analytic one the synthetic generator is built
  from, so the ground truth is exact rather than another estimate. Motion is
  parameterised as ``1 - cos(w t)`` so position, velocity, rotation and angular
  rate are all zero at ``t = 0``; an estimator initialised at the identity pose
  is then *exactly* correct at t=0 and every later error belongs to the filter.

* ATE is reported four ways, never one. ``none`` is the honest number for a
  filter that is already in the reference frame; ``rigid`` fits a transform to
  all poses; ``rigid_start`` fits on the first 20% only, so it cannot hide
  accumulated drift; ``similarity`` adds a scale degree of freedom. An ATE
  quoted without its alignment is not a result.

* Calibration is scored with the filter's own covariance. A filter that is wrong
  by 31 m and claims 0.3 m of uncertainty is the failure this project exists to
  surface, so NEES and coverage are reported next to the position error, not
  instead of it.

* All results are labelled as synthetic. These are numbers from a known-answer
  fixture, not from any real sensor capture, and no claim in this repository
  treats them as field performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .degrade.config import Scenario, scenario_from_dict
from .degrade.inject import config_hash, inject
from .estimators.dead_reckoning import DeadReckoning
from .estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from .eval.calibration import (
    normalized_error_squared,
    summarise,
)
from .eval.metrics import (
    ate_bundle,
    drift,
    outage_summary,
    relative_pose_error,
)
from .sensors.models import gnss_fixes, visual_updates
from .synthetic import SyntheticConfig, seeded_scene, synthetic_imu, synthetic_trajectory
from .types import GnssFix

#: How the shipped scenario file is named in a result. It is a label for the canonical
#: source, so a result made from the packaged copy of the file reads the same as one made
#: from the repository copy.
DEFAULT_CONFIG_LABEL = "configs/benchmark.yaml"
DEFAULT_OUT = Path("results") / "benchmark.json"


def default_config_path() -> Path:
    """Locate the default scenario file.

    A source checkout (including an editable install) has ``configs/benchmark.yaml``
    next to ``src/``. An installed wheel carries a copy at ``navkit/configs/``, put
    there at build time, so the command works from any directory.
    """
    checkout = Path(__file__).resolve().parents[2] / "configs" / "benchmark.yaml"
    if checkout.is_file():
        return checkout
    packaged = resources.files("navkit") / "configs" / "benchmark.yaml"
    if packaged.is_file():
        return Path(str(packaged))
    raise FileNotFoundError("benchmark.yaml not found next to the source tree or inside the package; pass --config")


# Claim types, from navkit.analysis.findings. Every scalar this script emits is
# tagged so a downstream document cannot accidentally present a synthetic number
# as a field measurement.
MEASUREMENT = "MEASUREMENT"


def _jsonable(obj: Any) -> Any:
    """Convert dataclasses, numpy scalars and arrays into JSON-safe values."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(asdict(obj))
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def _sigma_scale(keys: dict[str, Any], key: str) -> float:
    """A positive multiplier on the noise the filter assumes for one sensor (default 1)."""
    scale = float(keys.get(key, 1.0))
    if not scale > 0.0 or not np.isfinite(scale):
        raise ValueError(f"estimator key {key!r} must be a positive finite number, got {scale!r}")
    return scale


def _eskf_config(scenario: Scenario, keys: dict[str, Any]) -> EskfConfig:
    """Build the filter config from a scenario plus estimator overrides.

    By default the filter is told the noise the generator used. ``gnss_sigma_scale`` and
    ``vision_sigma_scale`` multiply the sigmas the *filter* assumes and leave the generator
    alone, so the same data can be filtered with a wrong noise model. A value below 1 makes
    the filter more confident in the sensor than it should be; above 1, less.
    """
    noise = scenario.imu_noise.scaled(scenario.imu_noise_scale)
    gnss_scale = _sigma_scale(keys, "gnss_sigma_scale")
    vision_scale = _sigma_scale(keys, "vision_sigma_scale")
    return EskfConfig(
        imu_noise=noise,
        initial_gyro_bias_sigma=noise.gyro_bias_sigma,
        initial_accel_bias_sigma=noise.accel_bias_sigma,
        gnss_enabled=scenario.gnss.enabled,
        gnss_position_sigma_m=scenario.gnss.sigma_m * gnss_scale,
        vision_enabled=scenario.vision.enabled and bool(keys.get("vision_fuse", False)),
        vision_rot_sigma_deg=scenario.vision.rot_sigma_deg * vision_scale,
        vision_trans_sigma_m=scenario.vision.trans_sigma_m * vision_scale,
        vision_keyframe_interval=keys.get("vision_keyframe_interval", 1),
        vision_anchor_modelled=bool(keys.get("vision_anchor_modelled", True)),
        anchor_pos_sigma_m=keys.get("anchor_pos_sigma_m", 1.0),
        anchor_rot_sigma_deg=keys.get("anchor_rot_sigma_deg", 5.0),
        anchor_pos_drift_sigma_m_s=keys.get("anchor_pos_drift_sigma_m_s", 0.0),
        anchor_rot_drift_sigma_deg_s=keys.get("anchor_rot_drift_sigma_deg_s", 0.0),
        process_noise_form=str(keys.get("process_noise_form", "textbook")),
    )


def run_case(
    name: str,
    case: dict[str, Any],
    defaults: dict[str, Any],
    seed: int | None = None,
    scene_seed: int | None = None,
    trajectories: bool = False,
    gnss_hook: Callable[[GnssFix], GnssFix] | None = None,
    fdir_events: bool = False,
) -> dict[str, Any]:
    """Run one scenario end to end and return its result record.

    ``seed`` overrides every stochastic stream in the scenario (GNSS, vision
    and camera drop) so a benchmark can be repeated over independent draws.
    Because the scenario is mutated before it is hashed, each override produces
    its own ``config_hash`` and the provenance stays truthful.

    ``scene_seed`` is a separate axis: it varies the *trajectory* rather than
    the sensor noise, so the question becomes "is this a property of the filter"
    instead of "was this a property of one noise draw". The two are independent
    on purpose, and passing both sweeps the full cross product.

    ``trajectories`` adds ``trajectory_est`` and ``trajectory_ref`` (time and positions, the
    reference resampled onto the estimate's timestamps) for a caller that draws the path. It
    is off by default so the benchmark JSON stays small and unchanged.

    ``gnss_hook`` receives the GNSS stream after the scenario has been applied and returns the
    stream the filter sees. It is for a fault the scenario schema does not describe, such as a
    position offset (a spoof); the fault matrix uses it. The hook is not part of the scenario,
    so it is not in ``config_hash``: a caller that uses it must record the fault itself.

    ``fdir_events`` adds the FDIR event log (declarations, lockouts, inflation grants) to the record
    as ``fdir_events``. It is off by default so the benchmark JSON is unchanged.

    Every scenario goes through the injection layer, including one with no outage or camera drop.
    The synthetic IMU has no noise of its own; the IMU noise and bias come from that layer, so
    skipping it ran some cases with a noiseless IMU (ADR-0012).
    """
    merged = {**defaults.get("synthetic", {}), **case.get("synthetic", {})}
    syn = SyntheticConfig(**merged)
    if scene_seed is not None:
        syn = seeded_scene(syn, scene_seed)
    keys = {**defaults.get("estimator", {}), **case.get("estimator", {})}

    scenario = scenario_from_dict(case.get("scenario", {}))
    if scenario is None:
        raise ValueError(f"case {name!r} has no scenario block")
    scenario.name = case.get("name", name)
    if seed is not None:
        scenario.gnss.seed = seed
        scenario.vision.seed = seed
        if scenario.camera_drop is not None:
            scenario.camera_drop.seed = seed

    # Clean streams from the analytic reference, then degraded by the scenario.
    reference = synthetic_trajectory(syn, name=f"{name}-reference")
    imu_clean = synthetic_imu(syn)
    gnss_clean = gnss_fixes(reference, scenario.gnss)
    vision_clean = visual_updates(reference, scenario.vision)

    streams = inject(scenario, imu_clean, gnss_clean, vision_clean, reference=reference)
    imu, gnss, vision, manifest = streams.imu, streams.gnss, streams.vision, streams.manifest

    if gnss_hook is not None:
        gnss = gnss_hook(gnss)

    cfg = _eskf_config(scenario, keys)

    # Dispatch on the declared estimator rather than assuming the ESKF, so a
    # config can name a control case and get the control it asked for. Silently
    # running an ESKF for a case labelled DeadReckoning would produce a
    # confidently wrong table.
    estimator_name = keys.get("class", "ErrorStateKalmanFilter")
    if estimator_name == "DeadReckoning":
        result = DeadReckoning().run(imu)
    elif estimator_name == "ErrorStateKalmanFilter":
        result = ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, vision=vision)
    else:
        raise ValueError(
            f"case {name!r} requests unknown estimator {estimator_name!r}; known: ErrorStateKalmanFilter, DeadReckoning"
        )

    est = result.trajectory

    # Score the estimate against the analytic reference at the estimate's own
    # timestamps. `none` is the headline: the synthetic filter is initialised in
    # the reference frame, so there is no global offset for a fit to absorb.
    ate = ate_bundle(est, reference)
    headline = ate["none"]

    # The reference must be resampled onto the estimate's timestamps before the
    # covariance can be scored index by index.
    from navkit.types import interpolate_trajectory

    ref_on_est = interpolate_trajectory(reference, est.t)

    record: dict[str, Any] = {
        "name": scenario.name,
        "description": case.get("description", scenario.description),
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        # The estimator block goes into the hash as well as the record: it
        # changes the filter without changing the scenario, so a scenario-only
        # hash would let two different filters claim the same provenance.
        "config_hash": config_hash(scenario, estimator={"class": estimator_name, **cfg.as_dict()}),
        "seed": scenario.gnss.seed,
        "scene_seed": scene_seed,
        "synthetic": syn.as_dict(),
        "scenario": scenario.as_dict(),
        "estimator": {"class": estimator_name, **cfg.as_dict()},
        "runtime_s": result.runtime_s,
        "stats": dict(result.stats),
        "summary": result.summary(),
        "manifest": manifest,
        "ate": {k: v.as_dict() for k, v in ate.items()},
        "headline": {
            "alignment": headline.alignment,
            "ate_rmse_m": headline.position_m.rmse,
            "ate_median_m": headline.position_m.median,
            "ate_p95_m": headline.position_percentiles_m.get("p95"),
            "rotation_rmse_deg": headline.rotation_deg.rmse,
        },
    }

    # Calibration, only when the filter reported a covariance. Dead reckoning
    # has no uncertainty model, and reporting a NEES for it would be meaningless.
    if result.position_cov is not None:
        series = normalized_error_squared(est.positions, ref_on_est.positions, result.position_cov)
        cal = summarise(
            estimator="eskf",
            scenario=scenario.name,
            series=series,
            notes=("synthetic fixture; not field performance",),
        )
        record["calibration"] = cal.as_dict()
        record["headline"]["nees_mean"] = series.mean_squared()
        record["headline"]["nees_expected"] = float(series.dof)
        # The filter's own claimed 1-sigma, read out of the covariance it
        # reported. Deriving it from an inflation factor times the RMSE would be
        # meaningless: inflation scales the filter's sigma, not the error.
        claimed = np.sqrt(np.trace(result.position_cov, axis1=1, axis2=2) / 3.0)
        record["headline"]["claimed_sigma_p_m"] = float(np.median(claimed))
        record["headline"]["claimed_sigma_p95_m"] = float(np.percentile(claimed, 95))
        record["headline"]["coverage"] = {f"{p.sigma_per_axis:g}sigma": p.observed for p in cal.coverage.points}
        record["headline"]["calibration_verdict"] = cal.verdict
        # Bulk and tail are reported separately, because they detect different
        # failure modes and can disagree for a filter that is only slightly
        # miscalibrated in the bulk but never produces a tail escape.
        record["headline"]["bulk_verdict"] = cal.bulk_verdict
        record["headline"]["tail_verdict"] = cal.tail_verdict
        record["headline"]["calibrated"] = bool(cal.calibrated)

        # Error over time is what a GNSS outage is judged on, so it is emitted
        # per case rather than reconstructed from the summary.
        record["error_time_series"] = {
            "t": est.t.tolist(),
            "position_error_m": headline.per_pose_position_m.tolist(),
            # The filter's own per-axis 1-sigma, next to the error it claims to bound. The
            # hero figure is this series against the error.
            "claimed_sigma_p_m": claimed.tolist(),
        }
        if scenario.gnss_outages:
            baseline = float(np.median(headline.per_pose_position_m[: max(1, len(est) // 10)]))
            record["outages"] = outage_summary(
                est.t,
                headline.per_pose_position_m,
                [(o.start_s, o.start_s + o.duration_s) for o in scenario.gnss_outages],
                baseline_error_m=baseline,
            )

    rpe = relative_pose_error(est, reference, delta=float(keys.get("rpe_delta_s", 1.0)), mode="time")
    record["rpe_1s"] = rpe.as_dict()
    record["drift"] = drift(ate["none"], reference).as_dict()

    if fdir_events:
        record["fdir_events"] = list(est.metadata.get("fdir_events", []))

    if trajectories:
        record["trajectory_est"] = {"t": est.t.tolist(), "positions": est.positions.tolist()}
        record["trajectory_ref"] = {"t": ref_on_est.t.tolist(), "positions": ref_on_est.positions.tolist()}

    return record


def as_markdown_table(results: list[dict[str, Any]]) -> str:
    """Render the results as the table quoted in README.md.

    Generated rather than hand-written on purpose: a table that someone typed in
    by hand is a table that will silently disagree with the code the next time a
    default changes. ``docs/`` and the README are both expected to be regenerated
    from this output.
    """
    lines = [
        "| Scenario | ATE RMSE (m) | Claimed 1-sigma (m) | Mean NEES (exp. 3) | Coverage at 2 sigma | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in results:
        h = r["headline"]
        claim = h.get("claimed_sigma_p_m")
        nees = h.get("nees_mean")
        cov = (h.get("coverage") or {}).get("2sigma")
        verdict = h.get("calibration_verdict") or "no covariance reported"
        lines.append(
            "| {name} | {ate:.3f} | {claim} | {nees} | {cov} | {verdict} |".format(
                name=r["name"],
                ate=h["ate_rmse_m"],
                claim=f"{claim:.3f}" if isinstance(claim, (int, float)) else "n/a",
                nees=f"{nees:.1f}" if isinstance(nees, (int, float)) else "n/a",
                cov=f"{cov:.1%}" if isinstance(cov, (int, float)) else "n/a",
                verdict=verdict,
            )
        )
    return "\n".join(lines)


def _config_label(path: Path, given: bool) -> str:
    """Name the scenario file in a result: the canonical label, or the path as given."""
    if not given:
        return DEFAULT_CONFIG_LABEL
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="navkit run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", type=Path, default=None, help="scenario file (default: the shipped benchmark.yaml)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="result JSON (default: results/benchmark.json)")
    ap.add_argument("--only", nargs="*", default=None, help="run only these case names")
    ap.add_argument("--all", action="store_true", help="run every case (the default)")
    ap.add_argument("--list", action="store_true", help="list case names and exit")
    ap.add_argument("--markdown", action="store_true", help="also print the results table as Markdown")
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="override every stochastic stream in the scenario (GNSS, vision, camera drop)",
    )
    ap.add_argument(
        "--scene-seed",
        type=int,
        default=None,
        help=(
            "vary the trajectory itself (radius, turning, sway) rather than the sensor noise. "
            "Use with --seed to sweep the cross product; both default to the configured scene"
        ),
    )
    args = ap.parse_args(argv)
    config_given = args.config is not None
    if args.config is None:
        args.config = default_config_path()

    doc = yaml.safe_load(args.config.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})
    if not cases:
        raise SystemExit(f"no cases defined in {args.config}")

    if args.list:
        for k in cases:
            print(k)
        return 0

    selected = args.only or list(cases)
    unknown = [k for k in selected if k not in cases]
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(cases)}")

    results: list[dict[str, Any]] = []
    for name in selected:
        print(f"running {name} ...", file=sys.stderr, flush=True)
        t0 = time.perf_counter()
        rec = run_case(name, cases[name], defaults, seed=args.seed, scene_seed=args.scene_seed)
        rec["wall_s"] = round(time.perf_counter() - t0, 3)
        results.append(rec)
        h = rec["headline"]
        cov = h.get("coverage", {}).get("2sigma")
        cov_s = f"{cov:.1%}" if isinstance(cov, (int, float)) else "n/a"
        print(
            f"  ate(rmse)={h['ate_rmse_m']:.3f} m  "
            f"claimed 1s={h.get('claimed_sigma_p_m', float('nan')):.3f} m  "
            f"nees={h.get('nees_mean', float('nan')):.4g} (exp {h.get('nees_expected', 3)})  "
            f"cov@2s={cov_s}  verdict={h.get('calibration_verdict', 'n/a')}",
            file=sys.stderr,
            flush=True,
        )

    payload = {
        "schema": "navkit-benchmark/1",
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "disclaimer": (
            "All numbers are from a known-answer synthetic fixture. They are not "
            "field measurements and must not be presented as real-sensor performance."
        ),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "config_file": _config_label(args.config, config_given),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "cases": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out} ({len(results)} cases)", file=sys.stderr)
    if args.markdown:
        print()
        print(as_markdown_table(results))
    return 0
