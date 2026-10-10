"""What the recorded-dataset paths share: the sequence type, its error, and the z-up gravity vector.

``navkit.euroc_eval`` runs the filter on a sequence and ``navkit.tumvi_data`` reads TUM VI into one. Both need
these definitions, and neither should import the other for them, so they live here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .io.imu import ImuNoiseModel
from .types import GRAVITY, ImuSample, Trajectory

#: Gravity vector of a z-up world, in the sign convention of ``ErrorStateKalmanFilter``
#: (``a_world = R @ specific_force + g``).
GRAVITY_Z_UP = -GRAVITY


class SequenceError(ValueError):
    """The files of a sequence are missing or do not look like the dataset's data."""


@dataclass
class EurocSequence:
    """One sequence in memory. Time is in seconds from the first IMU sample.

    Named for the first dataset that used it; TUM VI sequences are the same type.
    """

    name: str
    imu: ImuSample
    truth: Trajectory
    velocity: np.ndarray  # (N, 3) world frame, on truth.t
    gyro_bias: np.ndarray  # (N, 3), on truth.t
    accel_bias: np.ndarray  # (N, 3), on truth.t
    noise: ImuNoiseModel
    noise_source: str
    sha256: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Which dataset this is, and the short name used in result file names.
    dataset: str = "EuRoC MAV"
    slug: str = "euroc"
    #: False when the ground truth carries no bias columns, so the start bias cannot come from it.
    bias_known: bool = True
    #: Other noise figures the dataset supplies, selectable with ``RunOptions.noise_source``.
    noise_variants: dict[str, ImuNoiseModel] = field(default_factory=dict)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
