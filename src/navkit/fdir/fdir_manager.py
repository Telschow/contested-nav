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

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .gating import DEFAULT_CONFIDENCE, chi2_dof, chi2_threshold, mahalanobis_sq
from .nis_monitor import NisConfig, NisWindowMonitor

__all__ = [
    "STATUS_ACCEPTED",
    "STATUS_REJECTED_SPOOF",
    "STATUS_REJECTED_PERSISTENT",
    "STATUS_REACCEPTED_WITH_INFLATION",
    "STATUS_SENSOR_FAULT",
    "ChannelState",
    "FdirConfig",
    "FdirEvent",
    "FdirManager",
    "GatingDecision",
    "SENSOR_CHANNELS",
]

STATUS_ACCEPTED = "ACCEPTED"
#: An isolated gate failure, with no run of failures behind it. The name states
#: the *policy* -- an unproven channel gets no covariance relief and is treated as
#: untrusted -- and deliberately does not assert a cause. A lone large residual
#: is what multipath looks like and what a spoof looks like, and ADR-0005 records
#: that the gate cannot tell them apart; calling this "spoof" would be the same
#: over-claim in a string literal that the ADR refuses to make in prose.
STATUS_REJECTED_SPOOF = "REJECTED_SPOOF"
#: A run of failures too long to be attributed to a single bad epoch, and too
#: long to be relieved by the inflation in :mod:`navkit.fdir.nis_monitor`. Still a
#: sensor, not the filter.
STATUS_REJECTED_PERSISTENT = "REJECTED_PERSISTENT"
#: A channel that has been failing for long enough to look like the filter's own
#: overconfidence, and whose innovation became plausible once a bounded amount of
#: covariance was admitted. This is the one verdict that *loosens* the filter, so
#: it is always an event and never just a counter.
STATUS_REACCEPTED_WITH_INFLATION = "REACCEPTED_WITH_INFLATION"
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
    #: Consecutive gate failures that make a channel eligible for adaptive
    #: covariance inflation. Three is the smallest run that separates a filter
    #: which has been walked away from truth -- which stays wrong until it is
    #: corrected, and correcting it takes an accepted update -- from multipath,
    #: which arrives in single samples. Below three, a two-sample multipath burst
    #: could buy covariance inflation.
    reacq_consecutive_rejections: int = 3
    #: Retained gate outcomes per channel. Reporting only; the decision above
    #: reads just the trailing run.
    reacq_window: int = 5
    #: Ceiling on how much of its own uncertainty an adaptation may surrender,
    #: as a multiple of the variance named in ``reacq_sigma_m`` below. This is a
    #: security control rather than a tuning knob: it bounds the trust a
    #: persistent spoof can buy, and it is the reason the inflation is safe to
    #: enable at all. See :mod:`navkit.fdir.nis_monitor`.
    max_inflation_factor: float = 100.0
    #: 1-sigma of position uncertainty admitted to a channel judged to be
    #: re-acquiring, before the drift bound below is applied.
    reacq_sigma_m: float = 3.0
    #: 1-sigma per second by which a dead-reckoned position may be wrong. The
    #: bound that makes this mechanism safe, and the reason
    #: ``max_inflation_factor`` alone is not enough -- see
    #: :attr:`navkit.fdir.nis_monitor.NisConfig.max_drift_sigma_mps`.
    max_drift_sigma_mps: float = 0.5
    #: A re-accepted innovation must sit this far inside the gate, not merely
    #: under it -- see
    #: :attr:`navkit.fdir.nis_monitor.NisConfig.reaccept_margin` for why a
    #: marginal pass is the dangerous case rather than the safe one.
    reaccept_margin: float = 0.25

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
        if self.reacq_consecutive_rejections < 1:
            raise ValueError("reacq_consecutive_rejections must be at least 1")
        if self.reacq_window < 1:
            raise ValueError("reacq_window must be at least 1")
        if self.max_inflation_factor < 1.0:
            raise ValueError("max_inflation_factor must be at least 1")
        if self.reacq_sigma_m <= 0.0:
            raise ValueError("reacq_sigma_m must be positive")
        if self.max_drift_sigma_mps <= 0.0:
            raise ValueError("max_drift_sigma_mps must be positive")
        if not 0.0 < self.reaccept_margin <= 1.0:
            raise ValueError("reaccept_margin must lie in (0, 1]")

    @property
    def alpha(self) -> float:
        """Significance level, the upper-tail probability of a false rejection."""
        return 1.0 - self.confidence_level

    def nis_config(self) -> NisConfig:
        """The persistence monitor's configuration, derived from these fields.

        Derived rather than nested so that :meth:`as_dict` stays flat and one
        number in one place governs both the estimator's configuration and the
        monitor built from it.
        """
        return NisConfig(
            window_size=self.reacq_window,
            consecutive_rejection_threshold=self.reacq_consecutive_rejections,
            max_inflation_factor=self.max_inflation_factor,
            reacq_pos_sigma_m=self.reacq_sigma_m,
            max_drift_sigma_mps=self.max_drift_sigma_mps,
            reaccept_margin=self.reaccept_margin,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "confidence_level": self.confidence_level,
            "max_consecutive_rejections": self.max_consecutive_rejections,
            "auto_recovery_count": self.auto_recovery_count,
            "reacq_consecutive_rejections": self.reacq_consecutive_rejections,
            "reacq_window": self.reacq_window,
            "max_inflation_factor": self.max_inflation_factor,
            "reacq_sigma_m": self.reacq_sigma_m,
            "max_drift_sigma_mps": self.max_drift_sigma_mps,
            "reaccept_margin": self.reaccept_margin,
        }


