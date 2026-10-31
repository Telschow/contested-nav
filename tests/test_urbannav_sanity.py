"""The three sanity checks of issue #182 on the made-up sequence, with known answers.

No test here needs the dataset (S2), so CI runs them. The real-data test skips without it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from navkit import urbannav_run as ur
from navkit import urbannav_sanity as us
from test_urbannav_synthetic import SEQ, write_tunnel

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "raw" / "urbannav"


@pytest.fixture(scope="module")
def aided_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_tunnel(tmp_path_factory.mktemp("sanity_aided"), outage=False)


@pytest.fixture(scope="module")
def outage_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_tunnel(tmp_path_factory.mktemp("sanity_outage"))


@pytest.fixture(scope="module")
def aided_built(aided_root: Path):
    return ur.build(aided_root)


@pytest.fixture(scope="module")
def rows(aided_root: Path) -> list[dict]:
    return us.measure(aided_root, SEQ)


def _q(rows: list[dict]) -> dict[str, dict]:
    return {r["quantity"]: r for r in rows}


def test_the_shift_is_a_declared_constant():
    assert us.CLOCK_SHIFT_S == 0.26


def test_the_shifted_clock_moves_the_imu_by_exactly_the_shift_and_leaves_the_input(aided_built):
    seq = aided_built[0]
    before = seq.imu.t.copy()
    moved = us.shift_imu_clock(seq, 0.26)
    assert np.allclose(moved.imu.t - before, 0.26)
    assert np.array_equal(moved.imu.accel, seq.imu.accel)
    assert np.array_equal(seq.imu.t, before)


def test_the_zero_shift_row_is_the_plain_aided_run(aided_built, rows):
    seq, gnss, spans, info = aided_built
    plain = ur.run_once(seq, gnss, spans, info, us.SEED, "declared")
    q = _q(rows)
    assert q["clock_shift_zero_hor_nees_mean"]["value"] == f"{plain['hor_nees_mean']:.4g}"
    assert q["clock_shift_zero_ate_rmse"]["value"] == f"{plain['ate_rmse_m']:.4g}"
    assert {"clock_shift_minus_ate_rmse", "clock_shift_plus_ate_rmse"} <= set(q)
    assert q["clock_shift"]["value"] == us.CLOCK_SHIFT_S


def test_the_clock_shift_check_does_not_apply_with_an_outage(outage_root):
    seq, gnss, spans, info = ur.build(outage_root)
    assert spans and us.clock_shift_rows(seq, gnss, spans, info) == []


def test_the_dead_reckoning_row_is_the_accelerometer_only_drift_over_the_window(aided_built, rows):
    seq = aided_built[0]
    t0 = float(seq.imu.t[0])
    drift = ur.accel_only_error_m(seq, (t0, t0 + us.DEAD_RECKONING_S))
    q = _q(rows)
    assert q["dead_reckoning_accel_only_hor_err"]["value"] == f"{drift:.4g}"
    assert q["dead_reckoning_window"]["value"] == us.DEAD_RECKONING_S
    ratio = float(q["dead_reckoning_accel_only_hor_err"]["value"]) / float(q["dead_reckoning_aided_hor_rmse"]["value"])
    assert float(q["dead_reckoning_to_aided_ratio"]["value"]) == pytest.approx(ratio, rel=1e-3)


def test_a_sequence_shorter_than_the_window_is_refused(aided_built, monkeypatch):
    monkeypatch.setattr(us, "DEAD_RECKONING_S", 1.0e6)
    with pytest.raises(us.SequenceError):
        us.dead_reckoning_rows(*aided_built)


def test_a_period_20_sine_has_lag_10_correlation_minus_one_under_every_estimator():
    t = np.arange(200.0)
    err = np.column_stack([np.sin(2 * np.pi * t / 20), np.cos(2 * np.pi * t / 20)])
    est = us.correlation_estimates(t, err)
    assert set(est) >= {"pooled_tol0.25", "pooled_tol0.5", "pooled_tol1", "mean_of_axes", "pooled_pair_centred"}
    assert all(v == pytest.approx(-1.0, abs=0.05) for v in est.values())
    q = _q([{"sequence": "s", **r} for r in us.fix_correlation_rows(t, err)])
    assert float(q["fix_corr_lag10s_spread"]["value"]) < 0.1


def test_the_spread_is_the_largest_minus_the_smallest_estimate_and_a_trend_separates_the_estimators():
    t = np.arange(100.0)
    err = np.column_stack([0.1 * t, 0.2 * t])
    est = us.correlation_estimates(t, err)
    q = _q(us.fix_correlation_rows(t, err))
    spread = float(q["fix_corr_lag10s_spread"]["value"])
    assert spread == pytest.approx(max(est.values()) - min(est.values()), abs=1e-3)
    assert spread > 0.05  # pair centring removes the trend of the pairs, the global centring does not


def test_no_pairs_at_the_lag_is_refused():
    t = np.array([0.0, 1.0, 2.0])
    with pytest.raises(us.SequenceError):
        us.fix_correlation_rows(t, np.ones((3, 2)) * np.arange(3)[:, None])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_main_writes_rows_through_the_merge_writer_and_keeps_other_blocks_byte_identical(aided_root, tmp_path):
    out = tmp_path / "s.csv"
    committed = sorted((REPO / "docs" / "data").glob("urbannav_*.csv"))
    before = {p.name: _sha(p) for p in committed}
    other = "deepurban1,keep_me,1,count\r\n"
    out.write_bytes(("sequence,quantity,value,unit\r\n" + other).encode())
    assert us.main(["--root", str(aided_root), "--sequence", SEQ, "--csv", str(out)]) == 0
    text = out.read_bytes().decode()
    assert text.startswith("sequence,quantity,value,unit\r\n") and other in text
    assert f"{SEQ},clock_shift,0.26,s\r\n" in text
    assert {p.name: _sha(p) for p in committed} == before


def test_main_prints_without_csv_and_reports_a_missing_dataset(aided_root, tmp_path, capsys):
    assert us.main(["--root", str(aided_root), "--sequence", SEQ]) == 0
    assert "dead_reckoning_window" in capsys.readouterr().out
    assert us.main(["--root", str(tmp_path / "none"), "--sequence", SEQ]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.skipif(not (DATA / "tunnel1").is_dir(), reason="UrbanNav data not fetched")
def test_real_data_rows_are_finite(tmp_path):  # pragma: no cover
    out = tmp_path / "r.csv"
    assert us.main(["--root", str(DATA), "--sequence", "tunnel1", "--csv", str(out)]) == 0
