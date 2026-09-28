"""Sensor state machine: detect, isolate, recover.

Detection alone is not isolation
--------------------------------
:mod:`navkit.fdir.gating` answers "is this measurement consistent with the
filter's own uncertainty?" Turning that into a usable fault-handling layer takes
three more decisions, and this module owns all three.

**Transience.** A single rejected update is ambiguous. It could be multipath on
one epoch, or the first sign of a dead sensor, and the two demand opposite
responses: one wants the next update, the other wants the sensor excluded.
Distinguishing them on a single sample is not possible, so this module does not
pretend to. It counts consecutive rejections and declares a fault only after
``max_consecutive_rejections`` of them, which is a deliberate trade of detection
delay for immunity to single-epoch noise.

**Isolation.** Once a channel is declared faulty, what happens to its updates?
The tempting answer -- inflate its noise until the innovation fits -- is exactly
the failure mode ADR-0003 documents: it makes the filter *confidently wrong*
rather than merely uncertain. A faulted channel is therefore rejected outright
and its updates do not enter the filter. The filter coasts on inertial
propagation, which is honest: no measurement, no information, and the covariance
grows because nothing is constraining it.

**Recovery.** Isolation without a way back is a one-way ratchet that ends in a
dead sensor. Recovery is symmetric hysteresis: ``auto_recovery_count`` consecutive
*accepted* updates clear the fault. The asymmetry is intentional -- a fault needs
several bad epochs to declare, and several good ones to clear, so a signal
oscillating around the threshold cannot oscillate the state machine with it.

What this does not do
---------------------
It does not tell you *which kind* of fault you have. Multipath inflates
innovation variance without shifting the mean; a spoofed fix is internally
consistent and agrees with nothing else; a drifting bias moves the mean slowly
and takes longer to cross a threshold than a step does. Separating those needs
cross-sensor consistency checks and residual whiteness tests over a window, which
is ROADMAP Track A. This module is the isolation layer those detectors would
report into, and it is honest about being the part that does the damage control
rather than the part that does the diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .gating import DEFAULT_CONFIDENCE, chi2_dof, chi2_threshold, mahalanobis_sq

__all__ = [
    "STATUS_ACCEPTED",
    "STATUS_REJECTED_TRANSIENT",
    "STATUS_REJECTED_PERSISTENT",
    "STATUS_SENSOR_FAULT",
    "ChannelState",
    "FdirConfig",
    "FdirEvent",
    "FdirTracker",
    "GatingDecision",
    "SENSOR_CHANNELS",
]

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED_TRANSIENT = "REJECTED_TRANSIENT"
STATUS_REJECTED_PERSISTENT = "REJECTED_PERSISTENT"
STATUS_SENSOR_FAULT = "SENSOR_FAULT"

#: Channels the tracker understands. The names match the ``sensor=`` argument the
#: measurement models in :mod:`navkit.estimators.eskf` actually pass, so a log
#: line can be read back to a source.
#:
#: ``vision`` is deliberately absent. A relative-pose fix arrives as two
#: independent blocks -- rotation and translation -- with different dimensions,
#: different noise, and different failure modes, so gating them under one channel
#: would let a bad rotation mask a good translation. They are tracked separately
#: and share nothing but the run.
SENSOR_CHANNELS = ("gnss", "vision_rot", "vision_trans", "altimeter")


@dataclass
class FdirConfig:
    """Fault-detection policy. All thresholds are stated, none are implicit."""

    enabled: bool = True
    #: One minus the upper-tail probability of a false rejection on a healthy
    #: sensor. The default is 0.999, so the declared cost of catching a rare
    #: fault is one wrongly-rejected update in a thousand; see
    #: :data:`navkit.fdir.gating.DEFAULT_CONFIDENCE` for the measurement behind
    #: that choice, which is not the conventional 0.99.
    confidence_level: float = DEFAULT_CONFIDENCE
    #: Consecutive rejections before a channel is declared faulty. Declaring a
    #: fault from a single bad measurement is how a filter loses a good sensor to
    #: one bad epoch, so the default requires five failures running.
    max_consecutive_rejections: int = 5
    #: Consecutive accepted updates needed to clear a declared fault.
    auto_recovery_count: int = 10

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError(
                f"confidence_level must lie strictly inside (0, 1), got "
                f"{self.confidence_level}"
            )
        if self.max_consecutive_rejections < 1:
            raise ValueError("max_consecutive_rejections must be at least 1")
        if self.auto_recovery_count < 1:
            raise ValueError("auto_recovery_count must be at least 1")

    @property
    def alpha(self) -> float:
        """Significance level, the upper-tail probability of a false rejection."""
        return 1.0 - self.confidence_level

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "confidence_level": self.confidence_level,
            "max_consecutive_rejections": self.max_consecutive_rejections,
            "auto_recovery_count": self.auto_recovery_count,
        }


@dataclass(frozen=True)
class GatingDecision:
    """Outcome of one innovation test.

    ``accepted`` is the only field the estimator acts on. ``status`` carries the
    reason, because a filter that silently drops 40% of its GNSS fixes is
    indistinguishable from one that has degraded gracefully until you read a
    counter.
    """

    accepted: bool
    mahalanobis_sq: float
    threshold: float
    dof: int
    status: str

    @property
    def sensor_fault(self) -> bool:
        return self.status == STATUS_SENSOR_FAULT

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "mahalanobis_sq": self.mahalanobis_sq,
            "threshold": self.threshold,
            "dof": self.dof,
            "status": self.status,
        }


@dataclass
class FdirEvent:
    """A state transition worth logging rather than merely counting."""

    t_s: float
    sensor: str
    status: str
    mahalanobis_sq: float
    threshold: float
    consecutive_rejections: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": self.t_s,
            "sensor": self.sensor,
            "status": self.status,
            "mahalanobis_sq": self.mahalanobis_sq,
            "threshold": self.threshold,
            "consecutive_rejections": self.consecutive_rejections,
        }


@dataclass
class ChannelState:
    """Per-channel counters. Public because the estimator reports them."""

    consecutive_rejections: int = 0
    consecutive_accepts: int = 0
    rejected_total: int = 0
    accepted_total: int = 0
    fault_declared: bool = False
    last_mahalanobis_sq: float = float("nan")
    last_threshold: float = float("nan")

    @property
    def faulted(self) -> bool:
        return self.fault_declared

    def reset_fault(self) -> None:
        self.fault_declared = False
        self.consecutive_rejections = 0
        self.consecutive_accepts = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "consecutive_rejections": self.consecutive_rejections,
            "consecutive_accepts": self.consecutive_accepts,
            "rejected_total": self.rejected_total,
            "accepted_total": self.accepted_total,
            "fault_declared": self.fault_declared,
            "last_mahalanobis_sq": self.last_mahalanobis_sq,
            "last_threshold": self.last_threshold,
        }


class FdirTracker:
    """Chi-square gate plus per-channel isolation state.

    One tracker serves every channel and holds their states independently: a
    faulted GNSS receiver says nothing about the camera. The state is not thread
    safe, and does not need to be -- a filter's update path is single-threaded by
    construction here.
    """

    def __init__(self, config: FdirConfig | None = None) -> None:
        self.cfg = config or FdirConfig()
        self._channels: dict[str, ChannelState] = {}
        self.events: list[FdirEvent] = []

    # -- introspection --------------------------------------------------------

    def state(self, sensor: str) -> ChannelState:
        """State for ``sensor``, created on first use.

        Channels are created lazily rather than from a fixed enum so that adding
        a measurement model does not require editing the gate.
        """
        st = self._channels.get(sensor)
        if st is None:
            st = ChannelState()
            self._channels[sensor] = st
        return st

    def is_faulted(self, sensor: str) -> bool:
        return self.state(sensor).fault_declared

    @property
    def channels(self) -> dict[str, ChannelState]:
        return dict(self._channels)

    def stats(self) -> dict[str, Any]:
        """Flat counters for the estimator's result dictionary."""
        out: dict[str, Any] = {
            "fdir_channels": len(self._channels),
            "fdir_events": float(len(self.events)),
        }
        for name, st in sorted(self._channels.items()):
            out[f"fdir_{name}_rejected"] = float(st.rejected_total)
            out[f"fdir_{name}_accepted"] = float(st.accepted_total)
            out[f"fdir_{name}_faulted"] = float(st.fault_declared)
            out[f"fdir_{name}_consecutive_rejections"] = float(st.consecutive_rejections)
        return out

    def reset(self) -> None:
        self._channels.clear()
        self.events.clear()

    # -- the decision ---------------------------------------------------------

    def check(
        self,
        sensor: str,
        innovation: np.ndarray,
        S: np.ndarray,
        t_s: float = 0.0,
    ) -> GatingDecision:
        """Gate one measurement and update the channel's isolation state.

        Order of operations is deliberate. The innovation is gated *first*, even
        for an already-faulted channel: a faulted channel whose measurements are
        suddenly consistent again must be able to recover, and recovery is
        decided on how many good updates have arrived. Skipping the gate for a
        faulted channel would make recovery impossible, because every update
        would be excluded and nothing would ever be counted as good.
        """
        innov = np.asarray(innovation, dtype=float).reshape(-1)
        dof = chi2_dof(innov)

        if not self.cfg.enabled:
            # Disabled means disabled, not "gate with an infinite threshold". No
            # channel state is created or advanced, so a run with FDIR off leaves
            # no counters and no fault history -- neither of which could later be
            # mistaken for evidence that the channel was healthy. An all-zero
            # "fdir_gnss_rejected" alongside a populated "gnss_updates_used" would
            # read as a gate that never fired, which is a different claim.
            return GatingDecision(
                accepted=True,
                mahalanobis_sq=0.0,
                threshold=float("inf"),
                dof=dof,
                status=STATUS_ACCEPTED,
            )

        st = self.state(sensor)
        threshold = chi2_threshold(dof, self.cfg.alpha)
        d2 = mahalanobis_sq(innov, S)
        st.last_mahalanobis_sq = d2
        st.last_threshold = threshold

        if d2 <= threshold and not st.fault_declared:
            return self._accept(st, d2, threshold, dof)
        if d2 <= threshold:
            # Consistent again while faulted: credit it toward recovery, but do
            # not clear the fault on one good sample. The hysteresis count in
            # auto_recovery_count is what makes that stick.
            st.consecutive_accepts += 1
            if st.consecutive_accepts >= self.cfg.auto_recovery_count:
                st.reset_fault()
                st.accepted_total += 1
                self._log_recovery(t_s, sensor, d2, threshold)
                return GatingDecision(
                    accepted=True,
                    mahalanobis_sq=d2,
                    threshold=threshold,
                    dof=dof,
                    status=STATUS_ACCEPTED,
                )
            # Still excluded: recovery is not yet proven.
            st.consecutive_rejections = 0
            status = STATUS_REJECTED_PERSISTENT
            st.rejected_total += 1
            self._log(t_s, sensor, status, d2, threshold, st.consecutive_rejections)
            return GatingDecision(
                accepted=False,
                mahalanobis_sq=d2,
                threshold=threshold,
                dof=dof,
                status=status,
            )

        # Inconsistent: either trip the gate, or hold the channel in isolation if
        # it is already faulted.
        st.consecutive_accepts = 0
        st.consecutive_rejections += 1
        st.rejected_total += 1
        if st.fault_declared:
            status = STATUS_REJECTED_PERSISTENT
        elif st.consecutive_rejections >= self.cfg.max_consecutive_rejections:
            st.fault_declared = True
            status = STATUS_SENSOR_FAULT
        else:
            status = STATUS_REJECTED_TRANSIENT
        self._log(t_s, sensor, status, d2, threshold, st.consecutive_rejections)
        return GatingDecision(
            accepted=False,
            mahalanobis_sq=d2,
            threshold=threshold,
            dof=dof,
            status=status,
        )

    def _accept(self, st: ChannelState, d2: float, threshold: float, dof: int) -> GatingDecision:
        st.consecutive_rejections = 0
        st.consecutive_accepts += 1
        st.accepted_total += 1
        return GatingDecision(
            accepted=True,
            mahalanobis_sq=d2,
            threshold=threshold,
            dof=dof,
            status=STATUS_ACCEPTED,
        )

    def _log(
        self,
        t_s: float,
        sensor: str,
        status: str,
        d2: float,
        threshold: float,
        consecutive: int,
    ) -> None:
        """Record isolation transitions; count the rest.

        Only two things are worth an event record: a channel being declared
        faulty, and a channel coming back. A transient rejection on an otherwise
        healthy sensor is noise that belongs in a counter -- an event log that
        captured all of them would grow without bound and bury the two lines a
        human actually needs. A rejection *while already faulted* is logged,
        because that is the evidence that isolation is holding rather than
        having silently stopped.
        """
        if status not in (STATUS_SENSOR_FAULT, STATUS_REJECTED_PERSISTENT):
            return
        self.events.append(
            FdirEvent(
                t_s=float(t_s),
                sensor=sensor,
                status=status,
                mahalanobis_sq=float(d2),
                threshold=float(threshold),
                consecutive_rejections=int(consecutive),
            )
        )

    def _log_recovery(self, t_s: float, sensor: str, d2: float, threshold: float) -> None:
        self.events.append(
            FdirEvent(
                t_s=float(t_s),
                sensor=sensor,
                status=STATUS_ACCEPTED,
                mahalanobis_sq=float(d2),
                threshold=float(threshold),
                consecutive_rejections=0,
            )
        )
