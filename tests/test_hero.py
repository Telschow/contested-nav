"""The hero figure and its animation, built from benchmark result records."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from navkit import hero


def _case(name: str, claimed: float | None) -> dict[str, Any]:
    t = [i * 0.5 for i in range(61)]
    series: dict[str, Any] = {"t": t, "position_error_m": [0.05 * x for x in t]}
    if claimed is not None:
        series["claimed_sigma_p_m"] = [claimed] * len(t)
    return {"name": name, "error_time_series": series, "outages": [{"start_s": 5.0, "end_s": 20.0}]}


def _cases() -> list[dict[str, Any]]:
    return [_case("outage_control", 0.5), _case("outage_visual", 0.2), _case("gnss_only", 0.3)]


def test_the_bound_is_the_two_sigma_per_axis_ellipsoid_radius() -> None:
    # Squared Mahalanobis radius 2^2 * 3 = 12, the 99.3% ellipsoid the README quotes.
    assert pytest.approx(math.sqrt(12.0)) == hero.BOUND_PER_SIGMA


def test_hero_cases_come_back_in_panel_order() -> None:
    names = [c["name"] for c, _ in hero.hero_cases(_cases())]
    assert names == ["outage_control", "outage_visual"]


def test_hero_cases_are_empty_when_a_case_or_the_claimed_series_is_missing() -> None:
    assert hero.hero_cases([_case("outage_control", 0.5)]) == []
    assert hero.hero_cases([_case("outage_control", 0.5), _case("outage_visual", None)]) == []


def test_fig_hero_writes_a_png_and_returns_none_without_the_cases(tmp_path: Path) -> None:
    out = hero.fig_hero(_cases(), tmp_path / "sub" / "hero.png")
    assert out is not None
    assert Image.open(out).format == "PNG"
    assert hero.fig_hero([], tmp_path / "none.png") is None
    assert not (tmp_path / "none.png").exists()


def test_animate_hero_writes_a_multi_frame_gif_under_the_size_budget(tmp_path: Path) -> None:
    out = hero.animate_hero(_cases(), tmp_path / "hero.gif", frames=6, fps=5)
    assert out is not None
    im = Image.open(out)
    assert im.format == "GIF"
    assert im.n_frames > 1
    assert out.stat().st_size < 5 * 1024 * 1024
    assert hero.animate_hero([], tmp_path / "none.gif") is None
