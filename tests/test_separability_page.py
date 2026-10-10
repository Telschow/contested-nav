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
