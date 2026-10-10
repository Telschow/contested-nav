"""The EuRoC evaluation path, exercised on a synthetic sequence written in the EuRoC file layout.

None of this is evidence about real data. It checks that every step between a fetched file and
a result record is right: units, time origin, frames, gravity sign, the start state, the
simulated GNSS and the scoring. The thresholds below are regression guards on the fixture, not
claims about the filter.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_cli
from navkit import euroc_eval as ee
from navkit.cli import main as cli_main
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig, InitialState
from navkit.io.imu import DEFAULT_NOISE
from navkit.types import GRAVITY, ImuSample

NAME = "FIXTURE_z_up"


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("euroc")
    ee.write_fixture(path, NAME)
    return path


@pytest.fixture(scope="module")
def seq(root: Path) -> ee.EurocSequence:
    return ee.load_sequence(root, NAME)


def _run(seq: ee.EurocSequence, **kw):
    return ee.run_sequence(seq, ee.RunOptions(**kw))


# ----------------------------------------------------------------- loading


def test_loading_puts_both_streams_on_one_time_axis_in_seconds(seq):
    assert seq.imu.t[0] == 0.0
    assert seq.imu.rate_hz() == pytest.approx(200.0, rel=1e-6)
    assert seq.truth.t[0] == pytest.approx(0.0, abs=1e-9)
    assert seq.truth.t[-1] == pytest.approx(seq.imu.t[-1], abs=1e-9)


def test_the_nanosecond_offset_costs_less_than_a_microsecond(seq):
    # Raw timestamps are about 1.4e18 ns, which a float64 second holds to about 0.24 microseconds.
    # That is the loader's floor, and it is five orders below the 5 ms sample interval.
    assert np.allclose(np.diff(seq.imu.t), 0.005, atol=1e-6)


def test_the_noise_model_comes_from_sensor_yaml_when_it_has_the_terms(seq):
    assert seq.noise_source == "imu0/sensor.yaml"
    assert seq.noise.accel_noise_density == DEFAULT_NOISE.accel_noise_density


def test_missing_or_partial_sensor_yaml_falls_back_and_says_so(tmp_path):
    model, source = ee.read_noise(tmp_path / "absent.yaml")
    assert model is DEFAULT_NOISE and "project default" in source
    partial = tmp_path / "sensor.yaml"
    partial.write_text("gyroscope_noise_density: 0.001\n")
    model, source = ee.read_noise(partial)
    assert model is DEFAULT_NOISE and "project default" in source
    partial.write_text("{not yaml")
    assert ee.read_noise(partial)[0] is DEFAULT_NOISE


def test_a_missing_sequence_names_the_command_that_fetches_it(tmp_path):
    with pytest.raises(ee.SequenceError, match="navkit euroc fetch --sequence MH_01_easy"):
        ee.load_sequence(tmp_path, "MH_01_easy")


def test_timestamps_in_seconds_are_rejected_not_rescaled(tmp_path):
    ee.write_fixture(tmp_path, "S")
    truth = tmp_path / "S" / ee.TRUTH_CSV
    lines = truth.read_text().splitlines()
    fixed = [lines[0]] + [f"{float(row.split(',')[0]) / 1e9}," + row.split(",", 1)[1] for row in lines[1:]]
    truth.write_text("\n".join(fixed) + "\n")
    with pytest.raises(ee.SequenceError, match="nanoseconds"):
        ee.load_sequence(tmp_path, "S")


def test_non_unit_quaternions_are_rejected(tmp_path):
    ee.write_fixture(tmp_path, "S")
    truth = tmp_path / "S" / ee.TRUTH_CSV
    lines = truth.read_text().splitlines()
    cols = lines[1].split(",")
    cols[4] = "5.0"
    lines[1] = ",".join(cols)
    truth.write_text("\n".join(lines) + "\n")
    with pytest.raises(ee.SequenceError, match="unit length"):
        ee.load_sequence(tmp_path, "S")


def test_input_hashes_are_those_of_the_files_on_disk(root, seq):
    import hashlib

    for rel, digest in seq.sha256.items():
        assert digest == hashlib.sha256((root / NAME / rel).read_bytes()).hexdigest()


# ----------------------------------------------------------------- running


def test_the_pipeline_runs_and_tracks_the_reference_with_gnss(seq):
    record = _run(seq)
    head = record["headline"]
    assert head["ate_rmse_m"] < 2.0
    assert np.isfinite(head["nees_mean"])
    assert record["data_class"] == ee.DATA_CLASS
    assert record["claim_type"] == "MEASUREMENT"
    assert record["gravity_check"]["warning"] is False
    assert any("simulated" in c for c in record["caveats"])
    json.dumps(record)  # serialisable as is


def test_the_default_gravity_is_wrong_by_orders_of_magnitude(seq, monkeypatch):
    """The sign convention that works for the synthetic benchmark breaks a physical z-up IMU."""
    good = _run(seq, outages=((15.0, 10.0),))["headline"]["ate_rmse_m"]
    monkeypatch.setattr(ee, "GRAVITY_Z_UP", GRAVITY)
    bad = _run(seq, outages=((15.0, 10.0),))["headline"]["ate_rmse_m"]
    assert good < 5.0
    assert bad > 100.0 * good


def test_an_outage_raises_the_error_and_is_reported(seq):
    control = _run(seq)
    cut = _run(seq, outages=((15.0, 10.0),))
    assert max(cut["error_time_series"]["position_error_m"]) > max(control["error_time_series"]["position_error_m"])
    (outage,) = cut["outages"]
    assert outage["start_s"] == pytest.approx(15.0, abs=0.01)
    assert outage["duration_s"] == pytest.approx(10.0)
    assert outage["error_peak_m"] > outage["error_before_m"]
    assert "outages" not in control


def test_the_whole_run_without_gnss_is_allowed(seq):
    record = _run(seq, outages=((0.0, 1e6),))
    assert record["stats"]["gnss_updates_used"] == 0.0


def test_an_outage_outside_the_window_is_an_error(seq):
    with pytest.raises(ee.SequenceError, match="outside"):
        _run(seq, outages=((500.0, 5.0),))


def test_a_window_that_is_too_short_is_an_error(seq):
    with pytest.raises(ee.SequenceError, match="too short"):
        _run(seq, duration_s=0.5)


def test_skip_and_duration_select_the_window(seq):
    record = _run(seq, skip_s=10.0, duration_s=20.0)
    assert record["window_s"]["start"] == pytest.approx(10.0)
    assert record["window_s"]["end"] == pytest.approx(30.0)
    assert record["imu_samples"] == 4001


def test_the_same_seed_gives_the_same_result_and_another_seed_a_different_one(seq):
    a = _run(seq, seed=3)["headline"]["ate_rmse_m"]
    assert _run(seq, seed=3)["headline"]["ate_rmse_m"] == a
    assert _run(seq, seed=4)["headline"]["ate_rmse_m"] != a


def test_exact_init_starts_on_the_ground_truth(seq):
    # Without GNSS the first pose is the start state itself; with it, the first fix already moves it.
    kw = {"outages": ((0.0, 1e6),), "duration_s": 5.0}
    exact = _run(seq, exact_init=True, **kw)
    perturbed = _run(seq, exact_init=False, **kw)
    assert exact["error_time_series"]["position_error_m"][0] < 1e-6
    assert perturbed["error_time_series"]["position_error_m"][0] > 1e-3


def test_a_zero_bias_start_needs_a_declared_bias_sigma(seq):
    with pytest.raises(ee.SequenceError, match="bias-sigma"):
        _run(seq, init_bias="zero")
    record = _run(seq, init_bias="zero", bias_sigma=0.02, outages=((15.0, 10.0),))
    assert record["headline"]["ate_rmse_m"] < 10.0


def test_unknown_bias_mode_is_rejected(seq):
    with pytest.raises(ValueError, match="init_bias"):
        _run(seq, init_bias="guess")


def test_gravity_check_flags_a_frame_that_is_off_by_ninety_degrees(seq):
    from navkit.types import Trajectory

    turned = seq.truth.poses.copy()
    rx = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0.0]])
    turned[:, :3, :3] = np.einsum("ij,njk->nik", rx, turned[:, :3, :3])
    wrong = Trajectory(t=seq.truth.t, poses=turned)
    check = ee.gravity_check(seq.imu, wrong, np.zeros(3))
    assert check["warning"] is True
    assert check["angle_to_vertical_deg"] > 45.0


def test_gravity_check_skips_a_shaken_start_and_reports_the_window():
    from navkit.types import Trajectory

    t = np.arange(0.0, 20.0, 0.005)
    rng = np.random.default_rng(0)
    accel = np.tile([0.0, 0.0, 9.80665], (len(t), 1))
    accel[t < 3.0] += rng.standard_normal(((t < 3.0).sum(), 3)) * 4.0  # being carried
    imu = ImuSample(t=t, accel=accel, gyro=np.zeros((len(t), 3)))
    poses = np.tile(np.eye(4), (2, 1, 1))
    truth = Trajectory(t=np.array([0.0, 20.0]), poses=poses)
    check = ee.gravity_check(imu, truth, np.zeros(3))
    assert check["window_start_s"] >= 2.5
    assert check["warning"] is False
    assert check["norm_m_s2"] == pytest.approx(9.80665, abs=1e-6)


def test_record_scores_against_the_same_reference_as_the_synthetic_benchmark(seq):
    record = _run(seq)
    head = record["headline"]
    for key in ("ate_rmse_m", "nees_mean", "nees_expected", "coverage", "calibration_verdict", "bulk_verdict"):
        assert key in head
    assert head["nees_expected"] == 3.0
    assert set(head["coverage"]) >= {"2sigma"}


# -------------------------------------------------------- estimator start


def test_initial_state_sets_the_first_pose_velocity_and_biases():
    cfg = EskfConfig(imu_noise=DEFAULT_NOISE, gravity=ee.GRAVITY_Z_UP)
    t = np.arange(0, 1.0, 0.01)
    imu = ImuSample(t=t, accel=np.tile([0.0, 0.0, 9.80665], (len(t), 1)), gyro=np.zeros((len(t), 3)))
    start = InitialState(R=np.eye(3), p=[1.0, 2.0, 3.0], v=[0.0, 0.0, 0.0], b_a=[0.01, 0.0, 0.0])
    result = ErrorStateKalmanFilter(cfg).run(imu, initial=start)
    assert np.allclose(result.trajectory.positions[0], [1.0, 2.0, 3.0])
    # At rest with gravity cancelled, it stays put (up to the declared accelerometer bias).
    assert np.linalg.norm(result.trajectory.positions[-1] - [1.0, 2.0, 3.0]) < 0.1


def test_initial_state_rejects_a_matrix_that_is_not_a_rotation():
    with pytest.raises(ValueError, match="rotation"):
        InitialState(R=np.diag([1.0, 2.0, 3.0]), p=np.zeros(3))


def test_run_without_initial_still_starts_at_the_origin():
    cfg = EskfConfig(imu_noise=DEFAULT_NOISE)
    t = np.arange(0, 0.5, 0.01)
    imu = ImuSample(t=t, accel=np.tile([0.0, 0.0, -9.80665], (len(t), 1)), gyro=np.zeros((len(t), 3)))
    result = ErrorStateKalmanFilter(cfg).run(imu)
    assert np.allclose(result.trajectory.positions[0], 0.0)


# --------------------------------------------------------------------- CLI


def test_run_writes_a_result_file_and_a_table(root, tmp_path, capsys):
    out = tmp_path / "r.json"
    code = euroc_cli.main(
        ["run", "--root", str(root), "-s", NAME, "--outage", "15:10", "--out", str(out), "--markdown"]
    )
    assert code == 0
    record = json.loads(out.read_text())
    assert record["options"]["outages"] == [[15.0, 10.0]]
    table = capsys.readouterr().out
    assert table.startswith("| Sequence |") and NAME in table and "15+10" in table


def test_the_preset_sets_noise_scale_and_bias_sigma_and_flags_override_it(root, tmp_path):
    out = tmp_path / "p.json"
    assert euroc_cli.main(["run", "--root", str(root), "-s", NAME, "--preset", "adis16448", "--out", str(out)]) == 0
    opts = json.loads(out.read_text())["options"]
    assert (opts["preset"], opts["noise_scale"], opts["bias_sigma"]) == ("adis16448", 3.0, 0.05)
    assert (
        euroc_cli.main(
            ["run", "--root", str(root), "-s", NAME, "--preset", "adis16448", "--noise-scale", "2", "--out", str(out)]
        )
        == 0
    )
    assert json.loads(out.read_text())["options"]["noise_scale"] == 2.0
    assert euroc_cli.main(["run", "--root", str(root), "-s", NAME, "--out", str(out)]) == 0
    opts = json.loads(out.read_text())["options"]
    assert (opts["preset"], opts["noise_scale"], opts["bias_sigma"]) == (None, 1.0, None)


def test_run_without_a_fetched_sequence_exits_with_the_fetch_hint(tmp_path, capsys):
    assert euroc_cli.main(["run", "--root", str(tmp_path), "-s", "MH_01_easy"]) == 1
    assert "navkit euroc fetch" in capsys.readouterr().err


def test_bad_outage_syntax_is_a_usage_error(root):
    with pytest.raises(SystemExit):
        euroc_cli.main(["run", "--root", str(root), "-s", NAME, "--outage", "15"])


def test_out_with_two_sequences_is_refused(root, capsys):
    assert euroc_cli.main(["run", "--root", str(root), "-s", NAME, "-s", "MH_01_easy", "--out", "x.json"]) == 2


def test_euroc_command_is_routed_from_the_cli(capsys):
    assert cli_main(["euroc"]) == 2
    assert "fetch" in capsys.readouterr().err
    assert euroc_cli.main(["--help"]) == 0


def test_selftest_runs_without_any_download(capsys):
    assert euroc_cli.main(["selftest"]) == 0
    out = capsys.readouterr().out
    assert "FIXTURE_z_up" in out and "not the filter on real data" in out


def test_bias_walk_scale_multiplies_only_the_two_walks_on_top_of_the_noise_scale():
    noise = ee.ImuNoiseModel(1e-4, 2e-3, 3e-5, 4e-3, 0.0, 0.0)
    plain = ee._filter_noise(noise, ee.RunOptions())
    assert plain.accel_bias_rw == noise.accel_bias_rw and plain.gyro_noise_density == noise.gyro_noise_density
    both = ee._filter_noise(noise, ee.RunOptions(noise_scale=2.0, bias_walk_scale=5.0))
    assert both.gyro_noise_density == pytest.approx(2e-4) and both.accel_noise_density == pytest.approx(4e-3)
    assert both.gyro_bias_rw == pytest.approx(3e-5 * 2.0 * 5.0) and both.accel_bias_rw == pytest.approx(
        4e-3 * 2.0 * 5.0
    )


def test_bias_walk_scale_is_recorded_and_changes_the_claimed_uncertainty(seq):
    base = _run(seq, outages=((15.0, 10.0),))
    wide = _run(seq, outages=((15.0, 10.0),), bias_walk_scale=10.0)
    assert wide["options"]["bias_walk_scale"] == 10.0 and base["options"]["bias_walk_scale"] == 1.0
    assert wide["headline"]["claimed_sigma_p_m"] > base["headline"]["claimed_sigma_p_m"]
    assert wide["estimator"]["imu_noise"]["accel_bias_rw"] == pytest.approx(
        10.0 * base["estimator"]["imu_noise"]["accel_bias_rw"]
    )


def test_the_cli_takes_bias_walk_scale(root, tmp_path):
    out = tmp_path / "w.json"
    assert euroc_cli.main(["run", "--root", str(root), "-s", NAME, "--bias-walk-scale", "4", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["options"]["bias_walk_scale"] == 4.0


def test_the_walk_preset_scales_only_the_bias_walks(root, tmp_path):
    out = tmp_path / "w.json"
    assert (
        euroc_cli.main(["run", "--root", str(root), "-s", NAME, "--preset", "adis16448-walk", "--out", str(out)]) == 0
    )
    opts = json.loads(out.read_text())["options"]
    assert (opts["preset"], opts["noise_scale"], opts["bias_walk_scale"], opts["bias_sigma"]) == (
        "adis16448-walk",
        1.0,
        10.0,
        0.05,
    )
    assert ee.PRESETS["adis16448"] == {"noise_scale": 3.0, "bias_sigma": 0.05}
