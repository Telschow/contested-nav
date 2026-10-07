"""Records produced and kept by the FDIR layer.

:class:`GatingDecision` is the verdict on one update, :class:`FdirEvent` is a logged
state transition, and :class:`ChannelState` is everything the manager remembers about
one measurement channel. They are plain data with ``as_dict`` serialisers; the policy
that fills them in is :class:`navkit.fdir.fdir_manager.FdirManager`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .status import STATUS_SENSOR_FAULT

__all__ = ["ChannelState", "FdirEvent", "GatingDecision"]


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
    #: Variance to add to ``inflation_block`` even though the update is *not*
    #: being fused, and the state indices to add it to. ADR-0007 option 2.
    #:
    #: This is the one place a rejection carries a covariance change, and it is
    #: what makes a lockout recoverable. Without it the filter would coast on a
    #: covariance that no longer describes a displaced mean, and would walk
    #: straight back into the same error the moment the lockout expired. Adding
    #: variance while refusing the measurement keeps the two apart: the filter
    #: admits it no longer knows where it is, without believing the thing that
    #: told it.
    reexpansion_variance: float = 0.0
    reexpansion_block: tuple = ()

    @property
    def sensor_fault(self) -> bool:
        return self.status == STATUS_SENSOR_FAULT

    @property
    def inflated(self) -> bool:
        return self.inflation_variance > 0.0

    @property
    def reexpanded(self) -> bool:
        return self.reexpansion_variance > 0.0

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
            "reexpanded": self.reexpanded,
            "reexpansion_variance": self.reexpansion_variance,
            "reexpansion_block": list(self.reexpansion_block),
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
    #: Inflation grants this channel has needed in the current episode, per
    #: ADR-0007.
    #:
    #: Distinct from :attr:`inflation_granted_in_episode`, which is a one-shot
    #: latch guarding the "one grant per episode" bound. This counter is what
    #: detects *permanence*: the latch resets on any clean accept, but a channel
    #: that keeps needing covariance is telling the filter something the latch
    #: cannot express. Two grants inside one episode is the discriminator.
    grants_this_episode: int = 0
    #: Whether this channel is currently locked out as spoofed, and until when.
    #: ADR-0007.
    locked_out: bool = False
    lockout_until_s: float = float("nan")
    #: Extra variance forced onto the measurement block at the moment of
    #: lockout, in m^2. Retained so the escalation is auditable after the fact
    #: rather than being a one-shot side effect with no record.
    reexpansion_variance: float = 0.0
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
        self.grants_this_episode = 0

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
            "grants_this_episode": self.grants_this_episode,
            "locked_out": self.locked_out,
            "lockout_until_s": self.lockout_until_s,
            "reexpansion_variance": self.reexpansion_variance,
            "t_last_trusted": self.t_last_trusted,
            "longest_silence_s": self.longest_silence_s,
            "silence_at_run_start": self.silence_at_run_start,
            "t_last_arrival": self.t_last_arrival,
        }
