"""Fault detection, isolation and recovery for measurement channels.

The estimator is the only thing that can tell a corrupted measurement from an
unlikely one, because only it knows how much uncertainty it has already
accumulated. This package provides that judgement in two layers:

``navkit.fdir.gating``
    The statistics. Squared Mahalanobis distance of an innovation, against a
    chi-square threshold with a stated false-alarm rate. Tabulated quantiles for
    the degrees of freedom a navigation filter produces, Wilson-Hilferty
    elsewhere, no SciPy.
``navkit.fdir.fdir_manager``
    The policy. Per-channel state that turns a stream of accept/reject verdicts
    into isolation and recovery, so a single bad epoch cannot remove a good
    sensor and a dead sensor is not permanent.

Wiring into the 21-state ESKF is described in ADR-0005 and ``docs/architecture.md``.
"""

from .fdir_manager import (
    SENSOR_CHANNELS,
    STATUS_ACCEPTED,
    STATUS_REJECTED_PERSISTENT,
    STATUS_REJECTED_TRANSIENT,
    STATUS_SENSOR_FAULT,
    ChannelState,
    FdirConfig,
    FdirEvent,
    FdirTracker,
    GatingDecision,
)
from .gating import (
    CHI2_THRESHOLDS,
    DEFAULT_CONFIDENCE,
    MAX_CONDITION_NUMBER,
    chi2_dof,
    chi2_threshold,
    mahalanobis_sq,
    normal_quantile,
    wilson_hilferty,
)

__all__ = [
    "SENSOR_CHANNELS",
    "STATUS_ACCEPTED",
    "STATUS_REJECTED_PERSISTENT",
    "STATUS_REJECTED_TRANSIENT",
    "STATUS_SENSOR_FAULT",
    "ChannelState",
    "FdirConfig",
    "FdirEvent",
    "FdirTracker",
    "GatingDecision",
    "CHI2_THRESHOLDS",
    "DEFAULT_CONFIDENCE",
    "MAX_CONDITION_NUMBER",
    "chi2_dof",
    "chi2_threshold",
    "mahalanobis_sq",
    "normal_quantile",
    "wilson_hilferty",
]
