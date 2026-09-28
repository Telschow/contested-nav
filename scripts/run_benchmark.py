#!/usr/bin/env python
"""Reproducible benchmark for the 21-state ESKF.

Every number quoted in README.md, docs/ and the paper draft is produced by this
script, from a YAML scenario in ``configs/``, with a fixed seed. Nothing here is
hand-entered. The point is that a reader can rerun it and get the same digits:

    python scripts/run_benchmark.py --out results/benchmark.json
    python scripts/run_benchmark.py --only gnss_only outage_visual

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
import json
import platform
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navkit.degrade.config import Outage, Scenario, scenario_from_dict  # noqa: E402
from navkit.degrade.inject import config_hash, inject  # noqa: E402
from navkit.estimators.dead_reckoning import DeadReckoning  # noqa: E402
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig  # noqa: E402
from navkit.eval.calibration import (  # noqa: E402
    normalized_error_squared,
    summarise,
)
from navkit.eval.metrics import (  # noqa: E402
    ate_bundle,
    drift,
    outage_summary,
    relative_pose_error,
)
from navkit.sensors.models import GnssConfig, VisionConfig, gnss_fixes, visual_updates  # noqa: E402
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory  # noqa: E402

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


def _eskf_config(scenario: Scenario, keys: dict[str, Any]) -> EskfConfig:
    """Build the filter config from a scenario plus estimator overrides."""
    noise = scenario.imu_noise
    return EskfConfig(
        imu_noise=noise.scaled(scenario.imu_noise_scale),
        gnss_enabled=scenario.gnss.enabled,
        gnss_position_sigma_m=scenario.gnss.sigma_m,
        vision_enabled=scenario.vision.enabled and bool(keys.get("vision_fuse", False)),
        vision_rot_sigma_deg=scenario.vision.rot_sigma_deg,
        vision_trans_sigma_m=scenario.vision.trans_sigma_m,
        vision_keyframe_interval=keys.get("vision_keyframe_interval", 1),
        vision_anchor_modelled=bool(keys.get("vision_anchor_modelled", True)),
        anchor_pos_sigma_m=keys.get("anchor_pos_sigma_m", 1.0),
        anchor_rot_sigma_deg=keys.get("anchor_rot_sigma_deg", 5.0),
        anchor_pos_drift_sigma_m_s=keys.get("anchor_pos_drift_sigma_m_s", 0.0),
        anchor_rot_drift_sigma_deg_s=keys.get("anchor_rot_drift_sigma_deg_s", 0.0),
    )


def run_case(name: str, case: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario end to end and return its result record."""
    merged = {**defaults.get("synthetic", {}), **case.get("synthetic", {})}
    syn = SyntheticConfig(**merged)
    keys = {**defaults.get("estimator", {}), **case.get("estimator", {})}

    scenario = scenario_from_dict(case.get("scenario", {}))
    if scenario is None:
        raise ValueError(f"case {name!r} has no scenario block")
    scenario.name = case.get("name", name)

    # Clean streams from the analytic reference, then degraded by the scenario.
    reference = synthetic_trajectory(syn, name=f"{name}-reference")
    imu_clean = synthetic_imu(syn)
    gnss_clean = gnss_fixes(reference, scenario.gnss)
    vision_clean = visual_updates(reference, scenario.vision)

    if scenario.camera_drop is not None or scenario.gnss_outages or scenario.vision_outages or scenario.imu_outages:
        streams = inject(scenario, imu_clean, gnss_clean, vision_clean, reference=reference)
        imu, gnss, vision, manifest = streams.imu, streams.gnss, streams.vision, streams.manifest
    else:
        imu, gnss, vision, manifest = imu_clean, gnss_clean, vision_clean, {}

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
            f"case {name!r} requests unknown estimator {estimator_name!r}; "
            "known: ErrorStateKalmanFilter, DeadReckoning"
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
        "config_hash": config_hash(scenario),
        "seed": scenario.gnss.seed,
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
        record["headline"]["coverage"] = {
            f"{p.sigma_per_axis:g}sigma": p.observed for p in cal.coverage.points
        }
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "benchmark.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "benchmark.json")
    ap.add_argument("--only", nargs="*", default=None, help="run only these case names")
    ap.add_argument("--all", action="store_true", help="run every case (the default)")
    ap.add_argument("--list", action="store_true", help="list case names and exit")
    ap.add_argument("--markdown", action="store_true", help="also print the results table as Markdown")
    args = ap.parse_args(argv)

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
        rec = run_case(name, cases[name], defaults)
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
        "config_file": str(args.config.relative_to(ROOT)),
        "config_sha256": __import__("hashlib").sha256(args.config.read_bytes()).hexdigest(),
        "cases": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n")
    # An --out outside the repository is legitimate (CI writes to a temp dir to
    # diff two runs), so do not assume the path is under ROOT.
    try:
        shown = args.out.relative_to(ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown} ({len(results)} cases)", file=sys.stderr)
    if args.markdown:
        print()
        print(as_markdown_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
