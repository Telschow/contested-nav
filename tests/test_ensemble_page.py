"""The ensemble table on ``docs/calibration.md`` is the committed CSV, and each sentence about it follows from it.

This reads only the CSV and the page, so it runs in a documentation-only pull request. The producer is tested in
``test_ensemble_nees.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import ensemble
from navkit.eval.calibration import ensemble_nees_band

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "ensemble_nees.csv"
PAGE = ROOT / "docs" / "calibration.md"

MOST = 0.9  # "most scored epochs"
NEARLY_ALL = 0.95  # "nearly all scored epochs"
MAJORITY = 0.75  # "more than three quarters of its scored epochs"

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
SCALE_DRIFT = "outage_visual_clone_scale_drift"
CLONE_WITHOUT_DRIFT = tuple(c for c in CLONE_INDEPENDENT if c != SCALE_DRIFT)
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
def test_the_independent_clone_rows_are_never_below_the_band(rows, case):
    for r in _of(rows, case):
        assert r["fraction_below"] == 0.0, (case, r["scope"])


@pytest.mark.parametrize("case", CLONE_WITHOUT_DRIFT)
def test_the_independent_clone_rows_except_the_drifting_scale_are_inside_for_more_than_three_quarters(rows, case):
    for r in _of(rows, case):
        assert r["fraction_inside"] > MAJORITY, (case, r["scope"])


def test_the_drifting_scale_clone_has_a_large_share_above_the_band(rows):
    by_scope = {r["scope"]: r for r in _of(rows, SCALE_DRIFT)}
    assert by_scope["full"]["fraction_above"] > 1.0 / 3.0  # "more than a third in the full scope"
    assert by_scope["outage"]["fraction_above"] > 0.5  # "more than half in the outage scope"


def test_the_correlated_clone_is_above_the_band_and_the_inflated_one_is_no_longer_mostly_inside(rows):
    for r in _of(rows, CORRELATED):
        assert r["fraction_above"] >= NEARLY_ALL, r["scope"]
    by_scope = {r["scope"]: r for r in _of(rows, CORRELATED_INFLATED)}
    assert by_scope["full"]["fraction_above"] > 0.5 and by_scope["full"]["fraction_inside"] < 0.5
    assert by_scope["outage"]["fraction_above"] >= NEARLY_ALL


def test_the_page_states_the_sentences_that_the_tests_above_check():
    text = " ".join(PAGE.read_text(encoding="utf-8").split())
    for phrase in (
        "are never below the band",
        "inside the band for more than three quarters of its scored epochs",
        "more than a third in the full scope and more than half in the outage scope",
        "is no longer mostly inside the band",
    ):
        assert phrase in text, phrase
    assert "inside or below the band" not in text


def test_every_case_in_the_csv_is_named_in_one_of_the_sentences(rows):
    named = set(CONTROLS) | set(ANCHOR) | set(CLONE_INDEPENDENT) | {CORRELATED, CORRELATED_INFLATED}
    assert {r["case"] for r in rows} == named
