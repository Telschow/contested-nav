"""docs/urbannav.md against the committed CSV, and the clock-offset method against known shifts.

The dataset is not vendored (S2), so CI cannot reread it. It checks that the page is the table the committed CSV
produces and that the prose follows from the CSV. The fetched files, when present, must reproduce the CSV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import urbannav_check as uc
from navkit import urbannav_data as ud
from navkit.types import ImuSample

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "urbannav.md"
CSV = ROOT / "docs" / "data" / "urbannav_data.csv"
FETCHED = ROOT / "data" / "raw" / "urbannav"


@pytest.fixture(scope="module")
def rows():
    return uc.rows_from_csv(CSV)


@pytest.fixture(scope="module")
def q(rows):
    return {r["quantity"]: float(r["value"]) for r in rows}


def test_the_page_block_is_the_table_the_csv_produces(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in uc.BLOCKS.values():
        assert fn(rows) in text


def test_every_quantity_has_a_label(rows):
    assert all(r["quantity"] in uc.LABELS for r in rows)


def test_there_is_one_real_outage_and_it_is_inside_the_recording(q):
    assert q["gnss_outages"] == 1
    assert 0.0 < q["outage_start"] < q["outage_end"] < q["imu_span"]
    assert q["outage_length"] == pytest.approx(q["outage_end"] - q["outage_start"], abs=0.2)
    assert q["gnss_denied_epochs"] == pytest.approx(q["outage_length"], abs=1.0)


def test_the_clocks_agree_to_within_one_search_step(q):
    assert abs(q["clock_offset"]) <= q["clock_offset_grid_step"] + 1e-12


def test_the_fixes_next_to_the_outage_are_worse_than_the_rest(q):
    assert q["fix_error_max_last_valid_before_outage"] > 10 * q["fix_horizontal_error_median"]
    assert q["fix_error_first_valid_after_outage"] > 10 * q["fix_horizontal_error_median"]
    assert q["fix_horizontal_error_max"] == pytest.approx(q["fix_error_max_last_valid_before_outage"])


def test_the_vertical_bias_differs_between_the_two_sides_of_the_outage(q):
    assert abs(q["fix_vertical_bias_before_outage"] - q["fix_vertical_bias_after_outage"]) > 2.0


def test_the_data_section_of_the_page_is_separate_from_the_filter_result():
    text = PAGE.read_text(encoding="utf-8")
    assert "## What the files contain" in text and "## The run" in text
    assert text.index("## What the files contain") < text.index("## The run")


# ----------------------------------------------------------- the offset method


def _sequence(shift_s: float) -> ud.UrbanNavSequence:
    """A turning vehicle where reference time t is IMU time t + ``shift_s``."""
    t = np.arange(0.0, 120.0, 0.0025)
    gz = 0.4 * np.sin(0.3 * t) + 0.3 * np.sin(0.9 * t + 1.0) + 0.2 * np.sin(2.1 * t)
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (gz[1:] + gz[:-1]) * np.diff(t))])
    truth_t = np.arange(3.0, 115.0, 1.0)
    heading = np.degrees(-np.interp(truth_t + shift_s, t, cum)) % 360.0
    n = truth_t.size
    zeros = np.zeros((n, 3))
    rpy = zeros.copy()
    rpy[:, 2] = heading
    ref = ud.Reference(
        truth_t + 1.6e9,
        np.full(n, 2158.0),
        truth_t,
        np.full(n, 22.3),
        np.full(n, 114.2),
        np.zeros(n),
        zeros,
        zeros,
        rpy,
        np.ones(n, dtype=int),
    )
    gyro = np.zeros((t.size, 3))
    gyro[:, 2] = gz + 0.01  # a constant bias must drop out
    imu = ImuSample(t=t, accel=np.tile([0.0, 0.0, 9.8], (t.size, 1)), gyro=gyro)
    return ud.UrbanNavSequence("synthetic", imu, 1.6e9, ref, truth_t, zeros, (22.3, 114.2, 0.0))


@pytest.mark.parametrize("shift", [0.0, 0.05, 0.2, -0.3, 0.7])
def test_the_offset_method_recovers_a_known_shift(shift):
    assert uc.clock_offset(_sequence(shift)) == pytest.approx(shift, abs=0.011)


def test_too_little_overlap_is_an_error():
    seq = _sequence(0.0)
    seq.truth_t = seq.truth_t + 1000.0
    with pytest.raises(uc.SequenceError, match="too little overlap"):
        uc.clock_offset(seq)


# ---------------------------------------------------------------------- the CLI


def test_main_rebuilds_the_page_from_the_csv(tmp_path):
    page = tmp_path / "p.md"
    page.write_text("x\n<!-- urbannav-data:start -->\n<!-- urbannav-data:end -->\ny\n", encoding="utf-8")
    assert uc.main(["--from-csv", str(CSV), "--page", str(page)]) == 0
    assert uc.table_markdown(uc.rows_from_csv(CSV)) in page.read_text(encoding="utf-8")


def test_main_reports_a_page_without_the_markers(tmp_path):
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert uc.main(["--from-csv", str(CSV), "--page", str(page)]) == 1


def test_main_reports_missing_data(tmp_path):
    assert uc.main(["--root", str(tmp_path), "--sequence", "tunnel1"]) == 1


# ------------------------------------------------------------ the real files


def test_the_fetched_files_reproduce_the_committed_csv(rows):
    if not (FETCHED / "tunnel1" / ud.NMEA_FILES["tunnel1"]).is_file():
        pytest.skip("tunnel1 is not fetched with its NMEA file (see docs/urbannav.md)")
    fresh = uc.measure(FETCHED, "tunnel1")
    assert [(r["quantity"], str(r["value"])) for r in fresh] == [(r["quantity"], r["value"]) for r in rows]
