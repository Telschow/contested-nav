"""The adaptive scale of ADR-0031 and ADR-0032: one scalar on a block of the stochastic clone's visual measurement
covariance.

The filter holds two instances, one for the rotation block and one for the translation block. At each visual update
the filter gives the instance ``d = y^T S0^-1 y / 3``, the normalised squared innovation of the block against the
innovation covariance ``S0`` built with the *base* covariance, so that ``E[d] = 1`` when the filter is consistent with
its declared noise. The scale is an exponentially weighted mean of ``d``:

    s  <-  s + w (min(d, s_max) - s),        w = 1 - exp(-dt / tau)

where ``dt`` is the time since the previous update. It starts at 1 and is clipped to ``[s_min, s_max]`` after every
update, so there is no hidden state that could wind up beyond the bounds.

**Every update counts (ADR-0032).** ADR-0031 let only updates that the chi-square gate accepted enter the mean. With
that rule, a channel whose errors the gate rejects could never raise its own scale, because its rejected updates did
not reach the mean. Now every visual update contributes, accepted or not, and each ``d`` is capped at ``s_max`` before
it enters the mean so that one outlier cannot move the scale far. A ``d`` below ``s_min`` is not floored; only the
stored state is clipped. The gate keeps using the scaled covariance. The cost is that a visual fault also moves the
scale, towards ``s_max`` at the rate ``tau`` allows, and widens the gate for the updates that follow.

**What the scale is.** It is a catch-all for model error in the visual channel, which includes visual errors
correlated over time and the conservatism of the clone. It is not an estimate of the sensor's noise. ``d`` uses
``S0 = H P H^T + R0``, which includes the state uncertainty, so ``E[d]`` is below the true ratio of variances when
``P`` is not small, and the scale does not converge to that ratio.

**Conventions.**

* The first update only records its time: ``dt`` is undefined there, so the weight is zero.
* With no update the scale is held. There is no clock in this class.
* A non-finite ``d`` passed to :meth:`update` raises ``ValueError``. Time going backwards raises ``ValueError``.
* An update whose innovation covariance is not usable gives a non-finite ``d`` in the filter. The filter does not pass
  it on: it calls :meth:`skip_nonfinite`, the scale holds, the time is not recorded, and :attr:`n_skipped_nonfinite`
  counts it. A run never raises for it.
* :attr:`n_used` counts the updates that moved or recorded the scale. :attr:`n_rejected_used` counts those among them
  that the gate rejected; the filter calls :meth:`mark_rejected_used`, because the gate's decision is not an input
  of the scale and this class does not see it. The counts show how much of the adaptation came from rejected updates.
* :attr:`mean`, :attr:`min_seen` and :attr:`max_seen` are over the value of the scale after each update, and are the
  current value (1 at the start) when nothing was seen.

No I/O and no filter state: the class is a function of the ``(d, t)`` stream.
"""

from __future__ import annotations

import math


class VisualScale:
    """One adaptive scale: an exponentially weighted mean of ``d``, capped and bounded, with running statistics."""

    def __init__(self, tau_s: float, s_min: float, s_max: float) -> None:
        if not (math.isfinite(tau_s) and tau_s > 0.0):
            raise ValueError(f"tau_s must be finite and positive, got {tau_s!r}")
        if not (math.isfinite(s_min) and math.isfinite(s_max) and 0.0 < s_min <= 1.0 <= s_max):
            raise ValueError(f"the bounds must satisfy 0 < s_min <= 1 <= s_max and be finite, got {s_min!r}, {s_max!r}")
        self._tau = float(tau_s)
        self._lo = float(s_min)
        self._hi = float(s_max)
        self._s = 1.0
        self._t_prev: float | None = None
        self._n = 0
        self._sum = 0.0
        self._min = 1.0
        self._max = 1.0
        self._n_rejected_used = 0
        self._n_skipped = 0

    @property
    def value(self) -> float:
        """The current scale, in ``[s_min, s_max]``."""
        return self._s

    @property
    def n_used(self) -> int:
        """How many updates the scale has seen, the first one included."""
        return self._n

    @property
    def n_rejected_used(self) -> int:
        """How many of those updates the gate had rejected, as reported by :meth:`mark_rejected_used`."""
        return self._n_rejected_used

    @property
    def n_skipped_nonfinite(self) -> int:
        """How many updates were skipped because their statistic was not finite."""
        return self._n_skipped

    @property
    def mean(self) -> float:
        return self._sum / self._n if self._n else self._s

    @property
    def min_seen(self) -> float:
        return self._min if self._n else self._s

    @property
    def max_seen(self) -> float:
        return self._max if self._n else self._s

    def update(self, d: float, t_s: float) -> None:
        """Take one visual update, accepted by the gate or not."""
        if not math.isfinite(d):
            raise ValueError(f"d must be finite, got {d!r}")
        if self._t_prev is not None:
            dt = t_s - self._t_prev
            if dt < 0.0:
                raise ValueError(f"time must not go backwards: {t_s!r} after {self._t_prev!r}")
            w = 1.0 - math.exp(-dt / self._tau)
            self._s = min(max(self._s + w * (min(d, self._hi) - self._s), self._lo), self._hi)
        self._t_prev = float(t_s)
        self._n += 1
        self._sum += self._s
        self._min = self._s if self._n == 1 else min(self._min, self._s)
        self._max = self._s if self._n == 1 else max(self._max, self._s)

    def mark_rejected_used(self) -> None:
        """Count that the update just given to :meth:`update` was one the gate had rejected."""
        self._n_rejected_used += 1

    def skip_nonfinite(self) -> None:
        """Count an update whose statistic was not finite. The scale and the recorded time are untouched."""
        self._n_skipped += 1
