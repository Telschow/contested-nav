"""The pre-registered properties of ADR-0030, checked by simulation on the committed pool of effective sample sizes.

ADR-0030 requires, before any candidate is evaluated, that conditions (U) and (L) behave as intended on simulated runs
whose per-run mean is chi-square with ``3 n_i`` degrees of freedom divided by ``n_i``, with the ``n_i`` drawn from the
effective sample sizes of the existing candidate on seeds 25 to 99. The only permitted correction is to the
confidence level of (U). Tests read the committed CSV and do not run cases.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from navkit.eval import candidate_gate as cg
from navkit.eval.calibration import wilson_interval
from navkit.eval.candidate_gate import (
    GateProperties,
    select_upper_quantile,
    simulate_gate_properties,
)

ROOT = Path(__file__).resolve().parent.parent
POOL_CSV = ROOT / "docs" / "data" / "gate_n_eff_pool.csv"


@pytest.fixture(scope="module")
def pool() -> np.ndarray:
    rows = list(csv.DictReader(POOL_CSV.read_text(encoding="utf-8").splitlines()))
    return np.array([float(r["n_eff"]) for r in rows])


# ------------------------------------------------------------------------------------------- the pool file


def test_the_pool_is_the_75_runs_of_seeds_25_to_99_and_nothing_else():
    rows = list(csv.DictReader(POOL_CSV.read_text(encoding="utf-8").splitlines()))
    assert list(rows[0].keys()) == ["seeds", "n_eff"]
    assert [int(r["seeds"]) for r in rows] == list(range(25, 100))
    assert all(float(r["n_eff"]) >= 1.0 for r in rows)


def test_the_pool_file_round_trips_to_the_same_bytes():
    text = POOL_CSV.read_text(encoding="utf-8")
    rows = cg.parse_pool_csv(text)
    assert cg.pool_csv_text(rows) == text


# --------------------------------------------------------------------------------------- the simulation


def test_the_simulation_is_deterministic_for_a_seed(pool):
    a = simulate_gate_properties(pool, n_sets=2000, seed=7, upper_quantile=0.99)
    b = simulate_gate_properties(pool, n_sets=2000, seed=7, upper_quantile=0.99)
    assert a == b
    assert simulate_gate_properties(pool, n_sets=2000, seed=8, upper_quantile=0.99) != a


def test_the_rates_are_shares_of_sets_with_a_wilson_interval_that_contains_them(pool):
    props = simulate_gate_properties(pool, n_sets=3000, seed=1, upper_quantile=0.99)
    assert isinstance(props, GateProperties)
    for rate, interval in (
        (props.consistent_rate, props.consistent_interval),
        (props.high_fail_rate, props.high_fail_interval),
        (props.low_fail_rate, props.low_fail_interval),
    ):
        assert 0.0 <= rate <= 1.0
        assert interval[0] <= rate <= interval[1]
        assert interval == pytest.approx(wilson_interval(round(rate * props.n_sets), props.n_sets))
    assert props.n_sets == 3000 and props.upper_quantile == 0.99


def test_the_defaults_are_at_least_ten_thousand_sets_and_a_fixed_seed():
    assert cg.SIMULATION_SETS >= 10000
    assert isinstance(cg.SIMULATION_SEED, int)


def test_a_higher_level_is_a_looser_u_so_it_helps_the_consistent_filter_and_hurts_the_failing_one(pool):
    lo = simulate_gate_properties(pool, n_sets=4000, seed=2, upper_quantile=0.975)
    hi = simulate_gate_properties(pool, n_sets=4000, seed=2, upper_quantile=0.995)
    assert hi.consistent_rate >= lo.consistent_rate
    assert hi.high_fail_rate <= lo.high_fail_rate


def test_the_low_factor_is_independent_of_the_level(pool):
    """(L) does not use the confidence level, so the low-NEES property is the same at every level."""
    rates = {
        q: simulate_gate_properties(pool, n_sets=3000, seed=4, upper_quantile=q).low_fail_rate
        for q in cg.UPPER_QUANTILE_LEVELS
    }
    assert len(set(rates.values())) == 1


def test_the_simulation_refuses_a_bad_pool_or_size(pool):
    with pytest.raises(ValueError):
        simulate_gate_properties(np.array([]), n_sets=100, seed=0, upper_quantile=0.975)
    with pytest.raises(ValueError):
        simulate_gate_properties(np.array([0.0, 2.0]), n_sets=100, seed=0, upper_quantile=0.975)
    with pytest.raises(ValueError):
        simulate_gate_properties(pool, n_sets=0, seed=0, upper_quantile=0.975)


# ------------------------------------------------------------------------------- the pre-registered rule


def test_the_thresholds_of_the_properties_are_the_adr_numbers():
    assert cg.PROPERTY_MIN_CONSISTENT == 0.90
    assert cg.PROPERTY_MIN_HIGH_FAIL == 0.99 and cg.PROPERTY_MIN_LOW_FAIL == 0.99
    assert cg.SIMULATION_FACTOR_HIGH == 2.0 and cg.SIMULATION_FACTOR_LOW == 0.3
    assert cg.UPPER_QUANTILE_LEVELS == (0.975, 0.99, 0.995)
    assert cg.SIMULATION_RUNS == 25


def test_the_selected_level_meets_all_three_properties_on_the_committed_pool(pool):
    props = simulate_gate_properties(pool, upper_quantile=cg.CANDIDATE_GATE_UPPER_QUANTILE)
    assert props.consistent_rate >= cg.PROPERTY_MIN_CONSISTENT, props
    assert props.high_fail_rate >= cg.PROPERTY_MIN_HIGH_FAIL, props
    assert props.low_fail_rate >= cg.PROPERTY_MIN_LOW_FAIL, props
    assert cg.properties_met(props)


def test_the_constant_is_what_the_rule_returns_for_the_committed_pool(pool):
    """The level is never set by hand: it is the first level that meets all three properties."""
    assert select_upper_quantile(pool) == cg.CANDIDATE_GATE_UPPER_QUANTILE


def test_every_level_below_the_selected_one_fails_a_property(pool):
    chosen = cg.CANDIDATE_GATE_UPPER_QUANTILE
    for level in cg.UPPER_QUANTILE_LEVELS:
        if level >= chosen:
            break
        assert not cg.properties_met(simulate_gate_properties(pool, upper_quantile=level)), level


def test_the_rule_takes_the_first_level_that_meets_the_properties(pool, monkeypatch):
    seen = []
    real = cg.simulate_gate_properties

    def fake(n_eff_pool, n_sets=0, seed=0, upper_quantile=0.975, **kw):
        seen.append(upper_quantile)
        base = real(n_eff_pool, n_sets=200, seed=seed, upper_quantile=upper_quantile)
        ok = upper_quantile >= 0.99
        return GateProperties(
            upper_quantile=upper_quantile,
            n_sets=base.n_sets,
            consistent_rate=0.95 if ok else 0.5,
            high_fail_rate=1.0,
            low_fail_rate=1.0,
            consistent_interval=(0.0, 1.0),
            high_fail_interval=(0.0, 1.0),
            low_fail_interval=(0.0, 1.0),
        )

    monkeypatch.setattr(cg, "simulate_gate_properties", fake)
    assert select_upper_quantile(pool) == 0.99
    assert seen == [0.975, 0.99]  # it stops at the first level that works


def test_the_rule_raises_when_no_level_meets_the_properties(pool, monkeypatch):
    def fake(n_eff_pool, n_sets=0, seed=0, upper_quantile=0.975, **kw):
        return GateProperties(
            upper_quantile=upper_quantile,
            n_sets=100,
            consistent_rate=0.1,
            high_fail_rate=1.0,
            low_fail_rate=1.0,
            consistent_interval=(0.0, 1.0),
            high_fail_interval=(0.0, 1.0),
            low_fail_interval=(0.0, 1.0),
        )

    monkeypatch.setattr(cg, "simulate_gate_properties", fake)
    with pytest.raises(ValueError, match="no level"):
        select_upper_quantile(pool)


def test_a_larger_consistent_factor_moves_the_rule_to_a_higher_level(pool, monkeypatch):
    """If a property is not met at one level, the rule moves up (the mutation shown in the PR)."""
    before = select_upper_quantile(pool)
    monkeypatch.setattr(cg, "SIMULATION_FACTOR_CONSISTENT", 1.25)
    try:
        after = select_upper_quantile(pool)
    except ValueError:
        after = None
    assert after is None or after > before
