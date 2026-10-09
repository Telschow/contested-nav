"""The TUM VI loader and its place in the shared pipeline, on a synthetic sequence in the fetched layout.

Nothing here says anything about the filter on real data. It checks the bookkeeping that differs from
EuRoC: no velocity or bias in the ground truth, noise figures with a raw set in comments, and a start
bias that has to be estimated.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_cli
from navkit import euroc_compare as ec
from navkit import euroc_eval as ee
from navkit import tumvi_data as td

NAME = "room1"
BIAS_A = (0.04, -0.03, 0.06)
BIAS_G = (0.003, -0.002, 0.004)


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("tumvi")
    td.write_fixture(path, NAME, seed=1, accel_bias=BIAS_A, gyro_bias=BIAS_G)
    td.write_fixture(path, "room2", seed=2)
    return path


@pytest.fixture(scope="module")
def seq(root: Path) -> ee.EurocSequence:
    return td.load_sequence(root, NAME)


# ----------------------------------------------------------------- reading


def test_the_sequence_says_which_dataset_it_is_and_that_its_bias_is_unknown(seq):
    assert (seq.dataset, seq.slug, seq.bias_known) == ("TUM VI", "tumvi", False)
    assert np.all(seq.gyro_bias == 0.0) and np.all(seq.accel_bias == 0.0)
    assert any("no velocity or bias" in n for n in seq.notes)


def test_both_streams_are_on_one_time_axis_in_seconds(seq):
    assert seq.imu.t[0] == 0.0
    assert seq.imu.rate_hz() == pytest.approx(200.0, rel=1e-3)
    assert seq.truth.rate_hz() == pytest.approx(120.0, rel=1e-3)
    assert seq.truth.t[0] == pytest.approx(0.0072, abs=1e-6)  # the mocap clock is not on the IMU's grid


def test_noise_has_the_active_figures_and_the_raw_ones(seq):
    assert seq.noise.accel_bias_rw == pytest.approx(8.6e-4)
    assert seq.noise.gyro_noise_density == pytest.approx(1.6e-4)
    raw = seq.noise_variants["allan"]
    assert raw.accel_bias_rw == pytest.approx(8.6e-5) and raw.accel_noise_density == pytest.approx(1.4e-3)
    assert "inflated" in seq.noise_source


def test_the_noise_reader_copes_with_missing_partial_and_uncommented_files(tmp_path):
    assert td.read_noise(tmp_path / "absent.yaml") == (None, None)
    plain = tmp_path / "a.yaml"
    plain.write_text(
        "accelerometer_noise_density: 0.1\naccelerometer_random_walk: 0.2\n"
        "gyroscope_noise_density: 0.3\ngyroscope_random_walk: 0.4\n"
    )
    active, raw = td.read_noise(plain)
    assert active is not None and active.gyro_bias_rw == 0.4 and raw is None
    plain.write_text("gyroscope_noise_density: 0.3\n")
    assert td.read_noise(plain) == (None, None)
    plain.write_text("{not yaml")
    assert td.read_noise(plain)[0] is None


def test_a_missing_sequence_names_the_fetch_command(tmp_path):
    with pytest.raises(ee.SequenceError, match="navkit tumvi fetch --sequence room3"):
        td.load_sequence(tmp_path, "room3")
    with pytest.raises(ee.SequenceError, match="unknown TUM VI sequence"):
        td.load_sequence(tmp_path, "MH_01_easy")


def test_missing_noise_file_falls_back_to_the_default_and_says_so(root, tmp_path):
    td.write_fixture(tmp_path, NAME)
    (tmp_path / NAME / td.NOISE_YAML).unlink()
    loaded = td.load_sequence(tmp_path, NAME)
    assert "project default" in loaded.noise_source and loaded.noise_variants == {}


# --------------------------------------------------------------- velocity


def test_smoothed_velocity_is_exact_for_constant_velocity_and_beats_a_plain_difference():
    t = np.arange(0.0, 5.0, 1 / 120)
    p = np.stack([1.0 * t, -2.0 * t, 0.5 * t], axis=1)
    assert np.allclose(td.smoothed_velocity(t, p), [1.0, -2.0, 0.5], atol=1e-9)
    noisy = p + np.random.default_rng(0).standard_normal(p.shape) * 1e-3
    fit_err = np.abs(td.smoothed_velocity(t, noisy)[20:-20] - [1.0, -2.0, 0.5]).max()
    diff_err = np.abs(np.diff(noisy, axis=0)[20:-20] * 120 - [1.0, -2.0, 0.5]).max()
    assert fit_err < diff_err / 3


def test_smoothed_velocity_leaves_a_lone_sample_at_zero():
    assert np.allclose(td.smoothed_velocity(np.array([0.0]), np.array([[1.0, 2.0, 3.0]])), 0.0)


def test_the_loaded_velocity_matches_the_truths_own_motion(seq):
    # At rest to begin with, so the first value is near zero, and it moves afterwards.
    speed = np.linalg.norm(seq.velocity, axis=1)
    assert speed[0] < 0.05 and speed.max() > 0.5


# ------------------------------------------------------------ static bias


def test_the_static_estimate_recovers_the_bias_of_a_rig_that_starts_at_rest(seq):
    est = ee.static_bias_estimate(seq.imu, seq.truth)
    assert est["quiet"] is True
    assert np.allclose(est["accel_bias"], BIAS_A, atol=0.02)
    assert np.allclose(est["gyro_bias"], BIAS_G, atol=0.003)


def test_a_steady_rotation_is_not_mistaken_for_rest():
    """The accelerometer norm is constant while the rig turns, so the score must use each axis."""
    from navkit.types import ImuSample, Trajectory

    t = np.arange(0, 6.0, 0.005)
    w = 0.8
    accel = np.stack([9.8 * np.sin(w * t), np.zeros_like(t), 9.8 * np.cos(w * t)], axis=1)
    gyro = np.tile([0.0, w, 0.0], (len(t), 1))
    poses = np.tile(np.eye(4), (2, 1, 1))
    truth = Trajectory(t=np.array([0.0, 6.0]), poses=poses)
    assert ee.static_bias_estimate(ImuSample(t=t, accel=accel, gyro=gyro), truth)["quiet"] is False


# --------------------------------------------------------- run, pipeline


def test_a_run_resolves_the_start_bias_to_static_and_says_so(seq):
    record = ee.run_sequence(seq, ee.RunOptions(bias_sigma=0.05, outages=((10.0, 10.0),)))
    assert record["options"]["init_bias"] == "static"
    assert record["dataset"] == "TUM VI" and record["name"] == "tumvi_room1"
    assert ee.STATIC_BIAS_CAVEAT in record["caveats"]
    sb = record["inputs"]["static_bias"]
    assert sb["quiet"] is True and len(sb["accel_bias_m_s2"]) == 3
    assert record["gravity_check"]["warning"] is False
    json.dumps(record)


def test_the_truth_start_is_refused_when_the_data_has_no_bias(seq):
    with pytest.raises(ee.SequenceError, match="no bias columns"):
        ee.run_sequence(seq, ee.RunOptions(init_bias="truth"))


def test_the_raw_noise_source_changes_the_run_and_an_unknown_one_is_refused(seq):
    a = ee.run_sequence(seq, ee.RunOptions(bias_sigma=0.05))["estimator"]["imu_noise"]
    b = ee.run_sequence(seq, ee.RunOptions(bias_sigma=0.05, noise_source="allan"))["estimator"]["imu_noise"]
    assert (
        b["accel_bias_rw"] == pytest.approx(a["accel_bias_rw"] / 10)
        and b["gyro_noise_density"] < a["gyro_noise_density"]
    )
    with pytest.raises(ee.SequenceError, match="no noise source 'nope'"):
        ee.run_sequence(seq, ee.RunOptions(noise_source="nope"))


def test_euroc_sequences_have_no_allan_figures(tmp_path):
    ee.write_fixture(tmp_path)
    with pytest.raises(ee.SequenceError, match="no noise source 'allan'"):
        ee.run_sequence(ee.load_sequence(tmp_path, "FIXTURE_z_up"), ee.RunOptions(noise_source="allan"))


def test_the_run_command_takes_the_dataset_and_writes_a_tumvi_named_file(root, tmp_path, capsys):
    out = tmp_path / "r.json"
    code = euroc_cli.main(
        ["run", "--dataset", "tumvi", "--root", str(root), "-s", NAME, "--bias-sigma", "0.05", "--out", str(out)]
    )
    assert code == 0 and json.loads(out.read_text())["dataset"] == "TUM VI"
    assert "room1: ATE RMSE" in capsys.readouterr().out
    assert euroc_cli.main(["run", "--dataset", "tumvi", "--root", str(root), "-s", "room3"]) == 1


def test_an_unknown_dataset_is_an_error():
    with pytest.raises(ee.SequenceError, match="unknown dataset"):
        ee.dataset_loader("kitti")


# ---------------------------------------------------------------- compare


def test_discovery_and_grouping_know_tum_vi(root):
    assert ec.fetched_sequences(root, "tumvi") == ["room1", "room2"]
    assert ec.fetched_sequences(root, "euroc") == []
    assert ec.group_of("room4") == "TUM VI room"


def test_compare_runs_the_tumvi_configs_and_refuses_the_euroc_ones(root):
    rows, _ = ec.compare(root, [NAME], ("file", "allan"), (5.0,), 10.0, 1, 0.2, dataset="tumvi")
    assert {r.config for r in rows} == {"file", "allan"} and len(rows) == 2
    with pytest.raises(ec.CompareError, match="unknown configuration 'preset' for tumvi"):
        ec.compare(root, [NAME], ("preset",), (5.0,), 10.0, 1, 0.2, dataset="tumvi")
    with pytest.raises(ec.CompareError, match="unknown configuration 'file' for euroc"):
        ec.compare(root, [NAME], ("file",), (5.0,), 10.0, 1, 0.2)


def test_the_compare_command_writes_a_tumvi_record(root, tmp_path, capsys):
    j, c = tmp_path / "r.json", tmp_path / "r.csv"
    args = ["--dataset", "tumvi", "--root", str(root), "--starts", "5", "--outage", "10", "--seeds", "1"]
    assert ec.main([*args, "--json", str(j), "--csv", str(c), "--markdown"]) == 0
    record = json.loads(j.read_text())
    assert record["dataset"] == "TUM VI" and set(record["configs"]) == {"file", "allan"}
    out = capsys.readouterr().out
    assert "| room1 | file |" in out and "| TUM VI room |" not in out  # one environment adds no row of its own
    assert ec.main(["--dataset", "tumvi", "--root", str(tmp_path / "none")]) == 1
    assert "navkit tumvi fetch" in capsys.readouterr().err
