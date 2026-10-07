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
from dataclasses import replace
from typing import Any

import numpy as np

from .config import FdirConfig
from .gating import chi2_dof, chi2_threshold, mahalanobis_sq
from .nis_monitor import NisWindowMonitor
from .records import ChannelState, FdirEvent, GatingDecision
from .status import (
    SENSOR_CHANNELS,
    STATUS_ACCEPTED,
    STATUS_REACCEPTED_WITH_INFLATION,
    STATUS_REJECTED_PERSISTENT,
    STATUS_REJECTED_SPOOF,
    STATUS_SENSOR_FAULT,
)

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

    def is_locked_out(self, sensor: str) -> bool:
        """True while this channel is in an ADR-0007 spoof cooldown.

        Separate from :meth:`is_faulted` because the two expire on different
        clocks: a fault clears on ``auto_recovery_count`` clean updates, a
        lockout only on elapsed time. A caller reporting "is this sensor usable"
        needs both.
        """
        return self.state(sensor).locked_out

    def _maybe_release_lockout(self, st: ChannelState, t_s: float) -> None:
        """Expire a lockout whose cooldown has elapsed, per ADR-0007.

        Release clears the lockout but deliberately leaves ``fault_declared``
        alone. The channel must then earn its way back through the ordinary
        ``auto_recovery_count`` hysteresis, so the cooldown buys time rather
        than granting trust: an attacker who replays the same step the instant
        the lockout expires is still looking at a faulted channel, and has to
        produce ``auto_recovery_count`` clean updates first.
        """
        if not st.locked_out:
            return
        if not math.isfinite(st.lockout_until_s) or t_s < st.lockout_until_s:
            return
        st.locked_out = False
        st.lockout_until_s = float("nan")
        st.grants_this_episode = 0
        st.reexpansion_variance = 0.0
        st.consecutive_rejections = 0
        st.consecutive_accepts = 0

    def _lock_out(self, st: ChannelState, t_s: float, variance: float) -> None:
        """Escalate this channel to a spoof lockout, per ADR-0007.

        Sets both the fault and the lockout because the two answer different
        questions. The fault says "do not fuse this channel right now"; the
        lockout says "do not come back to this channel for ``spoof_lockout_s``",
        which ordinary recovery hysteresis cannot express, because recovery
        counts clean accepts and a spoofed channel produces them once the filter
        has moved.
        """
        st.fault_declared = True
        st.locked_out = True
        st.lockout_until_s = float(t_s) + self.cfg.spoof_lockout_s
        st.reexpansion_variance = float(variance)
        st.consecutive_rejections += 1
        st.consecutive_accepts = 0

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
        self._maybe_release_lockout(st, t_s)
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
            adapted = self._reaccept_with_inflation(sensor, innovation, S, P, H, block, decision, t_s)
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
        if st.locked_out:
            # Inside a spoof lockout. The channel is not eligible for anything,
            # least of all more uncertainty: a lockout exists precisely because
            # covariance is what the attacker was able to buy once already.
            return decision
        if st.inflation_granted_in_episode:
            # Already spent this episode's grant. A channel that keeps failing
            # after having been relieved once is not re-acquiring, and the
            # answer is isolation, not more uncertainty.
            #
            # ADR-0007 sharpens this. "Keeps failing" is now measured as a
            # count of grants needed within the episode rather than as a single
            # latch, because the latch resets on any clean accept and a spoofed
            # channel produces clean accepts once the filter has moved. The
            # second grant is the signal that the first one did not fix
            # anything, which is what distinguishes a permanently adopted
            # offset from a filter genuinely walking back to truth.
            st.grants_this_episode += 1
            if st.grants_this_episode >= self.cfg.spoof_grant_threshold:
                variance = self.nis.inflation_variance(
                    decision.mahalanobis_sq, decision.threshold, st.longest_silence_s
                )
                reexpansion = (
                    variance * self.cfg.spoof_reexpansion_factor
                    if variance > 0.0
                    else self.cfg.reacq_sigma_m**2 * self.cfg.spoof_reexpansion_factor
                )
                self._lock_out(st, t_s, reexpansion)
                self._log_lockout(sensor, t_s, reexpansion, st.grants_this_episode)
                # The variance rides out on the decision so the estimator can
                # widen the block while refusing the fix. It is carried in
                # `reexpansion_*` and not `inflation_*` precisely because this
                # update is not a fusion: conflating the two would let the
                # estimator's `if decision.inflated` branch treat a lockout as
                # a re-acquisition.
                return replace(
                    decision,
                    status=STATUS_REJECTED_SPOOF,
                    reexpansion_variance=reexpansion,
                    reexpansion_block=block,
                )
            return decision
        blind_s = st.longest_silence_s
        variance = self.nis.inflation_variance(decision.mahalanobis_sq, decision.threshold, blind_s)
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
        st.grants_this_episode += 1
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

    def _accept(self, st: ChannelState, d2: float, threshold: float, dof: int, t_s: float) -> GatingDecision:
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
        if st.consecutive_accepts >= self.cfg.auto_recovery_count and st.silence_at_run_start > 0.0:
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

    def _log_lockout(self, sensor: str, t_s: float, variance: float, grants: int) -> None:
        """Record a spoof escalation. See :meth:`_log` for what is worth recording.

        A lockout is logged even though it is a rejection, because it is not a
        rejection like the others: it is the subsystem concluding that covariance
        relief has been used against it, and that fact is what an operator needs
        to see. Logging it under the same rule as a transient rejection would
        bury the one line that says the receiver was judged compromised.
        """
        self.events.append(
            FdirEvent(
                t_s=float(t_s),
                sensor=sensor,
                status=STATUS_REJECTED_SPOOF,
                mahalanobis_sq=float("nan"),
                threshold=float("nan"),
                consecutive_rejections=int(grants),
                inflation_variance=float(variance),
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
