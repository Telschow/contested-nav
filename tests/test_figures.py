"""Each benchmark figure selects exactly the cases its docstring and the page say it shows."""

from __future__ import annotations

import numpy as np
import pytest

from navkit import figures


def _case(name: str, nees: float | None = 3.0, series: bool = True) -> dict:
    case: dict = {"name": name, "headline": {"nees_mean": nees}, "outages": [{"start_s": 5.0, "end_s": 20.0}]}
    if series:
        t = np.linspace(0.0, 30.0, 31)
        case["error_time_series"] = {"t": t.tolist(), "position_error_m": (0.1 * t).tolist()}
    return case


CASES = [
    _case("gnss_only"),
    _case("dead_reckoning", nees=None),
    _case("outage_control"),
    _case("outage_visual"),
    _case("outage_visual_clone"),
    _case("outage_visual_degraded_camera"),
    _case("vision_only_clone"),
]


def test_the_outage_figure_shows_the_two_outage_cases_and_no_others() -> None:
    assert [c["name"] for c in figures.outage_cases(CASES)] == ["outage_control", "outage_visual"]


def test_the_outage_figure_is_two_panels_wide(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(figures, "FIGDIR", tmp_path)
    out = figures.fig_outage(CASES)
    assert out is not None
    width, height = _png_size(out)
    # Two panels of 5.0 x 3.8 inches at 160 dpi. A substring selection made it as wide as the benchmark is long.
    assert (width, height) == pytest.approx((1600, 608), abs=40)


def test_the_outage_figure_is_skipped_when_a_case_is_missing() -> None:
    assert figures.outage_cases([c for c in CASES if c["name"] != "outage_visual"]) == []


def test_the_nees_figure_shows_every_case_that_has_a_nees() -> None:
    names = [c["name"] for c in figures.nees_cases(CASES)]
    assert names == [c["name"] for c in CASES if c["headline"]["nees_mean"] is not None]
    assert "dead_reckoning" not in names


def _png_size(path) -> tuple[int, int]:
    import struct

    data = path.read_bytes()
    return struct.unpack(">II", data[16:24])
