"""docs/euroc.md against the committed per-run CSV.

The dataset is not vendored (S2), so CI cannot rerun the comparison. What it can check is that the
page is the table that the committed CSV produces, and that the statements in the prose follow from
that CSV. A changed number that is not in the CSV fails here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_compare as ec

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "euroc.md"
CSV = ROOT / "docs" / "data" / "euroc_compare.csv"


@pytest.fixture(scope="module")
def rows():
    return ec.rows_from_csv(CSV)


def _block(text: str) -> str:
    start, end = ec.PAGE_MARKERS
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n")


def test_the_page_table_is_what_the_csv_produces(rows):
    assert _block(PAGE.read_text(encoding="utf-8")) == ec.page_block(rows, ec.DEFAULT_LOST_THRESHOLD)


def _group(rows, group, config):
    return [r for r in rows if r.config == config and (group == "all" or ec.group_of(r.sequence) == group)]


def _lost(rs):
    return sum(r.lost for r in rs)


def test_claim_1_the_preset_loses_fewer_runs_overall_and_in_each_environment(rows):
    for group in ("all", "Machine Hall", "Vicon room"):
        assert _lost(_group(rows, group, "preset")) < _lost(_group(rows, group, "default")), group


def test_claim_2_the_default_loses_a_larger_share_on_vicon_than_on_machine_hall(rows):
    share = {
        g: _lost(_group(rows, g, "default")) / len(_group(rows, g, "default")) for g in ("Machine Hall", "Vicon room")
    }
    assert share["Vicon room"] > share["Machine Hall"]


def test_claim_3_the_preset_is_near_nominal_and_not_perfect(rows):
    nees = float(np.median([r.nees_mean for r in _group(rows, "all", "preset")]))
    assert 3.0 / 2.0 <= nees <= 3.0 * 2.0
    assert _lost(_group(rows, "all", "preset")) > 0


def test_claim_4_the_fdir_flag_undercounts_the_lost_runs_of_the_default(rows):
    default = _group(rows, "all", "default")
    assert _lost(default) > sum(r.fdir_faulted for r in default)


def test_claim_5_most_runs_still_lost_with_the_preset_start_early(rows):
    lost = [r for r in rows if r.config == "preset" and r.lost]
    early = [r for r in lost if r.start_s <= 35.0]
    assert len(early) * 2 > len(lost)


def test_every_lost_preset_run_is_listed_on_the_page(rows):
    text = PAGE.read_text(encoding="utf-8")
    for r in rows:
        if r.config == "preset" and r.lost:
            assert f"| {r.sequence} | {r.start_s:g} | {r.seed} |" in text


def test_the_page_states_the_caveats_the_adr_requires():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in ("gnss is simulated", "not gnss-denied navigation", "preset is a tuning", "runs still fail"):
        assert phrase in text, phrase


def test_the_csv_holds_results_and_no_dataset_columns():
    header = CSV.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert tuple(header) == ec.CSV_COLUMNS
    assert not {"timestamp", "accel", "gyro", "position"} & set(header)
