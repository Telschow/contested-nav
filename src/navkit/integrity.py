"""The integrity status record of ADR-0035: one small, stable record per epoch for downstream decision logic.

The record says whether the claimed uncertainty may be believed under the checks the filter itself can make and the
calibration gates that exist. It says nothing about accuracy. The NIS state in particular says only that innovations are
not being persistently rejected: a filter that is confidently wrong can report ``ok``. That is why the usable rule has a
second part, the calibration gate of each aiding source, that does not depend on the filter at all.

No threshold is added here. The NIS state uses the persistent-divergence rule of
:class:`navkit.fdir.nis_monitor.NisWindowMonitor` (ADR-0006).
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .fdir.nis_monitor import NisWindowMonitor

#: A change of fields, of their meaning or of the usable rule is a new version and a new ADR.
SCHEMA_VERSION = 1

NIS_OK = "ok"
NIS_DIVERGING = "diverging"
NIS_UNKNOWN = "unknown"

REASON_OK = "ok"
REASON_SIGMA_NOT_FINITE = "sigma_not_finite"
REASON_NIS_DIVERGING = "nis_diverging"
REASON_AIDING_NOT_CALIBRATED = "aiding_not_calibrated"

#: Aiding sources that passed a calibration gate by a maintainer decision (ADR-0028, ADR-0030). GNSS is the reference
#: the filter is calibrated against and is not gated. Vision is absent: B1 is closed as characterised, not solved
#: (ADR-0036), so with vision on this record is never usable.
PASSED_CALIBRATION_GATES: frozenset[str] = frozenset()
UNGATED_AIDING = frozenset({"gnss"})

CSV_COLUMNS = (
    "schema_version",
    "t",
    "east",
    "north",
    "up",
    "sigma_h",
    "sigma_v",
    "nis_state",
    "monitored",
    "seconds_since_absolute_fix",
    "aiding",
    "usable",
    "reason",
)


@dataclass(frozen=True)
class IntegrityStatus:
    t: float
    position: tuple[float, float, float]
    #: Square root of the mean of the two horizontal claimed variances.
    sigma_h: float
    sigma_v: float
    nis_state: str
    #: True when at least one channel has history in its NIS window at this epoch.
    monitored: bool
    #: Time since the last accepted GNSS fix, or since the start when there has been none.
    seconds_since_absolute_fix: float
    #: The enabled aiding sources, drawn from gnss and vision, sorted.
    aiding: tuple[str, ...]
    usable: bool
    reason: str
    schema_version: int = SCHEMA_VERSION


def nis_state(monitor: NisWindowMonitor) -> tuple[str, bool]:
    """``(state, monitored)``: diverging if any channel is in persistent divergence, ok if at least one channel has
    history and none is, unknown if no channel has history."""
    with_history = [c for c in monitor.channels() if monitor.history(c)]
    if any(monitor.is_persistent_divergence(c) for c in with_history):
        return NIS_DIVERGING, True
    if with_history:
        return NIS_OK, True
    return NIS_UNKNOWN, False


def usable_rule(
    sigma_h: float,
    sigma_v: float,
    state: str,
    aiding: Iterable[str],
    passed_gates: frozenset[str] = PASSED_CALIBRATION_GATES,
) -> tuple[bool, str]:
    """The three conditions of ADR-0035, tested in order. The reason is the first that fails, or ``ok``."""
    if not (math.isfinite(sigma_h) and math.isfinite(sigma_v)):
        return False, REASON_SIGMA_NOT_FINITE
    if state == NIS_DIVERGING:
        return False, REASON_NIS_DIVERGING
    if any(a not in UNGATED_AIDING and a not in passed_gates for a in aiding):
        return False, REASON_AIDING_NOT_CALIBRATED
    return True, REASON_OK


def make_status(
    t: float,
    position: Iterable[float],
    sigma_h: float,
    sigma_v: float,
    monitor: NisWindowMonitor,
    seconds_since_absolute_fix: float,
    aiding: Iterable[str],
) -> IntegrityStatus:
    state, monitored = nis_state(monitor)
    sources = tuple(sorted(aiding))
    usable, reason = usable_rule(sigma_h, sigma_v, state, sources)
    x, y, z = (float(v) for v in position)
    return IntegrityStatus(
        t=float(t),
        position=(x, y, z),
        sigma_h=float(sigma_h),
        sigma_v=float(sigma_v),
        nis_state=state,
        monitored=monitored,
        seconds_since_absolute_fix=float(seconds_since_absolute_fix),
        aiding=sources,
        usable=usable,
        reason=reason,
    )


def write_csv(path: str | Path, records: Iterable[IntegrityStatus]) -> None:
    """One row per epoch, in time order, with the schema version on every row."""
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for r in records:
            w.writerow(
                [
                    r.schema_version,
                    f"{r.t:.6f}",
                    *(f"{v:.6f}" for v in r.position),
                    f"{r.sigma_h:.6g}",
                    f"{r.sigma_v:.6g}",
                    r.nis_state,
                    int(r.monitored),
                    f"{r.seconds_since_absolute_fix:.6f}",
                    "+".join(r.aiding),
                    int(r.usable),
                    r.reason,
                ]
            )
