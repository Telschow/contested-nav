"""Failure analysis with typed claims.

The point of this module is that a report must never let an interpretation read
as a measurement. Every statement carries one of four types, and the type is
enforced in the data model, not by convention:

``FACT``
    Directly readable from the configuration or the run log: a duration, a
    rate, a count. Verifiable by reading the config, with no reference to the
    result. "GNSS was unavailable from 30.0 s to 75.0 s" is a fact.

``MEASUREMENT``
    A number produced by the evaluation, together with the estimator, the
    alignment and the sample count needed to reproduce it. "ATE RMSE was
    0.31 m, rigid-aligned, over 2818 poses" is a measurement.

``INTERPRETATION``
    A proposed mechanism. It is a claim about *why*, and it is the class most
    likely to be wrong. Every interpretation must reference the measurements it
    rests on and must carry an explicit ``confidence`` and a
    ``falsification_test``: the experiment that would refute it. An
    interpretation without a falsification test is an opinion.

``HYPOTHESIS``
    A proposed future experiment, not a claim about the present run. "Reducing
    the GNSS outage to 10 s should halve the peak drift" is a hypothesis, and
    it may be wrong.

The generator below turns a scenario plus its metrics into this structure. The
mechanism descriptions come from a small library keyed by scenario name; they
are written as candidate explanations, not conclusions, and the library is
data, so a reader can disagree with a specific entry without changing the code.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ClaimType(StrEnum):
    FACT = "FACT"
    MEASUREMENT = "MEASUREMENT"
    INTERPRETATION = "INTERPRETATION"
    HYPOTHESIS = "HYPOTHESIS"

    @property
    def is_fact(self) -> bool:
        return self is ClaimType.FACT


@dataclass
class Claim:
    """One typed statement about a run."""

    type: ClaimType
    text: str
    # MEASUREMENT
    value: float | None = None
    unit: str = ""
    n_samples: int | None = None
    # INTERPRETATION
    confidence: str = ""
    falsification_test: str = ""
    # cross-references
    supports: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type is ClaimType.INTERPRETATION:
            if not self.falsification_test:
                raise ValueError(
                    "an INTERPRETATION must carry a falsification_test; "
                    "an explanation with nothing that could refute it is an opinion"
                )
            if self.confidence not in ("low", "medium", "high"):
                raise ValueError(f"INTERPRETATION needs a confidence of low/medium/high, got {self.confidence!r}")
        if self.type is ClaimType.MEASUREMENT and self.value is None:
            raise ValueError("a MEASUREMENT must carry a numeric value")
        if self.type is ClaimType.FACT and self.n_samples is not None:
            raise ValueError("a FACT must not carry n_samples; that is a MEASUREMENT field")

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value, "text": self.text}
        if self.value is not None:
            d["value"] = self.value
        if self.unit:
            d["unit"] = self.unit
        if self.n_samples is not None:
            d["n_samples"] = self.n_samples
        if self.confidence:
            d["confidence"] = self.confidence
        if self.falsification_test:
            d["falsification_test"] = self.falsification_test
        if self.supports:
            d["supports"] = self.supports
        if self.tags:
            d["tags"] = self.tags
        return d


@dataclass
class Analysis:
    """The full analysis for one scenario."""

    scenario: str
    description: str = ""
    claims: list[Claim] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def of_type(self, t: ClaimType) -> list[Claim]:
        return [c for c in self.claims if c.type is t]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "description": self.description,
            "facts": [c.as_dict() for c in self.of_type(ClaimType.FACT)],
            "measurements": [c.as_dict() for c in self.of_type(ClaimType.MEASUREMENT)],
            "interpretations": [c.as_dict() for c in self.of_type(ClaimType.INTERPRETATION)],
            "hypotheses": [c.as_dict() for c in self.of_type(ClaimType.HYPOTHESIS)],
            "limitations": self.limitations,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def to_markdown(self) -> str:
        return render_markdown(self)


# --------------------------------------------------------------- library ---

#: Candidate mechanisms, keyed by scenario name. Each entry is
#: ``(text, confidence, falsification_test)``. They are deliberately written as
#: candidate explanations of a mechanism, not as conclusions: a run that does
#: not support one should say so, and the falsification test is how you check.
MECHANISM_LIBRARY: dict[str, list[tuple[str, str, str]]] = {
    "gnss_denied": [
        (
            "Removing GNSS position fixes leaves inertial propagation as the only "
            "source of absolute position, so error accumulates from accelerometer "
            "bias and unmodelled dynamics rather than from any single bad measurement.",
            "high",
            "Run the same outage with a known zero initial bias. If peak drift is "
            "unchanged, accelerometer bias is not the dominant contributor and the "
            "explanation above is wrong.",
        ),
        (
            "Error growth during the outage should be close to linear in time if the "
            "dominant error source is a constant bias, and super-linear if it is a "
            "rate error or an unmodelled rotation.",
            "medium",
            "Plot error against time over outages of 5, 15, 45 and 90 s. Linear "
            "growth supports a bias-dominated explanation; convex growth refutes it.",
        ),
    ],
    "camera_drop": [
        (
            "Correlated frame loss lengthens the interval between relative-pose "
            "constraints, so the filter integrates unconstrained for longer between "
            "visual updates. Drift per metre travelled rises with the longest gap, not "
            "with the average frame rate.",
            "medium",
            "Hold the mean usable frame rate fixed while varying only the burst length. "
            "If drift tracks the longest gap, the explanation holds; if it tracks the "
            "mean rate, it does not.",
        ),
    ],
    "imu_noise": [
        (
            "Raising IMU noise density inflates both the process noise and the gain of "
            "every update, so the filter should trust its measurements more and its own "
            "propagation less. That is a trade, not a pure degradation, and the error "
            "may rise in smooth motion and fall during high-dynamic segments.",
            "medium",
            "Compare noise levels during a constant-velocity segment and during a "
            "high-angular-rate segment. A pure degradation degrades both; a "
            "trust trade-off does not.",
        ),
    ],
    "timestamp_offset": [
        (
            "A constant time offset between the visual and inertial streams means each "
            "relative-pose constraint is fused against a state that has already been "
            "propagated by the wrong amount of inertial motion. The resulting error is "
            "proportional to the platform speed times the offset, not to the offset "
            "itself.",
            "medium",
            "Sweep the offset at a fixed platform speed and at a different speed. If "
            "the error scales with speed times offset, the explanation holds; if it is "
            "independent of speed, the cause is elsewhere (for example extrinsic "
            "calibration).",
        ),
    ],
    "image_degradation": [
        (
            "Image degradation is modelled here only as an inflation of the "
            "relative-pose noise, not as a rendering-based blur model. Under that model "
            "the effect should be a smooth, monotone increase in error with the noise "
            "multiplier, with no new failure mode appearing.",
            "high",
            "Compare against real motion-blurred frames: if real blur produces a sharp "
            "threshold at which the front end stops producing constraints at all, the "
            "noise-inflation surrogate is inadequate and this explanation is wrong.",
        ),
    ],
    "sensor_outage": [
        (
            "A total inertial outage freezes the state. On re-entry the filter's "
            "covariance has not grown during the blind interval, so the first updates "
            "are over-trusted and the recovery is slower and more oscillatory than the "
            "filter's own uncertainty suggests.",
            "medium",
            "Compare against a run where the covariance is forced to grow during the "
            "blind interval. If recovery becomes well behaved, the explanation holds.",
        ),
    ],
}

GENERIC_LIMITATIONS = [
    "Inertial data is derived by differentiating a 120 Hz ground-truth pose stream. "
    "It is kinematically consistent but carries none of the real IMU effects: bias, "
    "scale-factor error, temperature dependence, digitisation, or accelerometer "
    "bandwidth. Injected noise is a model, not a measurement of this dataset's IMU.",
    "GNSS and visual measurements are synthesised from the same ground truth that "
    "the metrics are computed against. That makes the comparison a closed-loop test "
    "of the fusion and replay logic; it is not an independent measurement of real "
    "GNSS or visual error, which include multipath, outages, poor geometry, "
    "correlated biases and outright outliers.",
    "The estimator has no camera front end. Relative-pose constraints come from a "
    "generator that reads the ground truth, so frame-drop and image-degradation "
    "scenarios probe how a filter reacts to degraded constraints, not how a real "
    "front end behaves when it loses track.",
]


def _fmt(x: float | None, unit: str = "") -> str:
    if x is None:
        return "n/a"
    return f"{x:.4g}{(' ' + unit) if unit else ''}"


def build_analysis(
    scenario: str,
    description: str,
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    delta_vs_baseline: dict[str, Any] | None = None,
    extra_limitations: Sequence[str] = (),
) -> Analysis:
    """Assemble a typed analysis from a manifest and a metrics block.

    ``delta_vs_baseline`` carries the metric change relative to the ``normal``
    run, which is what makes a scenario comparable rather than merely bad.
    """
    a = Analysis(scenario=scenario, description=description)

    gnss = manifest.get("gnss", {})
    vis = manifest.get("vision", {})
    imu = manifest.get("imu", {})

    if not gnss.get("enabled", True):
        a.claims.append(
            Claim(
                type=ClaimType.FACT,
                text="GNSS is disabled for the whole run; no position fixes reach the estimator.",
                tags=["gnss"],
            )
        )
    else:
        intervals = gnss.get("unavailable_intervals_s") or []
        if intervals:
            spans = ", ".join(f"{s:.1f}-{e:.1f} s" for s, e in intervals)
            total = sum(float(e) - float(s) for s, e in intervals)
            a.claims.append(
                Claim(
                    type=ClaimType.FACT,
                    text=f"GNSS was unavailable for {total:.1f} s in {len(intervals)} interval(s): {spans}.",
                    tags=["gnss", "outage"],
                )
            )
        a.claims.append(
            Claim(
                type=ClaimType.FACT,
                text=f"GNSS was usable for {gnss.get('usable_fixes', 0)} of "
                f"{gnss.get('emitted_fixes', 0)} fixes "
                f"(configured {gnss.get('configured_rate_hz', float('nan')):g} Hz, "
                f"sigma {gnss.get('position_sigma_m', float('nan')):g} m).",
                tags=["gnss"],
            )
        )

    if vis.get("dropped_frames", 0) > 0:
        a.claims.append(
            Claim(
                type=ClaimType.FACT,
                text=f"{vis['dropped_frames']} of {vis['emitted_frames']} visual frames were "
                f"dropped ({vis.get('drop_fraction_measured', 0.0) * 100:.1f}%); the longest gap "
                f"between usable frames was {vis.get('longest_gap_s', 0.0):.3f} s.",
                tags=["vision", "frame_drop"],
            )
        )
    if abs(vis.get("time_offset_s", 0.0)) > 0.0:
        a.claims.append(
            Claim(
                type=ClaimType.FACT,
                text=f"Visual timestamps were shifted by {vis['time_offset_s'] * 1000:+.1f} ms "
                "relative to the inertial stream.",
                tags=["vision", "timing"],
            )
        )
    if abs(imu.get("time_offset_s", 0.0)) > 0.0:
        a.claims.append(
            Claim(
                type=ClaimType.FACT,
                text=f"Inertial timestamps were shifted by {imu['time_offset_s'] * 1000:+.1f} ms.",
                tags=["imu", "timing"],
            )
        )
    a.claims.append(
        Claim(
            type=ClaimType.FACT,
            text=f"Inertial stream: {imu.get('samples', 0)} samples at "
            f"{imu.get('rate_hz', 0.0):.1f} Hz, noise scale {imu.get('noise_scale', 1.0):g}.",
            tags=["imu"],
        )
    )

    ate = metrics.get("ate", {}).get("rigid_start", {})
    pos = ate.get("position_m", {})
    n = pos.get("count")
    a.claims.append(
        Claim(
            type=ClaimType.MEASUREMENT,
            text="Absolute trajectory error, rigid alignment fitted on the first 20% of the sequence (rigid_start).",
            value=float(pos.get("rmse", float("nan"))),
            unit="m",
            n_samples=n,
            tags=["ate"],
        )
    )
    a.claims.append(
        Claim(
            type=ClaimType.MEASUREMENT,
            text="Peak absolute trajectory error over the same alignment.",
            value=float(pos.get("max", float("nan"))),
            unit="m",
            n_samples=n,
            tags=["ate"],
        )
    )
    rpe = metrics.get("rpe", {}).get("1s", {})
    if rpe:
        a.claims.append(
            Claim(
                type=ClaimType.MEASUREMENT,
                text="Relative pose error over a 1 s baseline, translational part.",
                value=float(rpe.get("translation_m", {}).get("rmse", float("nan"))),
                unit="m",
                n_samples=rpe.get("translation_m", {}).get("count"),
                tags=["rpe"],
            )
        )
    dr = metrics.get("drift", {})
    if "final_drift_pct_path_length" in dr:
        a.claims.append(
            Claim(
                type=ClaimType.MEASUREMENT,
                text="Final drift as a percentage of travelled path length.",
                value=float(dr["final_drift_pct_path_length"]),
                unit="%",
                tags=["drift"],
            )
        )
    if dr.get("growth", {}).get("slope_m_per_s") is not None:
        a.claims.append(
            Claim(
                type=ClaimType.MEASUREMENT,
                text="Least-squares slope of position error against time over the second half "
                f"of the run (window {dr['growth']['window_s'][0]:.0f}-"
                f"{dr['growth']['window_s'][1]:.0f} s, R^2={dr['growth']['r_squared']:.3f}).",
                value=float(dr["growth"]["slope_m_per_s"]),
                unit="m/s",
                tags=["drift"],
            )
        )
    fr = metrics.get("failures", {})
    a.claims.append(
        Claim(
            type=ClaimType.MEASUREMENT,
            text=f"{fr.get('count', 0)} failure event(s) were detected against the configured "
            f"thresholds; the run {'passed' if fr.get('passed', True) else 'did not pass'}.",
            value=float(fr.get("count", 0)),
            unit="events",
            tags=["failures"],
        )
    )
    for ev in fr.get("events", []):
        a.claims.append(
            Claim(
                type=ClaimType.MEASUREMENT,
                text=f"{ev['kind']} from {ev['start_s']:.1f} s to {ev['end_s']:.1f} s: {ev['detail']}.",
                value=float(ev.get("peak_m", float("nan"))),
                unit="m",
                tags=["failures", ev["kind"]],
            )
        )

    if delta_vs_baseline:
        base = float(delta_vs_baseline.get("baseline_ate_rmse_m", float("nan")))
        cur = float(delta_vs_baseline.get("ate_rmse_m", float("nan")))
        ratio = (cur / base) if base not in (0.0,) and base == base else float("nan")
        direction = "higher" if cur > base else "lower"
        a.claims.append(
            Claim(
                type=ClaimType.MEASUREMENT,
                text=f"ATE RMSE changed from {base:.4g} m in the normal scenario to {cur:.4g} m, "
                f"a factor of {ratio:.3g} ({direction}). Same estimator, same sequence, same seed.",
                value=cur - base,
                unit="m (delta)",
                tags=["comparison"],
            )
        )
        bslope = delta_vs_baseline.get("baseline_drift_slope_m_per_s")
        cslope = delta_vs_baseline.get("drift_slope_m_per_s")
        if bslope is not None and cslope is not None:
            a.claims.append(
                Claim(
                    type=ClaimType.MEASUREMENT,
                    text=f"Steady-state drift slope changed from {float(bslope):.4g} m/s to {float(cslope):.4g} m/s.",
                    value=float(cslope) - float(bslope),
                    unit="m/s (delta)",
                    tags=["comparison", "drift"],
                )
            )

    for text, confidence, falsify in MECHANISM_LIBRARY.get(scenario, []):
        a.claims.append(
            Claim(
                type=ClaimType.INTERPRETATION,
                text=text,
                confidence=confidence,
                falsification_test=falsify,
                tags=["mechanism"],
            )
        )

    a.claims.extend(_hypotheses_for(scenario, delta_vs_baseline))
    a.limitations = list(GENERIC_LIMITATIONS) + list(extra_limitations)
    return a


def _hypotheses_for(scenario: str, delta: dict[str, Any] | None) -> list[Claim]:
    out: list[Claim] = []
    if scenario == "gnss_denied":
        out.append(
            Claim(
                type=ClaimType.HYPOTHESIS,
                text="Halving the outage duration should roughly halve the peak drift. If it "
                "does not, the error is dominated by something other than accumulated "
                "inertial error during the outage -- for example a single bad fix at "
                "re-acquisition.",
                tags=["experiment"],
            )
        )
        out.append(
            Claim(
                type=ClaimType.HYPOTHESIS,
                text="Raising the GNSS rate during the healthy segments should shorten "
                "time-to-recovery after the outage without changing the drift during the "
                "outage itself.",
                tags=["experiment"],
            )
        )
    elif scenario == "timestamp_offset":
        out.append(
            Claim(
                type=ClaimType.HYPOTHESIS,
                text="Sweeping the offset from -100 ms to +100 ms at two different platform "
                "speeds should show peak error proportional to speed times offset. A flat "
                "curve would point at extrinsic calibration instead.",
                tags=["experiment"],
            )
        )
    elif scenario == "camera_drop":
        out.append(
            Claim(
                type=ClaimType.HYPOTHESIS,
                text="Comparing burst-shaped drops against uniformly distributed drops at the "
                "same mean frame rate should show worse drift for the burst shape. If the two "
                "match, the longest gap is not the controlling variable.",
                tags=["experiment"],
            )
        )
    else:
        out.append(
            Claim(
                type=ClaimType.HYPOTHESIS,
                text="Swapping the baseline estimator (dead reckoning against the error-state "
                "filter) under the same scenario should show whether the observed degradation "
                "is a property of the sensing or of the filter.",
                tags=["experiment"],
            )
        )
    del delta
    return out


def render_markdown(a: Analysis) -> str:
    """Render the analysis as a Markdown section."""
    lines: list[str] = [f"## Failure analysis: `{a.scenario}`", ""]
    if a.description:
        lines += [a.description, ""]

    def block(title: str, claims: Iterable[Claim], note: str = "") -> None:
        items = list(claims)
        if not items:
            return
        # extend(), not += : an augmented assignment would make `lines` a local
        # of this closure and raise UnboundLocalError on the first read.
        lines.extend([f"### {title}", ""])
        if note:
            lines.extend([f"_{note}_", ""])
        for c in items:
            suffix = ""
            if c.value is not None:
                suffix = f" **{_fmt(c.value, c.unit)}**"
            if c.n_samples is not None:
                suffix += f" (n={c.n_samples})"
            lines.append(f"- **{c.type.value}** {c.text}{suffix}")
            if c.type is ClaimType.INTERPRETATION:
                lines.append(f"  - confidence: `{c.confidence}`")
                lines.append(f"  - would be refuted by: {c.falsification_test}")
        lines.append("")

    block("Facts", a.of_type(ClaimType.FACT), "Readable from the configuration and the run log.")
    block("Measurements", a.of_type(ClaimType.MEASUREMENT), "Produced by the evaluation, with sample counts.")
    block(
        "Interpretations",
        a.of_type(ClaimType.INTERPRETATION),
        "Candidate mechanisms, not conclusions. Each names the experiment that would refute it.",
    )
    block("Hypotheses", a.of_type(ClaimType.HYPOTHESIS), "Proposed next experiments.")

    if a.limitations:
        lines += ["### Limitations of this analysis", ""]
        for lim in a.limitations:
            lines.append(f"- {lim}")
        lines.append("")
    return "\n".join(lines)


def validate_claims(claims: Sequence[Claim]) -> list[str]:
    """Check the typing rules on a claim list; returns a list of problems."""
    problems: list[str] = []
    for i, c in enumerate(claims):
        try:
            Claim(**{**asdict(c), "type": c.type})
        except ValueError as exc:
            problems.append(f"claims[{i}]: {exc}")
    return problems
