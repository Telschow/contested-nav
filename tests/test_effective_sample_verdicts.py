"""ADR-0029: a single run's verdict is formed with the effective sample size of its scored NEES series.

The old rule counted every epoch as an independent sample. Epochs within a run are strongly autocorrelated, so the
old bands were too narrow. The tests below keep the old formula as a reference function and show where the two rules
part. A single run stays descriptive; the ensemble and the gate of ADR-0028 are the decision tools.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from navkit import benchmark as bm
from navkit.eval import calibration as cal
from navkit.eval.calibration import (
    CalibrationReport,
    CoveragePoint,
    CoverageReport,
    MahalanobisSeries,
    summarise,
    verdict_label,
    wilson_interval,
)
from navkit.eval.statistics import AutocorrelationEstimate, chi2_ppf, effective_sample_size

ROOT = Path(__file__).resolve().parent.parent
DOF = 3


def _series(squared: np.ndarray, dof: int = DOF) -> MahalanobisSeries:
    squared = np.asarray(squared, dtype=float)
    return MahalanobisSeries(squared=squared, radius=np.sqrt(squared), dof=dof)


def _report(squared: np.ndarray) -> CalibrationReport:
    return summarise("eskf", "s", _series(squared))


def _old_bulk(mean_nees: float, n: int, dof: int = DOF) -> str:
    """The rule before ADR-0029, kept as a reference: every epoch counts as an independent sample."""
    lo, hi = chi2_ppf(0.025, n * dof) / n, chi2_ppf(0.975, n * dof) / n
    return "overconfident" if mean_nees > hi else "underconfident" if mean_nees < lo else "calibrated"


def _white(n: int = 2000, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).chisquare(DOF, n)


def _ar1(n: int = 3000, rho: float = 0.99, seed: int = 0) -> np.ndarray:
    """NEES of three AR(1) components with unit variance: chi-square(3) marginally, strongly autocorrelated."""
    rng = np.random.default_rng(seed)
    z = np.empty((n, DOF))
    z[0] = rng.standard_normal(DOF)
    s = np.sqrt(1.0 - rho**2)
    for t in range(1, n):
        z[t] = rho * z[t - 1] + s * rng.standard_normal(DOF)
    return (z**2).sum(axis=1)


# ---------------------------------------------------------------------------------------------- known answers


def test_white_noise_is_worth_about_its_length_and_reads_consistent():
    x = _white()
    report = _report(x)
    assert 0.8 * x.size < report.n_eff <= x.size
    assert report.n_eff == pytest.approx(effective_sample_size(x))
    assert report.bulk_verdict == "consistent"
    assert report.verdict == "consistent"
    assert report.consistent is True


def test_an_autocorrelated_series_is_overconfident_by_the_old_rule_and_consistent_by_the_new_one():
    x = _ar1()
    n = x.size
    assert _old_bulk(float(x.mean()), n) == "overconfident"  # the old band is far too narrow for this series
    report = _report(x)
    assert report.n_eff < 0.05 * n  # the run is worth a few dozen samples, not three thousand
    assert report.bulk_verdict == "consistent"


def test_the_same_series_scaled_up_is_overconfident_and_scaled_down_is_underconfident():
    x = _ar1()
    assert _report(4.0 * x).bulk_verdict == "overconfident"
    assert _report(0.25 * x).bulk_verdict == "underconfident"


def test_the_band_is_chi_square_for_n_eff_times_dof_scaled_by_n_eff():
    x = _ar1()
    report = _report(x)
    m = report.n_eff
    lo, hi = chi2_ppf(0.025, m * DOF) / m, chi2_ppf(0.975, m * DOF) / m
    mean = float(x.mean())
    assert lo < mean < hi  # inside, so consistent
    assert _report(x * (hi * 0.999 / mean)).bulk_verdict == "consistent"
    # n_eff is estimated again from the rescaled series, which has the same shape, so the same band applies
    assert _report(x * (hi * 1.2 / mean)).bulk_verdict == "overconfident"
    assert _report(x * (lo * 0.8 / mean)).bulk_verdict == "underconfident"


def test_n_eff_is_at_least_one():
    report = CalibrationReport(
        estimator="e",
        scenario="s",
        coverage=CoverageReport(
            points=(CoveragePoint(sigma_per_axis=2.0, covered=10, epochs=10, n_eff=1.0),),
            mean_normalised_error=3.0,
            dof=DOF,
            n_eff=1.0,
        ),
        inflation_to_95=1.0,
        conformal={},
    )
    assert report.bulk_verdict == "consistent"  # a band for one sample is very wide, not an error


# --------------------------------------------------------------------------------------------- the coverage test


def test_the_wilson_interval_on_n_eff_trials_is_wider_than_on_epochs_and_contains_it():
    wide = CoveragePoint(sigma_per_axis=2.0, covered=2900, epochs=3000, n_eff=40.0)
    narrow = CoveragePoint(sigma_per_axis=2.0, covered=2900, epochs=3000)
    assert narrow.interval == wilson_interval(2900, 3000)  # without n_eff, the old behaviour
    lo, hi = wide.interval
    nlo, nhi = narrow.interval
    assert lo < nlo and hi > nhi
    assert wide.interval == wilson_interval(2900 / 3000 * 40.0, 40.0)


def test_a_coverage_that_the_old_interval_rejects_the_new_one_may_accept():
    # expected 2-sigma coverage is 0.9926; 97% observed over 3000 epochs is far outside the old interval
    old = CoveragePoint(sigma_per_axis=2.0, covered=2910, epochs=3000)
    new = CoveragePoint(sigma_per_axis=2.0, covered=2910, epochs=3000, n_eff=30.0)
    assert old.verdict == "overconfident"
    assert new.verdict == "consistent"


# -------------------------------------------------------------------------------------------- truncation, dagger


def _fake_estimate(truncated: bool):
    def fake(x, c=5.0):
        return AutocorrelationEstimate(tau=len(x) / 25.0, window=len(x) // 2, truncated=truncated, n=len(x), c=c)

    return fake


def test_the_truncation_flag_reaches_the_report_and_the_record(monkeypatch):
    x = _white(500)
    assert _report(x).n_eff_truncated is False
    monkeypatch.setattr(cal, "autocorrelation_estimate", _fake_estimate(True))
    report = _report(x)
    assert report.n_eff_truncated is True
    assert report.n_eff == pytest.approx(25.0)
    record = report.as_dict()
    assert record["n_eff"] == pytest.approx(25.0) and record["n_eff_truncated"] is True
    assert record["coverage"]["n_eff"] == pytest.approx(25.0) and record["coverage"]["n_eff_truncated"] is True
    assert "consistent" in record and "calibrated" not in record


def test_the_dagger_marks_a_truncated_verdict_and_nothing_else():
    assert verdict_label("consistent", False) == "consistent"
    assert verdict_label("consistent", True) == "consistent†"
    assert verdict_label("mixed(bulk=overconfident, tail=consistent)", True).endswith("†")
    assert verdict_label("n/a", True) == "n/a"  # no verdict, nothing to mark
    assert verdict_label("insufficient_data", True) == "insufficient_data"


def _case(verdict: str, truncated: bool) -> dict:
    return {
        "name": "c",
        "headline": {
            "ate_rmse_m": 1.0,
            "claimed_sigma_p_m": 0.5,
            "nees_mean": 3.0,
            "coverage": {"2sigma": 0.99},
            "calibration_verdict": verdict,
            "n_eff": 30.0,
            "n_eff_truncated": truncated,
        },
    }


def test_the_dagger_reaches_the_rendered_tables():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_doc_tables", ROOT / "scripts" / "check_doc_tables.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._named_row_cells(_case("consistent", True))[-1] == "consistent†"
    assert module._named_row_cells(_case("consistent", False))[-1] == "consistent"
    marked = bm.as_markdown_table([_case("consistent", True)])
    plain = bm.as_markdown_table([_case("consistent", False)])
    assert marked.splitlines()[-1].endswith("consistent† |")
    assert plain.splitlines()[-1].endswith("consistent |")


# ------------------------------------------------------------------------------------------ insufficient data


@pytest.mark.parametrize("squared", [np.array([3.0, 2.0, 4.0, 1.0, 5.0]), np.full(200, 3.0), np.array([])])
def test_a_series_that_cannot_give_an_estimate_is_insufficient_data_and_raises_nothing(squared):
    report = _report(squared)
    assert report.bulk_verdict == "insufficient_data"
    assert report.tail_verdict == "insufficient_data"
    assert report.verdict == "insufficient_data"
    assert report.consistent is False
    record = report.as_dict()
    assert record["n_eff"] is None and record["n_eff_truncated"] is False
    assert record["verdict"] == "insufficient_data"


def test_a_non_finite_series_is_insufficient_data_and_not_a_crash():
    x = _white(100)
    x[7] = np.nan
    assert _report(x).bulk_verdict == "insufficient_data"


# ------------------------------------------------------------------------------------------------ the rename


def test_the_old_verdict_word_and_field_are_gone_from_the_code():
    allowed = {
        "src/navkit/figures.py",  # a label on a reference line in a plot
        "src/navkit/separability.py",  # "calibrated" as the name of a bias-walk setting
        "tests/test_effective_sample_verdicts.py",
        "tests/test_fdir_false_alarm_page.py",  # words that a page must not use
        "tests/test_b1_gate_page.py",
        "tests/test_candidate_gate_page.py",
        "tests/test_ensemble_page.py",
    }
    pattern = re.compile(r"\.calibrated\b|[\"']calibrated[\"']")
    found = []
    for folder in ("src", "tests", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in allowed:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    found.append(f"{rel}:{number}: {line.strip()}")
    assert not found, "\n".join(found)


def test_the_report_has_consistent_and_not_calibrated():
    report = _report(_white())
    assert hasattr(report, "consistent") and not hasattr(report, "calibrated")
    assert "consistent" in report.as_dict() and "calibrated" not in report.as_dict()


def test_a_hand_built_report_without_n_eff_counts_its_epochs_as_before():
    """A caller that builds a report by hand and gives no n_eff asserts that its epochs are independent."""
    cov = CoverageReport(
        points=(CoveragePoint(sigma_per_axis=2.0, covered=2976, epochs=3000),), mean_normalised_error=3.0, dof=DOF
    )
    report = CalibrationReport(estimator="e", scenario="s", coverage=cov, inflation_to_95=1.0, conformal={})
    assert report.bulk_verdict == _old_bulk(3.0, 3000).replace("calibrated", "consistent")
    assert report.as_dict()["n_eff"] is None
