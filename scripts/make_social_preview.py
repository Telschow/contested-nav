#!/usr/bin/env python
"""Render the repository's social preview image (1280 x 640) from a benchmark result.

    navkit run --out results/benchmark.json
    python scripts/make_social_preview.py            # writes docs/assets/social-preview.png

GitHub shows this image when the repository is linked. It is rendered from the same result
file as every other figure, so the numbers on it cannot disagree with the README: the headline
values are read from ``results/benchmark.json``, never typed here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navkit.hero import BOUND_PER_SIGMA

BG, INK, MUTED = "#101820", "#e8eef3", "#9db0bf"
C_ERR, C_CLAIM, C_OUT = "#6fb3e0", "#e88b7d", "#f0b35a"
WIDTH_PX, HEIGHT_PX, DPI = 1280, 640, 100


def render(results: dict, out: Path) -> Path:
    cases = {c["name"]: c for c in results["cases"]}
    vis = cases["outage_visual"]
    head = vis["headline"]
    ts = vis["error_time_series"]
    t = np.asarray(ts["t"], float)
    err = np.asarray(ts["position_error_m"], float)
    bound = BOUND_PER_SIGMA * np.asarray(ts["claimed_sigma_p_m"], float)

    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=BG)
    fig.text(0.05, 0.84, "contested-nav", color=INK, fontsize=46, fontweight="bold", va="center")
    fig.text(0.05, 0.71, "Is the filter right about how wrong it is?", color=MUTED, fontsize=21, va="center")

    cov = 100.0 * head["coverage"]["2sigma"]
    lines = [
        ("position error (ATE RMSE)", f"{head['ate_rmse_m']:.3f} m", C_ERR),
        ("claimed 1-sigma", f"{head['claimed_sigma_p_m']:.3f} m", C_CLAIM),
        ("2-sigma coverage", f"{cov:.1f}% (99.3% expected)", C_CLAIM),
    ]
    for i, (label, value, colour) in enumerate(lines):
        y = 0.52 - 0.115 * i
        fig.text(0.05, y, label, color=MUTED, fontsize=15, va="center")
        fig.text(0.28, y, value, color=colour, fontsize=17, fontweight="bold", va="center")

    ax = fig.add_axes([0.60, 0.17, 0.35, 0.60])
    ax.set_facecolor(BG)
    for o in vis.get("outages", []):
        ax.axvspan(o["start_s"], o["end_s"], color=C_OUT, alpha=0.18, lw=0)
    ax.fill_between(t, 0, bound, color=C_CLAIM, alpha=0.18, lw=0)
    ax.plot(t, bound, color=C_CLAIM, lw=1.6)
    ax.plot(t, err, color=C_ERR, lw=2.0)
    ax.set_xlim(t[0], t[-1])
    ax.set_ylim(0, float(np.max(err)) * 1.1)
    ax.set_xlabel("time (s), GNSS denied in the shaded window", color=MUTED, fontsize=10)
    ax.tick_params(colors=MUTED, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#2b3a47")
    ax.text(0.02, 0.95, "actual error", color=C_ERR, transform=ax.transAxes, ha="left", fontsize=11)
    ax.text(0.02, 0.87, "claimed 2-sigma bound", color=C_CLAIM, transform=ax.transAxes, ha="left", fontsize=11)

    fig.text(0.05, 0.06, "Synthetic fixture. Not field validated. MIT.", color=MUTED, fontsize=12, va="center")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=Path("results") / "benchmark.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "assets" / "social-preview.png")
    args = ap.parse_args(argv)
    if not args.results.exists():
        raise SystemExit(f"{args.results} not found; run `navkit run` first")
    out = render(json.loads(args.results.read_text()), args.out)
    print(f"wrote {out} ({out.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
