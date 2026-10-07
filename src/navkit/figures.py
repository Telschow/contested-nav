"""Render the benchmark figures committed under ``docs/figures/``.

Figures are committed rather than generated on demand because they are the
evidence behind the numbers in README.md and docs/. A reader should not have to
run a 30 s filter to see what was measured, and a reviewer should be able to
diff the figures between commits.

    navkit figures --results results/benchmark.json

Every figure is regenerated from the JSON the benchmark wrote, never from
in-memory state, so a figure can always be traced back to a recorded result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: required for CI and for a server without a display
import matplotlib.pyplot as plt
import numpy as np

from .hero import animate_hero, fig_hero

FIGDIR = Path("docs") / "figures"

# Colourblind-safe, and distinguishable in greyscale, because these get pasted
# into slides and printed.
C_ERR = "#1b6ca8"
C_CLAIM = "#c0392b"
C_OK = "#1e8449"
C_GREY = "#7f8c8d"


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(True, alpha=0.25, linewidth=0.6)
    ax.tick_params(labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def fig_error_vs_claim(cases: list[dict]) -> Path:
    """The headline figure: how wrong the filter is against what it claims.

    A dot on the diagonal is a calibrated filter. Dots far above it are the
    failure this project exists to document: the filter is more confident than
    the error justifies. The line is 1:1, not a fit, so the eye is not invited
    to look for a trend that is not being claimed.
    """
    pts = [
        (c["headline"]["claimed_sigma_p_m"], c["headline"]["ate_rmse_m"], c["name"])
        for c in cases
        if isinstance(c["headline"].get("claimed_sigma_p_m"), (int, float))
    ]
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    hi = max(max(a, b) for a, b, _ in pts) * 1.15
    ax.plot([0, hi], [0, hi], color=C_GREY, linestyle="--", linewidth=1.0, zorder=1)
    ax.text(hi * 0.72, hi * 0.86, "calibrated", color=C_GREY, fontsize=8, rotation=33)

    for claim, ate, name in pts:
        bad = ate > claim
        ax.scatter([claim], [ate], s=70, color=C_ERR if bad else C_OK, zorder=3, edgecolor="white", linewidth=0.8)
        ax.annotate(name, (claim, ate), textcoords="offset points", xytext=(7, 5), fontsize=7.5, color="#333333")

    _style(ax, "Error against claimed uncertainty", "Claimed position 1-sigma (m)", "ATE RMSE (m)")
    fig.text(0.01, 0.01, "Synthetic fixture. Above the dashed line = overconfident.", fontsize=7, color=C_GREY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = FIGDIR / "error-vs-claim.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def fig_coverage(cases: list[dict]) -> Path:
    """Coverage at each per-axis sigma against the 3-dof expectation.

    The expectation is not 68/95/99.7: those are the one-dimensional numbers,
    and quoting them for a 3-d position error is one of the easier ways to
    misreport a filter. The bars are the exact ellipsoid coverage.
    """
    from navkit.eval.statistics import ellipsoid_coverage

    sigmas = (1.0, 2.0, 3.0)
    exp = [ellipsoid_coverage(s, 3) for s in sigmas]
    x = np.arange(len(sigmas))
    width = 0.8 / max(1, len(cases))

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.bar(x - 0.4 + width / 2, exp, width=width, color=C_GREY, label="expected (3 dof)", zorder=2)
    for i, c in enumerate(cases):
        cov = c["headline"].get("coverage")
        if not cov:
            continue
        obs = [cov.get(f"{s:g}sigma") for s in sigmas]
        if any(v is None for v in obs):
            continue
        ax.bar(x - 0.4 + width * (i + 1.5), obs, width=width, label=c["name"], zorder=2)

    ax.set_xticks(x, [f"{s:g} sigma" for s in sigmas])
    _style(ax, "Covariance coverage, observed vs expected", "Ellipsoid size", "Fraction of epochs covered")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=6.5, ncol=2, frameon=False)
    fig.tight_layout()
    out = FIGDIR / "coverage.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def fig_outage(cases: list[dict]) -> Path | None:
    """Error against time through the GNSS outage, for the two outage cases."""
    sel = [c for c in cases if "outage" in c["name"] and "error_time_series" in c]
    if not sel:
        return None
    fig, axes = plt.subplots(1, len(sel), figsize=(5.0 * len(sel), 3.8), squeeze=False)
    for ax, c in zip(axes[0], sel, strict=False):
        ts = c["error_time_series"]
        t = np.asarray(ts["t"], float)
        e = np.asarray(ts["position_error_m"], float)
        outages = [(o["start_s"], o["end_s"]) for o in c.get("outages", [])]
        for s, en in outages:
            ax.axvspan(s, en, color="#f39c12", alpha=0.18, zorder=0, label="GNSS outage")

        claim = c["headline"].get("claimed_sigma_p95_m")
        if isinstance(claim, (int, float)):
            ax.axhline(
                claim, color=C_CLAIM, linestyle="--", linewidth=1.0, label=f"claimed 1-sigma (p95) = {claim:.2f} m"
            )
        ax.plot(t, e, color=C_ERR, linewidth=1.2, zorder=3, label="position error")
        _style(ax, c["name"], "time (s)", "position error (m)")
        ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    out = FIGDIR / "outage-error.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def fig_nees(cases: list[dict]) -> Path | None:
    """Mean NEES against the expected value, which is the number a reviewer
    will check first when judging whether a filter is honest."""
    sel = [c for c in cases if isinstance(c["headline"].get("nees_mean"), (int, float))]
    if not sel:
        return None
    vals = [c["headline"]["nees_mean"] for c in sel]
    names = [c["name"] for c in sel]
    y = np.arange(len(sel))

    fig, ax = plt.subplots(figsize=(6.8, 0.42 * len(sel) + 1.8))
    ax.barh(y, vals, color=[C_ERR if v > 3.0 else C_OK for v in vals], zorder=2)
    ax.axvline(3.0, color=C_GREY, linestyle="--", linewidth=1.2, zorder=3)
    ax.text(3.0, len(sel) - 0.4, " expected = 3", fontsize=8, color=C_GREY)
    ax.set_xscale("log")
    ax.set_yticks(y, names)
    for yi, v in zip(y, vals, strict=False):
        ax.text(v * 1.15, float(yi), f"{v:.1f}", va="center", fontsize=7.5, color="#333333")
    _style(ax, "Mean NEES by scenario (log scale)", "mean NEES", "")
    fig.tight_layout()
    out = FIGDIR / "nees.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def fig_outage_sweep(cells: list[dict], out: Path) -> Path:
    """Error, NEES and coverage against outage length, one column per outage start.

    Each line is a case and the band is its bootstrap 95% interval over noise seeds.
    The reference lines are what a calibrated filter would show: NEES 3 and 99.3%
    coverage of the 2-sigma ellipsoid. Written to ``out``, not ``FIGDIR``, because the
    sweep is a command with its own output path.
    """
    from .eval.statistics import ellipsoid_coverage

    starts = sorted({c["start_s"] for c in cells})
    names = sorted({c["case"] for c in cells})
    colours = dict(zip(names, (C_OK, C_ERR, C_CLAIM, C_GREY), strict=False))
    rows = (
        ("ate_rmse_m", "ATE RMSE (m)", False),
        ("nees_mean", "mean NEES", True),
        ("coverage_2sigma_pct", "2-sigma coverage (%)", False),
    )
    fig, axes = plt.subplots(len(rows), len(starts), figsize=(3.6 * len(starts) + 0.8, 7.2), squeeze=False, sharex=True)
    expected_cov = 100.0 * ellipsoid_coverage(2.0, 3)
    for j, start in enumerate(starts):
        for i, (metric, label, logy) in enumerate(rows):
            ax = axes[i][j]
            for name in names:
                pts = sorted(
                    (c["duration_s"], c[metric])
                    for c in cells
                    if c["case"] == name and c["start_s"] == start and c[metric]
                )
                if not pts:
                    continue
                x = [d for d, _ in pts]
                ax.plot(
                    x, [m["mean"] for _, m in pts], marker="o", markersize=4, color=colours[name], label=name, zorder=3
                )
                ax.fill_between(
                    x, [m["lo"] for _, m in pts], [m["hi"] for _, m in pts], color=colours[name], alpha=0.18, zorder=2
                )
            if metric == "nees_mean":
                ax.axhline(3.0, color=C_GREY, linestyle="--", linewidth=1.0)
            if metric == "coverage_2sigma_pct":
                ax.axhline(expected_cov, color=C_GREY, linestyle="--", linewidth=1.0)
                ax.set_ylim(0, 105)
            if logy:
                ax.set_yscale("log")
            _style(
                ax,
                f"outage starts at {start:g} s" if i == 0 else "",
                "outage duration (s)" if i == len(rows) - 1 else "",
                label if j == 0 else "",
            )
    axes[0][0].legend(fontsize=7, frameon=False)
    fig.text(
        0.01,
        0.005,
        "Synthetic fixture. Dashed = calibrated. Band = bootstrap 95% over noise seeds.",
        fontsize=7,
        color=C_GREY,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=Path("results") / "benchmark.json")
    ap.add_argument("--animate", action="store_true", help="also write docs/figures/hero.gif (a few seconds more)")
    args = ap.parse_args(argv)

    if not args.results.exists():
        raise SystemExit(f"{args.results} not found; run `navkit run` first")

    doc = json.loads(args.results.read_text())
    cases = doc["cases"]
    FIGDIR.mkdir(parents=True, exist_ok=True)

    made = [fig_error_vs_claim(cases), fig_coverage(cases)]
    for fn in (fig_outage, fig_nees):
        p = fn(cases)
        if p:
            made.append(p)
    hero = fig_hero(cases, FIGDIR / "hero.png")
    if hero:
        made.append(hero)
    if args.animate:
        gif = animate_hero(cases, FIGDIR / "hero.gif")
        if gif:
            made.append(gif)

    for p in made:
        print(f"wrote {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
