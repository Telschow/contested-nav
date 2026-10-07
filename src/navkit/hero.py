"""The hero figure and its animation: the error the filter makes against the error it claims.

Two panels, one per case, with the same GNSS outage in both. The control (no vision)
reports an uncertainty that grows through the outage and contains its error. The visual
case reports a small, nearly flat uncertainty while its error leaves the claimed bound.
That gap is the project's result, in one picture.

The claimed bound is the filter's own 2-sigma-per-axis ellipsoid, expressed as a radius.
For an isotropic position covariance with per-axis sigma ``s`` the squared Mahalanobis
radius is ``2**2 * 3``, so the bound on the error norm is ``2 * sqrt(3) * s``; the
benchmark expects 99.3% of epochs inside it. The covariance is not exactly isotropic, so
the bound is an approximation of the ellipsoid in each direction, which is why the
coverage figures in the README come from the ellipsoid itself and not from this picture.

Both functions read only the benchmark result JSON, so a figure can always be traced to a
recorded run.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter

C_ERR = "#1b6ca8"
C_CLAIM = "#c0392b"
C_GREY = "#7f8c8d"
C_OUTAGE = "#f39c12"

#: Radius of the 2-sigma-per-axis ellipsoid in units of the per-axis sigma, for 3 degrees
#: of freedom: sqrt(2**2 * 3).
BOUND_PER_SIGMA = math.sqrt(2.0**2 * 3.0)

PANELS = (
    ("outage_control", "No vision: bound grows with error"),
    ("outage_visual", "Vision: bound stays small, error grows"),
)


def hero_cases(cases: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """The two cases the figure needs, in panel order. Empty if the result lacks them."""
    by_name = {c["name"]: c for c in cases}
    out = []
    for name, title in PANELS:
        case = by_name.get(name)
        if case is None or "claimed_sigma_p_m" not in case.get("error_time_series", {}):
            return []
        out.append((case, title))
    return out


def _series(case: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ts = case["error_time_series"]
    t = np.asarray(ts["t"], float)
    err = np.asarray(ts["position_error_m"], float)
    bound = BOUND_PER_SIGMA * np.asarray(ts["claimed_sigma_p_m"], float)
    return t, err, bound


def _style(ax: Any, title: str, show_ylabel: bool) -> None:
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel("time (s)", fontsize=9)
    if show_ylabel:
        ax.set_ylabel("position error (m)", fontsize=9)
    ax.grid(True, alpha=0.25, linewidth=0.6)
    ax.tick_params(labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _draw(axes: Any, panels: list[tuple[dict[str, Any], str]], upto: float | None) -> None:
    """Draw both panels; ``upto`` clips to a time, for the animation, and ``None`` draws everything."""
    ymax = max(float(np.max(_series(c)[1])) for c, _ in panels) * 1.08
    for i, (ax, (case, title)) in enumerate(zip(axes, panels, strict=True)):
        t, err, bound = _series(case)
        for o in case.get("outages", []):
            ax.axvspan(o["start_s"], o["end_s"], color=C_OUTAGE, alpha=0.16, zorder=0, label="GNSS outage")
        n = len(t) if upto is None else int(np.searchsorted(t, upto, side="right"))
        n = max(n, 2)
        ax.fill_between(t[:n], 0.0, bound[:n], color=C_CLAIM, alpha=0.14, zorder=1)
        ax.plot(t[:n], bound[:n], color=C_CLAIM, linewidth=1.3, zorder=2, label="claimed 2-sigma bound")
        ax.plot(t[:n], err[:n], color=C_ERR, linewidth=1.6, zorder=3, label="actual position error")
        ax.set_xlim(float(t[0]), float(t[-1]))
        ax.set_ylim(0.0, ymax)
        _style(ax, title, show_ylabel=(i == 0))
    axes[1].legend(fontsize=7.5, frameon=False, loc="upper right")


def fig_hero(cases: list[dict[str, Any]], out: Path) -> Path | None:
    """Write the static hero figure. Returns ``None`` when the result lacks the two cases."""
    panels = hero_cases(cases)
    if not panels:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0), sharey=True)
    _draw(axes, panels, upto=None)
    fig.text(
        0.01,
        0.01,
        "Synthetic fixture, 30 s run, seed 0, GNSS denied 5 s to 20 s. "
        "Shaded red = region the filter claims contains the error.",
        fontsize=7,
        color=C_GREY,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def animate_hero(cases: list[dict[str, Any]], out: Path, frames: int = 45, fps: int = 9) -> Path | None:
    """Write the hero figure as a GIF that reveals the run in time order."""
    panels = hero_cases(cases)
    if not panels:
        return None
    t_end = float(_series(panels[0][0])[0][-1])
    # A pause on the finished picture, so the last frame is readable before it loops.
    times = list(np.linspace(0.0, t_end, frames)) + [t_end] * 8
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4), sharey=True)
    fig.tight_layout()

    def update(k: int) -> list[Any]:
        for ax in axes:
            ax.clear()
        _draw(axes, panels, upto=times[k])
        return []

    anim = FuncAnimation(fig, update, frames=len(times), blit=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    anim.save(out, writer=PillowWriter(fps=fps), dpi=100)
    plt.close(fig)
    return out
