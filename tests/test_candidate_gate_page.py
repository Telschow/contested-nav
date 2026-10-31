"""The candidate gate table on ``docs/calibration.md`` is the committed development CSV, and the prose says no more.

This reads only the CSV, the page and the pool file, so it runs in a documentation-only pull request. The function is
tested in ``test_candidate_gate.py`` and the cases in ``test_candidate_gate_run.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from navkit import candidate_gate as run
from navkit.eval import candidate_gate as cg
from navkit.report.page import splice_block

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "candidate_gate_dev.csv"
PAGE = ROOT / "docs" / "calibration.md"
CONDITIONS = ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return run.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    page = PAGE.read_text(encoding="utf-8")
    start = page.index("## The candidate gate of ADR-0030 on the development seeds")
    return " ".join(page[start:].split("\n## ", 1)[0].split())


def test_the_page_table_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "candidate-gate-dev", run.markdown_table(rows))


def test_the_csv_round_trips_to_the_same_bytes(rows):
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(run.CSV_FIELDS)
    assert run.csv_text(rows) == text


def test_the_file_is_the_development_run_on_seeds_25_to_49_and_nothing_held_out(rows):
    assert {r["seeds"] for r in rows} == {"25-49"}
    assert {r["n_runs"] for r in rows} == {cg.CANDIDATE_GATE_RUNS}
    assert max(int(s) for s in ["25", "49"]) < 100


def test_the_subjects_are_the_candidate_and_two_labelled_diagnostics_in_both_scenarios(rows):
    seen = []
    for r in rows:
        key = (r["role"], r["subject"], r["scenario"])
        if key not in seen:
            seen.append(key)
    assert seen == [
        ("candidate", "outage_visual+clone+measured-front-end", "S1"),
        ("candidate", "outage_visual+clone+measured-front-end", "S2"),
        ("DIAGNOSTIC", "outage_visual_clone", "S1"),
        ("DIAGNOSTIC", "outage_visual_clone", "S2"),
        ("DIAGNOSTIC", "outage_visual", "S1"),
        ("DIAGNOSTIC", "outage_visual", "S2"),
    ]
    for role, subject, scenario in seen:
        assert [
            r["condition"] for r in rows if (r["role"], r["subject"], r["scenario"]) == (role, subject, scenario)
        ] == CONDITIONS


def test_every_value_and_threshold_is_in_the_table(rows):
    page = PAGE.read_text(encoding="utf-8")
    for r in rows:
        assert run._format_value(r["condition"], r["value"]) in page
        assert run._format_threshold(r["condition"], r["relation"], r["threshold"]) in page


def test_the_thresholds_in_the_file_are_the_adr_constants(rows):
    for r in rows:
        t = {
            x["condition"]: x["threshold"]
            for x in rows
            if (x["subject"], x["scenario"]) == (r["subject"], r["scenario"])
        }
        assert t["lower"] == cg.CANDIDATE_GATE_LOWER_PER_DOF * 3
        assert t["coverage"] == cg.CANDIDATE_GATE_COVERAGE_MIN
        assert (
            t["median_ratio"] == cg.CANDIDATE_GATE_MEDIAN_RATIO_MAX
            and t["worst_ratio"] == cg.CANDIDATE_GATE_WORST_RATIO_MAX
        )
        assert t["better"] == 20
        assert r["upper_quantile"] == cg.CANDIDATE_GATE_UPPER_QUANTILE
        assert r["m"] >= 1.0


def test_flags_follow_the_relations_and_roll_up(rows):
    for r in rows:
        holds = r["value"] <= r["threshold"] if r["relation"] == "<=" else r["value"] >= r["threshold"]
        assert holds == r["passed"], (r["subject"], r["scenario"], r["condition"])
    for r in rows:
        mine = [x for x in rows if (x["subject"], x["scenario"]) == (r["subject"], r["scenario"])]
        assert r["scenario_passed"] == all(x["passed"] for x in mine)
        both = [x for x in rows if x["subject"] == r["subject"]]
        assert r["subject_passed"] == all(x["passed"] for x in both)


def test_the_anchor_diagnostic_fails_s1(rows):
    anchor = [r for r in rows if r["subject"] == "outage_visual" and r["scenario"] == "S1"]
    assert anchor and not anchor[0]["scenario_passed"]


def _failed(rows, role, subject, scenario):
    return {
        r["condition"]
        for r in rows
        if (r["role"], r["subject"], r["scenario"]) == (role, subject, scenario) and not r["passed"]
    }


FOUR = {"upper", "coverage", "better", "worst_ratio"}
CANDIDATE = "outage_visual+clone+measured-front-end"


def test_the_plain_clone_passes_s1_and_fails_s2_on_four_conditions(rows):
    assert _failed(rows, "DIAGNOSTIC", "outage_visual_clone", "S1") == set()
    assert _failed(rows, "DIAGNOSTIC", "outage_visual_clone", "S2") == FOUR


def test_the_candidate_fails_s1_on_the_lower_bound_only_and_s2_on_the_same_four_conditions(rows):
    assert _failed(rows, "candidate", CANDIDATE, "S1") == {"lower"}
    assert _failed(rows, "candidate", CANDIDATE, "S2") == FOUR


def test_the_single_anchor_fails_both_scenarios(rows):
    for scenario in ("S1", "S2"):
        mine = [
            r for r in rows if (r["role"], r["subject"], r["scenario"]) == ("DIAGNOSTIC", "outage_visual", scenario)
        ]
        assert mine and not mine[0]["scenario_passed"], scenario


def test_the_prose_states_what_the_table_shows_and_what_the_cause_was(section):
    text = " ".join(section.split())
    for phrase in (
        "The plain clone `outage_visual_clone` passes all six conditions in S1.",
        "In S2 it fails the upper edge, the coverage, the paired count and the largest ratio.",
        "fails one condition in S1, the lower bound on the median NEES, and fails the same four conditions in S2",
        "The single anchor `outage_visual` fails both scenarios.",
        "no longer meets S2 on the synthetic fixture",
        "was produced on a different fixture and is not affected",
        "the generator and the filter using different noise conventions",
    ):
        assert phrase in text, phrase


def test_the_prose_explains_the_conditions_and_the_scenarios_and_says_it_is_the_development_run(section):
    for phrase in (
        "development run",
        "S1",
        "S2",
        "(U)",
        "(L)",
        "(C)",
        "(P)",
        "ADR-0030",
        "is a separate maintainer decision",
        "navkit gate candidate --seeds 25-49 --csv docs/data/candidate_gate_dev.csv --page docs/calibration.md",
    ):
        assert phrase in section, phrase


def test_the_prose_gives_no_verdict_on_b1(section):
    low = section.lower()
    for forbidden in (
        "b1 is closed",
        "b1 passes",
        "b1 fails",
        "gate passes",
        "gate fails",
        "meets the gate",
        "calibrated",
    ):
        assert forbidden not in low, forbidden


def test_the_prose_types_no_decimal_number_or_percentage(section):
    prose = section.split("<!-- candidate-gate-dev:start -->")[0] + section.split("<!-- candidate-gate-dev:end -->")[1]
    assert not re.search(r"\d\.\d|\d%", prose), prose[:300]
