"""docs/tumvi.md against the committed per-run CSV.

The dataset is not vendored (S2), so CI cannot rerun the comparison. What it can check is that the page is the
table the committed CSV produces, and that the statements in the prose follow from that CSV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_compare as ec

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "tumvi.md"
CSV = ROOT / "docs" / "data" / "tumvi_compare.csv"
TIMING = ROOT / "docs" / "data" / "timing.csv"
NOMINAL_COVERAGE = 0.9926


@pytest.fixture(scope="module")
def rows():
    return ec.rows_from_csv(CSV)


def _sel(rows, config):
    return [r for r in rows if r.config == config]


def _lost(rs):
    return sum(r.lost for r in rs)


def _median_nees(rs):
    return float(np.median([r.nees_mean for r in rs]))


def _coverage(rs):
    return float(np.mean([r.coverage_2sigma for r in rs]))


def test_the_page_table_is_what_the_csv_produces(rows):
    start, end = ec.markers("tumvi")
    block = PAGE.read_text(encoding="utf-8").split(start, 1)[1].split(end, 1)[0].strip("\n")
    assert block == ec.page_block(rows, ec.DEFAULT_LOST_THRESHOLD)


def test_the_csv_runs_the_three_settings_on_the_same_cases_over_all_six_rooms(rows):
    cases = {c: {(r.sequence, r.start_s, r.outage_s, r.seed) for r in _sel(rows, c)} for c in ec.TUMVI_CONFIGS}
    assert all(cases[c] == cases["file"] for c in cases) and len(cases["file"]) > 0
    assert {r.sequence for r in rows} == {f"room{n}" for n in range(1, 7)}
    assert all(ec.group_of(r.sequence) == "TUM VI room" for r in rows)


def test_claim_1_the_raw_figures_lose_more_than_the_inflated_ones_which_lose_more_than_the_bias_walk_setting(rows):
    assert _lost(_sel(rows, "allan")) > _lost(_sel(rows, "file")) > _lost(_sel(rows, "file-walk10"))
    assert _lost(_sel(rows, "file-walk10")) == 0


def test_claim_2_the_same_ordering_holds_for_calibration(rows):
    nees = [_median_nees(_sel(rows, c)) for c in ("allan", "file", "file-walk10")]
    cov = [_coverage(_sel(rows, c)) for c in ("allan", "file", "file-walk10")]
    assert nees[0] > nees[1] > nees[2]
    assert cov[0] < cov[1] < cov[2]


def test_claim_3_changing_only_the_bias_walk_takes_the_loss_from_some_runs_to_none(rows):
    assert _lost(_sel(rows, "file")) > 0 and _lost(_sel(rows, "file-walk10")) == 0
    assert ec.TUMVI_CONFIGS["file-walk10"] == {"bias_sigma": 0.05, "bias_walk_scale": 10.0}
    assert ec.TUMVI_CONFIGS["file"] == {"bias_sigma": 0.05}  # the same prior and the same noise source


def test_claim_4_the_bias_walk_setting_is_close_to_nominal(rows):
    walk = _sel(rows, "file-walk10")
    assert _median_nees(walk) < 3.0
    assert abs(_coverage(walk) - NOMINAL_COVERAGE) < 0.01


def test_claim_5_the_ordering_also_holds_in_the_rooms_with_the_fewest_dropouts(rows):
    import csv

    with TIMING.open(newline="", encoding="utf-8") as fh:
        gap = {r["sequence"]: float(r["truth_gap_fraction"]) for r in csv.DictReader(fh) if r["dataset"] == "TUM VI"}
    gappy = {room for room, share in gap.items() if share > 0.05}
    assert len(gappy) == 2  # the two rooms the page names
    kept = [r for r in rows if r.sequence not in gappy]
    assert len({r.sequence for r in kept}) == 4
    assert _lost(_sel(kept, "allan")) > _lost(_sel(kept, "file")) > _lost(_sel(kept, "file-walk10"))


def test_every_lost_run_of_a_non_baseline_setting_is_listed_on_the_page(rows):
    text = PAGE.read_text(encoding="utf-8")
    for r in rows:
        if r.config not in ec.BASELINE_CONFIGS and r.lost:
            assert f"| {r.sequence} | {r.start_s:g} | {r.seed} |" in text


def test_the_page_states_the_caveats_the_adr_requires():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in (
        "gnss is simulated",
        "not gnss-denied navigation",
        "start bias is estimated",
        "were not tuned on this dataset",
        "motion capture has dropouts",
        "cc by 4.0",
        "runs can still fail",
    ):
        assert phrase in text, phrase
