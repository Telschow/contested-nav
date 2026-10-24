"""docs/urbannav.md's run section against the committed CSV, and the pieces of the run against known answers.

The dataset is not vendored (S2), so CI cannot rerun the filter on it. It checks that the page is the table the CSV
produces, that every sentence of the prose follows from the CSV, and that the helpers give the right answer on
sequences built here. The fetched files, when present, must reproduce the committed numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import urbannav_data as ud
from navkit import urbannav_run as ur
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.fdir.gating import chi2_threshold
from navkit.recorded import EurocSequence
from navkit.types import GRAVITY, GnssFix, ImuSample, Trajectory, interpolate_trajectory

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "urbannav.md"
CSV = ROOT / "docs" / "data" / "urbannav_run.csv"
FETCHED = ROOT / "data" / "raw" / "urbannav"


@pytest.fixture(scope="module")
def rows():
    return ur.rows_from_csv(CSV)


TUNNEL, DEEP = "tunnel1", "deepurban1"


def _q(rows, variant, key, sequence=TUNNEL):
    return np.array(
        [
            float(r["value"])
            for r in rows
            if r["sequence"] == sequence and r["variant"] == variant and r["quantity"] == key
        ]
    )


# ---------------------------------------------------------------------- the page


def test_the_page_blocks_are_what_the_code_and_the_csv_produce(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in {**ur.BLOCKS, **ur.CODE_BLOCKS}.values():
        assert fn(rows) in text


def test_the_csv_has_every_variant_and_every_seed_and_quantity(rows):
    for v in ur.ALL_VARIANTS:
        for key, _, _ in ur.QUANTITIES:
            assert len(_q(rows, v, key)) == len(ur.SEEDS), (v, key)
    tunnel = ur.rows_of(rows, TUNNEL)
    assert {int(r["seed"]) for r in tunnel} == set(ur.SEEDS)
    assert {r["variant"] for r in tunnel} == set(ur.ALL_VARIANTS)


def test_the_csv_holds_aggregates_only():
    """S2: no raw rows. One row is a sequence, a variant, a seed and a named quantity; the quantities are declared."""
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(ur.CSV_COLUMNS)
    all_rows = ur.rows_from_csv(CSV)
    assert {r["sequence"] for r in all_rows} <= {TUNNEL, DEEP}
    tunnel = ur.rows_of(all_rows, TUNNEL)
    assert {r["quantity"] for r in tunnel} == {k for k, _, _ in ur.QUANTITIES}
    assert len(tunnel) == len(ur.ALL_VARIANTS) * len(ur.SEEDS) * len(ur.QUANTITIES)
    deep = ur.rows_of(all_rows, DEEP)
    if deep:  # an aided sequence: the declared and per-fix variants only, and its own quantities
        assert {r["quantity"] for r in deep} == {k for k, _, _ in ur.AIDED_QUANTITIES}
        assert {r["variant"] for r in deep} == set(ur.VARIANTS)
        assert len(deep) == len(ur.VARIANTS) * len(ur.SEEDS) * len(ur.AIDED_QUANTITIES)
    assert len(all_rows) == len(tunnel) + len(deep)


def test_the_oracle_variants_are_declared_and_labelled_as_diagnostics_that_use_the_reference():
    assert ur.ORACLE_VARIANTS == ("oracle_tilt", "oracle_yaw", "oracle_attitude")
    assert set(ur.ALL_VARIANTS) == set(ur.VARIANTS) | set(ur.ORACLE_VARIANTS)
    for v in ur.ORACLE_VARIANTS:
        meaning = ur.DECLARED[f"variant: {v}"][1]
        assert "ORACLE DIAGNOSTIC" in meaning and "reference" in meaning and "not a filter" in meaning


def test_the_oracle_rows_are_labelled_on_the_page_and_the_page_is_generated_from_the_csv(rows):
    block = ur.oracle_markdown(rows)
    assert block in PAGE.read_text(encoding="utf-8")
    assert block.count("ORACLE DIAGNOSTIC") == len(ur.ORACLE_VARIANTS)


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


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_the_tilt_error_grows_through_the_outage(rows, variant):
    def tilt(when):
        return np.maximum(
            np.abs(_q(rows, variant, f"att_roll_err_at_{when}_deg")),
            np.abs(_q(rows, variant, f"att_pitch_err_at_{when}_deg")),
        )

    assert np.all(tilt("end") > 2.0 * tilt("start"))
    assert np.all(tilt("end") > 1.0)


def test_reference_roll_and_pitch_remove_most_of_the_outage_error_and_reference_yaw_does_not(rows):
    base = _q(rows, "declared", "hor_err_at_end_m")
    for v in ("oracle_tilt", "oracle_attitude"):
        assert np.all(_q(rows, v, "hor_err_at_end_m") < 0.1 * base), v
        assert np.all(_q(rows, v, "gnss_updates_rejected") < 0.5 * _q(rows, "declared", "gnss_updates_rejected")), v
    assert np.all(np.abs(_q(rows, "oracle_yaw", "hor_err_at_end_m") / base - 1.0) < 0.05)


def test_the_oracles_start_from_the_same_state_as_the_filter_they_are_compared_with(rows):
    """Outside the outage an oracle is the declared filter, so what it did before the outage is identical."""
    for v in ur.ORACLE_VARIANTS:
        for key in ("hor_err_median_before_m", "hor_nees_before", "hor_err_at_start_m"):
            assert _q(rows, v, key) == pytest.approx(_q(rows, "declared", key), rel=1e-3), (v, key)


@pytest.mark.parametrize("variant", ur.VARIANTS)
def test_every_fix_after_the_outage_is_over_the_gate_and_the_first_return_is_far_over_it(rows, variant):
    level = chi2_threshold(3, ur.GATE_ALPHA)
    after = _q(rows, variant, "fixes_after_outage")
    assert np.all(after > 0)
    assert np.all(after == _q(rows, variant, "fixes_after_outage_over_gate"))
    assert np.all(_q(rows, variant, "nis_first_return") > 2.0 * level)


def test_the_run_reports_what_the_reader_dropped_and_the_variances_the_filter_would_floor(rows):
    for v in ur.ALL_VARIANTS:
        assert np.all(_q(rows, v, "epochs_not_valid") > 0)
        assert np.all(_q(rows, v, "fixes_variance_unusable") == 0)
        assert np.all(_q(rows, v, "fixes_variance_below_floor") == 0)


def test_the_page_says_what_it_does_not_show():
    text = PAGE.read_text(encoding="utf-8")
    assert "has not been fetched or run" not in text  # Deep-Urban-1 has been run, as an aided run
    assert "does not say how the filter does on a sequence where the receiver reports no outage" in text
    assert "not blind" in text and "not field performance" in text


def test_the_page_labels_the_oracles_the_hypothesis_and_the_missing_link():
    text = PAGE.read_text(encoding="utf-8")
    assert "ORACLE DIAGNOSTIC" in text
    assert "HYPOTHESIS" in text and "not tested" in text
    assert "A link between" in text and "is not shown" in text
    assert "one sequence, one receiver" in text.lower()
    assert "measured as zero" not in text


# ------------------------------------------------------------------ the Deep-Urban-1 section


def _deep_section() -> str:
    text = PAGE.read_text(encoding="utf-8")
    start = text.index("## Deep-Urban-1: real urban GNSS, no outage")
    return text[start : text.index("## What follows")]


def _outside_blocks(section: str) -> str:
    return re.sub(r"<!-- ([a-z-]+):start -->.*?<!-- \1:end -->", "", section, flags=re.S)


def test_the_deep_urban_section_says_what_it_is_and_what_it_is_not():
    section = _deep_section()
    for phrase in (
        "One sequence, one receiver, one recording",
        "The receiver reports no outage here",
        "aided run",
        "not applicable",
        "right about how wrong it is",
        "multipath fixes",
        "It is not field performance",
        "Imposed outages are a separate experiment",
    ):
        assert phrase in section, phrase
    assert "issue #95" in section  # the outage rule was not changed to find one


def test_the_deep_urban_section_has_its_generated_blocks_and_nothing_typed_in_them():
    section = _deep_section()
    for name in ("urbannav-deep-urban-run-declared", "urbannav-deep-urban-run-per-fix", "urbannav-deep-urban-oracle"):
        assert f"<!-- {name}:start -->" in section and f"<!-- {name}:end -->" in section
        assert name in {**ur.BLOCKS, **ur.CODE_BLOCKS}
    assert "oracle" not in {n for n in ur.BLOCKS if "deep-urban" in n}  # no oracle table is generated for it


def test_the_deep_urban_prose_has_no_typed_numbers():
    prose = _outside_blocks(_deep_section())
    for allowed in ("Deep-Urban-1", "Tunnel-1", "issue #95", "2-sigma", "SPAN-CPT"):
        prose = prose.replace(allowed, "")
    prose = re.sub(r"^\s*\d+\. ", "", prose, flags=re.M)  # the numbering of a list
    assert not re.search(r"\d", prose), re.findall(r".{20}\d.{20}", prose)


def test_a_sequence_with_no_rows_is_said_not_to_have_been_run():
    assert "has not been run for this page" in ur.run_markdown([], "declared", DEEP)
    assert "has not been run for this page" in ur.oracle_markdown([], DEEP)
    assert "has not been run" not in ur.run_markdown(ur.rows_from_csv(CSV), "declared", DEEP)


def test_the_deep_urban_status_is_that_it_has_been_run(rows):
    section = _deep_section()
    assert ur.rows_of(rows, DEEP) and "Status: run for this page" in section
    assert "has not been run for this page" not in section
    assert "Status: not run" not in PAGE.read_text(encoding="utf-8")


def test_deep_urban_1_has_rows_and_they_are_the_aided_run(rows):
    deep = ur.rows_of(rows, DEEP)
    assert {r["variant"] for r in deep} == set(ur.VARIANTS)  # no oracle rows
    assert ur.oracle_markdown(rows, DEEP) == ur.ORACLE_NOT_APPLICABLE
    assert ur.ORACLE_NOT_APPLICABLE in PAGE.read_text(encoding="utf-8")
    for v in ur.VARIANTS:
        used, rejected = _q(rows, v, "fixes_used", DEEP), _q(rows, v, "gnss_updates_rejected", DEEP)
        assert np.all(used + rejected == _q(rows, v, "fixes_total", DEEP))
        assert np.all(_q(rows, v, "epochs_not_valid", DEEP) == 0)
        for key, _, _ in ur.AIDED_QUANTITIES:
            assert len(_q(rows, v, key, DEEP)) == len(ur.SEEDS), (v, key)


def test_the_absolute_trajectory_error_is_in_the_csv_and_not_in_the_page_tables(rows):
    assert all(len(_q(rows, v, "ate_rmse_m", DEEP)) == len(ur.SEEDS) for v in ur.VARIANTS)
    for v in ur.VARIANTS:
        assert "Absolute trajectory error" not in ur.run_markdown(rows, v, DEEP)
        assert "Horizontal position RMSE" in ur.run_markdown(rows, v, DEEP)
    assert "Absolute trajectory error" not in PAGE.read_text(encoding="utf-8")


# -------------------------------------- the statements of the Deep-Urban-1 section, each tied to the CSVs

DATA_CSV = ROOT / "docs" / "data" / "urbannav_data.csv"
FIX_ERRORS_CSV = ROOT / "docs" / "data" / "urbannav_fix_errors.csv"
HOR_NEES_EXPECTED, ATT_NEES_EXPECTED = 2.0, 3.0


def _fix_errors(sequence, quantity):
    from navkit import urbannav_fix_errors as fe

    (value,) = [
        float(r["value"])
        for r in fe.rows_from_csv(FIX_ERRORS_CSV)
        if r["sequence"] == sequence and r["quantity"] == quantity
    ]
    return value


def _data(sequence, quantity):
    from navkit import urbannav_check as uc

    (value,) = [
        float(r["value"]) for r in uc.rows_from_csv(DATA_CSV) if r["sequence"] == sequence and r["quantity"] == quantity
    ]
    return value


def test_statement_the_receiver_reports_no_outage(rows):
    assert _data(DEEP, "gnss_outages") == 0 and _data(DEEP, "gnss_denied_epochs") == 0
    assert _data(DEEP, "gnss_epochs") == _data(DEEP, "reference_epochs")
    assert _data(TUNNEL, "gnss_outages") == 1  # the control: the same rule does find the tunnel
    assert "The receiver reports no outage here" in _deep_section()


def test_statement_the_gate_rejects_none_though_far_fixes_exist_and_the_nis_is_far_below_its_level(rows):
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "gnss_updates_rejected", DEEP) == 0)
        assert np.all(_q(rows, v, "gnss_channel_faulted", DEEP) == 0)
        assert np.all(_q(rows, v, "fixes_over_3sigma", DEEP) > 0) and np.all(_q(rows, v, "wrong_fixes", DEEP) > 0)
        assert np.all(_q(rows, v, "wrong_fixes_over_gate", DEEP) == 0)
        assert np.all(_q(rows, v, "nis_mean", DEEP) < 0.25 * _q(rows, v, "fix_gate_level", DEEP))
        alpha = _q(rows, v, "fix_gate_alpha", DEEP)
        assert np.all(_q(rows, v, "fix_rejection_wilson_lo", DEEP) <= alpha)
        assert np.all(alpha <= _q(rows, v, "fix_rejection_wilson_hi", DEEP))
        assert np.all(_q(rows, v, "fix_gate_level", DEEP) == pytest.approx(chi2_threshold(3, ur.GATE_ALPHA), rel=1e-3))
    assert "The gate rejects none of the offered fixes" in _deep_section()


def test_statement_the_rejection_count_convention_for_a_constant_series(rows):
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "fix_rejection_ess_defined", DEEP) == 0)
        assert np.all(_q(rows, v, "fix_rejection_ess", DEEP) == _q(rows, v, "fixes_total", DEEP))
        assert np.all(_q(rows, v, "fix_rejection_eff_wilson_hi", DEEP) == _q(rows, v, "fix_rejection_wilson_hi", DEEP))
    assert "counts every fix as an independent" in " ".join(_deep_section().split())


def test_statement_the_filter_is_overconfident_in_position_and_attitude(rows):
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "hor_nees_mean", DEEP) > 3 * HOR_NEES_EXPECTED)
        assert np.all(_q(rows, v, "att_nees_mean", DEEP) > 3 * ATT_NEES_EXPECTED)
        assert np.all(_q(rows, v, "hor_coverage_2sigma", DEEP) < ur.COVERAGE_2SIGMA_GAUSSIAN - 0.25)
        assert np.all(_q(rows, v, "claimed_sigma_median_m", DEEP) < _q(rows, v, "receiver_sigma_median_m", DEEP))
    assert "The filter is overconfident against this reference" in _deep_section()


def test_statement_the_excess_is_in_every_third_so_it_is_not_a_start_up_transient(rows):
    for v in ur.VARIANTS:
        for k in (1, 2, 3):
            assert np.all(_q(rows, v, f"hor_nees_third{k}", DEEP) > 2 * HOR_NEES_EXPECTED), (v, k)
            assert np.all(_q(rows, v, f"att_nees_third{k}", DEEP) > 2 * ATT_NEES_EXPECTED), (v, k)
        mean = (
            _q(rows, v, "hor_nees_third1", DEEP)
            + _q(rows, v, "hor_nees_third2", DEEP)
            + _q(rows, v, "hor_nees_third3", DEEP)
        ) / 3
        assert mean == pytest.approx(_q(rows, v, "hor_nees_mean", DEEP), rel=0.01)  # the thirds are the run's parts
    assert "not a start-up transient" in _deep_section()


def test_statement_the_means_have_few_independent_samples_behind_them(rows):
    for v in ur.VARIANTS:
        n = _q(rows, v, "fixes_total", DEEP)
        assert np.all(_q(rows, v, "hor_nees_ess", DEEP) < 100)  # of 614782 IMU steps
        assert np.all(_q(rows, v, "hor_nees_ess", DEEP) < n) and np.all(_q(rows, v, "att_nees_ess", DEEP) < n)
    assert "few independent samples" in _deep_section()


def test_statement_the_receivers_own_sigma_is_optimistic_and_both_variants_see_the_same_fixes(rows):
    for key in ("fix_nees_mean", "fix_err_p50_m", "fix_err_p95_m", "fix_err_p99_m", "fixes_over_3sigma", "wrong_fixes"):
        assert np.array_equal(_q(rows, "declared", key, DEEP), _q(rows, "per_fix", key, DEEP)), key
    assert np.all(_q(rows, "declared", "fix_nees_mean", DEEP) > HOR_NEES_EXPECTED)


def test_statement_the_height_is_not_relied_on_and_its_error_is_large(rows):
    assert float(ur.DECLARED["gnss_vertical_sigma"][0]) == 100.0
    for v in ur.VARIANTS:
        assert np.all(_q(rows, v, "ver_rmse_m", DEEP) > 2 * _q(rows, v, "hor_rmse_m", DEEP))
    assert "The height is not relied on" in _deep_section()


def test_statement_the_reference_is_an_estimate_with_several_quality_codes():
    assert _data(DEEP, "reference_quality_codes") > 1
    section = " ".join(_deep_section().split())
    assert "post-processed estimate" in section and "its error is not known" in section


def test_interpretation_the_fix_errors_are_correlated_over_tens_of_seconds_and_few_samples_are_independent():
    n = _fix_errors(DEEP, "fix_error_fixes")
    assert _fix_errors(DEEP, "fix_error_corr_pooled_lag10s") > 0.9
    assert _fix_errors(DEEP, "fix_error_corr_pooled_lag30s") > 0.5
    assert _fix_errors(DEEP, "fix_error_corr_pooled_lag60s") > 0.3
    for axis in ("east", "north"):
        assert _fix_errors(DEEP, f"fix_error_ess_{axis}") < 0.05 * n
        assert _fix_errors(DEEP, f"fix_error_ess_{axis}_truncated") == 0
    # the other sequence is less correlated at ten seconds: the correlation is not a property of every sequence
    assert _fix_errors(TUNNEL, "fix_error_corr_pooled_lag10s") < 0.5 * _fix_errors(DEEP, "fix_error_corr_pooled_lag10s")
    section = " ".join(_deep_section().split())
    for phrase in (
        "INTERPRETATION, not a result of this page",
        "treats the receiver's fixes as independent measurements",
        "correlated over tens of seconds",
        "does not prove the cause",
        "the filter was not run with a correlated-error model here",
        "some of the correlated difference could be in the reference",
    ):
        assert phrase in section, phrase


def test_the_fix_error_block_is_what_the_code_and_its_csv_produce():
    from navkit import urbannav_fix_errors as fe

    rows = fe.rows_from_csv(FIX_ERRORS_CSV)
    assert {r["sequence"] for r in rows} == {TUNNEL, DEEP}
    text = PAGE.read_text(encoding="utf-8")
    for fn in fe.BLOCKS.values():
        assert fn(rows) in text


def test_the_fix_error_csv_holds_aggregates_only_and_the_tunnel_data_rows_are_untouched():
    from navkit import urbannav_fix_errors as fe

    text = FIX_ERRORS_CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(fe.CSV_COLUMNS)
    assert all(r["quantity"] in fe.LABELS for r in fe.rows_from_csv(FIX_ERRORS_CSV))
    assert len(text.splitlines()) < 100  # a table of aggregates, not of fixes
    # the committed Tunnel-1 lines of the two older CSVs, hashed (the values recorded before Deep-Urban-1 was added)
    import hashlib

    def tunnel_hash(path):
        lines = [x for x in path.read_bytes().splitlines(keepends=True) if x.startswith(b"tunnel1,")]
        return hashlib.sha256(b"".join(lines)).hexdigest()

    assert tunnel_hash(CSV) == "de65bb1c4a9cee30aaaafc02f8046ab23b339d0bf7379d3a279433ec815783c3"
    assert tunnel_hash(DATA_CSV) == "b9d3fc433e183e15c30c6a44a5c9a4c28b86cdc973fc0da8b439486a480a0b68"


# ----------------------------------------------------- the reader's report and the oracles


def test_unusable_variances_are_counted_and_dropped_and_small_ones_are_counted():
    cov = np.array(
        [[1, 1, 1], [np.nan, 1, 1], [1, -1, 1], [0, 1, 1], [1e-6, 1, 1], [np.inf, 1, 1], [4, 4, 1e4]], dtype=float
    )
    assert ur.usable_variance_mask(cov).tolist() == [True, False, False, True, True, False, True]
    report = ur.variance_report(cov, floor_sigma_m=0.01)
    assert report == {"unusable": 3, "below_floor": 2}


def test_the_default_floor_the_report_uses_is_the_filters():
    assert EskfConfig(imu_noise=ur.imu_noise()).gnss_per_fix_min_sigma_m == ur.FLOOR_SIGMA_M


def test_epochs_not_valid_counts_what_the_outage_rule_treats_as_denied():
    n = 5
    fixes = ud.GgaFixes(
        np.arange(n, dtype=float),
        np.array([22.3, np.nan, 22.3, 22.3, 22.3]),
        np.array([114.2, np.nan, 114.2, 114.2, 114.2]),
        np.zeros(n),
        np.array([2, 0, 0, 1, 2]),
        np.full(n, 12),
        np.full(n, 0.6),
    )
    assert ur.epochs_not_valid(fixes) == 2


@pytest.mark.parametrize("mode", ur.ORACLE_VARIANTS)
def test_an_oracle_overwrites_only_the_named_attitude_and_only_inside_the_outage(tmp_path, mode):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    t0 = float(seq.imu.t[0])
    span = (t0 + 10.0, t0 + 20.0)
    orig = ErrorStateKalmanFilter._propagate
    filt = ErrorStateKalmanFilter(EskfConfig(imu_noise=ur.imu_noise()))
    x = filt._initial_state()
    own = ud.rpy_to_rotation(np.array([11.0]), np.array([6.0]), np.array([57.0]))[0]
    x["R"] = own.copy()
    ref = interpolate_trajectory(seq.truth, seq.imu.t)
    ref_r, ref_p, ref_h = ud.rotation_to_rpy(ref.rotations)
    own_r, own_p, own_h = ud.rotation_to_rpy(own)
    seen_inside = 0
    with ur.oracle_attitude(seq, span, mode):
        t = 0.0
        for _ in range(3000):
            filt._propagate(x, np.array([0.0, 0.0, 9.81]), np.zeros(3), 0.01)
            t += 0.01
            r, p, h = ud.rotation_to_rpy(x["R"])
            k = min(int(np.searchsorted(seq.imu.t - t0, t)), len(seq.imu.t) - 1)
            if t < 10.0 - 1e-9:
                assert (r, p, h) == pytest.approx((own_r, own_p, own_h), abs=1e-6)
            elif 10.0 + 1e-6 < t < 20.0 - 1e-6:
                seen_inside += 1
                want_r, want_p, want_h = {
                    "oracle_tilt": (ref_r[k], ref_p[k], own_h),
                    "oracle_yaw": (own_r, own_p, ref_h[k]),
                    "oracle_attitude": (ref_r[k], ref_p[k], ref_h[k]),
                }[mode]
                assert r == pytest.approx(want_r, abs=1e-6)
                assert p == pytest.approx(want_p, abs=1e-6)
                assert (h - want_h + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-6)
            if t >= 22.0:
                break
    assert seen_inside > 500
    assert ErrorStateKalmanFilter._propagate is orig


def test_the_oracle_patch_is_removed_even_when_the_run_fails(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=20.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    orig = ErrorStateKalmanFilter._propagate
    with pytest.raises(RuntimeError), ur.oracle_attitude(seq, (1.0, 2.0), "oracle_tilt"):
        raise RuntimeError("boom")
    assert ErrorStateKalmanFilter._propagate is orig


def test_an_unknown_oracle_is_refused():
    with pytest.raises(ValueError), ur.oracle_attitude(_line_sequence(0.0), (1.0, 2.0), "oracle_nothing"):
        pass


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
            next(
                r["value"]
                for r in rows
                if r["sequence"] == TUNNEL and r["variant"] == "declared" and r["seed"] == "0" and r["quantity"] == key
            )
        )
        assert got[key] == pytest.approx(want, rel=1e-3), key


def _fetched_or_skip():
    if not (FETCHED / "tunnel1" / ud.NMEA_FILES["tunnel1"]).is_file():
        pytest.skip("tunnel1 is not fetched with its NMEA file (see docs/urbannav.md)")


def test_the_reported_counts_match_the_fetched_data(rows):
    _fetched_or_skip()
    fixes = ud.load_gga(FETCHED, "tunnel1")
    _, gnss, _, info = ur.build(FETCHED)
    dropped = int(np.sum((fixes.quality == 0) | ~np.isfinite(fixes.lat_deg)))
    assert info["epochs_not_valid"] == dropped
    assert info["fixes_variance_unusable"] == 0
    assert info["fixes_variance_below_floor"] == int(
        np.sum(np.any(gnss.cov < ur.FLOOR_SIGMA_M**2, axis=1) & ur.usable_variance_mask(gnss.cov))
    )
    assert np.all(ur.usable_variance_mask(gnss.cov))
    for v in ur.ALL_VARIANTS:
        assert len(_q(rows, v, "epochs_not_valid")) == len(ur.SEEDS)
        assert np.all(_q(rows, v, "epochs_not_valid") == dropped)
        assert np.all(_q(rows, v, "fixes_variance_below_floor") == info["fixes_variance_below_floor"])


def test_an_oracle_run_is_deterministic():
    _fetched_or_skip()
    seq, gnss, spans, info = ur.build(FETCHED)
    a = ur.run_once(seq, gnss, spans, info, seed=0, variant="oracle_tilt")
    b = ur.run_once(seq, gnss, spans, info, seed=0, variant="oracle_tilt")
    assert a == b
