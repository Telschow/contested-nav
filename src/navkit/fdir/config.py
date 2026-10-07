"""Configuration of the FDIR layer.

Every threshold the gate, the NIS monitor and the isolation state machine read is a
field of :class:`FdirConfig`, so a run's behaviour is fixed by one serialisable
object. The values are choices, not results; the evidence behind each default is in
ADR-0005, ADR-0006 and ADR-0007.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gating import DEFAULT_CONFIDENCE
from .nis_monitor import NisConfig

__all__ = ["FdirConfig"]


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
    #: Consecutive updates needing an inflation grant before the channel is
    #: treated as spoofed rather than displaced, per ADR-0007.
    #:
    #: One grant is a filter that has been walked off position and is being
    #: walked back. A *second* grant is something else: the first grant moved the
    #: state part-way toward the offset, and if the same offset then needs
    #: inflating again, either the first grant was too small (the channel is
    #: genuinely drifting and the filter cannot keep up) or the channel was
    #: never truthful and the grant is compounding an attack. The filter cannot
    #: tell those apart from a single channel, so it takes the safe branch.
    #:
    #: Two rather than three, because the benchmark's own cases grant exactly
    #: once on a spoof, which means the discriminator has to fire on the
    #: *second* need, not on the first. A threshold of one would escalate every
    #: genuine post-outage re-acquisition and lock out a working receiver.
    spoof_grant_threshold: int = 2
    #: Seconds a channel stays locked out as spoofed before it may be evaluated
    #: again, per ADR-0007.
    #:
    #: This is not a retry timer. A 60 s lockout on a 5 Hz channel discards ~300
    #: fixes, and a GNSS receiver that is genuinely denied for that long has lost
    #: the outage anyway, so the cost of being wrong in this direction is bounded
    #: by the denial the system is trying to survive. A shorter lockout would
    #: spend the same attacker step over and over.
    spoof_lockout_s: float = 60.0
    #: Extra covariance, in units of the granted 1-sigma, forced onto the block
    #: when a channel is locked out, per ADR-0007 option 2.
    #:
    #: Re-expansion is what makes the lockout recoverable. Without it the filter
    #: would coast on a covariance that no longer reflects a displaced mean, and
    #: would re-acquire into the same error the moment the lockout expired.
    spoof_reexpansion_factor: float = 2.0

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError(f"confidence_level must lie strictly inside (0, 1), got {self.confidence_level}")
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
        if self.spoof_grant_threshold < 1:
            raise ValueError("spoof_grant_threshold must be at least 1")
        if self.spoof_lockout_s <= 0.0:
            raise ValueError("spoof_lockout_s must be positive")
        if self.spoof_reexpansion_factor < 1.0:
            raise ValueError("spoof_reexpansion_factor must be at least 1")

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
            "spoof_grant_threshold": self.spoof_grant_threshold,
            "spoof_lockout_s": self.spoof_lockout_s,
            "spoof_reexpansion_factor": self.spoof_reexpansion_factor,
        }
