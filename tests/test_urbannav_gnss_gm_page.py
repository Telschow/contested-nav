"""The statements of the "A correlated-error GNSS term" section of docs/urbannav.md, each tied to the committed CSVs.

The tests read the committed CSVs, so CI runs them without the dataset (S2).
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from navkit import urbannav_run as ur

ROOT = Path(__file__).resolve().parents[1]
GM_CSV = ROOT / "docs" / "data" / "urbannav_gnss_gm.csv"
RUN_CSV = ROOT / "docs" / "data" / "urbannav_run.csv"
PAGE = ROOT / "docs" / "urbannav.md"
DEEP = "deepurban1"
PAIRS = (("declared", "declared_gm"), ("per_fix", "per_fix_gm"))
HOR_NEES_EXPECTED, ATT_NEES_EXPECTED = 2.0, 3.0


def _median(path: Path, variant: str, quantity: str) -> float:
    with path.open(newline="", encoding="utf-8") as f:
        v = [
            float(r["value"])
            for r in csv.DictReader(f)
            if r["sequence"] == DEEP and r["variant"] == variant and r["quantity"] == quantity
        ]
    assert v, f"no rows for {variant} {quantity}"
    return statistics.median(v)


def _section() -> str:
    return PAGE.read_text(encoding="utf-8").split("## A correlated-error GNSS term", 1)[1].split("\n## ", 1)[0]


def test_the_gm_csv_holds_only_the_two_gm_variants_and_the_declared_constants_are_the_ones_in_code() -> None:
    with GM_CSV.open(newline="", encoding="utf-8") as f:
        assert {r["variant"] for r in csv.DictReader(f)} == set(ur.GM_VARIANTS)
    assert (ur.GM_TAU_S, ur.GM_SIGMA_M) == (30.0, 1.5)


def test_statement_the_term_lowers_the_mean_horizontal_nees_and_it_stays_above_expected() -> None:
    for base, gm in PAIRS:
        assert _median(GM_CSV, gm, "hor_nees_mean") < _median(RUN_CSV, base, "hor_nees_mean")
        assert _median(GM_CSV, gm, "hor_nees_mean") > HOR_NEES_EXPECTED
    assert "lowers the mean horizontal NEES in both variants, and it stays above its expected value" in _section()


def test_statement_coverage_rises_and_stays_below_nominal() -> None:
    for base, gm in PAIRS:
        assert _median(GM_CSV, gm, "hor_inside_95") > _median(RUN_CSV, base, "hor_inside_95")
        assert _median(GM_CSV, gm, "hor_inside_95") < 0.95
    assert "The share of epochs inside the confidence ellipse rises and stays below the nominal level" in _section()


def test_statement_the_position_error_is_essentially_unchanged() -> None:
    for base, gm in PAIRS:
        before = _median(RUN_CSV, base, "hor_rmse_m")
        assert abs(_median(GM_CSV, gm, "hor_rmse_m") - before) < 0.05 * before
    assert "The position error is essentially unchanged" in _section()


def test_statement_the_attitude_nees_is_essentially_unchanged_and_far_above_expected() -> None:
    for base, gm in PAIRS:
        before = _median(RUN_CSV, base, "att_nees_mean")
        assert abs(_median(GM_CSV, gm, "att_nees_mean") - before) < 0.1 * before
        assert _median(GM_CSV, gm, "att_nees_mean") > 3 * ATT_NEES_EXPECTED
    assert "essentially unchanged and stays far above its expected value" in _section()


def test_statement_the_gate_rejects_no_fix_with_or_without_the_term() -> None:
    for variant in ("declared", "per_fix"):
        assert _median(RUN_CSV, variant, "gnss_updates_rejected") == 0
    for variant in ur.GM_VARIANTS:
        assert _median(GM_CSV, variant, "gnss_updates_rejected") == 0
    assert "The gate rejects no fix with the term, as without it" in _section()