@dataclass(frozen=True)
class GatingDecision:
    """Outcome of one innovation test.

    ``accepted`` is the only field the estimator acts on. ``status`` carries the
    reason, because a filter that silently drops 40% of its GNSS fixes is
    indistinguishable from one that has degraded gracefully until you read a
    counter.

    ``inflation_variance`` is the one field that asks the estimator to do
    something. When it is non-zero the estimator must add it to the diagonal of
    the state block named in ``inflation_block`` *before* forming the Kalman
    gain, and must recompute ``S`` from the inflated covariance -- not merely
    reuse the value the gate already saw. The gate's own re-gate in
    :meth:`FdirManager.evaluate_and_adapt` is computed from exactly that
    modification, so applying it as stated reproduces the distance the verdict was
    based on. Ignoring this field and fusing anyway would be a smaller change to
    the filter than honouring it, which is exactly why it is spelled out here.
    """

    accepted: bool
    mahalanobis_sq: float
    threshold: float
    dof: int
    status: str
    #: Per-axis variance to add to ``inflation_block``, in m^2 or rad^2. Zero
    #: unless the verdict is :data:`STATUS_REACCEPTED_WITH_INFLATION`.
    inflation_variance: float = 0.0
    #: State indices the variance applies to. Empty unless inflating.
    inflation_block: tuple = ()
    #: Distance the same innovation would have had under the inflated
    #: covariance. Recorded so the log shows what the inflation bought rather
    #: than only that it happened.
    mahalanobis_sq_inflated: float = float("nan")
    #: True when this update cleared a declared fault. Carried on the decision
    #: rather than logged inside the gate because the same two-pass split that
    #: holds back a rejection has to hold back a recovery: a channel that
    #: recovers and is then re-fused is not a recovery.
    recovered: bool = False
    #: True when the *numbers* excluded this sample -- that is, when the
    #: innovation was an outlier against the covariance the filter had. False
    #: when the sample was consistent but the channel is still under a declared
    #: fault, which is a different exclusion with the same ``accepted=False``.
    #:
    #: This distinction is what stops adaptive inflation from undoing fault
    #: isolation. Without it, a spoof small enough that the filter drifts toward
    #: it eventually produces an innovation *inside* the threshold; the gate is
    #: happy, the fault hold is not, and the second pass would spend the drift
    #: budget buying back a channel the first pass had correctly condemned.
    #: A fault is a security decision, and a 0.1 m budget must not be able to
    #: overturn it. Only a genuine outlier is eligible for relief.
    outlier: bool = False

    @property
    def sensor_fault(self) -> bool:
        return self.status == STATUS_SENSOR_FAULT

    @property
    def inflated(self) -> bool:
        return self.inflation_variance > 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "mahalanobis_sq": self.mahalanobis_sq,
            "threshold": self.threshold,
            "dof": self.dof,
            "status": self.status,
            "inflated": self.inflated,
            "inflation_variance": self.inflation_variance,
            "inflation_block": list(self.inflation_block),
            "mahalanobis_sq_inflated": self.mahalanobis_sq_inflated,
            "recovered": self.recovered,
            "outlier": self.outlier,
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
    #: Present only on :data:`STATUS_REACCEPTED_WITH_INFLATION` events. The
    #: variance handed to the estimator, so the log records how much uncertainty
    #: the filter surrendered rather than only that it did.
    inflation_variance: float = 0.0
    #: The distance the innovation had under the inflated covariance.
    mahalanobis_sq_inflated: float = float("nan")

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": self.t_s,
            "sensor": self.sensor,
            "status": self.status,
            "mahalanobis_sq": self.mahalanobis_sq,
            "threshold": self.threshold,
            "consecutive_rejections": self.consecutive_rejections,
            "inflation_variance": self.inflation_variance,
            "mahalanobis_sq_inflated": self.mahalanobis_sq_inflated,
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
    last_mahalanobis_sq_inflated: float = float("nan")
    #: Updates admitted after adaptive inflation, and the total variance added
    #: doing so. Counted separately from ``accepted_total`` because these are the
    #: only fusions the filter performed on evidence it had previously declared
    #: implausible, and a reader auditing trust decisions needs them separable.
    reaccepted_total: int = 0
    inflation_variance_total: float = 0.0
    #: True once this channel has been granted adaptive inflation during the
    #: current divergence episode, which runs from the first rejection of a run
    #: until an update is accepted on its own merits.
    #:
    #: This is the control that makes the cap mean anything. ``max_inflation_
    #: factor`` bounds what a *single* adaptation may add, so without a limit on
    #: how many adaptations one episode may buy, a channel delivering a thousand
    #: consistent bad fixes would collect a thousand grants and the bound would be
    #: a bound on the increment rather than on the total. One grant per episode
    #: turns it into a bound on the total uncertainty a channel can ever talk the
    #: filter out of, which is the quantity the security argument is about.
    inflation_granted_in_episode: bool = False
    #: Timestamp of the last measurement this channel passed through the
    #: *unmodified* gate.
    #:
    #: Deliberately not updated by an update that needed inflation. A fix the
    #: filter could only accept after being given extra uncertainty has not
    #: verified the filter, and counting it as a clean fix would let an attacker
    #: reset the clock: grant a step, the partially-moved filter then passes the
    #: ordinary gate on the next fix, the episode closes, and a fresh envelope
    #: opens. That converges geometrically onto any offset, however large, and it
    #: is the difference between a bound and no bound at all. The drift budget is
    #: measured from the last time the filter was *unverified*.
    t_last_trusted: float = float("nan")
    #: Longest single silence this channel has suffered since the filter was last
    #: confident, in seconds. The drift budget is measured from this and not
    #: from elapsed time, and the distinction is the whole security argument.
    #:
    #: "No measurement arrived" and "a measurement arrived and we rejected it"
    #: are different facts with opposite meanings. Only the first means the
    #: filter has actually gone blind and may really have drifted, and only the
    #: first should buy covariance. Summing the inter-arrival intervals instead
    #: -- which is the obvious way to measure it -- counts a sustained spoof
    #: delivering a fix every 200 ms as six seconds of blindness, which hands
    #: the attacker exactly the envelope they are trying to buy. The longest
    #: single gap cannot be inflated that way: a channel streaming data has a
    #: longest silence of one sample period, whatever it is sending.
    longest_silence_s: float = 0.0
    #: Value of ``longest_silence_s`` when the current run of accepted updates
    #: began. This is what stops a health count from before a silence being spent
    #: clearing a silence that came after it.
    #:
    #: Measured, not theorised: in ``outage_visual_degraded_camera`` the channel
    #: had 26 consecutive accepted fixes before the 15 s denial, so the first
    #: accepted fix on return carried ``consecutive_accepts`` straight past
    #: ``auto_recovery_count`` and banked silence was wiped by a counter that
    #: knew nothing about the outage. Twenty-six healthy fixes an hour earlier is
    #: not evidence about the filter's state now.
    silence_at_run_start: float = 0.0
    #: Shortest positive gap ever seen on this channel, which for a regularly
    #: scheduled source is its true period. Used to tell an ordinary gap from a
    #: material one.
    min_gap_s: float = float("inf")
    #: Timestamp of the last sample offered on this channel, accepted or not.
    t_last_arrival: float = float("nan")

    @property
    def faulted(self) -> bool:
        return self.fault_declared

    def reset_fault(self) -> None:
        self.fault_declared = False
        self.consecutive_rejections = 0
        self.consecutive_accepts = 0
        self.inflation_granted_in_episode = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "consecutive_rejections": self.consecutive_rejections,
            "consecutive_accepts": self.consecutive_accepts,
            "rejected_total": self.rejected_total,
            "accepted_total": self.accepted_total,
            "fault_declared": self.fault_declared,
            "last_mahalanobis_sq": self.last_mahalanobis_sq,
            "last_threshold": self.last_threshold,
            "last_mahalanobis_sq_inflated": self.last_mahalanobis_sq_inflated,
            "reaccepted_total": self.reaccepted_total,
            "inflation_variance_total": self.inflation_variance_total,
            "inflation_granted_in_episode": self.inflation_granted_in_episode,
            "t_last_trusted": self.t_last_trusted,
            "longest_silence_s": self.longest_silence_s,
            "silence_at_run_start": self.silence_at_run_start,
            "t_last_arrival": self.t_last_arrival,
        }


