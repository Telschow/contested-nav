"""Rolling NIS history, used to tell a spoof apart from a re-acquisition.

The chi-square gate in :mod:`navkit.fdir.gating` answers one question -- is this
innovation consistent with what the filter expected? -- and it answers it the
same way for every innovation. That is a weakness, not an oversight, and
ADR-0005 names it: a gate on its own cannot tell multipath from spoofing from a
filter that has become overconfident. All three look like the same large
residual.

The distinguishing signal is not the size of the residual but its *shape over
time*, and it is the only one that is available without a second sensor:

* An isolated large residual on a channel whose recent residuals were nominal is
  a single-sample event. Multipath, a multipath-induced cycle slip, and a
  spoofed burst that the attacker chose not to sustain all look like this. There
  is no evidence of a systematic error, so the covariance must not be relaxed:
  inflating it here is exactly the "make the outlier fit" move that ADR-0003
  documents as the failure mode of a filter that has stopped being able to say
  no.

* A run of large residuals on a channel that is otherwise trusted points at the
  *filter*, not the sensor. The canonical case is re-acquisition: a 15 s denial
  walks the solution away from truth, the covariance keeps shrinking on process
  noise alone because nothing is correcting it, and when the honest fix arrives
  the filter is certain and wrong. Every innovation afterwards fails the gate,
  and a filter that only knows how to reject sits there accumulating error while
  the measurements that would rescue it pile up on the floor.

The second reading is the one that acts, and it carries the whole safety
argument. Three things have to be true before this module authorises any
relaxation, and each of them closes a hole the others leave:

* the failures must be **consecutive**, so an old burst cannot keep a channel
  eligible indefinitely (``is_persistent_divergence``);
* the channel must have actually been **silent**, so that the uncertainty it is
  being granted is bounded by how long the filter could plausibly have drifted
  (``max_drift_sigma_mps``) rather than by the size of the residual it produced;
* and the sample must be a genuine **outlier** rather than a measurement the
  gate was already happy with, which a declared fault is holding out anyway
  (``GatingDecision.outlier``).

That last one is not a detail. ``max_inflation_factor`` on its own is *not*
sufficient, and this module previously claimed it was; measurement contradicted
that. A 1 m sustained spoof does not stay a 1 m innovation -- the filter is
pulled toward it until the residual is comfortably inside the gate, at which
point a second pass that could not distinguish the two exclusions spent the
drift budget buying back a channel the first pass had correctly condemned. The
offset that defeated it was smaller than the offset that was correctly refused.
The cap still earns its place as a ceiling on any single grant, but the bound
that does the work is the silence.

This module holds the second signal: a bounded window of recent outcomes per
channel, and the decision built on top of it. It computes no statistics on the
innovation itself -- that is ``gating``'s job, and this module takes the
Mahalanobis distance as given. ADR-0006 records the reasoning and the
alternatives rejected.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

__all__ = [
    "NisConfig",
    "NisWindowMonitor",
]


@dataclass(frozen=True)
class NisConfig:
    """Tunables for the persistence monitor.

    The defaults are chosen for measurement streams arriving at 5--20 Hz on a
    platform that has just lost one of its sensors, which is the case this
    exists for.
    """

    #: How many recent outcomes to retain per channel. The window is a memory
    #: bound and a reporting aid; the *decision* below reads only the trailing
    #: run of outcomes, so this does not need to be long enough to characterise
    #: a channel's normal behaviour. It is kept at 5 so that ``mean_nis`` has
    #: enough samples to be worth printing in a trajectory summary.
    window_size: int = 5

    #: How many consecutive gate failures must appear before the divergence is
    #: called persistent and covariance inflation is permitted. At 3 this
    #: distinguishes re-acquisition from multipath: multipath arrives in
    #: single-digit metres and single samples, whereas a filter that is displaced
    #: by metres stays displaced until it is corrected, and correcting it takes
    #: at least one accepted update. Two is too few to be separable from a
    #: two-sample multipath burst; four is too slow to help, because by then the
    #: dead-reckoned error has grown further and the inflation needed is larger.
    consecutive_rejection_threshold: int = 3

    #: Hard cap on the ratio between the observed Mahalanobis distance and the
    #: gate threshold that a single adaptation is allowed to assume. This is a
    #: security control, not a tuning knob: it bounds the trust an attacker can
    #: buy. At the default of 100, and with ``reacq_pos_sigma_m`` of 3, the
    #: largest position variance any one adaptation may add is 900 m^2 (a
    #: 30 m 1-sigma) -- enough to absorb a re-acquisition offset of tens of
    #: metres, and far short of enough to make an arbitrary offset plausible.
    max_inflation_factor: float = 100.0

    #: 1-sigma per second by which a dead-reckoned position may be wrong, in
    #: m/s. This is the bound that actually makes the mechanism safe, and it
    #: replaces the intuition that a fixed factor does not.
    #:
    #: A filter that has had no accepted position fix for ``T`` seconds has
    #: drifted, and the size of the drift is a property of the platform, not of
    #: the attack. Half a metre per second is generous for a MEMS-grade IMU over
    #: the tens of seconds a re-acquisition gap lasts, and it is deliberately
    #: generous: the cost of setting it too high is that a spoofed offset inside
    #: the bound is followed, and the cost of too low is that a genuine
    #: re-acquisition is still rejected, which is the failure this whole mechanism
    #: exists to remove.
    #:
    #: Concretely, at 5 Hz a re-acquisition one second after the last good fix
    #: gets a 0.5 m 1-sigma and a spoofed 2 m offset is still rejected; after a
    #: 15 s denial it gets 7.5 m and a 3.4 m offset -- the displacement in the
    #: outage_visual case -- is admitted, while a 60 m offset is not. A constant
    #: bound cannot draw that line, because the correct limit depends on how long
    #: the filter was blind, and 30 m of slack in the first second is not a bound
    #: on anything.
    max_drift_sigma_mps: float = 0.5

    #: A re-accepted innovation must sit this far *inside* the gate, not merely
    #: under it.
    #:
    #: This is the control that makes the inflation safe in practice, and it was
    #: found by measurement rather than by reasoning. The obvious implementation
    #: -- re-gate against the inflated covariance and accept if it passes -- is
    #: unsafe at the margin, because a marginal pass is exactly the case where
    #: the Kalman gain is large: the innovation is about four sigma under the
    #: original covariance and about four sigma under the inflated one, so the
    #: filter takes a multi-metre step toward a value that was never verified.
    #: Measured on a stationary rig, that produced a 7.3 m displacement from a
    #: 6 m spoof at one setting and nothing at all at a neighbouring one, which is
    #: what a knife-edge looks like.
    #:
    #: Requiring headroom means the filter only ever acts on an innovation it is
    #: confident about, and a step taken on a confident measurement is a small
    #: step. The cost is that a genuine re-acquisition needs a slightly larger
    #: inflation before it is admitted, which costs one more rejected update and
    #: nothing else: the outage_visual displacement is 3.4 m against a 7.5 m
    #: drift envelope, so it clears even a 0.1 margin with room to spare.
    reaccept_margin: float = 0.25

    #: 1-sigma on the position uncertainty admitted when a channel is judged to
    #: be re-acquiring. 3 m is a little over the metre-level drift a 15 s
    #: dead-reckoned walk accumulates on a small platform, so one application is
    #: normally enough to make the re-acquiring measurement plausible, and
    #: normally only one is applied.
    reacq_pos_sigma_m: float = 3.0

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {self.window_size}")
        if self.consecutive_rejection_threshold < 1:
            raise ValueError(
                "consecutive_rejection_threshold must be >= 1, got "
                f"{self.consecutive_rejection_threshold}"
            )
        if self.max_inflation_factor < 1.0:
            raise ValueError(
                f"max_inflation_factor must be >= 1, got {self.max_inflation_factor}"
            )
        if not 0.0 < self.reaccept_margin <= 1.0:
            raise ValueError(
                f"reaccept_margin must lie in (0, 1], got {self.reaccept_margin}"
            )
        if self.max_drift_sigma_mps <= 0.0:
            raise ValueError(
                f"max_drift_sigma_mps must be > 0, got {self.max_drift_sigma_mps}"
            )
        if self.reacq_pos_sigma_m <= 0.0:
            raise ValueError(
                f"reacq_pos_sigma_m must be > 0, got {self.reacq_pos_sigma_m}"
            )


class NisWindowMonitor:
    """Per-channel rolling record of gate outcomes, and the divergence call.

    One monitor is shared by every channel, keyed by channel name, because the
    two visual blocks are gated separately and a channel that has been rejected
    three times running says nothing about its neighbour.
    """

    def __init__(self, cfg: NisConfig | None = None) -> None:
        self.cfg = cfg if cfg is not None else NisConfig()
        self._windows: dict[str, deque] = {}

    def _window(self, channel: str) -> deque:
        w = self._windows.get(channel)
        if w is None:
            w = deque(maxlen=self.cfg.window_size)
            self._windows[channel] = w
        return w

    def add_sample(self, channel: str, mahalanobis_sq: float, accepted: bool) -> None:
        """Record one gate outcome for ``channel``.

        ``accepted`` is the verdict the gate already reached; this monitor does
        not re-judge it. Recording the distance as well as the verdict is what
        lets :meth:`mean_nis` answer "was this channel nominal before?", which is
        the comparison that separates an isolated impulse from a channel that
        has been off for a while.
        """
        self._window(channel).append((float(mahalanobis_sq), bool(accepted)))

    def is_persistent_divergence(self, channel: str) -> bool:
        """True if the last ``K`` outcomes for ``channel`` were all rejections.

        Reads only the trailing run, so an old burst of failures cannot keep a
        channel eligible for inflation indefinitely: the moment one update is
        accepted the count restarts.
        """
        outcomes = self._windows.get(channel)
        if not outcomes:
            return False
        k = self.cfg.consecutive_rejection_threshold
        if len(outcomes) < k:
            return False
        return all(not accepted for _, accepted in list(outcomes)[-k:])

    def mean_nis(self, channel: str) -> float:
        """Mean Mahalanobis distance over the retained window, or 0.0 if empty.

        Reported rather than used in the divergence decision. Under a correct
        model this sits near the degrees of freedom, so a value far above them is
        a useful summary statistic for a trajectory and a useful thing to log
        next to a fault; a value far below them is the overconfidence signature
        that motivated this work.
        """
        outcomes = self._windows.get(channel)
        if not outcomes:
            return 0.0
        return sum(d2 for d2, _ in outcomes) / len(outcomes)

    def history(self, channel: str) -> tuple:
        """The retained ``(mahalanobis_sq, accepted)`` pairs, oldest first."""
        outcomes = self._windows.get(channel)
        return tuple(outcomes) if outcomes else ()

    def reset_channel(self, channel: str) -> None:
        """Forget ``channel``'s history, so no stale run can authorise inflation.

        Called when a channel is re-enabled or when the filter is re-initialised,
        because in both cases the geometry that produced the history is gone and
        carrying it across would let a stale divergence authorise an inflation on
        a filter that has not earned it.
        """
        self._windows.pop(channel, None)

    def reset(self) -> None:
        """Forget every channel."""
        self._windows.clear()

    def channels(self) -> tuple:
        """Channels with retained history, in insertion order."""
        return tuple(self._windows)

    def inflation_factor(self, mahalanobis_sq: float, threshold: float) -> float:
        """Ratio of the observed distance to the gate threshold, capped.

        The cap is ``max_inflation_factor`` and it is never lifted, including
        when the observed distance is not finite. A singular or ill-conditioned
        innovation covariance arrives here as ``inf``, and ``inf`` is exactly the
        case where trusting the filter's own confidence has been disproved: the
        cost of the cap being wrong is that such a channel is faulted, while the
        cost of no cap is unbounded.
        """
        if not threshold > 0.0 or not mahalanobis_sq > 0.0:
            return 1.0
        if not math.isfinite(mahalanobis_sq):
            return self.cfg.max_inflation_factor
        return min(mahalanobis_sq / threshold, self.cfg.max_inflation_factor)

    def inflation_variance(
        self,
        mahalanobis_sq: float,
        threshold: float,
        blind_s: float = 0.0,
    ) -> float:
        """Per-axis covariance to add to the inflated block, in m^2 (or rad^2).

        Two bounds apply and the tighter one wins.

        The first is ``max_inflation_factor`` on the variance named by
        ``reacq_pos_sigma_m``, a ceiling on what a single adaptation may add.

        The second, and the one that does the real work, is the drift bound: the
        1-sigma may not exceed ``max_drift_sigma_mps * blind_s``, where
        ``blind_s`` is how long the channel has gone without an accepted
        measurement. A filter that has been blind for two seconds cannot have got
        a position more than about a metre wrong, so no offset beyond that is
        explainable as drift no matter how large a variance it is offered, and the
        re-gate will keep failing. That is the difference between bounding the
        increment and bounding the total, and between bounding the slack and
        bounding the error.
        """
        factor = self.inflation_factor(mahalanobis_sq, threshold)
        variance = factor * self.cfg.reacq_pos_sigma_m**2
        drift = (self.cfg.max_drift_sigma_mps * max(blind_s, 0.0)) ** 2
        return min(variance, drift) if blind_s > 0.0 else variance
