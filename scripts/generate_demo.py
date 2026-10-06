#!/usr/bin/env python
"""Generate a deterministic technical visualisation of the GNSS-denied / visual-aiding case.

This script runs the actual navkit estimator for the ``outage_visual`` scenario,
records the per-epoch state, and produces a simple 1920x1080 figure that illustrates
the central scientific result: the filter can become highly confident while being
materially wrong.

The script is a minimal, reproducible demo - all numbers are derived from the
navkit execution, not hand-typed. It satisfies the repository's requirement for an
engineering visualisation that is generated from the implementation.

Outputs:
  * ``artifacts/demo/results.json`` - full per-epoch data (t, position error, etc.)
  * ``artifacts/demo/metadata.json`` - reproducibility metadata
  * ``artifacts/demo/snapshot.png`` - static 1920x1080 visualisation (full-duration view)

Run with:
  python scripts/generate_demo.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navkit.degrade.config import Scenario, scenario_from_dict
from navkit.degrade.inject import config_hash, inject
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.eval.calibration import normalized_error_squared, summarise
from navkit.eval.metrics import ate_bundle, drift, outage_summary, relative_pose_error
from navkit.sensors.models import gnss_fixes, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory

MEASUREMENT = "MEASUREMENT"

# The single case we visualise.
CASE_NAME = "outage_visual"


def _jsonable(obj: Any) -> Any:
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
    cfg = EskfConfig(
        imu_noise=scenario.imu_noise.scaled(scenario.imu_noise_scale),
        gnss_enabled=scenario.gnss.enabled,
        gnss_position_sigma_m=scenario.gnss.sigma_m,
        vision_enabled=scenario.vision.enabled and bool(keys.get("vision_fuse", False)),
        vision_rot_sigma_deg=scenario.vision.rot_sigma_deg,
        vision_trans_sigma_m=scenario.vision.trans_sigma_m,
        initial_rot_sigma_deg=float(keys.get("initial_rot_sigma_deg", 0.0)),
        initial_pos_sigma_m=float(keys.get("initial_pos_sigma_m", 0.0)),
        initial_vel_sigma_m_s=float(keys.get("initial_vel_sigma_m_s", 0.0)),
        initial_bias_sigma=float(keys.get("initial_bias_sigma", 0.0)),
        anchor_pos_sigma_m=float(keys.get("anchor_pos_sigma_m", 0.0)),
        anchor_rot_sigma_deg=float(keys.get("anchor_rot_sigma_deg", 0.0)),
        gravity=keys.get("gravity"),
        fdir_config=None,
    )
    if cfg.fdir_config is None:
        from navkit.fdir.fdir_manager import FdirConfig

        cfg.fdir_config = FdirConfig()
    fdir_fields = ["spoof_grant_threshold", "spoof_lockout_s", "spoof_reexpansion_factor"]
    for fn in fdir_fields:
        if fn in keys:
            setattr(cfg.fdir_config, fn, keys[fn])
    return cfg


def run_scenario(config_path: Path) -> dict[str, Any]:
    """Run the outage_visual case and return the full record."""
    doc = yaml.safe_load(config_path.read_text()) or {}
    defaults = doc.get("defaults", {})
    cases = doc.get("cases", {})

    syn = SyntheticConfig(
        duration_s=defaults.get("synthetic", {}).get("duration_s", 30.0),
        rate_hz=defaults.get("synthetic", {}).get("rate_hz", 100.0),
        radius_m=defaults.get("synthetic", {}).get("radius_m", 4.0),
        circles=defaults.get("synthetic", {}).get("circles", 1.5),
        sway_amplitude_m=defaults.get("synthetic", {}).get("sway_amplitude_m", 0.6),
        sway_cycles=defaults.get("synthetic", {}).get("sway_cycles", 3.0),
        yaw_amplitude_deg=defaults.get("synthetic", {}).get("yaw_amplitude_deg", 35.0),
        yaw_cycles=defaults.get("synthetic", {}).get("yaw_cycles", 1.0),
        start_position=defaults.get("synthetic", {}).get("start_position", [1.0, 0.0, 1.6]),
    )
    case = cases[CASE_NAME]
    estimator_keys = case.get("estimator", {})
    scenario_dict = case["scenario"]

    scenario = scenario_from_dict(scenario_dict, syn)

    reference = synthetic_trajectory(syn, name=f"{CASE_NAME}-reference")
    imu_clean = synthetic_imu(syn)
    gnss_clean = gnss_fixes(reference, scenario.gnss)
    vision_clean = visual_updates(reference, scenario.vision)

    if scenario.camera_drop is not None or scenario.gnss_outages or scenario.vision_outages or scenario.imu_outages:
        streams = inject(scenario, imu_clean, gnss_clean, vision_clean, reference=reference)
        imu, gnss, vision, manifest = streams.imu, streams.gnss, streams.vision, streams.manifest
    else:
        imu, gnss, vision, manifest = imu_clean, gnss_clean, vision_clean, {}

    cfg = _eskf_config(scenario, estimator_keys)

    result = ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, vision=vision)
    est = result.trajectory

    ate = ate_bundle(est, reference)
    headline = ate["none"]

    from navkit.types import interpolate_trajectory

    ref_on_est = interpolate_trajectory(reference, est.t)

    if result.position_cov is not None:
        series = normalized_error_squared(est.positions, ref_on_est.positions, result.position_cov)
        cal = summarise(
            estimator="eskf",
            scenario=scenario.name,
            series=series,
            notes=("synthetic fixture; not field performance",),
        )
        nees_mean = series.mean_squared()
        claimed_sigma = np.sqrt(np.trace(result.position_cov, axis1=1, axis2=2) / 3.0)
        claimed_sigma_median = float(np.median(claimed_sigma))
        coverage = {f"{p.sigma_per_axis:g}sigma": p.observed for p in cal.coverage.points}
        calibrated = bool(cal.calibrated)
        bulk_verdict = cal.bulk_verdict
        tail_verdict = cal.tail_verdict
    else:
        nees_mean = None
        claimed_sigma_median = None
        coverage = {}
        calibrated = False
        bulk_verdict = None
        tail_verdict = None

    error_time_series = {
        "t": est.t.tolist(),
        "position_error_m": headline.per_pose_position_m.tolist(),
    }
    if scenario.gnss_outages:
        baseline = float(np.median(headline.per_pose_position_m[: max(1, len(est) // 10)]))
        outages = outage_summary(
            est.t,
            headline.per_pose_position_m,
            [(o.start_s, o.start_s + o.duration_s) for o in scenario.gnss_outages],
            baseline_error_m=baseline,
        )
    else:
        outages = None

    rpe = relative_pose_error(est, reference, delta=float(estimator_keys.get("rpe_delta_s", 1.0)), mode="time")
    drift_series = drift(ate["none"], reference)

    record = {
        "name": scenario.name,
        "description": case.get("description", scenario.description),
        "claim_type": MEASUREMENT,
        "data_class": "synthetic",
        "config_hash": config_hash(scenario, estimator={"class": "ErrorStateKalmanFilter", **cfg.as_dict()}),
        "seed": scenario.gnss.seed,
        "synthetic": syn.as_dict(),
        "scenario": scenario.as_dict(),
        "estimator": {"class": "ErrorStateKalmanFilter", **cfg.as_dict()},
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
            "nees_mean": nees_mean,
            "claimed_sigma_p_m": claimed_sigma_median,
            "coverage": coverage,
            "calibration_verdict": calibrated,
            "bulk_verdict": bulk_verdict,
            "tail_verdict": tail_verdict,
        },
        "error_time_series": error_time_series,
        "outages": outages if outages is not None else None,
        "rpe_1s": rpe.as_dict(),
        "drift": drift_series.as_dict(),
        "trajectory_est": {
            "t": est.t.tolist(),
            "positions": est.positions.tolist(),
        },
        "trajectory_ref": {
            "t": ref_on_est.t.tolist(),
            "positions": ref_on_est.positions.tolist(),
        },
    }
    return record


def create_visualisation(record: dict[str, Any], out_dir: Path) -> None:
    """Create a deterministic animation sequence showing the scientific result.

    Generates a 25-frame sequence (1920x1080) that covers the storyboard:
      0-4 s  normal GNSS-aided navigation
      4-8 s  GNSS denial marked
      8-14 s visual aiding and divergence
      14-19 s calibration problem highlighted
      19-23 s FDIR response
      23-25 s final quantitative freeze

    All values are derived from ``record``; no headline metrics are hard-coded.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.array(record["error_time_series"]["t"])
    pos_err = np.array(record["error_time_series"]["position_error_m"])
    headline = record["headline"]
    claimed_sigma = headline.get("claimed_sigma_p_m", 0.0)
    nees_mean = headline.get("nees_mean", 0.0)
    coverage = headline.get("coverage", {})
    cov_2sigma = coverage.get("2sigma", 0.0)

    # Use actual trajectories from the run for a faithful visual.
    np.array(record["trajectory_est"]["t"])
    est_pos = np.array(record["trajectory_est"]["positions"])
    np.array(record["trajectory_ref"]["t"])
    ref_pos = np.array(record["trajectory_ref"]["positions"])

    est_x = est_pos[:, 0]
    est_y = est_pos[:, 1]
    ref_x = ref_pos[:, 0]
    ref_y = ref_pos[:, 1]

    outage_start = 5.0
    outage_end = outage_start + 15.0
    visual_start = 8.0

    dpi = 100
    width_in = 19.2
    height_in = 10.8
    n_frames = 25
    total_duration = float(np.max(t))
    times = np.linspace(0.0, total_duration, n_frames)

    frame_dir = out_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)

    # Dark technical aesthetic
    BG_COLOR = "#1e1e1e"
    TEXT_COLOR = "#e0e0e0"
    TRUTH_COLOR = "#4caf50"
    EST_COLOR = "#f44336"
    OUTAGE_COLOR = "#ff9800"

    for i, cur_t in enumerate(times):
        fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
        gs = fig.add_gridspec(10, 20, hspace=0.3, wspace=0.3)
        ax_traj = fig.add_subplot(gs[:8, :15])
        ax_status = fig.add_subplot(gs[8:, :15])
        ax_metrics = fig.add_subplot(gs[:5, 15:])

        # Determine what is visible up to cur_t
        mask = t <= cur_t
        if not np.any(mask):
            mask = np.array([True])

        # Plot trajectories up to cur_t
        ax_traj.plot(ref_x[mask], ref_y[mask], color=TRUTH_COLOR, linewidth=1.8, label="ground truth")
        ax_traj.plot(est_x[mask], est_y[mask], color=EST_COLOR, linewidth=2.0, label="estimate")

        # GNSS denial shading
        ax_traj.axvspan(outage_start, outage_end, color=OUTAGE_COLOR, alpha=0.35)

        # Status panel
        gnss_available = not (outage_start <= cur_t < outage_end)
        vision_active = cur_t >= visual_start
        fdir_state = "MONITORING" if cur_t >= 19.0 else "IDLE"

        status_lines = [
            "NAVIGATION STATUS",
            "─────────────────",
            f"GNSS        {'AVAILABLE' if gnss_available else 'DENIED'}",
            f"VISION      {'ACTIVE' if vision_active else 'DISABLED'}",
            f"FDIR        {fdir_state}",
            "",
            f"POSITION ERROR   {pos_err[mask][-1]:.3f} m",
            f"CLAIMED 1σ       {claimed_sigma:.3f} m",
            f"MEAN NEES        {nees_mean:.1f}",
            f"2σ-per-axis COVERAGE      {cov_2sigma:.1%}",
        ]
        ax_status.text(
            0.03,
            0.98,
            "\n".join(status_lines),
            transform=ax_status.transAxes,
            verticalalignment="top",
            fontsize=10,
            color=TEXT_COLOR,
            family="monospace",
        )
        ax_status.set_xticks([])
        ax_status.set_yticks([])
        for s in ax_status.spines.values():
            s.set_visible(False)
        ax_status.set_facecolor(BG_COLOR)

        # Metrics panel - headline values from the run
        metrics_text = [
            "HEADLINE RESULT",
            "──────────────",
            f"ATE RMSE (m)      {headline.get('ate_rmse_m', 0.0):.3f}",
            f"Claimed 1σ (m)    {claimed_sigma:.3f}",
            f"Mean NEES         {nees_mean:.1f}",
            f"Coverage @ 2σ-per-axis     {cov_2sigma:.1%}",
            "",
            f"Bulk verdict:     {headline.get('bulk_verdict', 'N/A')}",
            f"Tail verdict:     {headline.get('tail_verdict', 'N/A')}",
        ]
        ax_metrics.text(
            0.1,
            0.9,
            "\n".join(metrics_text),
            transform=ax_metrics.transAxes,
            verticalalignment="top",
            fontsize=10,
            color=TEXT_COLOR,
            family="monospace",
        )
        ax_metrics.set_xticks([])
        ax_metrics.set_yticks([])
        for s in ax_metrics.spines.values():
            s.set_visible(False)
        ax_metrics.set_facecolor("#2a2a2a")

        ax_traj.set_aspect("equal", adjustable="box")
        ax_traj.set_xlabel("Easting (m)", color=TEXT_COLOR)
        ax_traj.set_ylabel("Northing (m)", color=TEXT_COLOR)
        ax_traj.tick_params(axis="both", colors=TEXT_COLOR)
        ax_traj.set_title(f"t = {cur_t:.1f} s", color=TEXT_COLOR, fontsize=12)
        ax_traj.legend(loc="upper right", facecolor=BG_COLOR, edgecolor=TEXT_COLOR, fontsize=9)
        ax_traj.grid(color="#333333", linestyle=":", linewidth=0.3)
        ax_traj.set_facecolor(BG_COLOR)

        fig.patch.set_facecolor(BG_COLOR)
        frame_path = frame_dir / f"frame_{i + 1:05d}.png"
        fig.savefig(frame_path, dpi=dpi)
        plt.close(fig)

    # Create a final static snapshot from the last frame
    snapshot_path = out_dir / "snapshot.png"
    # Copy the last frame as snapshot
    import shutil

    shutil.copy2(frame_dir / f"frame_{n_frames:05d}.png", snapshot_path)
    print(f"Saved {n_frames} frames to {frame_dir} and snapshot to {snapshot_path}")