class FdirManager:
    """Chi-square gate, per-channel isolation, and adaptive re-acquisition.

    One manager serves every channel and holds their states independently: a
    faulted GNSS receiver says nothing about the camera. The state is not thread
    safe, and does not need to be -- a filter's update path is single-threaded by
    construction here.

    Two entry points, and the difference between them is the whole design:
    :meth:`check` is the plain gate, and :meth:`evaluate_and_adapt` adds the
    second pass that relieves a channel the filter itself has dislocated. Callers
    that cannot supply a covariance to inflate use ``check``; the estimator uses
    ``evaluate_and_adapt``.
    """

    def __init__(self, config: FdirConfig | None = None) -> None:
        self.cfg = config or FdirConfig()
        self._channels: dict[str, ChannelState] = {}
        self.events: list[FdirEvent] = []
        self.nis = NisWindowMonitor(self.cfg.nis_config())

    # -- introspection --------------------------------------------------------

    def state(self, sensor: str) -> ChannelState:
        """State for ``sensor``, created on first use.

        Channels are created lazily rather than from a fixed enum so that adding a
        measurement model does not require editing the gate.
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

    def mean_nis(self, sensor: str) -> float:
        """Rolling mean innovation distance for ``sensor``.

        Exposed on the manager as well as the monitor because the diagnostics
        tool prints it per channel and a caller should not have to know the
        monitor is reachable.
        """
        return self.nis.mean_nis(sensor)

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
            out[f"fdir_{name}_reaccepted"] = float(st.reaccepted_total)
            out[f"fdir_{name}_inflation_variance"] = float(st.inflation_variance_total)
            out[f"fdir_{name}_mean_nis"] = float(self.nis.mean_nis(name))
        return out

    def reset(self) -> None:
        self._channels.clear()
        self.events.clear()
        self.nis.reset()

    def reset_channel(self, sensor: str) -> None:
        """Drop one channel's isolation state and its NIS history.

        Both, and that is the point: re-enabling a sensor that the filter is no
        longer in the same place as would otherwise inherit the run of failures
        that disqualified it, and could be granted inflation on the strength of
        evidence gathered under a different geometry.
        """
        self._channels.pop(sensor, None)
        self.nis.reset_channel(sensor)

    # -- pass 1: the gate -----------------------------------------------------

    def _evaluate(
        self,
        sensor: str,
        innovation: np.ndarray,
        S: np.ndarray,
        t_s: float = 0.0,
    ) -> GatingDecision:
        """Gate one innovation and advance the channel state. Emits no event.

        Split out from :meth:`check` so that :meth:`evaluate_and_adapt` can hold
        the verdict until the second pass has had its chance to overturn it.
        Logging a rejection and then accepting the same update on the next line
        would leave both in the event log, and the log is the thing an operator
        reads to find out what the filter did.
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
        if math.isfinite(st.t_last_arrival):
            gap = t_s - st.t_last_arrival
            if gap > 0.0:
                st.min_gap_s = min(st.min_gap_s, gap)
                st.longest_silence_s = max(st.longest_silence_s, gap)
                if gap > 2.0 * st.min_gap_s:
                    # A material silence: the channel went quiet for several of
                    # its own periods, so the filter stopped being checked. Any
                    # run of accepted updates it had before the gap says nothing
                    # about where it is now, and carrying that count across is
                    # what let a 26-fix healthy history wipe a 15 s denial's
                    # drift budget on the first update after it ended.
                    st.consecutive_accepts = 0
        st.t_last_arrival = float(t_s)
        if st.consecutive_rejections == 0:
            # First update of a run of accepts: snapshot the bank so the run can
            # be held to clearing the silence it started in, and not a silence
            # that predates it.
            st.silence_at_run_start = st.longest_silence_s
        threshold = chi2_threshold(dof, self.cfg.alpha)
        d2 = mahalanobis_sq(innov, S)
        st.last_mahalanobis_sq = d2
        st.last_threshold = threshold

        if d2 <= threshold and not st.fault_declared:
            return self._accept(st, d2, threshold, dof, t_s)
        if d2 <= threshold:
            # Consistent again while faulted: credit it toward recovery, but do
            # not clear the fault on one good sample. The hysteresis count in
            # auto_recovery_count is what makes that stick.
            st.consecutive_accepts += 1
            if st.consecutive_accepts >= self.cfg.auto_recovery_count:
                st.reset_fault()
                st.accepted_total += 1
                st.t_last_trusted = float(t_s)
                st.longest_silence_s = 0.0
                return GatingDecision(
                    accepted=True,
                    mahalanobis_sq=d2,
                    threshold=threshold,
                    dof=dof,
                    status=STATUS_ACCEPTED,
                    recovered=True,
                )
            # Still excluded: recovery is not yet proven.
            st.consecutive_rejections = 0
            st.rejected_total += 1
            return GatingDecision(
                accepted=False,
                mahalanobis_sq=d2,
                threshold=threshold,
                dof=dof,
                status=STATUS_REJECTED_PERSISTENT,
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
            # Provisional. `evaluate_and_adapt` rewrites this to the persistent
            # label once it has ruled on whether the run of failures belongs to
            # the sensor or to the filter; a caller that never runs the second
            # pass leaves an isolated impulse named as such.
            status = STATUS_REJECTED_SPOOF
        return GatingDecision(
            accepted=False,
            mahalanobis_sq=d2,
            threshold=threshold,
            dof=dof,
            status=status,
            outlier=True,
        )

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

        No covariance inflation happens here. Callers that have a covariance to
        offer should use :meth:`evaluate_and_adapt`; this method exists for the
        case where they do not, and for tests that want the bare gate.
        """
        decision = self._evaluate(sensor, innovation, S, t_s)
        if self.cfg.enabled:
            self.nis.add_sample(sensor, decision.mahalanobis_sq, decision.accepted)
        self._log_decision(decision, t_s, sensor)
        return decision

    # -- pass 2: adaptive re-acquisition --------------------------------------

    def evaluate_and_adapt(
        self,
        sensor: str,
        innovation: np.ndarray,
        S: np.ndarray,
        t_s: float = 0.0,
        P: np.ndarray | None = None,
        H: np.ndarray | None = None,
        block: tuple = (),
    ) -> GatingDecision:
        """Gate, and if the failure looks like the filter's own fault, re-gate.

        This is the fix for blocker B5, and the reasoning behind both branches is
        the argument in :mod:`navkit.fdir.nis_monitor`.

        A rejection is re-tested only when three things hold. The channel must
        have failed ``reacq_consecutive_rejections`` times running -- one bad
        measurement is not evidence of anything. The caller must have supplied
        ``P`` and ``H``, because inflating a covariance you cannot see is not
        possible. And the re-gate must pass *under the inflated covariance*, not
        approximately.

        The inflated innovation covariance is formed as ``S + H dP H^T`` rather
        than rebuilt from ``P`` and ``R``. That is not an optimisation: it is
        exactly the value the estimator will have once it honours the decision,
        since ``S = H P H^T + R`` and the inflation adds to ``P`` only. Deriving
        it the other way would require the caller to also pass ``R`` and would
        create two chances for the re-gate and the fusion to disagree.

        ``block`` names the state indices the measurement actually constrains.
        Inflating the whole 21x21 state on the strength of a position innovation
        would be both wrong and easy to get away with, because the result is still
        a valid covariance -- it would just be a filter that has suddenly become
        unsure of its own gyro bias.

        The caller owns the *units* of the block as much as its identity. The
        variance computed here is derived from a translational drift rate in
        metres per second, so it is only meaningful for a translational block; the
        estimator restricts it to GNSS for that reason and for want of evidence on
        the others, and an empty ``block`` disables the second pass entirely
        rather than guessing.
        """
        decision = self._evaluate(sensor, innovation, S, t_s)
        if not self.cfg.enabled:
            return decision

        self.nis.add_sample(sensor, decision.mahalanobis_sq, decision.accepted)
        if decision.accepted:
            self._log_decision(decision, t_s, sensor)
            return decision

        if not decision.outlier:
            # Not an outlier -- a sample the numbers were happy with, held out
            # only because the channel is still faulted. There is nothing here
            # for the filter to be blamed for, so there is nothing to buy its
            # way out of, and letting the second pass run here would let a drift
            # budget overturn a declared fault.
            self._log_decision(decision, t_s, sensor)
            return decision

        if not self.nis.is_persistent_divergence(sensor):
            self._log_decision(decision, t_s, sensor)
            return decision
        if P is not None and H is not None and block:
            adapted = self._reaccept_with_inflation(
                sensor, innovation, S, P, H, block, decision, t_s
            )
        else:
            # The second pass is unavailable, but what the monitor knows is not:
            # it still knows this is a run of failures rather than a stray one.
            adapted = decision
        if not adapted.inflated and adapted.status != STATUS_SENSOR_FAULT:
            # A run of failures that the inflation could not explain is a sensor,
            # not a filter -- so it is labelled as one. Never over a
            # SENSOR_FAULT, which pass 1 has already earned by counting five
            # consecutive failures: relabelling it here is how a declared fault
            # ends up recorded as an ordinary persistent rejection and never
            # appears in the log as a fault at all.
            adapted = _with_status(adapted, STATUS_REJECTED_PERSISTENT)
        self._log_decision(adapted, t_s, sensor)
        return adapted

    def _reaccept_with_inflation(
        self,
        sensor: str,
        innovation: np.ndarray,
        S: np.ndarray,
        P: np.ndarray,
        H: np.ndarray,
        block: tuple,
        decision: GatingDecision,
        t_s: float,
    ) -> GatingDecision:
        """Second pass. Returns a decision that may or might ask for inflation."""
        st = self.state(sensor)
        if st.inflation_granted_in_episode:
            # Already spent this episode's grant. A channel that keeps failing
            # after having been relieved once is not re-acquiring, and the
            # answer is isolation, not more uncertainty.
            return decision
        blind_s = st.longest_silence_s
        variance = self.nis.inflation_variance(
            decision.mahalanobis_sq, decision.threshold, blind_s
        )
        if not variance > 0.0:
            return decision

        dP = np.zeros_like(P)
        idx = np.ix_(block, block)
        dP[idx] = variance * np.eye(len(block))
        S_inflated = S + H @ dP @ H.T
        d2_inflated = mahalanobis_sq(innovation, S_inflated)

        if not d2_inflated <= self.cfg.reaccept_margin * decision.threshold:
            # The offset is larger than the bounded inflation can explain. This
            # is the spoof case the cap exists for: the channel keeps failing and
            # goes on to be isolated. Returning `decision` unchanged keeps the
            # original distance in the log, which is the number that matters.
            return decision

        # The inflation did it. Undo pass 1's rejection bookkeeping: this update
        # is a fusion, not a rejection, and leaving it in `rejected_total` would
        # have the re-acquisition read as a continued denial.
        #
        # The declared fault is cleared as well, and that is not optional. The
        # fault was declared *because* of a persistent divergence, and the
        # inflation has just resolved it; keeping the fault would fuse this fix
        # and then exclude the next three, which is the same discard-the-fix loop
        # that produced blocker B5 in the first place, one level up. A
        # re-acquisition that cannot converge is not a re-acquisition.
        #
        # What bounds the trust this buys is not the fault flag but the drift
        # bound and the need to earn a fresh grant: clear the fault, and the
        # channel must then pass the unmodified gate again before anything else
        # happens, which it will not if the offset was not really drift.
        st.rejected_total -= 1
        st.consecutive_rejections = 0
        st.consecutive_accepts = 0
        st.accepted_total += 1
        st.reaccepted_total += 1
        st.inflation_variance_total += variance
        st.inflation_granted_in_episode = True
        cleared_fault = st.fault_declared
        st.fault_declared = False
        st.last_mahalanobis_sq_inflated = d2_inflated

        return GatingDecision(
            accepted=True,
            mahalanobis_sq=decision.mahalanobis_sq,
            threshold=decision.threshold,
            dof=decision.dof,
            status=STATUS_REACCEPTED_WITH_INFLATION,
            inflation_variance=variance,
            inflation_block=block,
            mahalanobis_sq_inflated=d2_inflated,
            recovered=cleared_fault,
        )

    def _accept(
        self, st: ChannelState, d2: float, threshold: float, dof: int, t_s: float
    ) -> GatingDecision:
        st.consecutive_rejections = 0
        st.consecutive_accepts += 1
        st.accepted_total += 1
        st.t_last_trusted = float(t_s)
        # The banked silence is only cleared once the channel has earned it, on
        # the same hysteresis the tracker already uses to declare a channel
        # healthy again. Clearing it on a single accepted fix is wrong in a way
        # that measurement caught: in outage_visual_degraded_camera the first
        # fix after the 15 s denial happened to pass, and that one accept
        # discarded the whole drift budget, leaving the 50 genuinely rejected
        # fixes that followed to be judged as though the filter had been blind
        # for a fifth of a second. One accepted measurement out of seventy-six is
        # not evidence that a displaced filter is well placed, and the
        # auto_recovery_count threshold is the standard this file already applies
        # to that same question.
        if (
            st.consecutive_accepts >= self.cfg.auto_recovery_count
            and st.silence_at_run_start > 0.0
        ):
            st.longest_silence_s = 0.0
        # The episode is over: this update needed no help, so the next run of
        # failures will have to earn its own grant.
        st.inflation_granted_in_episode = False
        return GatingDecision(
            accepted=True,
            mahalanobis_sq=d2,
            threshold=threshold,
            dof=dof,
            status=STATUS_ACCEPTED,
        )

    def _log_decision(self, decision: GatingDecision, t_s: float, sensor: str) -> None:
        """Record the verdict. See :meth:`_log` for what is worth recording.

        The sensor name and the rejection count are passed in rather than read
        off the decision because the decision is a pure result -- it is compared
        for equality and returned to callers who have no use for the tracker
        internals -- while these two are the log's subject matter.
        """
        st = self._channels.get(sensor)
        if decision.status == STATUS_REACCEPTED_WITH_INFLATION:
            self._log_inflation(t_s, sensor, decision)
            return
        if decision.recovered:
            self._log(
                t_s,
                sensor,
                STATUS_ACCEPTED,
                decision.mahalanobis_sq,
                decision.threshold,
                0,
            )
            return
        if decision.accepted:
            return
        consecutive = st.consecutive_rejections if st is not None else 0
        self._log(
            t_s,
            sensor,
            decision.status,
            decision.mahalanobis_sq,
            decision.threshold,
            consecutive,
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

    def _log_inflation(self, t_s: float, sensor: str, decision: GatingDecision) -> None:
        self.events.append(
            FdirEvent(
                t_s=float(t_s),
                sensor=sensor,
                status=STATUS_REACCEPTED_WITH_INFLATION,
                mahalanobis_sq=float(decision.mahalanobis_sq),
                threshold=float(decision.threshold),
                consecutive_rejections=0,
                inflation_variance=float(decision.inflation_variance),
                mahalanobis_sq_inflated=float(decision.mahalanobis_sq_inflated),
            )
        )


def _with_status(decision: GatingDecision, status: str) -> GatingDecision:
    """Same verdict, different label. Used to relabel a rejection."""
    return replace(decision, status=status)
