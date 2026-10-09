"""docs/attribution.md against the committed per-run CSV.

The experiment takes about ten minutes, so CI does not rerun it. It checks that the page is the tables the committed
CSV produces and that each statement in the prose follows from that CSV.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import attribution as at

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "attribution.md"
CSV = ROOT / "docs" / "data" / "attribution.csv"
FAULT = "accelerometer bias step"


@pytest.fixture(scope="module")
def rows():
    return at.rows_from_csv(CSV)


def _ab(rows, arm):
    return at._mean(rows, "ablation", arm)


def _esc(rows, source, scale):
    return at._mean(rows, "escalation", source, scale)


def test_every_table_on_the_page_is_what_the_csv_produces(rows):
    text = PAGE.read_text(encoding="utf-8")
    for name, build in at.BLOCKS.items():
        start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
        assert text.split(start, 1)[1].split(end, 1)[0].strip("\n") == build(rows), name


def test_the_csv_has_the_four_experiments_with_their_arms(rows):
    assert tuple(rows[0]) == at.CSV_COLUMNS
    assert {r["experiment"] for r in rows} == {"ablation", "escalation", "growth", "fault"}
    assert {r["arm"] for r in rows if r["experiment"] == "growth"} == set(at.GROWTH_ARMS)
    assert {float(r["param"]) for r in rows if r["experiment"] == "fault"} == set(at.FAULT_SIZES)


def test_statement_1_removing_an_inertial_error_source_does_not_change_the_outage_error(rows):
    base = _ab(rows, "baseline")
    for arm in (f"no {s}" for s in at.SOURCES):
        assert abs(_ab(rows, arm) / base - 1) < 0.02, arm
    assert abs(_ab(rows, "no inertial errors") / base - 1) < 0.02


def test_statement_2_making_the_start_exact_does(rows):
    base = _ab(rows, "baseline")
    assert _ab(rows, "start known exactly") < 0.15 * base
    assert _ab(rows, "start known exactly, no inertial errors") < 0.15 * base
    assert _ab(rows, "GNSS noise x0.1") < 0.30 * base


def test_statement_3_a_source_has_to_be_far_larger_than_the_units_before_it_matters(rows):
    base = _ab(rows, "baseline")
    for source in at.SOURCES:
        for scale in (3.0, 10.0):
            assert abs(_esc(rows, source, scale) / base - 1) < 0.10, (source, scale)
        assert _esc(rows, source, 100.0) / base - 1 > 0.20, source
    first = [s for s in at.SOURCES if _esc(rows, s, 30.0) / base - 1 > 0.25]
    assert first == ["gyroscope white noise"]


def test_statement_4_the_error_grows_the_same_way_with_or_without_inertial_errors(rows):
    a, b = at.exponent(rows, "baseline"), at.exponent(rows, "no inertial errors")
    assert abs(a - b) < 0.05 and 1.0 < a < 2.0 and 1.0 < b < 2.0


def test_statement_5_the_method_finds_a_source_when_there_is_one(rows):
    base = at.exponent(rows, "baseline")
    assert at.exponent(rows, "gyroscope bias x300") - base > 0.5
    for arm in ("accelerometer bias x100", "accelerometer white noise x100", "gyroscope white noise x30"):
        assert abs(at.exponent(rows, arm) - base) < 0.2, arm


def test_statement_6_a_small_and_a_moderate_bias_fault_are_not_noticed(rows):
    base = at._mean(rows, "fault", FAULT, 0.0)
    assert abs(at._mean(rows, "fault", FAULT, 0.05) / base - 1) < 0.10
    assert 0.25 < at._mean(rows, "fault", FAULT, 0.2) / base - 1 < 0.50
    for size in (0.05, 0.2):
        assert at._mean(rows, "fault", FAULT, size, "gnss_rejected") == 0.0
        assert at._mean(rows, "fault", FAULT, size, "gnss_faulted") == 0.0


def test_statement_7_a_large_bias_fault_makes_the_filter_reject_the_healthy_gnss(rows):
    assert at._mean(rows, "fault", FAULT, 1.0, "gnss_rejected") > 0.0
    assert at._mean(rows, "fault", FAULT, 1.0, "gnss_faulted") == 1.0
    assert at._mean(rows, "fault", FAULT, 1.0, "error_after_return_m") > at._mean(rows, "fault", FAULT, 1.0)


def test_the_page_states_what_it_does_not_show():
    text = PAGE.read_text(encoding="utf-8").lower()
    for phrase in (
        "synthetic fixture only",
        "peak error inside the outage",
        "does not say that inertial errors never matter",
    ):
        assert phrase in text, phrase
