"""The correlated-GNSS-error study (issue #183): the scenario, the rows and the declared criteria.

The study asks whether the innovation gate notices a slow, time-correlated GNSS error. The size and the correlation time
are declared in the module before the study is run, and these tests pin them so that they cannot be tuned afterwards.
"""

from __future__ import annotations

import copy

import numpy as np
import numpy.linalg as la
import pytest
import yaml

from navkit import correlated_gnss_study as cg
from navkit.benchmark import default_config_path
from navkit.sensors.models import GnssConfig, gnss_fixes
from navkit.synthetic import SyntheticConfig, synthetic_trajectory
from navkit.types import interpolate_trajectory


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(default_config_path().read_text())


# ------------------------------------------------------------------ the scenario


def test_the_size_and_the_correlation_time_are_declared_before_any_run() -> None:
    assert (cg.CORR_SIGMA_M, cg.CORR_TAU_S) == (1.5, 30.0)


def test_the_independent_control_has_no_correlated_term_and_the_correlated_case_has_the_declared_one(doc) -> None:
    indep = cg.case_definition(doc, "independent")["scenario"]["gnss"]
    corr = cg.case_definition(doc, "correlated")["scenario"]["gnss"]
    assert indep.get("multipath_sigma_m", 0.0) == 0.0
    assert (corr["multipath_sigma_m"], corr["multipath_tau_s"]) == (cg.CORR_SIGMA_M, cg.CORR_TAU_S)
    assert indep["sigma_m"] == corr["sigma_m"]  # the receiver noise is the same, only the correlated term differs


def test_the_single_anchor_control_is_the_benchmark_case_unchanged(doc) -> None:
    assert cg.case_definition(doc, "single_anchor") == doc["cases"]["outage_visual"]


def test_a_case_definition_is_a_copy(doc) -> None:
    before = copy.deepcopy(doc)
    cg.case_definition(doc, "correlated")["scenario"]["gnss"]["sigma_m"] = 99.0
    assert doc == before


def _error_series(cfg: GnssConfig) -> np.ndarray:
    gt = synthetic_trajectory(SyntheticConfig(duration_s=120.0, rate_hz=100.0))
    gt = gt.transformed(la.inv(gt.poses[0]))
    fixes = gnss_fixes(gt, cfg)
    ref = interpolate_trajectory(gt, fixes.t).positions
    return (fixes.positions - ref)[:, 0]


def test_the_generated_error_is_correlated_at_the_declared_time_and_the_control_is_not() -> None:
    corr = _error_series(GnssConfig(sigma_m=0.0, multipath_sigma_m=cg.CORR_SIGMA_M, multipath_tau_s=cg.CORR_TAU_S))
    indep = _error_series(GnssConfig(sigma_m=0.8, seed=1))
    lag1 = float(np.corrcoef(corr[:-1], corr[1:])[0, 1])
    assert lag1 >= 0.98  # exp(-0.2 s / 30 s) is 0.993 for 5 Hz fixes
    assert abs(float(np.corrcoef(indep[:-1], indep[1:])[0, 1])) < 0.3


# ------------------------------------------------------------------ the rows


def row(case: str, seed: int, seen: int, rejected: int, nis: float, nees: float) -> dict:
    return {
        "case": case,
        "seed": seed,
        "fixes_seen": seen,
        "fixes_rejected": rejected,
        "mean_nis": nis,
        "nees_mean": nees,
        "ate_rmse_m": 1.0,
    }


def test_the_summary_pools_the_counts_and_gives_the_wilson_interval_of_the_pool() -> None:
    rows = [row("independent", 0, 100, 0, 3.0, 3.0), row("independent", 1, 100, 0, 3.4, 3.2)]
    s = cg.summarise(rows)["independent"]
    assert (s["seen"], s["rejected"], s["seeds"]) == (200, 0, 2)
    assert s["rate"] == 0.0 and s["rate_low"] == 0.0
    assert s["rate_high"] == pytest.approx(0.018845, abs=1e-5)  # z^2 / (n + z^2) for 0 of 200 at 95%
    assert s["mean_nis"] == pytest.approx(3.2) and s["nees_mean"] == pytest.approx(3.1)


def test_the_gate_level_is_the_chi_square_threshold_of_three_degrees_of_freedom_at_the_default_alpha() -> None:
    assert pytest.approx(16.266, abs=1e-3) == cg.GATE_LEVEL


def test_the_criteria_are_declared_and_all_three_conditions_are_needed() -> None:
    assert (cg.BLIND_REJECTION_UPPER, cg.BLIND_NEES_FACTOR) == (0.05, 3.0)
    quiet = {"rate_high": 0.01, "mean_nis": 4.0, "nees_mean": 30.0, "nees_expected": 3.0}
    assert cg.gate_is_blind(quiet)
    assert not cg.gate_is_blind({**quiet, "rate_high": 0.2})  # it rejected a lot: not blind
    assert not cg.gate_is_blind({**quiet, "mean_nis": 20.0})  # the mean NIS reached the gate level
    assert not cg.gate_is_blind({**quiet, "nees_mean": 5.0})  # the position error is not large against the claim


def test_the_csv_round_trips_and_the_comparison_names_a_changed_cell() -> None:
    rows = [row("correlated", 0, 150, 3, 8.5, 390.0)]
    assert cg.parse_csv(cg.csv_text(rows)) == rows
    changed = [{**rows[0], "fixes_rejected": 4}]
    assert cg.compare(changed, rows) != [] and cg.compare(rows, rows) == []


def test_held_out_seeds_are_refused() -> None:
    with pytest.raises(ValueError, match="held-out"):
        cg.refuse_held_out([3, 100])


def test_comparing_a_csv_with_itself_cannot_overwrite_it_first(tmp_path, monkeypatch) -> None:
    committed = tmp_path / "committed.csv"
    stale = [row(c, s, 100, 0, 3.0, 3.0) for c in cg.CASES for s in range(2)]
    committed.write_text(cg.csv_text(stale), encoding="utf-8")
    fresh = [{**r, "fixes_rejected": 1} for r in stale]
    monkeypatch.setattr(cg, "run_study", lambda doc, seeds=None: fresh)
    argv = ["--csv", str(committed), "--compare", str(committed), "--seeds", "0-1"]
    assert cg.main(argv) == 1  # the fresh rows differ from the committed ones
    # The comparison failed, and the committed file now holds the fresh rows only after it read the old ones.
    assert cg.parse_csv(committed.read_text(encoding="utf-8")) == fresh


def test_a_missing_case_is_a_clear_error_and_not_a_key_error() -> None:
    rows = [row("independent", 0, 100, 0, 3.0, 3.0)]
    with pytest.raises(ValueError, match="correlated"):
        cg.markdown_section(rows)
