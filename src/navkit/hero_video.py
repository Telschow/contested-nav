"""The hero video: an illustrated opener, the synthetic run, and the plain-language result.

Run it by hand. It needs a system ``ffmpeg`` and is not part of CI, so the runtime dependencies stay
numpy, matplotlib and pyyaml. Frames are drawn with matplotlib and piped to ffmpeg as raw pixels.

    navkit hero-video --results results/benchmark.json
    navkit hero-video --results results/benchmark.json --landscape

The first scene is an illustration. It is tagged "Illustration, not data" and shows no numbers. The other
two scenes are the same synthetic run as ``hero-plain.png``: the vision case of seed 0, read from the result
JSON, at the instant chosen by :func:`navkit.hero.plain_instant`. Every number on screen comes from that
file. Each export writes the video, an ``.srt`` with the same captions, and a poster frame.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from .hero import _commit, _series, hero_cases, plain_caption, plain_instant

BG = "#0a1017"
FG = "#e8eef5"
MUTED = "#8fa2b6"
BLUE = "#5aaeff"
RED = "#ff6b6b"
AMBER = "#f2a64b"
ROAD = "#2b3c50"
TUNNEL = "#04080c"

FPS = 15
OUT_FPS = 30
OPENER_S = 7.0
RUN_S = 16.0
RESULT_S = 9.0


@dataclass(frozen=True)
class Caption:
    """A line burned into the video and written to the ``.srt``, in seconds from the start of its scene."""

    start: float
    end: float
    text: str


def opener_captions() -> list[Caption]:
    return [
        Caption(0.0, 2.2, "Your phone's map dot follows the car."),
        Caption(2.2, 4.6, "In a tunnel the signal drops. The dot stops. It still looks sure."),
        Caption(4.6, OPENER_S, "The car keeps going. The map is sure, and wrong."),
    ]


def run_captions(outage: tuple[float, float], t_end: float) -> list[Caption]:
    """Captions of the run scene, in simulation seconds. The scene maps the simulation time onto its length."""
    start, end = outage
    return [
        Caption(0.0, start, "GNSS is available. The filter knows where it is."),
        Caption(start, end, "GNSS is denied. The error climbs. The red claim barely moves."),
        Caption(end, t_end, "GNSS is back."),
    ]


def result_captions(claimed_m: float, error_m: float) -> list[Caption]:
    says, truth = plain_caption(claimed_m, error_m)
    return [
        Caption(0.0, RESULT_S, "The filter is sure. It is wrong."),
        Caption(1.5, RESULT_S, says),
        Caption(3.0, RESULT_S, truth),
        Caption(5.0, RESULT_S, "So camera aiding ships switched off."),
    ]


def _active(captions: list[Caption], t: float) -> str:
    """The text of the last caption that has started and not ended at ``t``, or an empty string."""
    live = [c for c in captions if c.start <= t < c.end]
    return live[-1].text if live else ""


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000.0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries: list[tuple[float, float, str]], out: Path) -> Path:
    """Write ``(start, end, text)`` entries, in seconds from the start of the video, as an ``.srt`` file."""
    blocks = [f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n" for i, (a, b, text) in enumerate(entries, 1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(blocks))
    return out


def _new_figure(width: int, height: int) -> Figure:
    fig = plt.figure(figsize=(width / 100.0, height / 100.0), dpi=100, facecolor=BG)
    return fig


def _scale(width: int, height: int) -> float:
    return min(width, height) / 1080.0


def _caption(fig: Figure, text: str, y: float, size: float, color: str = FG, weight: str = "normal") -> None:
    if text:
        # Wrap to 84 percent of the frame width, so the text keeps a margin instead of running to the edge.
        px_per_char = 0.55 * size * fig.dpi / 72.0
        width = max(10, int(0.84 * fig.get_figwidth() * fig.dpi / px_per_char))
        fig.text(
            0.5, y, textwrap.fill(text, width), ha="center", va="center", fontsize=size, color=color, weight=weight
        )


def _footer(fig: Figure, text: str, scale: float) -> None:
    fig.text(0.5, 0.03, text, ha="center", va="center", fontsize=13 * scale, color=MUTED)


def _stage(fig: Figure, width: int, height: int) -> tuple[Any, float, float]:
    """An axes in pixel units, so that circles stay round. Returns it with its width and height in pixels."""
    rect = (0.06, 0.2, 0.88, 0.58)
    ax = fig.add_axes(rect)
    ws, hs = rect[2] * width, rect[3] * height
    ax.set_xlim(0.0, ws)
    ax.set_ylim(0.0, hs)
    ax.set_aspect("equal")
    ax.axis("off")
    return ax, ws, hs


def _road(u: np.ndarray | float, ws: float, hs: float) -> tuple[np.ndarray, np.ndarray]:
    u = np.asarray(u, float)
    return 0.08 * ws + 0.84 * ws * u, hs * (0.5 + 0.22 * np.sin(2.0 * np.pi * u))


def draw_opener(t: float, width: int, height: int) -> Figure:
    """The illustrated opener at time ``t``: the dot freezes in the tunnel while the car carries on."""
    scale = _scale(width, height)
    fig = _new_figure(width, height)
    ax, ws, hs = _stage(fig, width, height)
    grid = np.linspace(0.0, 1.0, 200)
    rx, ry = _road(grid, ws, hs)
    ax.plot(rx, ry, color=ROAD, linewidth=34 * scale, solid_capstyle="round", zorder=1)
    t0, t1 = 0.40, 0.68
    inside = (grid >= t0) & (grid <= t1)
    ax.plot(rx[inside], ry[inside], color=TUNNEL, linewidth=34 * scale, solid_capstyle="butt", zorder=2)
    tx, ty = _road((t0 + t1) / 2.0, ws, hs)
    ax.text(float(tx), float(ty) + 60 * scale, "tunnel", color=MUTED, fontsize=15 * scale, ha="center", zorder=3)

    u = 0.08 + 0.84 * min(t / OPENER_S, 1.0)
    vx, vy = (float(a) for a in _road(u, ws, hs))
    dx, dy = (float(a) for a in _road(min(u, t0), ws, hs))
    ax.add_patch(Circle((dx, dy), 0.05 * ws, facecolor=BLUE, alpha=0.2, edgecolor=BLUE, linewidth=2, zorder=4))
    ax.plot([dx], [dy], "o", color=BLUE, markersize=14 * scale, zorder=5)
    ax.plot(
        [vx], [vy], "o", markerfacecolor="none", markeredgecolor=FG, markeredgewidth=3, markersize=18 * scale, zorder=5
    )
    ax.text(dx, dy - 0.085 * ws, "map dot", color=BLUE, fontsize=16 * scale, ha="center", zorder=6)
    ax.text(vx, vy + 0.075 * ws, "the car", color=FG, fontsize=16 * scale, ha="center", zorder=6)

    fig.text(0.5, 0.93, "Illustration, not data", ha="center", fontsize=22 * scale, color=AMBER, weight="bold")
    _caption(fig, _active(opener_captions(), t), 0.1, 28 * scale)
    return fig


def draw_run(t_sim: float, case: dict[str, Any], commit: str, width: int, height: int) -> Figure:
    """The vision case revealed up to the simulation time ``t_sim``."""
    scale = _scale(width, height)
    fig = _new_figure(width, height)
    t, err, bound = _series(case)
    outage = (float(case["outages"][0]["start_s"]), float(case["outages"][0]["end_s"]))
    ax = fig.add_axes((0.14, 0.24, 0.8, 0.54), facecolor=BG)
    n = max(int(np.searchsorted(t, t_sim, side="right")), 2)
    ax.axvspan(outage[0], outage[1], color=AMBER, alpha=0.16, zorder=0)
    ax.fill_between(t[:n], 0.0, bound[:n], color=RED, alpha=0.25, zorder=1)
    ax.plot(t[:n], bound[:n], color=RED, linewidth=3 * scale, zorder=2, label="what the filter claims")
    ax.plot(t[:n], err[:n], color=BLUE, linewidth=3.5 * scale, zorder=3, label="actual position error")
    ax.set_xlim(float(t[0]), float(t[-1]))
    ax.set_ylim(0.0, float(np.max(err)) * 1.08)
    ax.set_xlabel("time (s)", color=MUTED, fontsize=16 * scale)
    ax.set_ylabel("position error (m)", color=MUTED, fontsize=16 * scale)
    ax.tick_params(colors=MUTED, labelsize=14 * scale)
    ax.grid(True, alpha=0.2)
    for name, spine in ax.spines.items():
        spine.set_visible(name in ("left", "bottom"))
        spine.set_color(MUTED)
    ax.legend(loc="upper left", fontsize=15 * scale, frameon=False, labelcolor=FG)
    fig.text(0.5, 0.93, "The same run, in time", ha="center", fontsize=22 * scale, color=FG, weight="bold")
    _caption(fig, _active(run_captions(outage, float(t[-1])), t_sim), 0.12, 21 * scale)
    _footer(fig, f"SYNTHETIC RUN, seed 0, vision case. Generated at commit {commit}.", scale)
    return fig


def draw_result(t: float, case: dict[str, Any], commit: str, width: int, height: int) -> Figure:
    """The plain-language result, line by line. At ``t`` past the last caption everything is on screen."""
    scale = _scale(width, height)
    fig = _new_figure(width, height)
    t_s, claimed, error = plain_instant(case)
    ax, ws, hs = _stage(fig, width, height)
    reach = max(error, claimed) * 1.25
    ax.set_xlim(-reach * 0.15, reach)
    span = (reach * 1.15) * hs / ws
    ax.set_ylim(-span / 2.0, span / 2.0)
    ax.add_patch(Circle((0.0, 0.0), claimed, facecolor=RED, alpha=0.3, edgecolor=RED, linewidth=2))
    ax.plot([0.0], [0.0], "o", color=MUTED, markersize=9 * scale)
    ax.plot([error], [0.0], "o", color=BLUE, markersize=18 * scale)
    ax.annotate(
        "what the filter claims",
        (0.0, claimed),
        (reach * 0.02, span * 0.22),
        color=RED,
        fontsize=18 * scale,
        arrowprops={"arrowstyle": "-", "color": RED},
    )
    ax.annotate(
        "where the vehicle is",
        (error, 0.0),
        (error * 0.45, -span * 0.22),
        color=BLUE,
        fontsize=18 * scale,
        arrowprops={"arrowstyle": "-", "color": BLUE},
    )
    caps = result_captions(claimed, error)
    fig.text(0.5, 0.92, caps[0].text, ha="center", fontsize=28 * scale, color=FG, weight="bold")
    if t >= caps[1].start:
        _caption(fig, caps[1].text, 0.17, 26 * scale, RED)
    if t >= caps[2].start:
        _caption(fig, caps[2].text, 0.12, 26 * scale, BLUE, "bold")
    if t >= caps[3].start:
        _caption(fig, caps[3].text, 0.075, 22 * scale)
    _footer(
        fig,
        f"SYNTHETIC RUN, seed 0, vision case, t = {t_s:.1f} s. Drawn to scale. Generated at commit {commit}.",
        scale,
    )
    return fig


def _frame_bytes(fig: Figure) -> bytes:
    fig.canvas.draw()
    return bytes(fig.canvas.buffer_rgba())  # type: ignore[attr-defined]


def encode(frames: list[bytes], width: int, height: int, out: Path) -> Path:
    """Pipe raw RGBA frames to ffmpeg as H.264. Raises ``SystemExit`` when ffmpeg is missing."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not found; install it to export the video (it is not a Python dependency)")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(OUT_FPS),
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    proc = subprocess.run(cmd, input=b"".join(frames), capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {proc.stderr.decode(errors='replace')}")
    return out


def export(
    cases: list[dict[str, Any]], out_dir: Path, landscape: bool = False, commit: str | None = None
) -> list[Path]:
    """Write the video, the ``.srt`` and the poster into ``out_dir``. Returns the paths, empty without the cases."""
    panels = hero_cases(cases)
    if not panels:
        return []
    case = panels[1][0]
    commit = commit or _commit()
    width, height = (1920, 1080) if landscape else (1080, 1920)
    tag = "landscape" if landscape else "portrait"
    t, _, _ = _series(case)
    t_end = float(t[-1])
    _, claimed, error = plain_instant(case)

    frames: list[bytes] = []
    scenes: list[tuple[float, Callable[[float], Figure]]] = [
        (OPENER_S, lambda s: draw_opener(s, width, height)),
        (RUN_S, lambda s: draw_run(s / RUN_S * t_end, case, commit, width, height)),
        (RESULT_S, lambda s: draw_result(s, case, commit, width, height)),
    ]
    for seconds, draw in scenes:
        for k in range(max(int(round(seconds * FPS)), 1)):
            fig = draw(k / FPS)
            frames.append(_frame_bytes(fig))
            plt.close(fig)
    poster = draw_result(RESULT_S, case, commit, width, height)

    entries: list[tuple[float, float, str]] = []
    offset = 0.0
    for c in opener_captions():
        entries.append((offset + c.start, offset + c.end, c.text))
    offset += OPENER_S
    outage = (float(case["outages"][0]["start_s"]), float(case["outages"][0]["end_s"]))
    for c in run_captions(outage, t_end):
        entries.append((offset + c.start / t_end * RUN_S, offset + c.end / t_end * RUN_S, c.text))
    offset += RUN_S
    for c in result_captions(claimed, error):
        entries.append((offset + c.start, offset + c.end, c.text))

    out_dir.mkdir(parents=True, exist_ok=True)
    video = encode(frames, width, height, out_dir / f"hero-{tag}.mp4")
    srt = write_srt(entries, out_dir / f"hero-{tag}.srt")
    poster_path = out_dir / f"hero-{tag}-poster.png"
    poster.savefig(poster_path, dpi=100, facecolor=BG)
    plt.close(poster)
    return [video, srt, poster_path]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=Path("results") / "benchmark.json")
    ap.add_argument("--out", type=Path, default=Path("results") / "hero-video")
    ap.add_argument("--landscape", action="store_true", help="1920x1080 instead of 1080x1920")
    args = ap.parse_args(argv)
    if not args.results.exists():
        raise SystemExit(f"{args.results} not found; run `navkit run` first")
    cases = json.loads(args.results.read_text())["cases"]
    paths = export(cases, args.out, landscape=args.landscape)
    if not paths:
        raise SystemExit("the result lacks the outage_control and outage_visual cases")
    for p in paths:
        print(f"wrote {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
