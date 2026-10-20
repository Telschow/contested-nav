"""The ensemble table on ``docs/calibration.md`` is the committed CSV, and each sentence about it follows from it.

This reads only the CSV and the page, so it runs in a documentation-only pull request. The producer is tested in
``test_ensemble_nees.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import ensemble
from navkit.eval.calibration import ensemble_nees_band

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "ensemble_nees.csv"
PAGE = ROOT / "docs" / "calibration.md"

MOST = 0.9  # "most scored epochs"
NEARLY_ALL = 0.95  # "nearly all scored epochs"

CONTROLS = ("gnss_only", "outage_control")
ANCHOR = (
    "vision_anchor_in_measurement_noise",
    "vision_only",
    "outage_visual",
    "outage_visual_degraded_camera",
    "outage_visual_degraded_camera_rereferenced",
)
CLONE_INDEPENDENT = (
    "outage_visual_clone",
    "outage_visual_degraded_camera_clone",
    "vision_only_clone",
    "outage_visual_clone_outliers",
    "outage_visual_clone_scale_drift",
)
CORRELATED = "outage_visual_clone_correlated"
CORRELATED_INFLATED = "outage_visual_clone_correlated_inflated"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return ensemble.parse_csv(CSV.read_text(encoding="utf-8"))


def _of(rows: list[dict], case: str) -> list[dict]:
    found = [r for r in rows if r["case"] == case]
    assert found, case
    return found


def test_the_page_table_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == ensemble.splice_table(page, ensemble.markdown_table(rows))


def test_the_committed_file_is_the_documented_ensemble(rows):
    assert CSV.read_text(encoding="utf-8").splitlines()[0] == ",".join(ensemble.CSV_FIELDS)
    assert {r["n_runs"] for r in rows} == {25}
    assert {r["dof"] for r in rows} == {3}
    band = ensemble_nees_band(25, 3)
    assert all((r["band_low"], r["band_high"]) == band for r in rows)
    assert "dead_reckoning" not in {r["case"] for r in rows}
    with_outage = {r["case"] for r in rows if r["scope"] == "outage"}
    assert {r["case"] for r in rows if r["scope"] == "full"} >= with_outage
    for r in rows:
        assert r["fraction_inside"] + r["fraction_below"] + r["fraction_above"] == pytest.approx(1.0)


def test_the_page_documents_the_command_and_the_committed_n():
    text = PAGE.read_text(encoding="utf-8")
    assert "navkit sweep seeds --seeds 25 --ensemble-csv docs/data/ensemble_nees.csv" in text
    assert "seeds 0 to 24" in text


def test_the_page_says_what_the_shares_are_and_what_they_are_not():
    text = " ".join(PAGE.read_text(encoding="utf-8").split())
    for phrase in (
        "not independent of one another",
        "same start draws",
        "The first epoch is not excluded",
        "descriptive, not a p-value",
        "effective_sample_size",
        "does not replace the single-run verdicts",
        "decided separately, with an ADR",
    ):
        assert phrase in text, phrase


def test_the_page_calls_no_case_calibrated_in_the_ensemble_section():
    page = PAGE.read_text(encoding="utf-8")
    section = page[page.index("## The ensemble over seeds") : page.index("## Worked example")].lower()
    assert "not calibrated" not in section and " is calibrated" not in section and "are calibrated" not in section


# ------------------------------------------------------------------------- each sentence, against the CSV


@pytest.mark.parametrize("case", CONTROLS)
def test_the_no_vision_controls_are_inside_the_band_for_most_scored_epochs(rows, case):
    for r in _of(rows, case):
        assert r["fraction_inside"] >= MOST, (case, r["scope"])


@pytest.mark.parametrize("case", ANCHOR)
def test_the_single_anchor_rows_are_above_the_band_for_nearly_all_scored_epochs(rows, case):
    for r in _of(rows, case):
        assert r["fraction_above"] >= 0.99, (case, r["scope"])


@pytest.mark.parametrize("case", CLONE_INDEPENDENT)
def test_the_independent_clone_rows_are_inside_or_below_the_band_for_most_scored_epochs(rows, case):
    for r in _of(rows, case):
        assert r["fraction_inside"] + r["fraction_below"] >= 0.85, (case, r["scope"])


def test_the_correlated_clone_is_above_the_band_and_the_inflated_one_mostly_inside(rows):
    for r in _of(rows, CORRELATED):
        assert r["fraction_above"] >= NEARLY_ALL, r["scope"]
    for r in _of(rows, CORRELATED_INFLATED):
        assert r["fraction_inside"] >= MOST, r["scope"]


def test_every_case_in_the_csv_is_named_in_one_of_the_sentences(rows):
    named = set(CONTROLS) | set(ANCHOR) | set(CLONE_INDEPENDENT) | {CORRELATED, CORRELATED_INFLATED}
    assert {r["case"] for r in rows} == named
