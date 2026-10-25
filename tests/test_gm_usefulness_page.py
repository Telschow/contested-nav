"""The usefulness section of ``docs/calibration.md`` is the committed CSV, and the prose says no more than the CSV does.

This reads only the CSV and the page, so it runs in a documentation-only pull request. The claims are checked here
from the rows directly, not through :func:`navkit.gm_usefulness.sentences`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from navkit import gm_usefulness as gu

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "gm_s2_usefulness.csv"
PAGE = ROOT / "docs" / "calibration.md"
HEADING = "## Usefulness in scenario S2 with a near-exact model (diagnostic)"
NEES = ("upper", "lower", "coverage")
USEFUL = ("better", "median_ratio", "worst_ratio")


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return gu.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def section(page) -> str:
    start = page.index(HEADING)
    return page[start:].split("\n## ", 1)[0]


def _subject(rows, label):
    return {r["condition"]: r for r in rows if r["subject"] == label}


def test_the_csv_has_the_three_subjects_on_the_development_seeds(rows):
    labels = [s.label for s in gu.SUBJECTS]
    assert sorted({r["subject"] for r in rows}) == sorted(labels)
    assert {r["scenario"] for r in rows} == {"S2"} and {r["seeds"] for r in rows} == {"25-49"}
    assert {r["runs"] for r in rows} == {25}
    for label in labels:
        assert list(_subject(rows, label)) == list(NEES + USEFUL)


def test_the_plain_clone_does_not_hold_the_nees_conditions_in_s2(rows):
    plain = _subject(rows, gu.SUBJECTS[0].label)
    assert not all(plain[c]["holds"] for c in NEES)


@pytest.mark.parametrize("which", [1, 2])
def test_a_gauss_markov_subject_holds_the_nees_conditions_and_not_the_usefulness_conditions(rows, which):
    gm = _subject(rows, gu.SUBJECTS[which].label)
    assert all(gm[c]["holds"] for c in NEES)
    assert not all(gm[c]["holds"] for c in USEFUL)


def test_making_the_model_more_exact_does_not_change_which_conditions_hold(rows):
    a = _subject(rows, gu.SUBJECTS[1].label)
    b = _subject(rows, gu.SUBJECTS[2].label)
    assert {c: a[c]["holds"] for c in a} == {c: b[c]["holds"] for c in b}


def test_the_better_condition_is_below_its_threshold_for_the_gauss_markov_subjects(rows):
    for which in (1, 2):
        gm = _subject(rows, gu.SUBJECTS[which].label)
        assert gm["better"]["value"] < gm["better"]["threshold"]


def test_the_page_block_is_the_generated_block_of_the_csv(page, rows):
    block = page.split(gu.START, 1)[1].split(gu.END, 1)[0].strip()
    assert block == gu.markdown_section(rows).strip()


def test_the_section_is_labelled_a_diagnostic_and_says_what_it_does_not_show(section):
    flat = " ".join(section.split())
    assert "DIAGNOSTIC" in flat
    assert "development seeds" in flat
    assert "does not show that no estimator" in flat
    assert "ADR-0036" in flat


def test_the_section_uses_none_of_the_words_the_other_gate_sections_forbid(section):
    low = section.lower()
    assert not re.search(r"\bcalibrated\b", low)
    for forbidden in (
        "b1 is closed",
        "b1 passes",
        "b1 fails",
        "gate passes",
        "gate fails",
        "meets the gate",
    ):
        assert forbidden not in low, forbidden