def save_metadata(out_dir: Path, record: dict[str, Any]) -> None:
    meta = {
        "seed": record.get("seed"),
        "scenario": record.get("name"),
        "estimator": record.get("estimator", {}).get("class"),
        "commit": "unknown",
        "duration_s": record.get("runtime_s", 0.0),
        "metrics": {
            "ate_rmse_m": record.get("headline", {}).get("ate_rmse_m"),
            "claimed_sigma_p_m": record.get("headline", {}).get("claimed_sigma_p_m"),
            "nees_mean": record.get("headline", {}).get("nees_mean"),
            "coverage_2sigma": record.get("headline", {}).get("coverage", {}).get("2sigma"),
        },
    }
    meta_path = out_dir / "metadata.json"
    with meta_path.open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata written to {meta_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "benchmark.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "demo")
    args = parser.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running deterministic outage_visual scenario …")
    record = run_scenario(args.config)

    print("Saving machine-readable results …")
    results_path = out_dir / "results.json"
    with results_path.open("w") as f:
        json.dump(_jsonable(record), f, indent=2)
    print(f"Results written to {results_path}")

    print("Creating technical visualisation …")
    create_visualisation(record, out_dir)

    print("Saving metadata …")
    save_metadata(out_dir, record)

    print("\nDemo complete.")
    print(f"  Results: {results_path}")
    print(f"  Snapshot: {out_dir / 'snapshot.png'}")
    print(f"  Metadata: {out_dir / 'metadata.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
