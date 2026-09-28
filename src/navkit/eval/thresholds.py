"""Failure detection: turning an error curve into a list of events.

A metric is a number; an event is something an engineer has to act on. This
module converts the per-pose error curve plus a set of thresholds into a list
of discrete failure events with start, end, peak and duration.

Event types
-----------
``threshold_exceeded``
    The error stayed above an absolute threshold for longer than
    ``min_duration_s``. The default threshold is scenario-independent and set
    in the config; a run that produces no event is a run that stayed inside
    the declared quality envelope, which is a meaningful statement.

``divergence``
    The error grew monotonically by more than ``divergence_growth_m`` over
    ``divergence_window_s`` without recovering. Monotonic growth is what
    separates divergence from a transient excursion, and it is the failure mode
    that matters most for a navigation system.

``rejected_updates``
    The estimator's innovation gate rejected a run of consecutive
    measurements. This is a *filter-health* event rather than a pose event: it
    says the filter stopped trusting its own measurements, which precedes
    divergence rather than following it.

Thresholds are explicit configuration, never hard-coded, and every event
records the threshold that produced it so a report can be audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ThresholdSet:
    """Quality thresholds for a run, all in metres and seconds."""

    position_rmse_m: float = 0.5
    position_peak_m: float = 1.0
    sustained_error_m: float = 0.5
    min_duration_s: float = 2.0
    divergence_growth_m: float = 1.0
    divergence_window_s: float = 10.0
    drift_pct_path_length: float = 5.0

    def as_dict(self) -> dict[str, float]:
        return {
            "position_rmse_m": self.position_rmse_m,
            "position_peak_m": self.position_peak_m,
            "sustained_error_m": self.sustained_error_m,
            "min_duration_s": self.min_duration_s,
            "divergence_growth_m": self.divergence_growth_m,
            "divergence_window_s": self.divergence_window_s,
            "drift_pct_path_length": self.drift_pct_path_length,
        }

    def violations(self) -> list[str]:
        p: list[str] = []
        if self.position_peak_m < self.sustained_error_m:
            p.append("position_peak_m must be >= sustained_error_m")
        if self.sustained_error_m <= 0.0:
            p.append("sustained_error_m must be > 0")
        if self.min_duration_s <= 0.0:
            p.append("min_duration_s must be > 0")
        if self.divergence_window_s <= 0.0:
            p.append("divergence_window_s must be > 0")
        if self.drift_pct_path_length <= 0.0:
            p.append("drift_pct_path_length must be > 0")
        return p


@dataclass
class FailureEvent:
    """One detected failure, with the threshold that produced it."""

    kind: str
    start_s: float
    end_s: float
    peak_m: float
    duration_s: float
    threshold_m: float
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "peak_m": self.peak_m,
            "duration_s": self.duration_s,
            "threshold_m": self.threshold_m,
            "detail": self.detail,
        }


@dataclass
class FailureReport:
    events: list[FailureEvent] = field(default_factory=list)
    thresholds: ThresholdSet = field(default_factory=ThresholdSet)
    passed: bool = True
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "count": len(self.events),
            "events": [e.as_dict() for e in self.events],
            "thresholds": self.thresholds.as_dict(),
            "reasons": self.reasons,
        }


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs of a boolean array as ``[start, end)`` index pairs."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def detect_failures(
    t: np.ndarray,
    error_m: np.ndarray,
    thresholds: ThresholdSet,
    drift_pct_path: float | None = None,
    rejected_runs: int = 0,
) -> FailureReport:
    """Detect failure events in an error curve.

    ``t`` must be relative to the start of the sequence (the caller is
    responsible for that), so the event times are directly comparable to the
    scenario's outage windows.
    """
    t = np.asarray(t, dtype=float)
    e = np.asarray(error_m, dtype=float)
    report = FailureReport(thresholds=thresholds)
    problems = thresholds.violations()
    if problems:
        raise ValueError("invalid thresholds: " + "; ".join(problems))
    if e.size == 0 or t.size != e.size:
        report.passed = False
        report.reasons.append("empty error curve")
        return report

    dt = float(np.median(np.diff(t))) if e.size > 1 else 1.0
    need = max(1, int(round(thresholds.min_duration_s / max(dt, 1e-9))))

    # Sustained threshold exceedance.
    for a, b in _runs(e > thresholds.sustained_error_m):
        duration = float(t[b - 1] - t[a])
        if b - a >= need or duration >= thresholds.min_duration_s:
            report.events.append(
                FailureEvent(
                    kind="threshold_exceeded",
                    start_s=float(t[a]),
                    end_s=float(t[b - 1]),
                    peak_m=float(np.max(e[a:b])),
                    duration_s=duration,
                    threshold_m=thresholds.sustained_error_m,
                    detail=f"error above {thresholds.sustained_error_m:g} m for "
                    f"{duration:.2f} s",
                )
            )

    # Divergence: growth over a sliding window with no recovery.
    win = max(2, int(round(thresholds.divergence_window_s / max(dt, 1e-9))))
    for a in range(0, max(1, len(e) - win + 1)):
        seg = e[a : a + win]
        if seg.size < win:
            break
        growth = float(seg[-1] - seg[0])
        if growth < thresholds.divergence_growth_m:
            continue
        # Monotonic within tolerance: no drop larger than 10% of the growth.
        drops = np.diff(seg)
        if np.any(drops < -0.1 * growth):
            continue
        report.events.append(
            FailureEvent(
                kind="divergence",
                start_s=float(t[a]),
                end_s=float(t[a + win - 1]),
                peak_m=float(np.max(seg)),
                duration_s=float(t[a + win - 1] - t[a]),
                threshold_m=thresholds.divergence_growth_m,
                detail=f"error grew {growth:.3f} m over "
                f"{thresholds.divergence_window_s:g} s without recovering",
            )
        )
        break  # one divergence event per run is enough to flag the run

    if rejected_runs > 0:
        report.events.append(
            FailureEvent(
                kind="rejected_updates",
                start_s=float(t[0]),
                end_s=float(t[-1]),
                peak_m=float("nan"),
                duration_s=float(t[-1] - t[0]),
                threshold_m=float("nan"),
                detail=f"{rejected_runs} measurement update(s) rejected by the innovation gate",
            )
        )

    if drift_pct_path is not None and drift_pct_path > thresholds.drift_pct_path_length:
        report.events.append(
            FailureEvent(
                kind="drift_exceeded",
                start_s=float(t[0]),
                end_s=float(t[-1]),
                peak_m=float("nan"),
                duration_s=float(t[-1] - t[0]),
                threshold_m=float("nan"),
                detail=f"final drift {drift_pct_path:.2f}% of path length exceeds "
                f"{thresholds.drift_pct_path_length:g}%",
            )
        )

    rmse = float(np.sqrt(np.mean(e**2)))
    peak = float(np.max(e))
    if rmse > thresholds.position_rmse_m:
        report.reasons.append(
            f"ATE RMSE {rmse:.3f} m exceeds threshold {thresholds.position_rmse_m:g} m"
        )
    if peak > thresholds.position_peak_m:
        report.reasons.append(
            f"peak error {peak:.3f} m exceeds threshold {thresholds.position_peak_m:g} m"
        )
    if report.events:
        report.reasons.append(f"{len(report.events)} failure event(s) detected")
    report.passed = not report.reasons
    return report
