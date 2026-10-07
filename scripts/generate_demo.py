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

from navkit.benchmark import run_case

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


def run_scenario(config_path: Path) -> dict[str, Any]:
    """Run the ``outage_visual`` benchmark case and return its record with trajectories.

    This calls :func:`navkit.benchmark.run_case`, the same function that produces every number
    in the documentation, so the demo cannot drift from the benchmark. An earlier version of
    this script carried its own copy of the filter configuration, got a different (collapsed)
    filter, and drew mean NEES 1.4e10 next to a README that said 419.4.
    """
    doc = yaml.safe_load(config_path.read_text()) or {}
    return run_case(CASE_NAME, doc["cases"][CASE_NAME], doc.get("defaults", {}), trajectories=True)


def create_visualisation(record: dict[str, Any], out_dir: Path) -> None:
    """Create a 25-frame sequence (1920x1080) that reveals the run in time order.

    Every value on screen comes from ``record``: the path, the GNSS outage window (from the
    scenario), whether vision is fused (from the estimator configuration), the gate counters,
    and the headline metrics. Nothing is a storyboard: an earlier version showed "VISION
    DISABLED" until 8 s and "FDIR MONITORING" after 19 s, which the run does not do.
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

    outages = [(o["start_s"], o["end_s"]) for o in record["scenario"].get("gnss_outages", [])]
    vision_fused = bool(record["estimator"].get("vision_enabled", False))
    summary = record.get("summary", {})
    gate_accepted = int(summary.get("fdir_gnss_accepted", 0))
    gate_rejected = int(summary.get("fdir_gnss_rejected", 0))

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
        gs = fig.add_gridspec(12, 20, hspace=0.45, wspace=0.3)
        ax_traj = fig.add_subplot(gs[:9, :15])
        ax_status = fig.add_subplot(gs[9:, :15])
        ax_metrics = fig.add_subplot(gs[:6, 15:])

        # Determine what is visible up to cur_t
        mask = t <= cur_t
        if not np.any(mask):
            mask = np.array([True])

        # Plot trajectories up to cur_t
        ax_traj.plot(ref_x[mask], ref_y[mask], color=TRUTH_COLOR, linewidth=1.8, label="ground truth")
        ax_traj.plot(est_x[mask], est_y[mask], color=EST_COLOR, linewidth=2.0, label="estimate")

        # Mark the part of the path flown with GNSS denied. The axes are position, not time,
        # so the outage is drawn as an underlay on the samples whose timestamps fall inside it.
        in_outage = np.zeros(len(t), dtype=bool)
        for start, end in outages:
            in_outage |= (t >= start) & (t < end)
        denied = mask & in_outage
        if np.any(denied):
            ax_traj.plot(ref_x[denied], ref_y[denied], color=OUTAGE_COLOR, linewidth=7.0, alpha=0.35, zorder=0)

        # Status panel
        gnss_available = not any(start <= cur_t < end for start, end in outages)

        status_lines = [
            "NAVIGATION STATUS",
            "─────────────────",
            f"GNSS        {'AVAILABLE' if gnss_available else 'DENIED'}",
            f"VISION      {'FUSED' if vision_fused else 'OFF'}",
            f"GNSS GATE   {gate_accepted} accepted, {gate_rejected} rejected (whole run)",
            "",
            f"POSITION ERROR   {pos_err[mask][-1]:.3f} m",
            f"CLAIMED 1σ       {claimed_sigma:.3f} m",
            f"MEAN NEES        {nees_mean:.1f}",
            f"2σ-per-axis COVERAGE      {cov_2sigma:.1%}",
        ]
        ax_status.text(
            0.03,
            0.78,
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
        ax_status.set_facecolor("none")

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
        ax_traj.legend(loc="upper right", facecolor=BG_COLOR, edgecolor=TEXT_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
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
