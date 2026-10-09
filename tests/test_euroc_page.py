"""docs/euroc.md against the committed per-run CSV files.

The dataset is not vendored (S2), so CI cannot rerun the comparison. What it can check is that the
page is the tables that the committed CSV files produce, and that the statements in the prose follow
from them. A changed number that is not in a CSV fails here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_compare as ec

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "euroc.md"
MAIN = ROOT / "docs" / "data" / "euroc_compare.csv"
CHECKS = ROOT / "docs" / "data" / "euroc_validation.csv"
NOMINAL_COVERAGE = 0.9926  # P(chi-square, 3 dof, <= 12), the value the FAQ derives


@pytest.fixture(scope="module")
def rows():
    return ec.rows_from_csv(MAIN)


@pytest.fixture(scope="module")
def checks():
    return ec.rows_from_csv(CHECKS)


def _block(text: str, name: str) -> str:
    start, end = ec.markers(name)
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n")


def test_the_main_table_is_what_the_csv_produces(rows):
    assert _block(PAGE.read_text(encoding="utf-8"), "euroc") == ec.page_block(rows, ec.DEFAULT_LOST_THRESHOLD)


def test_the_checks_table_is_what_its_csv_produces(checks):
    text = PAGE.read_text(encoding="utf-8")
    assert _block(text, "euroc-validation") == ec.validation_block(checks, ec.DEFAULT_LOST_THRESHOLD)


def _sel(rows, config, group="all", outage=None):
    return [
        r
        for r in rows
        if r.config == config
        and (group == "all" or ec.group_of(r.sequence) == group)
        and (outage is None or r.outage_s == outage)
    ]


def _lost(rs):
    return sum(r.lost for r in rs)


def test_the_main_and_the_later_runs_share_no_case(rows, checks):
    key = lambda r: (r.sequence, r.start_s, r.outage_s, r.seed)  # noqa: E731
    assert not {key(r) for r in rows} & {key(r) for r in checks}


def test_every_configuration_ran_the_same_cases(rows, checks):
    for data in (rows, checks):
        cases = {c: {(r.sequence, r.start_s, r.outage_s, r.seed) for r in data if r.config == c} for c in ec.CONFIGS}
        used = [c for c in cases if cases[c]]
        assert len(used) == 3 and all(cases[c] == cases[used[0]] for c in used)


def test_claim_1_both_presets_lose_fewer_runs_overall_and_in_each_environment(rows):
    for group in ("all", "Machine Hall", "Vicon room"):
        base = _lost(_sel(rows, "default", group))
        assert _lost(_sel(rows, "preset", group)) < base, group
        assert _lost(_sel(rows, "walk10", group)) < base, group


def test_claim_2_the_default_loses_a_larger_share_on_vicon_than_on_machine_hall(rows):
    share = {g: _lost(_sel(rows, "default", g)) / len(_sel(rows, "default", g)) for g in ("Machine Hall", "Vicon room")}
    assert share["Vicon room"] > share["Machine Hall"]


def test_claim_3_the_bias_walk_preset_loses_fewer_runs_than_the_noise_scale_preset(rows):
    assert _lost(_sel(rows, "walk10")) < _lost(_sel(rows, "preset"))


def test_claim_4_in_the_later_checks_the_bias_walk_preset_loses_nothing_and_the_other_does(checks):
    assert len({r.outage_s for r in checks}) >= 2
    for outage in sorted({r.outage_s for r in checks}):
        assert _lost(_sel(checks, "walk10", outage=outage)) == 0, outage
        assert _lost(_sel(checks, "preset", outage=outage)) > 0, outage


def test_claim_5_the_bias_walk_preset_is_slightly_conservative(rows, checks):
    for data, outage in [(rows, None), *[(checks, o) for o in sorted({r.outage_s for r in checks})]]:
        rs = _sel(data, "walk10", outage=outage)
        assert np.mean([r.coverage_2sigma for r in rs]) >= NOMINAL_COVERAGE, outage
        assert np.median([r.nees_mean for r in rs]) < 3.0, outage


def test_claim_6_the_fdir_flag_undercounts_the_lost_runs_of_the_default(rows):
    default = _sel(rows, "default")
    assert _lost(default) > sum(r.fdir_faulted for r in default)


def test_every_lost_noise_scale_run_in_the_main_table_is_listed_on_the_page(rows):
    text = PAGE.read_text(encoding="utf-8")
    for r in rows:
        if r.config == "preset" and r.lost:
            assert f"| {r.sequence} | {r.start_s:g} | {r.seed} |" in text


def test_the_page_states_the_caveats_the_adr_requires():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in (
        "gnss is simulated",
        "not gnss-denied navigation",
        "tunings for one sensor",
        "chosen after looking at failures",
        "runs can still fail",
    ):
        assert phrase in text, phrase


@pytest.mark.parametrize("path", [MAIN, CHECKS])
def test_the_csv_holds_results_and_no_dataset_columns(path):
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert tuple(header) == ec.CSV_COLUMNS
    assert not {"timestamp", "accel", "gyro", "position"} & set(header)
