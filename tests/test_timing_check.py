"""The timing evidence tool: interval statistics, dropout share and the ground-truth-to-IMU offset.

The offset estimate is checked against an offset put in on purpose, in both directions, so the sign convention is
pinned: ``offset_s`` is the shift ``dt`` for which ``truth.time_offset(dt)`` matches the IMU.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit import euroc_cli
from navkit import euroc_eval as ee
from navkit import timing_check as tc
from navkit.tumvi_data import write_fixture as write_tumvi_fixture
from navkit.types import ImuSample, Trajectory


@pytest.fixture(scope="module")
def seq(tmp_path_factory: pytest.TempPathFactory) -> ee.EurocSequence:
    root = tmp_path_factory.mktemp("timing")
    ee.write_fixture(root, "FIXTURE_z_up", duration_s=40.0)
    return ee.load_sequence(root, "FIXTURE_z_up")


def test_interval_stats_of_a_uniform_stream_and_of_one_with_a_gap():
    t = np.arange(0.0, 10.0, 0.005)
    s = tc.interval_stats(t)
    assert s.rate_hz == pytest.approx(200.0) and s.jitter_ms < 1e-6 and s.long_gaps == 0
    gapped = np.delete(t, slice(400, 440))
    g = tc.interval_stats(gapped)
    assert g.max_gap_ms == pytest.approx(1e3 * 41 * 0.005) and g.long_gaps == 1


def test_interval_stats_needs_three_timestamps():
    with pytest.raises(ValueError):
        tc.interval_stats(np.array([0.0, 1.0]))


def test_dropout_fraction_counts_the_time_inside_long_gaps():
    t = np.concatenate([np.arange(0.0, 5.0, 0.01), np.arange(7.0, 10.0, 0.01)])  # one 2 s gap in a 9.99 s span
    assert tc.dropout_fraction(t) == pytest.approx(2.01 / 9.99, abs=1e-3)
    assert tc.dropout_fraction(np.arange(0.0, 10.0, 0.01)) == 0.0


def test_an_aligned_recording_has_no_offset(seq):
    est = tc.estimate_offset(seq.imu, seq.truth)
    assert abs(est["offset_s"]) < 0.001
    assert est["correlation_peak"] > 0.95


@pytest.mark.parametrize("shift", [0.012, -0.020])
def test_an_offset_put_in_is_recovered_with_its_sign(seq, shift):
    moved = seq.truth.time_offset(shift)  # the truth stamps are now late by `shift`
    est = tc.estimate_offset(seq.imu, moved)
    assert est["offset_s"] == pytest.approx(-shift, abs=0.001)
    # Applying the estimate puts the stamps back, and the correlation rises to the aligned value.
    fixed = moved.time_offset(est["offset_s"])
    assert tc.estimate_offset(seq.imu, fixed)["offset_s"] == pytest.approx(0.0, abs=0.001)
    assert est["correlation_peak"] > est["correlation_at_zero"]


def test_the_vector_method_beats_the_magnitude_method_when_the_gyroscope_has_a_bias(seq):
    """A bias adds a cross-term to the size of the rate and shifts its peak; the vector method removes it."""
    vector = tc.estimate_offset(seq.imu, seq.truth)["offset_s"]
    magnitude = tc.estimate_offset(seq.imu, seq.truth, method="magnitude")["offset_s"]
    assert abs(vector) < abs(magnitude) < 0.006
    with pytest.raises(ValueError, match="method"):
        tc.estimate_offset(seq.imu, seq.truth, method="phase")


def test_a_rig_that_does_not_turn_gives_no_usable_estimate():
    t = np.arange(0.0, 30.0, 0.005)
    rng = np.random.default_rng(0)
    imu = ImuSample(t=t, accel=np.tile([0, 0, 9.8], (len(t), 1)), gyro=rng.standard_normal((len(t), 3)) * 1e-3)
    poses = np.tile(np.eye(4), (3000, 1, 1))
    truth = Trajectory(t=np.linspace(0.0, 30.0, 3000), poses=poses)
    assert tc.estimate_offset(imu, truth)["correlation_peak"] < 0.2


def test_too_little_shared_time_is_refused(seq):
    short = seq.truth.subset(0.0, 2.0)
    with pytest.raises(ValueError, match="too little time"):
        tc.estimate_offset(seq.imu, short)


def test_the_truth_rate_vector_is_the_body_frame_angular_rate():
    from navkit.geometry.rigid import rot_exp

    t = np.arange(0.0, 5.0, 0.01)
    omega = np.array([0.3, -0.2, 0.5])
    poses = np.tile(np.eye(4), (len(t), 1, 1))
    for k, tk in enumerate(t):
        poses[k, :3, :3] = rot_exp(omega * tk)
    _, w = tc.truth_rate_vector(Trajectory(t=t, poses=poses))
    assert np.allclose(w, omega, atol=1e-6)


def test_the_truth_rate_is_the_size_of_the_angular_rate():
    t = np.arange(0.0, 5.0, 0.01)
    from navkit.geometry.rigid import rot_exp

    poses = np.tile(np.eye(4), (len(t), 1, 1))
    for k, tk in enumerate(t):
        poses[k, :3, :3] = rot_exp(np.array([0.0, 0.0, 0.7 * tk]))
    _, w = tc.truth_rate_magnitude(Trajectory(t=t, poses=poses))
    assert np.allclose(w, 0.7, atol=1e-6)


def test_a_sequence_row_has_every_column_and_the_offset_displacement_follows_from_it(seq):
    row = tc.sequence_row(seq)
    assert set(row) == set(tc.CSV_COLUMNS)
    assert row["offset_displacement_mm"] == pytest.approx(abs(row["offset_ms"]) * row["median_speed_m_s"])
    assert row["dataset"] == "EuRoC MAV" and row["truth_gap_fraction"] == 0.0


def test_the_csv_round_trips_and_the_table_comes_from_it(seq, tmp_path):
    rows = [tc.sequence_row(seq)]
    out = tmp_path / "t.csv"
    tc.write_csv(out, rows)
    back = tc.rows_from_csv(out)
    assert tuple(back[0]) == tc.CSV_COLUMNS
    assert tc.table_markdown(back) == tc.table_markdown(rows)
    assert tc.table_markdown(back).count("\n| ") == 1  # the header is the first line; one data row follows


def test_the_page_block_is_replaced_and_a_page_without_markers_is_refused(tmp_path):
    page = tmp_path / "p.md"
    page.write_text("a\n<!-- timing:start -->\nold\n<!-- timing:end -->\nb\n")
    tc.write_block(page, "NEW")
    assert page.read_text() == "a\n<!-- timing:start -->\n\nNEW\n\n<!-- timing:end -->\nb\n"
    page.write_text("nothing")
    with pytest.raises(ValueError, match="timing:start"):
        tc.write_block(page, "x")


def test_the_command_reports_a_tumvi_fixture_and_is_routed_from_navkit_euroc(tmp_path, capsys):
    write_tumvi_fixture(tmp_path, "room1")
    csv_path = tmp_path / "t.csv"
    code = euroc_cli.main(
        ["timing", "--dataset", "tumvi", "--root", str(tmp_path), "--csv", str(csv_path), "--markdown"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "| room1 |" in out
    row = tc.rows_from_csv(csv_path)[0]
    assert row["dataset"] == "TUM VI" and float(row["truth_gap_fraction"]) == 0.0
    assert float(row["truth_rate_hz"]) == pytest.approx(120.0, rel=0.01)  # a mocap stream, not on the IMU's grid
    assert abs(float(row["offset_ms"])) < 3.0


def test_the_command_without_data_says_how_to_fetch_it(tmp_path, capsys):
    assert euroc_cli.main(["timing", "--dataset", "tumvi", "--root", str(tmp_path / "none")]) == 1
    assert "navkit euroc fetch" in capsys.readouterr().err
    assert euroc_cli.main(["timing", "--root", str(tmp_path)]) == 2  # --root needs one dataset
