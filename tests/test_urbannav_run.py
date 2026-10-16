"""docs/urbannav.md's run section against the committed CSV, and the pieces of the run against known answers.

The dataset is not vendored (S2), so CI cannot rerun the filter on it. It checks that the page is the table the CSV
produces, that every sentence of the prose follows from the CSV, and that the helpers give the right answer on
sequences built here. The fetched files, when present, must reproduce the committed numbers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import urbannav_data as ud
from navkit import urbannav_run as ur
from navkit.recorded import EurocSequence
from navkit.types import GRAVITY, GnssFix, ImuSample, Trajectory

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "urbannav.md"
CSV = ROOT / "docs" / "data" / "urbannav_run.csv"
FETCHED = ROOT / "data" / "raw" / "urbannav"


@pytest.fixture(scope="module")
def rows():
    return ur.rows_from_csv(CSV)


def _q(rows, variant, key):
    return np.array([float(r["value"]) for r in rows if r["variant"] == variant and r["quantity"] == key])


# ---------------------------------------------------------------------- the page


def test_the_page_blocks_are_what_the_code_and_the_csv_produce(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in {**ur.BLOCKS, **ur.CODE_BLOCKS}.values():
        assert fn(rows) in text


def test_the_csv_has_both_variants_and_every_seed_and_quantity(rows):
    for v in ur.VARIANTS:
        for key, _, _ in ur.QUANTITIES:
            assert len(_q(rows, v, key)) == len(ur.SEEDS), (v, key)
    assert {int(r["seed"]) for r in rows} == set(ur.SEEDS)


def test_the_declared_table_matches_the_numbers_the_run_uses():
    n = ur.imu_noise()
    assert float(ur.DECLARED["gyro_noise_density"][0]) == pytest.approx(n.gyro_noise_density, rel=1e-3)
    assert float(ur.DECLARED["accel_noise_density"][0]) == pytest.approx(n.accel_noise_density, rel=1e-3)
    assert float(ur.DECLARED["gnss_vertical_sigma"][0]) == ur.GNSS_VERTICAL_SIGMA_M
    # the larger of two disagreeing datasheet figures, as the rule says
    assert n.gyro_noise_density == pytest.approx(0.03 * np.pi / 180.0)
    assert n.accel_noise_density == pytest.approx(80.0e-6 * float(np.linalg.norm(GRAVITY)))


def test_the_second_variant_is_labelled_as_chosen_after_the_first_result():
    assert "AFTER" in ur.DECLARED["variant: per_fix"][1]
    assert "Not blind" in ur.DECLARED["variant: per_fix"][1]


# ------------------------------------------------------------ the prose, claim by claim


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_the_filter_is_wrong_and_overconfident_at_the_end_of_the_outage(rows, variant):
    err, claimed = _q(rows, variant, "hor_err_at_end_m"), _q(rows, variant, "hor_claimed_at_end_m")
    assert np.all(err > 3.0 * claimed)
    assert np.all(_q(rows, variant, "hor_nees_outage") > 2.0)


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_the_drift_is_far_more_than_the_accelerometer_alone_gives(rows, variant):
    alone = _q(rows, variant, "accel_only_hor_err_at_end_m")
    assert np.all(alone < 0.25 * _q(rows, variant, "hor_err_at_end_m"))
    assert np.all(_q(rows, variant, "att_err_at_end_deg") > 2.0)


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_the_channel_is_lost_for_good(rows, variant):
    assert np.all(_q(rows, variant, "gnss_channel_faulted") == 1)
    assert np.all(_q(rows, variant, "gnss_reaccepted") == 0)
    assert np.all(_q(rows, variant, "hor_err_median_after_m") > _q(rows, variant, "hor_err_at_end_m"))


def test_per_fix_weighting_follows_the_fixes_more_closely_and_is_still_not_calibrated(rows):
    assert np.median(_q(rows, "per_fix", "hor_err_median_before_m")) < np.median(
        _q(rows, "declared", "hor_err_median_before_m")
    )
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "hor_nees_before") > 2.0)


def test_the_scalar_variant_rejects_most_wrong_fixes_and_the_per_fix_variant_accepts_most(rows):
    wrong = _q(rows, "declared", "wrong_fixes")
    assert np.all(_q(rows, "declared", "wrong_fixes_over_gate") > 0.5 * wrong)
    assert np.all(_q(rows, "per_fix", "wrong_fixes_over_gate") < 0.5 * wrong)


def test_the_start_biases_were_a_guess(rows):
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "start_bias_at_rest") == 0)


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_the_seeds_agree(rows, variant):
    end = _q(rows, variant, "hor_err_at_end_m")
    assert end.max() < 1.1 * end.min()


def test_the_page_says_what_it_does_not_show():
    text = PAGE.read_text(encoding="utf-8")
    assert "Deep-Urban-1, the planned unseen check, has not been fetched or run" in text
    assert "not blind" in text and "not field performance" in text


# ------------------------------------------------------------------ the helpers


def _line_sequence(extra_accel: float, seconds: float = 60.0) -> EurocSequence:
    """A vehicle moving at constant velocity along x, with an accelerometer that reads gravity plus a bias."""
    t = np.arange(0.0, seconds, 0.01)
    f = np.tile([0.0, 0.0, float(np.linalg.norm(GRAVITY))], (t.size, 1))
    f[:, 0] += extra_accel
    imu = ImuSample(t=t, accel=f, gyro=np.zeros((t.size, 3)))
    tt = np.arange(0.0, seconds + 1.0, 1.0)
    poses = np.tile(np.eye(4), (tt.size, 1, 1))
    poses[:, 0, 3] = 10.0 * tt
    truth = Trajectory(t=tt, poses=poses)
    vel = np.tile([10.0, 0.0, 0.0], (tt.size, 1))
    z = np.zeros((tt.size, 3))
    return EurocSequence("line", imu, truth, vel, z, z, ur.imu_noise(), "test", bias_known=False)


def test_the_accelerometer_only_drift_is_zero_without_a_bias_and_half_a_t_squared_with_one():
    clean = ur.accel_only_error_m(_line_sequence(0.0), (5.0, 55.0))
    biased = ur.accel_only_error_m(_line_sequence(0.1), (5.0, 55.0))
    assert clean < 0.5
    assert biased == pytest.approx(0.5 * 0.1 * 50.0**2, rel=0.02)


def test_run_sequence_takes_real_fixes_labels_the_record_and_honours_per_fix_covariance(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    t = np.arange(float(seq.imu.t[0]) + 1.0, float(seq.imu.t[-1]) - 1.0, 1.0)
    keep = (t < 30.0) | (t >= 50.0)  # a 20 s gap is the outage
    truth_pos = np.column_stack([np.interp(t, seq.truth.t, seq.truth.positions[:, k]) for k in range(3)])

    def run(variance: float, offset: float, per_fix: bool = True):
        pos = truth_pos.copy()
        pos[:, 0] += offset
        fixes = GnssFix(t=t[keep], positions=pos[keep], cov=np.full((int(keep.sum()), 3), variance))
        opts = ee.RunOptions(
            gnss_sigma_m=1.0, outages=((30.0, 20.0),), gnss_per_fix_covariance=per_fix, exact_init=True
        )
        detail: dict = {}
        inn: list = []
        rec = ee.run_sequence(seq, opts, gnss_override=fixes, detail_out=detail, innovations_out=inn)
        est, ref = detail["est"], detail["reference"]
        window = (est.t > 15.0) & (est.t < 30.0)
        s_med = float(np.median([np.trace(i[2]) / 3.0 for i in inn[:40]]))
        return rec, float(np.mean((est.positions - ref.positions)[window, 0])), s_med

    tight, x_tp, s_tight = run(0.01, +5.0)
    _, x_tm, _ = run(0.01, -5.0)
    _, _, s_loose = run(10000.0, +5.0)
    _, _, s_off = run(10000.0, +5.0, per_fix=False)
    assert tight["data_class"] == ee.REAL_GNSS_DATA_CLASS
    assert not any("simulated" in c for c in tight["caveats"])
    assert tight["options"]["gnss_per_fix_covariance"] is True
    assert tight["outages"] and tight["outages"][0]["duration_s"] == pytest.approx(20.0)
    # The innovation covariance carries the variance the fix supplied: small for 0.01, huge for 10000.
    assert s_tight < 1.0 and s_loose > 1000.0
    # With the setting off the fix's own variance is ignored and the scalar sigma (1 m) is used.
    assert 1.0 < s_off < 10.0
    # A tight variance makes the estimate follow a 10 m swing of the fixes.
    assert x_tp - x_tm > 9.0


def test_without_an_override_the_record_is_still_the_simulated_one(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    rec = ee.run_sequence(ee.load_sequence(tmp_path, "MH_01_easy"), ee.RunOptions(exact_init=True))
    assert rec["data_class"] == ee.DATA_CLASS
    assert "gnss_per_fix_covariance" not in rec["options"]


# ------------------------------------------------------------ the real files


def test_the_fetched_files_reproduce_the_committed_numbers(rows):
    if not (FETCHED / "tunnel1" / ud.NMEA_FILES["tunnel1"]).is_file():
        pytest.skip("tunnel1 is not fetched with its NMEA file (see docs/urbannav.md)")
    seq, gnss, spans, info = ur.build(FETCHED)
    assert gnss.cov is not None and np.all(gnss.cov[:, 2] == ur.GNSS_VERTICAL_SIGMA_M**2)
    got = ur.run_once(seq, gnss, spans, info, seed=0, variant="declared")
    for key in ("hor_err_at_end_m", "hor_claimed_at_end_m", "hor_err_median_before_m", "accel_only_hor_err_at_end_m"):
        want = float(
            next(r["value"] for r in rows if r["variant"] == "declared" and r["seed"] == "0" and r["quantity"] == key)
        )
        assert got[key] == pytest.approx(want, rel=1e-3), key
