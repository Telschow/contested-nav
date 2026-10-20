"""The B1 gate table on ``docs/calibration.md`` is the committed development CSV, and the prose says no more than that.

This reads only the CSV and the page, so it runs in a documentation-only pull request. The function is tested in
``test_b1_gate.py`` and the cases in ``test_b1_gate_run.py``. The held-out set (seeds 100 to 124) is not in this file.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from navkit import b1_gate
from navkit.eval import gate

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "b1_gate_dev.csv"
PAGE = ROOT / "docs" / "calibration.md"

CONDITIONS = ["nees_upper", "nees_lower", "coverage", "ate_better", "ate_median", "ate_worst"]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return b1_gate.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    page = PAGE.read_text(encoding="utf-8")
    return " ".join(
        page[page.index("## The B1 gate on the development seeds") : page.index("## Worked example")].split()
    )


def test_the_page_table_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == b1_gate.splice_table(page, b1_gate.markdown_table(rows))


def test_the_csv_round_trips_to_the_same_bytes(rows):
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(b1_gate.CSV_FIELDS)
    assert b1_gate.csv_text(rows) == text


def test_the_committed_file_is_the_development_set_and_nothing_else(rows):
    assert {r["seeds"] for r in rows} == {"0-24"}
    assert {r["n_runs"] for r in rows} == {b1_gate.GATE_RUNS}
    assert not b1_gate._touches_held_out(b1_gate.parse_seeds("0-24"))


def test_the_rows_are_the_candidate_and_two_labelled_diagnostics(rows):
    subjects = []
    for r in rows:
        if (r["role"], r["subject"]) not in subjects:
            subjects.append((r["role"], r["subject"]))
    assert subjects == [
        ("candidate", "outage_visual+clone+measured-front-end"),
        ("DIAGNOSTIC", "outage_visual"),
        ("DIAGNOSTIC", "outage_visual_clone"),
    ]
    for _, name in subjects:
        assert [r["condition"] for r in rows if r["subject"] == name] == CONDITIONS


def test_every_condition_has_its_value_and_threshold_in_the_table(rows):
    page = PAGE.read_text(encoding="utf-8")
    for r in rows:
        c = r["condition"]
        assert b1_gate._format_value(c, r["value"]) in page
        assert b1_gate._format_threshold(c, r["relation"], r["threshold"]) in page


def test_the_thresholds_in_the_file_are_the_adr_constants(rows):
    for r in rows:
        t = {x["condition"]: x["threshold"] for x in rows if x["subject"] == r["subject"]}
        assert t["nees_lower"] == gate.B1_LOWER_BOUND_PER_DOF * r["dof"]
        assert t["coverage"] == gate.B1_COVERAGE_MIN
        assert t["ate_median"] == gate.B1_MEDIAN_RATIO_MAX and t["ate_worst"] == gate.B1_WORST_RATIO_MAX
        assert t["ate_better"] == math.ceil(round(gate.B1_BETTER_FRACTION_MIN * r["n_runs"], 9))
        assert r["degrees_of_freedom"] == math.floor(r["dof"] * r["sum_n_eff"])


def test_the_rows_are_consistent_with_their_own_relations(rows):
    for r in rows:
        holds = r["value"] <= r["threshold"] if r["relation"] == "<=" else r["value"] >= r["threshold"]
        assert holds == r["passed"], (r["subject"], r["condition"])
    for name in {r["subject"] for r in rows}:
        mine = [r for r in rows if r["subject"] == name]
        assert {r["subject_passed"] for r in mine} == {all(r["passed"] for r in mine)}


def test_the_anchor_diagnostic_does_not_pass_the_gate(rows):
    """The gate has to be able to say no. The single-anchor model is the case it must say no to."""
    anchor = [r for r in rows if r["subject"] == "outage_visual"]
    assert anchor and not anchor[0]["subject_passed"]
    assert not next(r for r in anchor if r["condition"] == "nees_upper")["passed"]


def test_the_prose_says_what_this_is_and_what_it_is_not(section):
    for phrase in (
        "This section is the development set, seeds 0 to 24",
        "It uses seeds 100 to 124, it is evaluated once",
        "navkit gate b1 --seeds 0-24 --csv docs/data/b1_gate_dev.csv --page docs/calibration.md",
        "The DIAGNOSTIC rows apply the same function",
        "They are not gate decisions",
        "It does not decide B1 and it does not change `vision_enabled`",
    ):
        assert phrase in section, phrase


def test_the_prose_gives_no_verdict_on_b1(section):
    low = section.lower()
    for forbidden in (
        "calibrated",
        "b1 is closed",
        "b1 passes",
        "b1 fails",
        "gate passes",
        "gate fails",
        "meets the gate",
    ):
        assert forbidden not in low, forbidden
