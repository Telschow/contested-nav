"""A multipath signature on a window of GNSS innovations.

Multipath puts noise on the fixes. Over a window of innovations that shows as an inflated normalised innovation
squared (NIS) with little correlation from one fix to the next. A persistent offset (a step or a ramp, a spoof) also
inflates the NIS, but its innovations are strongly autocorrelated. The signature is both together: a large NIS and a
low lag-1 autocorrelation.

The two thresholds are round numbers, set from the training runs of the fault-classification study and evaluated on
runs the study never used (``docs/multipath.md``). NIS is about 1 for a healthy channel, so 2 is twice the healthy
value. This is a function on a window of innovations. It is not wired into the filter, and it does not change what
the FDIR layer does (ADR-0022).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

#: Two rules, fixed before the evaluation on fresh runs. ``sensitive``: a window whose mean NIS is at least 2 (a healthy
#: channel is about 1). ``specific``: at least 6, the value the fault-classification tree learned on its training runs.
#: The first catches smaller multipath and also calls a small step. The second does neither.
NIS_MIN = 2.0
NIS_MIN_SPECIFIC = 6.0
RULES = ("sensitive", "specific")
#: A window whose lag-1 autocorrelation of the whitened innovation is above this is a persistent offset, not noise.
AC1_MAX = 0.8
#: Fewer innovations than this and no call is made.
MIN_FIXES = 20


@dataclass(frozen=True)
class Signature:
    """The two statistics of a window, and the call."""

    nis: float
    ac1: float
    n: int
    sensitive: bool
    specific: bool

    @property
    def multipath(self) -> bool:
        """The call under the specific rule, which is the default."""
        return self.specific


def signature(innovations: Sequence[tuple[float, np.ndarray, np.ndarray]]) -> Signature | None:
    """The multipath signature of ``(t, residual, S)`` innovations, or None if the window is too short.

    ``nis`` is the mean of ``r' S^-1 r`` over three degrees of freedom. ``ac1`` is the uncentred lag-1 autocorrelation
    of the whitened innovation ``L^-1 r`` with ``S = L L'``, so that a constant offset gives 1 and white noise gives 0.
    """
    if len(innovations) < MIN_FIXES:
        return None
    d2 = np.array([float(i[1] @ np.linalg.solve(i[2], i[1])) for i in innovations])
    z = np.stack([np.linalg.solve(np.linalg.cholesky(i[2]), i[1]) for i in innovations])
    nis = float(d2.mean() / 3.0)
    ac1 = float((z[:-1] * z[1:]).sum() / max(float((z * z).sum()), 1e-12))
    return Signature(
        nis=nis,
        ac1=ac1,
        n=len(innovations),
        sensitive=call(nis, ac1, "sensitive"),
        specific=call(nis, ac1, "specific"),
    )


def call(nis: float, ac1: float, rule: str = "specific") -> bool:
    """The call of one rule on the two statistics of a window."""
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}, got {rule!r}")
    floor = NIS_MIN if rule == "sensitive" else NIS_MIN_SPECIFIC
    return bool(nis >= floor and ac1 <= AC1_MAX)


def is_multipath(innovations: Sequence[tuple[float, np.ndarray, np.ndarray]], rule: str = "specific") -> bool:
    """True when the window looks like multipath; False when it does not or when it is too short to say."""
    sig = signature(innovations)
    return bool(sig and call(sig.nis, sig.ac1, rule))
