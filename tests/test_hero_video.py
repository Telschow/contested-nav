"""The hero video: captions, the ``.srt`` and the export, with ffmpeg only where it is installed."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from navkit import hero, hero_video


def _case(name: str, claimed: float, error: float) -> dict[str, Any]:
    t = [i * 0.5 for i in range(61)]
    series = {"t": t, "position_error_m": [error * x / 30.0 for x in t], "claimed_sigma_p_m": [claimed] * len(t)}
    return {"name": name, "error_time_series": series, "outages": [{"start_s": 5.0, "end_s": 20.0}]}


def _cases() -> list[dict[str, Any]]:
    return [_case("outage_control", 0.3, 2.0), _case("outage_visual", 0.1, 30.0)]


def test_srt_time_formats_hours_minutes_seconds_and_milliseconds() -> None:
    assert hero_video.srt_time(0.0) == "00:00:00,000"
    assert hero_video.srt_time(61.5) == "00:01:01,500"
    assert hero_video.srt_time(3723.004) == "01:02:03,004"


def test_write_srt_numbers_the_entries_from_one(tmp_path: Path) -> None:
    out = hero_video.write_srt([(0.0, 1.0, "a"), (1.0, 2.5, "b")], tmp_path / "sub" / "x.srt")
    assert out.read_text() == "1\n00:00:00,000 --> 00:00:01,000\na\n\n2\n00:00:01,000 --> 00:00:02,500\nb\n"


def test_the_opener_has_no_digits() -> None:
    assert not any(ch.isdigit() for c in hero_video.opener_captions() for ch in c.text)


def test_active_caption_is_the_last_one_that_has_started_and_not_ended() -> None:
    caps = hero_video.result_captions(0.49, 17.36)
    assert hero_video._active(caps, 0.5) == "The filter is sure. It is wrong."
    assert hero_video._active(caps, 3.5) == "It is 17.4 m off."
    assert hero_video._active(caps, hero_video.RESULT_S) == ""


def test_result_captions_come_from_the_plain_caption() -> None:
    says, truth = hero.plain_caption(0.49, 17.36)
    texts = [c.text for c in hero_video.result_captions(0.49, 17.36)]
    assert says in texts
    assert truth in texts


def test_export_returns_nothing_without_the_hero_cases(tmp_path: Path) -> None:
    assert hero_video.export([], tmp_path) == []


def test_encode_without_ffmpeg_exits_with_a_clear_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="ffmpeg not found"):
        hero_video.encode([b"\0" * 16], 2, 2, tmp_path / "x.mp4")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs a system ffmpeg")
def test_export_writes_a_video_an_srt_and_a_poster(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hero_video, "OPENER_S", 0.4)
    monkeypatch.setattr(hero_video, "RUN_S", 0.4)
    monkeypatch.setattr(hero_video, "RESULT_S", 0.4)
    paths = hero_video.export(_cases(), tmp_path / "out", commit="abc1234")
    assert [p.suffix for p in paths] == [".mp4", ".srt", ".png"]
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)
    assert paths[1].read_text().startswith("1\n")
