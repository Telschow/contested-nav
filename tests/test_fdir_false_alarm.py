"""The per-update false-alarm count, the settling window, the predicted rate and the one-at-a-time sweep.

The counting is tested on streams of known NIS values, so the answer is known by construction. Two short real runs
check the wiring (the CSV columns, determinism, and that the outage leaves no fix to count). The committed CSVs and
the page are tested in ``test_fdir_false_alarm_page.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from navkit import fdir_false_alarm as fa
from navkit.benchmark import default_config_path, run_case
from navkit.eval.calibration import wilson_interval
from navkit.fdir.config import FdirConfig
from navkit.fdir.gating import chi2_threshold

THRESHOLD = chi2_threshold(3, FdirConfig().alpha)


def _survival_dof3(x: float) -> float:
    """P(chi2_3 > x) in closed form, so the predicted rate is checked against something other than chi2_cdf."""
    return math.erfc(math.sqrt(x / 2.0)) + math.sqrt(2.0 * x / math.pi) * math.exp(-x / 2.0)


# --- counting ---------------------------------------------------------------------------------


@pytest.mark.parametrize("k", [0, 1, 7, 40])
def test_exactly_k_values_above_the_threshold_give_k_rejections(k: int) -> None:
    nis = np.full(200, 1.0)
    nis[np.arange(k) * 5] = THRESHOLD + 0.001
    assert fa.count_rejections(nis, THRESHOLD) == k
    assert int(fa.rejection_indicator(nis, THRESHOLD).sum()) == k


def test_a_value_equal_to_the_threshold_is_accepted_as_the_gate_accepts_it() -> None:
    nis = np.array([THRESHOLD, THRESHOLD, np.nextafter(THRESHOLD, np.inf)])
    assert fa.count_rejections(nis, THRESHOLD) == 1


def test_an_infinite_distance_is_a_rejection() -> None:
    assert fa.count_rejections(np.array([1.0, np.inf, 2.0]), THRESHOLD) == 1


def test_the_threshold_is_the_one_the_gate_uses() -> None:
    assert fa.gate_threshold() == chi2_threshold(3, FdirConfig().alpha)
    assert FdirConfig().alpha == fa.ALPHA
    assert fa.DOF == 3


# --- the settling window ----------------------------------------------------------------------


def test_the_settling_window_excludes_exactly_the_stated_epochs() -> None:
    t = np.arange(0.0, 30.0, 0.5)
    scopes = fa.scope_masks(t, [(5.0, 20.0)], settle_s=5.0)
    # Half-open, as the outage windows are: [5, 20) is the outage, [20, 25) the settling period.
    assert t[scopes["outage"]].tolist() == [x / 2 for x in range(10, 40)]
    assert t[scopes["settling"]].tolist() == [x / 2 for x in range(40, 50)]
    counted = t[scopes["counted"]]
    assert counted.tolist() == [x / 2 for x in range(0, 10)] + [x / 2 for x in range(50, 60)]
    assert scopes["outage"].sum() + scopes["settling"].sum() + scopes["counted"].sum() == t.size
    assert not (scopes["outage"] & scopes["settling"]).any()
    assert not (scopes["counted"] & (scopes["outage"] | scopes["settling"])).any()


def test_a_fix_at_the_end_of_the_settling_period_is_counted_and_one_at_the_return_is_not() -> None:
    t = np.array([4.5, 5.0, 19.5, 20.0, 24.5, 25.0, 25.5])
    counted = fa.scope_masks(t, [(5.0, 20.0)], settle_s=5.0)["counted"]
    assert t[counted].tolist() == [4.5, 25.0, 25.5]


def test_the_settling_period_is_the_stated_five_seconds() -> None:
    assert fa.SETTLE_S == 5.0


def test_no_window_leaves_every_epoch_counted() -> None:
    t = np.arange(0.0, 10.0, 1.0)
    scopes = fa.scope_masks(t, [], settle_s=5.0)
    assert scopes["counted"].all()
    assert not scopes["settling"].any() and not scopes["outage"].any()


def test_two_outages_each_get_their_own_settling_period() -> None:
    t = np.arange(0.0, 40.0, 1.0)
    scopes = fa.scope_masks(t, [(5.0, 10.0), (20.0, 25.0)], settle_s=2.0)
    assert t[scopes["settling"]].tolist() == [10.0, 11.0, 25.0, 26.0]


# --- the predicted rate -----------------------------------------------------------------------


def test_the_scale_factor_is_the_mean_distance_over_the_degrees_of_freedom() -> None:
    assert fa.scale_factor(np.full(10, 6.0), 3) == pytest.approx(2.0)
    assert fa.scale_factor(np.array([1.0, 3.0, 5.0]), 3) == pytest.approx(1.0)


def test_c_of_one_predicts_alpha() -> None:
    assert fa.predicted_rate(1.0, THRESHOLD, 3) == pytest.approx(FdirConfig().alpha, abs=2e-6)


@pytest.mark.parametrize("c", [0.5, 1.0, 1.5, 2.0, 3.0])
def test_the_predicted_rate_is_the_chi_square_tail_at_threshold_over_c(c: float) -> None:
    assert fa.predicted_rate(c, THRESHOLD, 3) == pytest.approx(_survival_dof3(THRESHOLD / c), rel=1e-6)


def test_a_larger_c_predicts_more_rejections() -> None:
    rates = [fa.predicted_rate(c, THRESHOLD, 3) for c in (0.8, 1.0, 1.2, 2.0)]
    assert rates == sorted(rates) and len(set(rates)) == 4


def test_a_c_that_is_not_positive_is_refused() -> None:
    with pytest.raises(ValueError):
        fa.predicted_rate(0.0, THRESHOLD, 3)


# --- the effective count ----------------------------------------------------------------------


def test_a_series_with_no_rejection_has_no_defined_effective_size_and_counts_as_independent() -> None:
    ess, defined = fa.series_ess(np.zeros(100))
    assert (ess, defined) == (100.0, False)


def test_a_run_of_adjacent_rejections_is_worth_fewer_samples_than_it_has() -> None:
    x = np.zeros(300)
    for start in range(10, 290, 30):
        x[start : start + 6] = 1.0
    ess, defined = fa.series_ess(x)
    assert defined and 1.0 <= ess < 300.0


def test_too_short_a_series_has_no_defined_effective_size() -> None:
    assert fa.series_ess(np.array([0.0, 1.0, 0.0])) == (3.0, False)


def test_the_pooled_row_uses_the_summed_effective_count() -> None:
    per_run = [
        {"updates": 100, "rejections": 4, "ess": 50.0, "ess_defined": 1, "nis_ess": 90.0, "mean_nis": 3.0},
        {"updates": 100, "rejections": 0, "ess": 100.0, "ess_defined": 0, "nis_ess": 80.0, "mean_nis": 3.0},
        {"updates": 50, "rejections": 5, "ess": 10.0, "ess_defined": 1, "nis_ess": 40.0, "mean_nis": 6.0},
    ]
    row = fa.pooled_row("gnss_only", "all", per_run, THRESHOLD)
    assert row["updates"] == 250 and row["rejections"] == 9
    assert row["rate"] == pytest.approx(9 / 250)
    assert row["ess"] == pytest.approx(160.0)
    assert row["ess_defined"] == 2
    assert row["nis_ess"] == pytest.approx(210.0)
    # Per run, rejections are scaled by ess / updates; the sum is the effective count of rejections.
    assert row["eff_rejections"] == pytest.approx(4 * 0.5 + 0.0 + 5 * 0.2)
    assert (row["wilson_lo"], row["wilson_hi"]) == pytest.approx(wilson_interval(9, 250))
    assert (row["eff_wilson_lo"], row["eff_wilson_hi"]) == pytest.approx(wilson_interval(3.0, 160.0))
    assert row["mean_nis"] == pytest.approx((300 + 300 + 300) / 250)
    assert row["c"] == pytest.approx(row["mean_nis"] / 3.0)
    assert row["predicted_rate"] == pytest.approx(fa.predicted_rate(row["c"], THRESHOLD, 3))
    assert row["alpha"] == FdirConfig().alpha and row["threshold"] == THRESHOLD


# --- the sensitivity settings -----------------------------------------------------------------


def test_the_three_constants_are_the_ones_asked_for_and_exist_on_the_config() -> None:
    assert fa.CONSTANTS == ("max_consecutive_rejections", "reacq_consecutive_rejections", "reacq_sigma_m")
    for name in fa.CONSTANTS:
        assert hasattr(FdirConfig(), name)


def test_half_and_double_round_half_up_for_an_integer_and_are_exact_for_a_float() -> None:
    assert fa.scaled_value(5, 0.5) == 3  # 2.5 rounds up
    assert fa.scaled_value(5, 2.0) == 10
    assert fa.scaled_value(3, 0.5) == 2  # 1.5 rounds up
    assert fa.scaled_value(3, 2.0) == 6
    assert fa.scaled_value(3.0, 0.5) == 1.5
    assert fa.scaled_value(3.0, 2.0) == 6.0
    assert isinstance(fa.scaled_value(5, 0.5), int)


def test_the_settings_are_the_default_then_half_and_double_of_each_constant_from_the_live_defaults() -> None:
    cfg = FdirConfig()
    settings = fa.sensitivity_settings()
    assert settings[0] == ("default", "default", None)
    assert [(c, s) for c, s, _ in settings[1:]] == [(c, s) for c in fa.CONSTANTS for s in ("half", "double")]
    for constant, setting, value in settings[1:]:
        assert value == fa.scaled_value(getattr(cfg, constant), 0.5 if setting == "half" else 2.0)
        assert value != getattr(cfg, constant)


def test_every_setting_is_a_valid_fdir_config() -> None:
    for _, _, value in fa.sensitivity_settings()[1:]:
        assert value is not None
    for constant, _, value in fa.sensitivity_settings()[1:]:
        FdirConfig(**{constant: value})


# --- reserved seeds ---------------------------------------------------------------------------


def test_the_seeds_are_the_development_set_and_never_the_reserved_ones() -> None:
    assert tuple(range(25)) == fa.SEEDS
    assert max(fa.SEEDS) < fa.RESERVED_SEED_START == 100
    with pytest.raises(ValueError, match="reserved"):
        fa.check_seeds([0, 1, 100])
    with pytest.raises(ValueError, match="reserved"):
        fa.check_seeds([124])
    fa.check_seeds(list(range(25)))


# --- the wiring, on real runs -----------------------------------------------------------------


def _doc() -> dict:
    import yaml

    return yaml.safe_load(default_config_path().read_text())


def test_run_case_without_the_new_arguments_is_unchanged_and_the_override_reaches_the_gate() -> None:
    doc = _doc()
    case = doc["cases"]["gnss_only"]
    plain = run_case("gnss_only", case, doc["defaults"], seed=0)
    also_plain = run_case("gnss_only", case, doc["defaults"], seed=0, fdir_overrides=None, innovations_out=None)
    assert plain["config_hash"] == also_plain["config_hash"]
    assert plain["headline"]["ate_rmse_m"] == also_plain["headline"]["ate_rmse_m"]
    changed = run_case("gnss_only", case, doc["defaults"], seed=0, fdir_overrides={"max_consecutive_rejections": 3})
    assert changed["config_hash"] != plain["config_hash"]
    assert changed["estimator"]["fdir_config"]["max_consecutive_rejections"] == 3
    assert plain["estimator"]["fdir_config"]["max_consecutive_rejections"] == 5
    with pytest.raises(TypeError):
        run_case("gnss_only", case, doc["defaults"], seed=0, fdir_overrides={"no_such_constant": 1})
    with pytest.raises(ValueError):
        run_case("gnss_only", case, doc["defaults"], seed=0, fdir_overrides={"max_consecutive_rejections": 0})


def test_the_innovations_are_one_per_gnss_update_and_the_outage_leaves_none_to_count() -> None:
    doc = _doc()
    case = doc["cases"]["outage_control"]
    box: list = []
    record = run_case("outage_control", case, doc["defaults"], seed=0, innovations_out=box)
    assert len(box) == int(record["stats"]["gnss_fixes_seen"])
    t = np.array([b[0] for b in box])
    windows = fa.outage_windows(case)
    assert windows == [(5.0, 20.0)]
    scopes = fa.scope_masks(t, windows, fa.SETTLE_S)
    assert scopes["outage"].sum() == 0
    assert scopes["settling"].sum() > 0 and scopes["counted"].sum() > 0


def test_the_per_run_record_counts_the_updates_the_filter_gated() -> None:
    doc = _doc()
    run = fa.run_one("gnss_only", 0, doc)
    assert set(run) == {"gnss_only/all"}
    rec = run["gnss_only/all"]
    box: list = []
    full = run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0, innovations_out=box)
    assert rec["updates"] == int(full["stats"]["gnss_fixes_seen"]) == len(box)
    nis = np.array([fa.mahalanobis_sq(r, s) for _, r, s in box])
    assert rec["rejections"] == int((nis > THRESHOLD).sum())
    assert rec["rate"] == rec["rejections"] / rec["updates"]
    assert rec["mean_nis"] == pytest.approx(float(nis.mean()))


def _write_read(table, rows, path):
    table.write(path, rows)
    return path.read_text(encoding="utf-8"), table.read(path)


def test_the_csv_columns_and_determinism(tmp_path) -> None:
    text_1, parsed = _write_read(fa.RATE_TABLE, fa.rate_rows(seeds=[0, 1]), tmp_path / "a.csv")
    text_2, _ = _write_read(fa.RATE_TABLE, fa.rate_rows(seeds=[0, 1]), tmp_path / "b.csv")
    assert text_1 == text_2
    lines = text_1.splitlines()
    assert lines[0] == ",".join(fa.RATE_FIELDS)
    assert fa.RATE_FIELDS[:3] == ("case", "scope", "seed")
    assert [(r["case"], r["scope"], r["seed"]) for r in parsed] == [
        ("gnss_only", "all", 0),
        ("gnss_only", "all", 1),
        ("gnss_only", "all", "all"),
        ("outage_control", "counted", 0),
        ("outage_control", "counted", 1),
        ("outage_control", "counted", "all"),
        ("outage_control", "settling", 0),
        ("outage_control", "settling", 1),
        ("outage_control", "settling", "all"),
    ]
    assert _write_read(fa.RATE_TABLE, parsed, tmp_path / "c.csv")[1] == parsed


def test_comparing_a_subset_of_seeds_checks_the_per_seed_rows_and_skips_the_pooled_ones() -> None:
    full = fa.rate_rows(seeds=[0, 1, 2])
    subset = fa.rate_rows(seeds=[0, 1])
    assert fa.compare_rate_rows(subset, full) == []
    broken = [dict(r) for r in full]
    first = next(r for r in broken if r["seed"] == 0 and r["case"] == "gnss_only")
    first["rejections"] += 1
    assert fa.compare_rate_rows(subset, broken)


def test_the_sensitivity_csv_columns_and_determinism_on_one_small_cell_set(tmp_path) -> None:
    kwargs = {"faults": ["gnss_spoof_sustained"], "constants": ["reacq_sigma_m"], "seeds": 2}
    text_1, rows = _write_read(fa.SENSITIVITY_TABLE, fa.sensitivity_rows(**kwargs), tmp_path / "a.csv")
    text_2, _ = _write_read(fa.SENSITIVITY_TABLE, fa.sensitivity_rows(**kwargs), tmp_path / "b.csv")
    assert text_1 == text_2
    assert text_1.splitlines()[0] == ",".join(fa.SENSITIVITY_FIELDS)
    # gnss_only control + three spoof levels, at the default and at half and double reacq_sigma_m.
    assert len(rows) == 4 * 3
    assert {(r["constant"], r["setting"]) for r in rows} == {
        ("default", "default"),
        ("reacq_sigma_m", "half"),
        ("reacq_sigma_m", "double"),
    }
    assert {r["n_seeds"] for r in rows} == {2}
    assert all(0 <= r["declared_n"] <= 2 and 0 <= r["detected_n"] <= 2 for r in rows)
    assert fa.compare_sensitivity_rows(rows, rows) == []
