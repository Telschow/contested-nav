"""docs/vision_ramp.md against the committed CSV. The sweep takes about an hour, so CI does not rerun it."""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import euroc_eval as ee
from navkit import slow_ramp as sr
from navkit import vision_ramp as vr

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "vision_ramp.md"
CSV = ROOT / "docs" / "data" / "vision_ramp.csv"
CELLS = [(ds, arm) for ds in ("euroc", "tumvi") for arm in sr.ARMS]


@pytest.fixture(scope="module")
def rows():
    return sr.rows_from_csv(CSV)


def _s(rows, front, ds, arm, rate):
    return sr.stats(vr.select(rows, front, ds, arm, rate))


def test_blocks_match_csv(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in vr.BLOCKS.values():
        assert fn(rows) in text


@pytest.mark.parametrize(("ds", "arm"), CELLS)
def test_independent_errors_catch_and_refuse_two_m_s(rows, ds, arm):
    sel = vr.select(rows, "independent", ds, arm, 2.0)
    s = sr.stats(sel)
    assert s["over_gate"] == 1.0 and s["faulted"] == 1.0 and s["captured"] == 0.0
    assert s["median_final_error_m"] < 10.0 < 150.0 < s["median_final_offset_m"]


@pytest.mark.parametrize(("ds", "arm"), CELLS)
def test_one_m_s_is_seen_and_mostly_followed(rows, ds, arm):
    s = _s(rows, "independent", ds, arm, 1.0)
    assert s["over_gate"] == 1.0
    assert s["faulted"] <= 3 / 11 + 1e-9
    assert 9 / 11 - 1e-9 <= s["captured"] <= 1.0


@pytest.mark.parametrize(("ds", "arm"), CELLS)
def test_nothing_is_seen_at_or_below_point_two(rows, ds, arm):
    for rate in (0.05, 0.2):
        s = _s(rows, "independent", ds, arm, rate)
        assert s["over_gate"] == 0.0 and s["captured"] == 1.0


@pytest.mark.parametrize(("ds", "arm"), CELLS)
def test_no_independent_control_run_alarms(rows, ds, arm):
    assert _s(rows, "independent", ds, arm, 0.0)["over_gate"] == 0.0


@pytest.mark.parametrize(("ds", "arm"), CELLS)
def test_correlated_errors_never_refuse_a_ramp(rows, ds, arm):
    for rate in (0.05, 0.2, 0.5, 1.0, 2.0):
        s = _s(rows, "correlated", ds, arm, rate)
        assert s["faulted"] == 0.0 and s["captured"] == 1.0


def test_vision_option_is_serialised_only_when_set():
    assert "vision" not in ee.RunOptions().as_dict()
    assert ee.RunOptions(vision="clone", vision_corr_s=1.0).as_dict()["vision"]["model"] == "clone"


def test_unknown_vision_model_is_rejected(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    with pytest.raises(ee.SequenceError):
        ee.run_sequence(seq, ee.RunOptions(vision="bogus"))


def test_run_case_with_vision_on_a_synthetic_sequence(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    row = sr.run_case(seq, "walk10", "clean", 0.0, 0, extra=vr.FRONT_ENDS["independent"])
    assert row is not None and row["final_error_m"] < 5.0


def test_csv_write_cli_rebuild_and_missing_markers(rows, tmp_path, capsys):
    out = tmp_path / "again.csv"
    vr.write_csv(out, rows)
    assert sr.rows_from_csv(out) == rows
    assert vr.main(["--from-csv", str(out), "--markdown"]) == 0
    assert "Front end" in capsys.readouterr().out
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert vr.main(["--from-csv", str(out), "--page", str(page)]) == 1


def test_sweep_rows_runs_every_front_end(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ARMS", ("clean",))
    monkeypatch.setattr(sr, "RATES_M_S", (0.0,))
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    got = vr.sweep_rows("euroc", tmp_path, ("walk10",), seeds=1)
    assert {r["front_end"] for r in got} == set(vr.FRONT_ENDS)
