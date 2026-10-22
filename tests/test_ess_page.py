"""The effective-sample-size table on ``docs/calibration.md`` is the committed CSV.

This reads only the CSV and the page, so it runs in a documentation-only pull request. The producer is tested in
``test_ess_table.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import ensemble

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "effective_sample_size.csv"
ENSEMBLE_CSV = ROOT / "docs" / "data" / "ensemble_nees.csv"
PAGE = ROOT / "docs" / "calibration.md"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return ensemble.parse_csv(CSV.read_text(encoding="utf-8"), ensemble.ESS_FIELDS)


def test_the_page_table_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == ensemble.splice_ess_table(page, ensemble.ess_markdown_table(rows))


def test_the_csv_round_trips_to_the_same_bytes(rows):
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(ensemble.ESS_FIELDS)
    assert ensemble.csv_text(rows, ensemble.ESS_FIELDS) == text


def test_the_table_describes_the_same_runs_as_the_ensemble(rows):
    ens = ensemble.parse_csv(ENSEMBLE_CSV.read_text(encoding="utf-8"))
    assert [(r["case"], r["scope"], r["n_runs"], r["epochs"]) for r in rows] == [
        (r["case"], r["scope"], r["n_runs"], r["n_epochs"]) for r in ens
    ]


def test_the_values_are_ordered_and_within_their_limits(rows):
    for r in rows:
        assert 1.0 <= r["n_eff_min"] <= r["n_eff_median"] <= r["n_eff_max"] <= r["epochs"], r["case"]
        assert 0 <= r["truncated_runs"] <= r["n_runs"], r["case"]


def test_the_page_no_longer_points_at_the_text_of_a_pull_request_for_these_values():
    text = " ".join(PAGE.read_text(encoding="utf-8").split())
    assert "has its measured values for these cases" not in text
    assert "[`data/effective_sample_size.csv`](data/effective_sample_size.csv)" in text
    assert "navkit sweep seeds --seeds 25 --ensemble-csv docs/data/ensemble_nees.csv" in text
    assert "--ess-csv docs/data/effective_sample_size.csv" in text


@pytest.mark.parametrize("name", ["README.md", "docs/results.md", "docs/getting-started.md"])
def test_a_page_with_a_dagger_in_a_table_explains_it(name):
    text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
    if "†" in text:
        assert "A dagger after a verdict" in text, name


def test_the_page_explains_the_dagger_once():
    text = PAGE.read_text(encoding="utf-8")
    assert text.count("A dagger after a verdict") == 1
