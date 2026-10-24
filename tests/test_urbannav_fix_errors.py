"""The fix-error aggregate: how the receiver's own fix errors behave in time (``navkit urbannav fixerrors``).

The functions are checked against series whose answer is known. No dataset is read here.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit import urbannav_fix_errors as fe


def _t(n: int) -> np.ndarray:
    return np.arange(n, dtype=float)


def test_the_pairs_of_a_lag_are_the_fixes_that_far_apart_within_the_tolerance():
    t = _t(100)
    i, j = fe.lag_pairs(t, 10)
    assert len(i) == 90 and np.all(j - i == 10)
    odd = np.arange(100) % 2
    assert len(fe.lag_pairs(t + 0.3 * odd, 11)[0]) == 89  # 10.7 and 11.3 s apart: within 0.5 of 11
    assert len(fe.lag_pairs(t + 0.7 * odd, 11)[0]) == 0  # 10.3 and 11.7 s apart: out


def test_a_gap_in_the_times_removes_the_pairs_across_it():
    t = np.concatenate([_t(50), _t(50) + 100.0])
    i, j = fe.lag_pairs(t, 10)
    assert len(i) == 80 and np.all(t[j] - t[i] == 10.0)


def test_a_sine_of_period_twenty_seconds_is_anticorrelated_at_ten_and_correlated_at_twenty():
    t = _t(400)
    x = np.sin(2 * np.pi * t / 20.0)
    assert fe.pair_correlation(x, *fe.lag_pairs(t, 10)) == pytest.approx(-1.0, abs=1e-9)
    assert fe.pair_correlation(x, *fe.lag_pairs(t, 20)) == pytest.approx(1.0, abs=1e-9)


def test_white_noise_has_a_small_correlation_at_every_lag_and_a_large_effective_sample_size():
    t = _t(1500)
    err = np.random.default_rng(1).normal(size=(1500, 2))
    rows = {r["quantity"]: float(r["value"]) for r in fe.rows_for("x", t, err)}
    for lag in fe.LAGS_S:
        assert abs(rows[f"fix_error_corr_pooled_lag{lag}s"]) < 0.1
    assert rows["fix_error_ess_east"] > 500 and rows["fix_error_ess_north"] > 500


def test_a_slowly_wandering_error_is_correlated_over_tens_of_seconds_and_has_few_effective_samples():
    t = _t(1500)
    rng = np.random.default_rng(2)
    walk = np.zeros(1500)
    for k in range(1, 1500):  # AR(1) with a correlation time of about 50 s
        walk[k] = 0.98 * walk[k - 1] + rng.normal()
    err = np.column_stack([walk, np.roll(walk, 7)])
    rows = {r["quantity"]: float(r["value"]) for r in fe.rows_for("x", t, err)}
    assert rows["fix_error_corr_pooled_lag1s"] > 0.95 and rows["fix_error_corr_pooled_lag10s"] > 0.6
    assert rows["fix_error_corr_pooled_lag10s"] > rows["fix_error_corr_pooled_lag60s"]
    assert rows["fix_error_ess_east"] < 100


def test_a_constant_offset_is_reported_and_does_not_change_the_correlation():
    t = _t(300)
    rng = np.random.default_rng(3)
    base = np.cumsum(rng.normal(size=(300, 2)), axis=0)
    a = {r["quantity"]: r["value"] for r in fe.rows_for("x", t, base)}
    b = {r["quantity"]: r["value"] for r in fe.rows_for("x", t, base + np.array([5.0, -3.0]))}
    assert float(b["fix_error_offset_east"]) == pytest.approx(float(a["fix_error_offset_east"]) + 5.0, abs=1e-2)
    assert float(b["fix_error_offset_north"]) == pytest.approx(float(a["fix_error_offset_north"]) - 3.0, abs=1e-2)
    for key in a:
        if key.startswith(("fix_error_corr", "fix_error_rms")):
            assert a[key] == b[key], key


def test_the_rms_about_the_offset_is_the_horizontal_root_mean_square_of_the_centred_error():
    t = _t(100)
    err = np.column_stack([np.where(np.arange(100) % 2, 3.0, -3.0), np.where(np.arange(100) % 2, 4.0, -4.0)])
    rows = {r["quantity"]: float(r["value"]) for r in fe.rows_for("x", t, err)}
    assert rows["fix_error_rms_about_offset"] == pytest.approx(5.0)
    assert rows["fix_error_offset_east"] == pytest.approx(0.0, abs=1e-9)


def test_a_lag_longer_than_the_sequence_has_no_pairs_and_no_correlation_row():
    rows = {r["quantity"] for r in fe.rows_for("x", _t(40), np.random.default_rng(4).normal(size=(40, 2)))}
    assert "fix_error_pairs_lag30s" in rows and "fix_error_corr_pooled_lag30s" in rows
    assert "fix_error_pairs_lag60s" in rows and "fix_error_corr_pooled_lag60s" not in rows


def test_every_quantity_has_a_label_and_the_rows_have_the_documented_columns():
    rows = fe.rows_for("x", _t(200), np.random.default_rng(5).normal(size=(200, 2)))
    assert all(set(r) == set(fe.CSV_COLUMNS) for r in rows)
    assert all(r["quantity"] in fe.LABELS for r in rows)
