"""Trajectory reader/writer tests.

Quaternion order is the dominant failure mode in this module: a wrong reorder
still yields a unit quaternion and a perfectly orthonormal, right-handed
rotation matrix of the wrong orientation. Every test here therefore checks a
*specific known rotation* rather than a shape, and each format is exercised as
a write/read round trip so the reader and the writer must agree.
"""

import numpy as np
import pytest

from navkit.io.trajectory import (
    TrajectoryParseError,
    detect_format,
    read_trajectory,
    write_euroc,
    write_tum,
    wxyz_to_xyzw,
    xyzw_to_wxyz,
)
from navkit.types import Trajectory

SQRT_HALF = np.sqrt(0.5)

# Rotations chosen so no two share a component pattern, which keeps a wrong
# permutation from accidentally producing a matching matrix.
YAW_90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
PITCH_90 = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
ROLL_90 = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])


def _pose(R: np.ndarray, p: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def _trajectory() -> Trajectory:
    poses = np.stack(
        [
            _pose(YAW_90, [1.0, 2.0, 3.0]),
            _pose(PITCH_90, [4.0, 5.0, 6.0]),
            _pose(ROLL_90, [7.0, 8.0, 9.0]),
        ]
    )
    return Trajectory(t=np.array([0.0, 0.5, 1.0]), poses=poses, name="rt")


def test_reorder_helpers_are_inverses():
    rng = np.random.default_rng(7)
    q = rng.normal(size=(64, 4))
    assert np.allclose(xyzw_to_wxyz(wxyz_to_xyzw(q)), q)
    assert np.allclose(wxyz_to_xyzw(xyzw_to_wxyz(q)), q)


def test_reorder_helpers_move_the_scalar_component():
    q = np.array([0.1, 0.2, 0.3, 0.4])
    assert np.allclose(xyzw_to_wxyz(q), [0.4, 0.1, 0.2, 0.3])
    assert np.allclose(wxyz_to_xyzw(q), [0.2, 0.3, 0.4, 0.1])


def test_tum_round_trip_preserves_rotation(tmp_path):
    """Regression: write_tum labelled its columns qx qy qz qw but wrote w x y z."""
    traj = _trajectory()
    path = tmp_path / "traj.txt"
    write_tum(str(path), traj)
    back = read_trajectory(str(path), fmt="tum")
    assert np.allclose(back.rotations, traj.rotations, atol=1e-9)
    assert np.allclose(back.positions, traj.positions, atol=1e-9)
    assert np.allclose(back.t, traj.t, atol=1e-9)


def test_tum_file_declares_scalar_last_order(tmp_path):
    path = tmp_path / "traj.txt"
    write_tum(str(path), _trajectory())
    header = path.read_text().splitlines()[0]
    assert header.strip() == "# timestamp tx ty tz qx qy qz qw"


def test_tum_reader_yields_the_expected_known_rotation(tmp_path):
    """A yaw of exactly 90 deg is the case the old order got wrong."""
    qw, qx, qy, qz = SQRT_HALF, 0.0, 0.0, SQRT_HALF
    path = tmp_path / "t.txt"
    path.write_text(f"0.0 0.0 0.0 0.0 {qx} {qy} {qz} {qw}\n")
    R = read_trajectory(str(path), fmt="tum").rotations[0]
    assert np.allclose(R, YAW_90, atol=1e-9)


def test_euroc_reader_yields_the_expected_known_rotation(tmp_path):
    """Regression: the EuRoC reader needlessly rotated an already-wxyz slice."""
    qw, qx, qy, qz = SQRT_HALF, 0.0, 0.0, SQRT_HALF
    path = tmp_path / "data.csv"
    path.write_text(
        "#timestamp [ns], p_RS_R_x, p_RS_R_y, p_RS_R_z, "
        "q_RS_w [], q_RS_x [], q_RS_y [], q_RS_z []\n"
        f"1000000000, 0.0, 0.0, 0.0, {qw}, {qx}, {qy}, {qz}\n"
    )
    R = read_trajectory(str(path), fmt="euroc").rotations[0]
    assert np.allclose(R, YAW_90, atol=1e-9)


def test_euroc_reader_converts_nanosecond_timestamps(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(
        "#timestamp [ns], px, py, pz, q_w, q_x, q_y, q_z\n"
        f"1000000000, 1.0, 2.0, 3.0, {SQRT_HALF}, 0.0, 0.0, {SQRT_HALF}\n"
        f"1500000000, 1.0, 2.0, 3.0, {SQRT_HALF}, 0.0, 0.0, {SQRT_HALF}\n"
    )
    traj = read_trajectory(str(path), fmt="euroc")
    assert np.allclose(traj.t, [1.0, 1.5])
    assert np.allclose(traj.positions[0], [1.0, 2.0, 3.0])


def test_nanosecond_unit_is_taken_from_the_header_not_the_magnitude(tmp_path):
    """Regression: a relative ns clock is indistinguishable from a huge seconds
    clock by magnitude alone, so the header is the only usable signal."""
    path = tmp_path / "data.csv"
    path.write_text(
        f"#timestamp [ns], px, py, pz, q_w, q_x, q_y, q_z\n1000000000, 0, 0, 0, {SQRT_HALF}, 0, 0, {SQRT_HALF}\n"
    )
    assert np.allclose(read_trajectory(str(path), fmt="euroc").t, [1.0])


def test_headerless_large_magnitudes_still_fall_back_to_nanoseconds(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text(f"1403636579758555584, 0, 0, 0, {SQRT_HALF}, 0, 0, {SQRT_HALF}\n")
    assert np.allclose(read_trajectory(str(path), fmt="tum").t, [1.4036365797585556e9])


def test_euroc_reader_keeps_velocity_when_present(tmp_path):
    """Regression: _read_rows truncated every row to 8 columns, so the
    velocity branch could never fire."""
    path = tmp_path / "data.csv"
    path.write_text(
        "#timestamp [ns], px, py, pz, q_w, q_x, q_y, q_z, vx, vy, vz, bwx, bwy, bwz, bax, bay, baz\n"
        f"1000000000, 0, 0, 0, {SQRT_HALF}, 0, 0, {SQRT_HALF}, 1.0, 2.0, 3.0, 0, 0, 0, 0, 0, 0\n"
    )
    traj = read_trajectory(str(path), fmt="euroc")
    assert "velocity" in traj.metadata
    assert np.allclose(traj.metadata["velocity"][0], [1.0, 2.0, 3.0])


def test_euroc_reader_omits_velocity_when_absent(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(
        f"#timestamp [ns], px, py, pz, q_w, q_x, q_y, q_z\n1000000000, 0, 0, 0, {SQRT_HALF}, 0, 0, {SQRT_HALF}\n"
    )
    assert "velocity" not in read_trajectory(str(path), fmt="euroc").metadata


def test_plotly_csv_round_trip_preserves_rotation(tmp_path):
    """Regression: the Plotly reader passed a scalar-last slice straight through."""
    traj = _trajectory()
    path = tmp_path / "gt.csv"
    rows = ["t,x,y,z,qx,qy,qz,qw"]
    for i in range(len(traj)):
        q = wxyz_to_xyzw(traj.quaternions[i])
        p = traj.positions[i]
        rows.append(f"{traj.t[i]:.12e},{p[0]:e},{p[1]:e},{p[2]:e},{q[0]:e},{q[1]:e},{q[2]:e},{q[3]:e}")
    path.write_text("\n".join(rows) + "\n")
    back = read_trajectory(str(path), fmt="csv_xyz_qw")
    assert np.allclose(back.rotations, traj.rotations, atol=1e-9)


def test_euroc_txt_round_trip_preserves_rotation(tmp_path):
    traj = _trajectory()
    path = tmp_path / "state.txt"
    write_euroc(str(path), traj)
    back = read_trajectory(str(path), fmt="euroc_txt")
    assert np.allclose(back.rotations, traj.rotations, atol=1e-9)
    assert np.allclose(back.t, traj.t, atol=1e-6)


def test_writers_agree_on_rotation_by_construction(tmp_path):
    traj = _trajectory()
    tum, euroc = tmp_path / "a.txt", tmp_path / "b.csv"
    write_tum(str(tum), traj)
    write_euroc(str(euroc), traj)
    a = read_trajectory(str(tum), fmt="tum")
    b = read_trajectory(str(euroc), fmt="euroc_txt")
    assert np.allclose(a.rotations, b.rotations, atol=1e-9)
    assert np.allclose(a.rotations, traj.rotations, atol=1e-9)


def test_written_rotations_stay_orthonormal_and_right_handed(tmp_path):
    """Guards the property a misordered file still violates only via direction."""
    traj = _trajectory()
    path = tmp_path / "t.txt"
    write_tum(str(path), traj)
    R = read_trajectory(str(path), fmt="tum").rotations
    for r in R:
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
        assert np.linalg.det(r) == pytest.approx(1.0, abs=1e-9)


def test_quaternion_normalization_is_tolerated(tmp_path):
    """Real exports carry unnormalized quaternions; the reader must cope."""
    from navkit.geometry.rigid import quat_to_matrix

    q = np.array([0.1, 0.2, 0.3, 0.4])
    q = q / np.linalg.norm(q)
    path = tmp_path / "t.txt"
    path.write_text("0.0 0 0 0 {:e} {:e} {:e} {:e}\n".format(*tuple(q * 5.0)))
    R = read_trajectory(str(path), fmt="tum").rotations[0]
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.allclose(R, quat_to_matrix(xyzw_to_wxyz(q)))


def test_unsorted_and_duplicate_timestamps_are_normalised(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text(f"1.0 0 0 0 {SQRT_HALF} 0 0 {SQRT_HALF}\n0.0 9 9 9 1 0 0 0\n1.0 5 5 5 1 0 0 0\n")
    traj = read_trajectory(str(path), fmt="tum")
    assert np.allclose(traj.t, [0.0, 1.0])
    # Sorting is stable and the first occurrence of a duplicate timestamp wins.
    assert np.allclose(traj.positions[0], [9.0, 9.0, 9.0])
    assert np.allclose(traj.positions[-1], [0.0, 0.0, 0.0])


def test_too_few_columns_is_rejected(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("0.0 1.0 2.0 3.0\n")
    with pytest.raises(TrajectoryParseError, match="expected 8 columns"):
        read_trajectory(str(path), fmt="tum")


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(TrajectoryParseError, match="no such file"):
        read_trajectory(str(tmp_path / "nope.txt"), fmt="tum")


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("# only a comment\n")
    with pytest.raises(TrajectoryParseError, match="no numeric rows"):
        read_trajectory(str(path), fmt="tum")


def test_unknown_format_is_rejected(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("0 0 0 0 1 0 0 0\n")
    with pytest.raises(TrajectoryParseError, match="unknown trajectory format"):
        read_trajectory(str(path), fmt="bogus")


def test_bad_field_in_a_data_row_is_rejected(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("0.0 0 0 0 1 0 0 0\nthen some words here\n")
    with pytest.raises(TrajectoryParseError, match="unexpected non-numeric field"):
        read_trajectory(str(path), fmt="tum")


def test_detect_format_recognises_euroc_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("#timestamp [ns], px, py, pz, q_w, q_x, q_y, q_z\n1,2,3,4,1,0,0,0\n")
    assert detect_format(str(path)) == "euroc"


def test_detect_format_recognises_plotly_csv(tmp_path):
    path = tmp_path / "gt.csv"
    path.write_text("t,x,y,z,qx,qy,qz,qw\n0,0,0,0,0,0,0,1\n")
    assert detect_format(str(path)) == "csv_xyz_qw"


def test_detect_format_falls_back_to_tum(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("0.0 0 0 0 1 0 0 0\n")
    assert detect_format(str(path)) == "tum"


def test_detect_format_rejects_unrecognisable_input(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("hello world\n")
    with pytest.raises(TrajectoryParseError, match="could not determine"):
        detect_format(str(path))


def test_auto_detection_round_trips_both_written_formats(tmp_path):
    traj = _trajectory()
    tum, euroc = tmp_path / "a.txt", tmp_path / "b.csv"
    write_tum(str(tum), traj)
    write_euroc(str(euroc), traj)
    for p in (tum, euroc):
        back = read_trajectory(str(p))
        assert np.allclose(back.rotations, traj.rotations, atol=1e-6)


# --- end-to-end check against the published TUM VI benchmark -----------------
#
# These are the strongest available check on quaternion handling, because the
# reference numbers are published. They only run when the dataset has been
# fetched, since the repo deliberately does not vendor third-party data.

TUM_EST = "/tmp/opencode/tumvi_ref/dataset-room1_512_16_basalt_poses.txt"
TUM_GT = "/tmp/opencode/tumvi_ref/dataset-room1_512_16_basalt_poses_groundtruth_plotly.csv"


def test_tum_vi_room1_ate_is_in_the_published_range():
    """Published room1/512/16 ATE is 0.069 m.

    The local reference is the subsampled Plotly export, not the full ground
    truth, so a loose band around the published value is the honest assertion.
    A wrong quaternion order moves ATE by orders of magnitude, so this still
    fails loudly if the readers regress.
    """
    import os

    if not (os.path.isfile(TUM_EST) and os.path.isfile(TUM_GT)):
        pytest.skip("TUM VI reference files not present")
    from navkit.eval.metrics import ate_bundle

    est = read_trajectory(TUM_EST, fmt="tum")
    gt = read_trajectory(TUM_GT, fmt="csv_xyz_qw")
    ate = ate_bundle(est, gt)["rigid"].position_m.rmse
    assert 0.02 < ate < 0.30, f"ATE {ate:.4f} m is far from the published 0.069 m"


def test_tum_vi_first_pose_is_nearly_identity():
    """A VI system starts close to its own initial frame.

    With the old scalar-last handling this was a near-180 degree flip, which
    stayed orthonormal and therefore slipped past every structural check.
    """
    import os

    if not os.path.isfile(TUM_EST):
        pytest.skip("TUM VI reference files not present")
    R = read_trajectory(TUM_EST, fmt="tum").rotations[0]
    assert np.trace(R) > 2.5, f"first pose is not near identity; trace={np.trace(R):.3f}"
