"""docs/product_management/04_sensor_sync_and_calibration_spec.md against the committed timing CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import timing_check as tc

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "product_management" / "04_sensor_sync_and_calibration_spec.md"
CSV = ROOT / "docs" / "data" / "timing.csv"
GNSS_SIGMA_M = 0.8


@pytest.fixture(scope="module")
def rows():
    return [{k: (v if k in ("sequence", "dataset") else float(v)) for k, v in r.items()} for r in tc.rows_from_csv(CSV)]


def _by(rows, dataset):
    return [r for r in rows if r["dataset"] == dataset]


def test_the_page_table_is_what_the_csv_produces():
    text = PAGE.read_text(encoding="utf-8")
    block = text.split("<!-- timing:start -->", 1)[1].split("<!-- timing:end -->", 1)[0].strip("\n")
    assert block == tc.table_markdown(tc.rows_from_csv(CSV))


def test_the_csv_covers_both_datasets_and_every_sequence(rows):
    assert tuple(tc.rows_from_csv(CSV)[0]) == tc.CSV_COLUMNS
    assert len(_by(rows, "EuRoC MAV")) == 11 and len(_by(rows, "TUM VI")) == 6


def test_statement_1_no_recording_has_a_long_imu_gap(rows):
    assert all(r["imu_long_gaps"] == 0 for r in rows)
    assert all(abs(r["imu_rate_hz"] - 200.0) < 1e-3 for r in _by(rows, "EuRoC MAV"))
    assert all(199.0 < r["imu_rate_hz"] < 199.9 for r in _by(rows, "TUM VI"))


def test_statement_2_euroc_truth_has_no_dropouts_and_tum_vi_has_them_in_every_room(rows):
    assert all(
        r["truth_gap_fraction"] == 0.0 and abs(r["truth_rate_hz"] - 200.0) < 1e-3 for r in _by(rows, "EuRoC MAV")
    )
    tum = _by(rows, "TUM VI")
    assert all(r["truth_gap_fraction"] > 0.0 and 100.0 < r["truth_rate_hz"] < 125.0 for r in tum)
    assert sum(r["truth_gap_fraction"] > 0.05 for r in tum) == 2  # two rooms spend about a tenth in dropouts


def test_statement_3_the_offsets_are_small_and_the_displacement_is_far_below_the_gnss_noise(rows):
    assert all(abs(r["offset_ms"]) < 5.0 for r in rows)
    assert all(r["offset_displacement_mm"] < 1e3 * GNSS_SIGMA_M / 100.0 for r in rows)  # under 1% of the GNSS sigma


def test_statement_4_the_estimates_are_meaningful(rows):
    assert all(r["correlation_peak"] > 0.85 for r in rows)
    assert all(r["correlation_peak"] - r["correlation_at_zero"] < 0.01 for r in rows)
    assert all(r["correlation_peak"] >= r["correlation_at_zero"] for r in rows)


def test_statement_5_the_two_methods_agree(rows):
    assert all(abs(r["offset_ms"] - r["offset_magnitude_ms"]) < 5.0 for r in rows)


def test_statement_6_the_tum_vi_alignment_holds_up(rows):
    assert all(abs(r["offset_ms"]) < 3.0 for r in _by(rows, "TUM VI"))


def test_the_page_names_its_limits():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in (
        "filtered estimate built from the inertial data",
        "needs the platform to turn",
        "no latency compensation",
        "what a real system would still need",
    ):
        assert phrase in text, phrase
