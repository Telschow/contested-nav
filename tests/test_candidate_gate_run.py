"""The candidate gate on real cases, development seeds only (25 to 99).

Seeds 100 and up are never run in this file. The anchor test is the gate's own control: it has to be able to say no.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit import candidate_gate as run
from navkit.eval import candidate_gate as cg
from navkit.eval.statistics import effective_sample_size

DEV = list(range(25, 50))


def test_no_seed_used_in_this_file_is_from_100_up():
    assert max(DEV) < 100
    assert max(run.POOL_SEEDS) < 100


@pytest.fixture(scope="module")
def doc():
    return run._document()


def test_one_scenario_run_gives_the_arrays_the_evaluator_needs(doc):
    arrays = run.run_scenario("S1", run.DEFAULT_ESTIMATOR, [25, 26, 27], doc)
    assert arrays["y"].shape == arrays["n_eff"].shape == arrays["ate"].shape == (3,)
    assert arrays["err"].shape == arrays["sigma"].shape == (3, arrays["err"].shape[1], 3)
    assert np.all(arrays["n_eff"] >= 1.0) and np.all(np.isfinite(arrays["y"]))


def test_y_is_the_window_mean_and_n_eff_the_effective_sample_size_of_the_same_series(doc):
    from navkit import benchmark as bm

    case = run.scenario_case(doc["cases"], "S1", run.DEFAULT_ESTIMATOR)
    box: dict = {}
    bm.run_case("c", case, doc["defaults"], seed=25, nees_out=box)
    window = run.window_arrays(box)
    arrays = run.run_scenario("S1", run.DEFAULT_ESTIMATOR, [25, 26], doc)
    assert arrays["y"][0] == pytest.approx(float(window["nees"].mean()))
    assert arrays["n_eff"][0] == pytest.approx(effective_sample_size(window["nees"]))


def test_a_small_run_gives_one_row_per_condition_scenario_and_subject_and_is_deterministic(doc):
    rows = run.run_candidate_gate([25, 26, 27], held_out=False, ledger=run.parse_ledger(run.LEDGER_PATH.read_text()))
    assert [r["role"] for r in rows[:6]] == ["candidate"] * 6
    assert {(r["role"], r["scenario"]) for r in rows} == {
        ("candidate", "S1"),
        ("candidate", "S2"),
        ("DIAGNOSTIC", "S1"),
        ("DIAGNOSTIC", "S2"),
    }
    assert {r["subject"] for r in rows if r["role"] == "DIAGNOSTIC"} == {"outage_visual_clone", "outage_visual"}
    assert len(rows) == 3 * 2 * 6
    again = run.run_candidate_gate([25, 26, 27], held_out=False, ledger=run.parse_ledger(run.LEDGER_PATH.read_text()))
    assert run.csv_text(again) == run.csv_text(rows)
    assert run.csv_text(run.parse_csv(run.csv_text(rows))) == run.csv_text(rows)


def test_the_anchor_diagnostic_fails_the_gate_in_s1_on_the_development_seeds(doc):
    """The gate's own control: the single-anchor model is overconfident, and the gate has to be able to say no."""
    anchor = run.run_scenario("S1", {}, DEV, doc)
    control = run.run_control("S1", DEV, doc)
    result = cg.evaluate_scenario_gate(
        anchor["y"], anchor["n_eff"], anchor["err"], anchor["sigma"], anchor["ate"], control["ate"]
    )
    assert not result.passed
    assert not result.upper.passed and not result.coverage.passed
    assert result.upper.value > 10.0 * result.upper.threshold
