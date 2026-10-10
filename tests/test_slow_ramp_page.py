"""docs/slow_ramp.md against the committed CSV. The sweep takes about 40 minutes, so CI does not rerun it."""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import euroc_eval as ee
from navkit import slow_ramp as sr

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "slow_ramp.md"
CSV = ROOT / "docs" / "data" / "slow_ramp.csv"


@pytest.fixture(scope="module")
def rows():
    return sr.rows_from_csv(CSV)


def _cells(rows):
    for ds, cfgs in sr.SETTINGS.items():
        for c in cfgs:
            for arm in sr.ARMS:
                for rate in sr.RATES_M_S:
                    sel = sr.select(rows, ds, c, arm, rate)
                    if sel:
                        yield ds, c, arm, rate, sel


def test_blocks_match_csv(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in sr.BLOCKS.values():
        assert fn(rows) in text


def test_every_spoofed_run_is_captured(rows):
    spoofed = [r for r in rows if float(r["rate_m_s"]) > 0.0]
    assert spoofed
    assert all(sr.captured(r) for r in spoofed)


def test_no_control_run_is_captured(rows):
    assert not any(sr.captured(r) for r in rows if float(r["rate_m_s"]) == 0.0)


def test_calibrated_clean_euroc_never_goes_over_the_gate(rows):
    sel = [r for r in rows if r["dataset"] == "euroc" and r["config"] == "walk10" and r["arm"] == "clean"]
    assert sel
    assert all(r["first_over_gate_s"] == "" for r in sel)


def test_tumvi_calibrated_first_reaction_is_at_two_m_s(rows):
    for rate in (0.05, 0.2, 0.5, 1.0):
        assert sr.stats(sr.select(rows, "tumvi", "file-walk10", "clean", rate))["over_gate"] == 0.0
    assert sr.stats(sr.select(rows, "tumvi", "file-walk10", "clean", 2.0))["over_gate"] == 0.5


def test_default_noise_reacts_but_never_in_every_run_faulty(rows):
    for _ds, c, _arm, rate, sel in _cells(rows):
        if c in ("default", "file") and rate > 0:
            assert sr.stats(sel)["faulted"] < 1.0
    assert sr.stats(sr.select(rows, "euroc", "default", "clean", 2.0))["over_gate"] == 1.0


def test_error_equals_offset_in_calibrated_settings(rows):
    for _ds, c, _arm, rate, sel in _cells(rows):
        if c in ("walk10", "file-walk10") and rate > 0:
            s = sr.stats(sel)
            assert s["median_final_error_m"] == pytest.approx(s["median_final_offset_m"], rel=0.05)


def test_spoof_option_is_serialised_only_when_set():
    assert "spoof" not in ee.RunOptions().as_dict()
    assert ee.RunOptions(spoof=(35.0, 1.0)).as_dict()["spoof"] == [35.0, 1.0]


def test_run_case_on_a_synthetic_sequence_follows_the_ramp(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    control = sr.run_case(seq, "walk10", "clean", 0.0, 0)
    spoofed = sr.run_case(seq, "walk10", "clean", 1.0, 0)
    assert control is not None and spoofed is not None
    assert spoofed["final_offset_m"] > 20.0
    assert spoofed["final_error_m"] > 0.5 * spoofed["final_offset_m"]
    assert control["final_error_m"] < 5.0


def test_a_recording_too_short_for_the_ramp_is_skipped(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    assert sr.run_case(seq, "walk10", "clean", 1.0, 0) is None


def test_csv_round_trip_cli_rebuild_and_missing_markers(rows, tmp_path, capsys):
    out = tmp_path / "again.csv"
    sr.write_csv(out, rows)
    assert sr.rows_from_csv(out) == rows
    assert sr.main(["--from-csv", str(out), "--markdown"]) == 0
    assert "Over the gate" in capsys.readouterr().out
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert sr.main(["--from-csv", str(out), "--page", str(page)]) == 1
