"""docs/separability.md against the committed CSV. The experiment takes about 30 minutes, so CI does not rerun it."""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import separability as sp

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "separability.md"


@pytest.fixture(scope="module")
def rows():
    return sp.rows_from_csv(ROOT / "docs" / "data" / "separability.csv")


def _far(rows, ds, cfg):
    sel = sp.select(rows, ds, cfg)
    return sum(sp.honest_d2(r) > sp.shipped_gate() for r in sel) / len(sel)


def test_blocks_match_csv(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in sp.BLOCKS.values():
        assert fn(rows) in text


def test_default_noise_overlaps(rows):
    assert 0.5 < _far(rows, "euroc", "default") < 0.6


def test_walk_setting_separates(rows):
    assert _far(rows, "euroc", "walk10") == 0.0
    assert _far(rows, "tumvi", "file-walk10") <= 0.02


def test_separation_costs_sensitivity(rows):
    sel = sp.select(rows, "euroc", "walk10")
    g = sp.shipped_gate()
    assert sp.detection_rate(sel, 20.0, g) < 0.05
    assert 0.3 < sp.detection_rate(sel, 100.0, g) < 0.7
    assert sp.detection_rate(sel, 200.0, g) > 0.95


def test_gate_transfer_is_imperfect(rows):
    g = sp.matched_gate(sp.select(rows, "euroc", "walk10"))
    tum = sp.select(rows, "tumvi", "file-walk10")
    assert sum(sp.honest_d2(r) > g for r in tum) / len(tum) > 0.1


def test_spoof_zero_matches_honest(rows):
    r = rows[0]
    assert sp.spoof_d2(r, 0.0).max() == pytest.approx(sp.honest_d2(r))


def test_honest_rows_run_on_a_synthetic_sequence(tmp_path):
    from navkit import euroc_eval as ee

    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=90.0, seed=1)
    got = sp.honest_rows("euroc", tmp_path, ("default",), seeds=1)
    assert got
    assert {r["config"] for r in got} == {"default"}
    assert all(sp.honest_d2(r) >= 0.0 and sp.sigma_m(r) > 0.0 for r in got)


def test_csv_round_trip_and_cli_rebuild(rows, tmp_path, capsys):
    out = tmp_path / "again.csv"
    sp.write_csv(out, rows)
    assert sp.rows_from_csv(out) == rows
    assert sp.main(["--from-csv", str(out), "--markdown"]) == 0
    assert "Honest returns" in capsys.readouterr().out


def test_page_writer_refuses_a_page_without_markers(rows, tmp_path, capsys):
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert sp.main(["--from-csv", str(ROOT / "docs" / "data" / "separability.csv"), "--page", str(page)]) == 1
    assert "error" in capsys.readouterr().err


def test_matched_gate_and_minimum_detected_size(rows):
    sel = sp.select(rows, "euroc", "walk10")
    assert sp.matched_gate(sel) > 0.0
    assert sp.min_detected_m(sel, sp.shipped_gate()) == 200.0
    assert sp.min_detected_m(sel, 1e9) is None
