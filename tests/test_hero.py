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
    with Image.open(out) as image:
        fmt = image.format
    assert fmt == "PNG"
    assert hero.fig_hero([], tmp_path / "none.png") is None
    assert not (tmp_path / "none.png").exists()


def test_animate_hero_writes_a_multi_frame_gif_under_the_size_budget(tmp_path: Path) -> None:
    out = hero.animate_hero(_cases(), tmp_path / "hero.gif", frames=6, fps=5)
    assert out is not None
    with Image.open(out) as im:
        fmt, frames = im.format, im.n_frames
    assert fmt == "GIF"
    assert frames > 1
    assert out.stat().st_size < 5 * 1024 * 1024
    assert hero.animate_hero([], tmp_path / "none.gif") is None


def _plain_case(name: str, claimed: float, error: float) -> dict[str, Any]:
    t = [i * 0.5 for i in range(61)]
    return {
        "name": name,
        "error_time_series": {
            "t": t,
            "position_error_m": [error * x / 30.0 for x in t],
            "claimed_sigma_p_m": [claimed] * len(t),
        },
        "outages": [{"start_s": 5.0, "end_s": 20.0}],
    }


def test_plain_instant_is_the_end_of_the_outage_not_a_run_average() -> None:
    case = _plain_case("outage_visual", 0.1, 30.0)
    t, bound, error = hero.plain_instant(case)
    assert t == 20.0
    assert bound == pytest.approx(0.1 * hero.BOUND_PER_SIGMA)
    assert error == pytest.approx(20.0)


def test_plain_instant_uses_the_last_sample_at_or_before_the_outage_end() -> None:
    case = _plain_case("outage_visual", 0.1, 30.0)
    case["outages"] = [{"start_s": 5.0, "end_s": 20.2}]
    assert hero.plain_instant(case)[0] == 20.0
    case["outages"] = [{"start_s": -2.0, "end_s": -1.0}]
    with pytest.raises(ValueError):
        hero.plain_instant(case)


def test_plain_caption_switches_from_centimetres_to_metres() -> None:
    assert hero.plain_caption(0.49, 17.36) == ("It says it is within 49 cm.", "It is 17.4 m off.")
    assert hero.plain_caption(2.0, 0.5) == ("It says it is within 2.0 m.", "It is 50 cm off.")


def test_fig_plain_writes_a_portrait_png_and_returns_none_without_the_cases(tmp_path: Path) -> None:
    cases = [_plain_case("outage_control", 0.3, 2.0), _plain_case("outage_visual", 0.1, 30.0)]
    out = hero.fig_plain(cases, tmp_path / "sub" / "plain.png", commit="abc1234")
    assert out is not None
    with Image.open(out) as image:
        fmt, (w, h) = image.format, image.size
    assert fmt == "PNG"
    assert h > w
    assert hero.fig_plain([], tmp_path / "none.png") is None
    assert not (tmp_path / "none.png").exists()
