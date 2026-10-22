"""The sentences about single-run verdicts (ADR-0029) agree with the committed tables they describe.

This reads the README table (which CI checks against a fresh benchmark), the ensemble and effective-sample-size CSVs
and the pages. It runs in a documentation-only pull request.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from navkit import ensemble
from navkit.benchmark import default_config_path
from navkit.eval.statistics import chi2_ppf

ROOT = Path(__file__).resolve().parent.parent

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


def _checker():
    spec = importlib.util.spec_from_file_location("check_doc_tables", ROOT / "scripts" / "check_doc_tables.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verdicts() -> dict[str, str]:
    """Case name -> the verdict cell of the README table, which CI compares with a fresh benchmark."""
    names = list(yaml.safe_load(default_config_path().read_text())["cases"])
    rows = _checker()._markdown_cells((ROOT / "README.md").read_text(encoding="utf-8"))
    assert len(rows) == len(names)
    return {name: row[5] for name, row in zip(names, rows, strict=True)}


def test_the_single_anchor_rows_are_overconfident_with_a_dagger(verdicts):
    for name in ANCHOR:
        assert verdicts[name] == "overconfident†", name


def test_the_controls_and_independent_clone_rows_do_not_carry_a_dagger(verdicts):
    for name in ("gnss_only", "outage_control", *CLONE_INDEPENDENT):
        assert "†" not in verdicts[name], name


def test_outage_control_and_the_independent_clone_rows_read_consistent_except_the_vision_only_clone(verdicts):
    assert verdicts["outage_control"] == "consistent"
    for name in CLONE_INDEPENDENT:
        if name == "vision_only_clone":
            assert verdicts[name] == "mixed: bulk underconfident, tail consistent"
        else:
            assert verdicts[name] == "consistent", name


def test_gnss_only_reads_mixed_with_an_overconfident_bulk_on_the_seed_of_the_table(verdicts):
    assert verdicts["gnss_only"] == "mixed: bulk overconfident, tail consistent"


def test_the_correlated_clone_stays_overconfident(verdicts):
    assert verdicts["outage_visual_clone_correlated"] == "overconfident"


def test_a_truncated_band_does_not_matter_for_the_anchor_rows():
    """Their mean NEES is orders of magnitude above the upper edge of the band, even for a very small n_eff."""
    results = _checker()._markdown_cells((ROOT / "README.md").read_text(encoding="utf-8"))
    names = list(yaml.safe_load(default_config_path().read_text())["cases"])
    mean = {name: float(row[3]) for name, row in zip(names, results, strict=True) if name in ANCHOR}
    # the smallest effective sample size of a single-anchor run in the ESS table is the widest band that matters
    ess = ensemble.parse_csv((ROOT / "docs" / "data" / "effective_sample_size.csv").read_text(), ensemble.ESS_FIELDS)
    smallest = min(r["n_eff_min"] for r in ess if r["case"] in ANCHOR)
    widest_high = chi2_ppf(0.975, smallest * 3) / smallest
    for name in ANCHOR:
        assert mean[name] > 100.0 * widest_high, name


def test_the_independent_clone_rows_have_a_grand_mean_below_the_expected_value_in_the_ensemble():
    rows = ensemble.parse_csv((ROOT / "docs" / "data" / "ensemble_nees.csv").read_text())
    for name in CLONE_INDEPENDENT:
        for r in rows:
            if r["case"] == name:
                assert r["grand_mean"] < r["dof"], (name, r["scope"])


def test_the_ensemble_puts_gnss_only_inside_its_band_for_most_scored_epochs():
    rows = ensemble.parse_csv((ROOT / "docs" / "data" / "ensemble_nees.csv").read_text())
    for r in rows:
        if r["case"] == "gnss_only":
            assert r["fraction_inside"] >= 0.9


def test_every_anchor_run_in_the_ess_table_is_mostly_truncated():
    ess = ensemble.parse_csv((ROOT / "docs" / "data" / "effective_sample_size.csv").read_text(), ensemble.ESS_FIELDS)
    for r in ess:
        if r["case"] in ANCHOR and r["scope"] == "outage":
            assert r["truncated_runs"] >= 0.9 * r["n_runs"], r["case"]


PAGES = (
    "README.md",
    "docs/index.md",
    "docs/getting-started.md",
    "docs/results.md",
    "docs/status.md",
    "docs/calibration.md",
    "docs/mismatch.md",
    "docs/faq.md",
    "docs/scenarios.md",
    "docs/concepts.md",
    "docs/architecture.md",
)


@pytest.mark.parametrize("name", PAGES)
def test_no_page_calls_a_single_run_or_a_case_calibrated(name):
    text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
    pattern = re.compile(r"\b(?:is|are|was|were|stays|remains)[ -]calibrated\b|\bcalibrated where\b")
    found = pattern.findall(text)
    assert not found, (name, found)


def test_the_pages_say_what_consistent_means():
    results = " ".join((ROOT / "docs" / "results.md").read_text(encoding="utf-8").split())
    assert "`consistent` means that the run did not reject calibration" in results
    assert "One run cannot establish calibration" in results
    assert "A dagger after a verdict" in results
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "A dagger after a verdict" in readme and "a single-run verdict is descriptive" in readme


def test_the_urbannav_note_is_dated_and_labelled():
    text = " ".join((ROOT / "docs" / "urbannav.md").read_text(encoding="utf-8").split())
    assert "Note (2026-10-22)" in text
    assert "measured once on one machine, not checked by CI" in text
    assert "overconfident for both variants on all five seeds" in text
