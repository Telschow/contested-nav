"""The quaternion order of the readers, checked against recorded gyroscopes.

This replaces two tests that compared a published Basalt estimate of TUM VI room1 with a subsampled ground truth.
Neither file could be fetched, so both always skipped (blocker B4). The rate of the ground-truth attitude must
match the gyroscope, and it does so only when the quaternion order is right. A wrong order stays orthonormal, so
no structural check sees it, but it lowers this correlation below the threshold.

The synthetic test always runs. The recorded tests run on the sequences that were fetched
(``navkit euroc fetch``, ``navkit tumvi fetch``) and skip otherwise, because the datasets are not vendored.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit.geometry.rigid import make_pose, quat_to_matrix
from navkit.io import euroc_fetch, tumvi_fetch
from navkit.timing_check import estimate_offset
from navkit.types import Trajectory

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
#: The lowest correlation at zero shift in the committed timing table is 0.93. On the fetched sequences a wrong order
#: gives at most 0.69, so one threshold separates them. The wrong order is not always near zero: a platform that
#: mostly turns about one axis keeps part of the correlation.
THRESHOLD = 0.9


def _misordered(truth: Trajectory) -> Trajectory:
    """The same attitudes read with the scalar last instead of first: orthonormal, and wrong."""
    q = np.roll(truth.quaternions, -1, axis=1)
    poses = np.array([make_pose(quat_to_matrix(qi), p) for qi, p in zip(q, truth.positions, strict=True)])
    return Trajectory(t=truth.t, poses=poses, name="misordered")


def _check(seq) -> None:
    right = estimate_offset(seq.imu, seq.truth)["correlation_at_zero"]
    wrong = estimate_offset(seq.imu, _misordered(seq.truth))["correlation_at_zero"]
    assert right > THRESHOLD, f"{seq.name}: the ground-truth rate matches the gyroscope only at {right:.3f}"
    assert wrong < THRESHOLD, f"{seq.name}: a wrong quaternion order still correlates at {wrong:.3f}"


def test_the_check_separates_the_right_order_from_the_wrong_one_on_a_synthetic_sequence(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=60.0, seed=3)
    _check(ee.load_sequence(tmp_path, "MH_01_easy"))


# The parameters are the fixed lists of known sequences, not whatever is on disk, so the number of collected tests
# does not depend on which datasets a machine has fetched.


@pytest.mark.parametrize("name", tumvi_fetch.SEQUENCES)
def test_tum_vi_ground_truth_orientation_matches_the_gyroscope(name):
    if not (RAW / "tumvi" / name).is_dir():
        pytest.skip(f"{name} is not fetched (navkit tumvi fetch)")
    from navkit.tumvi_data import load_sequence

    _check(load_sequence(RAW / "tumvi", name))


@pytest.mark.parametrize("name", euroc_fetch.SEQUENCES)
def test_euroc_ground_truth_orientation_matches_the_gyroscope(name):
    if not (RAW / "euroc" / name).is_dir():
        pytest.skip(f"{name} is not fetched (navkit euroc fetch)")
    _check(ee.load_sequence(RAW / "euroc", name))
