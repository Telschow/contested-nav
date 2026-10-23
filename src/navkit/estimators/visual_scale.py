"""The adaptive scale of ADR-0031: one scalar on a block of the stochastic clone's visual measurement covariance.

The filter holds two instances, one for the rotation block and one for the translation block. At each accepted visual
update the filter gives the instance ``d = y^T S0^-1 y / 3``, the normalised squared innovation of the block against
the innovation covariance ``S0`` built with the *base* covariance, so that ``E[d] = 1`` when the filter is consistent
with its declared noise. The scale is an exponentially weighted mean of ``d``:

    s  <-  s + w (d - s),        w = 1 - exp(-dt / tau)

where ``dt`` is the time since the previous accepted update. It starts at 1 and is clipped to ``[s_min, s_max]`` after
every update, so there is no hidden state that could wind up beyond the bounds.

**What the scale is.** It is a catch-all for model error in the visual channel, which includes visual errors
correlated over time and the conservatism of the clone. It is not an estimate of the sensor's noise. ``d`` uses
``S0 = H P H^T + R0``, which includes the state uncertainty, so ``E[d]`` is below the true ratio of variances when
``P`` is not small, and the scale does not converge to that ratio.

**Conventions.**

* The first accepted update only records its time: ``dt`` is undefined there, so the weight is zero. It is counted in
  :attr:`n_used`.
* A rejected update changes nothing, not even the recorded time, so ``dt`` is measured between accepted updates.
* With no update the scale is held. There is no clock in this class.
* A non-finite ``d`` raises ``ValueError``, accepted or not. Time going backwards raises ``ValueError``.
* :attr:`mean`, :attr:`min_seen` and :attr:`max_seen` are over the value of the scale after each accepted update,
  and are the current value (1 at the start) when nothing was accepted.

No I/O and no filter state: the class is a function of the ``(d, t, accepted)`` stream.
"""

from __future__ import annotations

import math


class VisualScale:
    """One adaptive scale: an exponentially weighted mean of ``d``, bounded, with running statistics."""

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

    @property
    def value(self) -> float:
        """The current scale, in ``[s_min, s_max]``."""
        return self._s

    @property
    def n_used(self) -> int:
        """How many accepted updates the scale has seen, the first one included."""
        return self._n

    @property
    def mean(self) -> float:
        return self._sum / self._n if self._n else self._s

    @property
    def min_seen(self) -> float:
        return self._min if self._n else self._s

    @property
    def max_seen(self) -> float:
        return self._max if self._n else self._s

    def update(self, d: float, t_s: float, accepted: bool) -> None:
        """Take one visual update. A rejected update changes nothing."""
        if not math.isfinite(d):
            raise ValueError(f"d must be finite, got {d!r}")
        if not accepted:
            return
        if self._t_prev is not None:
            dt = t_s - self._t_prev
            if dt < 0.0:
                raise ValueError(f"time must not go backwards: {t_s!r} after {self._t_prev!r}")
            w = 1.0 - math.exp(-dt / self._tau)
            self._s = min(max(self._s + w * (d - self._s), self._lo), self._hi)
        self._t_prev = float(t_s)
        self._n += 1
        self._sum += self._s
        self._min = self._s if self._n == 1 else min(self._min, self._s)
        self._max = self._s if self._n == 1 else max(self._max, self._s)
