"""Tests for the typed claim layer.

``analysis/findings.py`` was at 0% coverage. It is the module that enforces
the project's central editorial rule: a `FACT` is readable from the run log, a
`MEASUREMENT` carries a number and a sample count, an `INTERPRETATION` names
the experiment that would refute it, and a `HYPOTHESIS` is a proposed next
experiment. Nothing else in the repository is allowed to publish a claim
without going through these types, so their validation is worth testing
directly rather than trusting the dataclass constructors.
"""

import json

import pytest

from navkit.analysis.findings import (
    GENERIC_LIMITATIONS,
    MECHANISM_LIBRARY,
    Analysis,
    Claim,
    ClaimType,
    build_analysis,
    render_markdown,
    validate_claims,
)


def _exactly_one(claims, predicate, label):
    """Return the single claim matching ``predicate``, asserting there is one.

    Indexing with ``[0]`` or calling ``next()`` both pass when the analysis
    emits two claims that both match, which is precisely the duplication this
    suite is supposed to catch: a claim appearing twice means a number is being
    published twice, and either copy can then drift from the other.
    """
    matches = [c for c in claims if predicate(c)]
    assert len(matches) == 1, f"expected exactly 1 {label}, got {len(matches)}: {matches}"
    return matches[0]


MANIFEST = {
    "gnss": {
        "enabled": True,
        "usable_fixes": 80,
        "emitted_fixes": 100,
        "configured_rate_hz": 5.0,
        "position_sigma_m": 0.8,
        "unavailable_intervals_s": [[5.0, 20.0]],
    },
    "vision": {
        "dropped_frames": 12,
        "emitted_frames": 200,
        "drop_fraction_measured": 0.06,
        "longest_gap_s": 0.42,
        "time_offset_s": 0.0,
    },
    "imu": {"samples": 4000, "rate_hz": 200.0, "noise_scale": 1.0, "time_offset_s": 0.0},
}

METRICS = {
    "ate": {
        "rigid_start": {
            "position_m": {"rmse": 0.21, "max": 0.55, "count": 1000},
        }
    },
    "rpe": {"1s": {"translation_m": {"rmse": 0.03, "count": 999}}},
    "drift": {
        "final_drift_pct_path_length": 1.2,
        "growth": {"slope_m_per_s": 0.02, "window_s": [10.0, 20.0], "r_squared": 0.91},
    },
    "failures": {
        "count": 1,
        "passed": False,
        "events": [{"kind": "divergence", "start_s": 5.0, "end_s": 20.0, "detail": "error rose", "peak_m": 0.9}],
    },
}


# --- ClaimType ---------------------------------------------------------------


def test_is_fact_is_true_only_for_fact():
    assert ClaimType.FACT.is_fact
    assert not ClaimType.MEASUREMENT.is_fact
    assert not ClaimType.INTERPRETATION.is_fact
    assert not ClaimType.HYPOTHESIS.is_fact


def test_claim_type_values_are_the_documented_labels():
    assert [t.value for t in ClaimType] == [
        "FACT",
        "MEASUREMENT",
        "INTERPRETATION",
        "HYPOTHESIS",
    ]


# --- Claim construction rules ------------------------------------------------


def test_interpretation_without_falsification_test_is_rejected():
    """An explanation nothing could refute is an opinion."""
    with pytest.raises(ValueError, match="must carry a falsification_test"):
        Claim(type=ClaimType.INTERPRETATION, text="t", confidence="high")


@pytest.mark.parametrize("confidence", ["", "certain", "HIGH", "medium-high"])
def test_interpretation_rejects_confidence_outside_the_vocabulary(confidence):
    with pytest.raises(ValueError, match="needs a confidence of low/medium/high"):
        Claim(
            type=ClaimType.INTERPRETATION,
            text="t",
            confidence=confidence,
            falsification_test="f",
        )


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_interpretation_accepts_the_documented_confidence_levels(confidence):
    c = Claim(type=ClaimType.INTERPRETATION, text="t", confidence=confidence, falsification_test="f")
    assert c.confidence == confidence


def test_measurement_without_a_value_is_rejected():
    with pytest.raises(ValueError, match="MEASUREMENT must carry a numeric value"):
        Claim(type=ClaimType.MEASUREMENT, text="t")


def test_measurement_with_zero_value_is_accepted():
    """Zero is a measurement; None is the absence of one."""
    c = Claim(type=ClaimType.MEASUREMENT, text="t", value=0.0)
    assert c.value == 0.0


def test_fact_carrying_n_samples_is_rejected():
    """n_samples is what makes a claim a measurement rather than a fact."""
    with pytest.raises(ValueError, match="FACT must not carry n_samples"):
        Claim(type=ClaimType.FACT, text="t", n_samples=10)


def test_hypothesis_needs_nothing_extra():
    c = Claim(type=ClaimType.HYPOTHESIS, text="t")
    assert c.type is ClaimType.HYPOTHESIS


# --- serialisation -----------------------------------------------------------


def test_as_dict_omits_unset_optional_fields():
    d = Claim(type=ClaimType.FACT, text="t").as_dict()
    assert d == {"type": "FACT", "text": "t"}


def test_as_dict_includes_every_populated_field():
    c = Claim(
        type=ClaimType.MEASUREMENT,
        text="t",
        value=1.5,
        unit="m",
        n_samples=10,
        supports=["s1"],
        tags=["a", "b"],
    )
    d = c.as_dict()
    assert d == {
        "type": "MEASUREMENT",
        "text": "t",
        "value": 1.5,
        "unit": "m",
        "n_samples": 10,
        "supports": ["s1"],
        "tags": ["a", "b"],
    }


# --- Analysis ----------------------------------------------------------------


def _analysis() -> Analysis:
    return Analysis(
        scenario="gnss_denied",
        description="a 15 s outage",
        claims=[
            Claim(type=ClaimType.FACT, text="f"),
            Claim(type=ClaimType.MEASUREMENT, text="m", value=1.0),
            Claim(
                type=ClaimType.INTERPRETATION,
                text="i",
                confidence="high",
                falsification_test="x",
            ),
            Claim(type=ClaimType.HYPOTHESIS, text="h"),
        ],
        limitations=["only synthetic"],
    )


def test_of_type_filters_by_type():
    a = _analysis()
    assert [c.text for c in a.of_type(ClaimType.FACT)] == ["f"]
    assert len(a.of_type(ClaimType.MEASUREMENT)) == 1
    assert a.of_type(ClaimType.HYPOTHESIS)[0].text == "h"


def test_as_dict_partitions_claims_into_named_buckets():
    d = _analysis().as_dict()
    assert [c["text"] for c in d["facts"]] == ["f"]
    assert [c["text"] for c in d["interpretations"]] == ["i"]
    assert d["limitations"] == ["only synthetic"]


def test_to_json_is_valid_json_and_keeps_bucket_order():
    d = json.loads(_analysis().to_json())
    assert list(d)[:2] == ["scenario", "description"]
    assert "facts" in d and "hypotheses" in d


def test_to_markdown_delegates_to_render_markdown():
    a = _analysis()
    assert a.to_markdown() == render_markdown(a)


# --- build_analysis ----------------------------------------------------------


def test_build_analysis_reports_gnss_outage_intervals():
    a = build_analysis("gnss_denied", "15 s outage", MANIFEST, METRICS)
    text = " ".join(c.text for c in a.of_type(ClaimType.FACT))
    assert "unavailable for 15.0 s" in text
    assert "5.0-20.0 s" in text
    assert "80 of 100 fixes" in text


def test_build_analysis_reports_disabled_gnss_differently_from_an_outage():
    manifest = {"gnss": {"enabled": False}, "vision": {}, "imu": {}}
    a = build_analysis("normal", "", manifest, METRICS)
    text = " ".join(c.text for c in a.of_type(ClaimType.FACT))
    assert "disabled for the whole run" in text


def test_build_analysis_reports_frame_drops_and_the_longest_gap():
    a = build_analysis("camera_drop", "", MANIFEST, METRICS)
    text = " ".join(c.text for c in a.of_type(ClaimType.FACT))
    assert "12 of 200 visual frames" in text
    assert "6.0%" in text
    assert "0.420 s" in text


def test_build_analysis_omits_frame_drop_fact_when_nothing_was_dropped():
    manifest = {**MANIFEST, "vision": {**MANIFEST["vision"], "dropped_frames": 0}}
    a = build_analysis("camera_drop", "", manifest, METRICS)
    assert not any("dropped" in c.text for c in a.of_type(ClaimType.FACT))


def test_build_analysis_reports_timestamp_offsets_with_a_sign():
    manifest = {
        **MANIFEST,
        "vision": {**MANIFEST["vision"], "time_offset_s": 0.02},
        "imu": {**MANIFEST["imu"], "time_offset_s": -0.005},
    }
    text = " ".join(c.text for c in build_analysis("normal", "", manifest, METRICS).of_type(ClaimType.FACT))
    assert "+20.0 ms" in text
    assert "-5.0 ms" in text


def test_build_analysis_emits_ate_measurements_with_sample_counts():
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS).of_type(ClaimType.MEASUREMENT)
    ate = _exactly_one(ms, lambda c: "rigid_start" in c.text, "rigid_start claim")
    assert ate.value == pytest.approx(0.21)
    assert ate.n_samples == 1000
    assert ate.unit == "m"


def test_build_analysis_emits_drift_slope_with_its_fit_quality():
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS).of_type(ClaimType.MEASUREMENT)
    slope = _exactly_one(ms, lambda c: "slope" in c.text.lower() and c.unit == "m/s", "drift slope claim")
    assert slope.value == pytest.approx(0.02)
    assert "R^2=0.910" in slope.text


def test_build_analysis_omits_drift_slope_when_absent():
    metrics = {**METRICS, "drift": {"final_drift_pct_path_length": 1.0}}
    ms = build_analysis("gnss_denied", "", MANIFEST, metrics).of_type(ClaimType.MEASUREMENT)
    assert not any("slope" in c.text.lower() for c in ms)


def test_build_analysis_reports_one_claim_per_failure_event():
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS).of_type(ClaimType.MEASUREMENT)
    ev = _exactly_one(ms, lambda c: "failure event" in c.text, "failure-event claim")
    assert "did not pass" in ev.text
    detail = _exactly_one(ms, lambda c: "divergence" in c.text and "from 5.0 s" in c.text, "divergence claim")
    assert detail.value == pytest.approx(0.9)


def test_build_analysis_adds_the_baseline_comparison():
    delta = {"baseline_ate_rmse_m": 0.1, "ate_rmse_m": 0.4}
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS, delta).of_type(ClaimType.MEASUREMENT)
    cmp = _exactly_one(ms, lambda c: "changed from" in c.text, "comparison claim")
    assert "factor of 4" in cmp.text
    assert "higher" in cmp.text
    assert cmp.value == pytest.approx(0.3)


def test_baseline_comparison_survives_a_zero_baseline():
    """A zero baseline has no ratio; the claim must not divide by it."""
    delta = {"baseline_ate_rmse_m": 0.0, "ate_rmse_m": 0.4}
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS, delta).of_type(ClaimType.MEASUREMENT)
    cmp = _exactly_one(ms, lambda c: "changed from" in c.text, "comparison claim")
    assert "factor of nan" in cmp.text


def test_baseline_comparison_includes_drift_slope_delta_when_present():
    delta = {
        "baseline_ate_rmse_m": 0.1,
        "ate_rmse_m": 0.4,
        "baseline_drift_slope_m_per_s": 0.01,
        "drift_slope_m_per_s": 0.03,
    }
    ms = build_analysis("gnss_denied", "", MANIFEST, METRICS, delta).of_type(ClaimType.MEASUREMENT)
    d = _exactly_one(ms, lambda c: "Steady-state drift slope" in c.text, "steady-state slope claim")
    assert d.value == pytest.approx(0.02)


def test_build_analysis_attaches_interpretations_with_falsification_tests():
    a = build_analysis("gnss_denied", "", MANIFEST, METRICS)
    interps = a.of_type(ClaimType.INTERPRETATION)
    assert interps
    for c in interps:
        assert c.falsification_test
        assert c.confidence in ("low", "medium", "high")


def test_every_library_mechanism_is_well_formed():
    """The library is the source of published interpretations; police it here."""
    for scenario, entries in MECHANISM_LIBRARY.items():
        for text, confidence, falsify in entries:
            assert text.strip(), scenario
            assert confidence in ("low", "medium", "high"), scenario
            assert falsify.strip(), scenario
            # Must survive the Claim constructor.
            Claim(
                type=ClaimType.INTERPRETATION,
                text=text,
                confidence=confidence,
                falsification_test=falsify,
            )


def test_build_analysis_emits_hypotheses_for_known_scenarios():
    for scenario in ("gnss_denied", "timestamp_offset", "camera_drop", "anything_else"):
        a = build_analysis(scenario, "", MANIFEST, METRICS)
        assert a.of_type(ClaimType.HYPOTHESIS), scenario


def test_unknown_scenario_still_gets_a_baseline_swap_hypothesis():
    a = build_analysis("unheard_of", "", MANIFEST, METRICS)
    assert "dead reckoning" in a.of_type(ClaimType.HYPOTHESIS)[0].text


def test_generic_limitations_are_always_attached():
    a = build_analysis("normal", "", MANIFEST, METRICS)
    assert a.limitations[: len(GENERIC_LIMITATIONS)] == GENERIC_LIMITATIONS


def test_extra_limitations_are_appended():
    a = build_analysis("normal", "", MANIFEST, METRICS, extra_limitations=["sat only"])
    assert a.limitations[-1] == "sat only"


def test_build_analysis_tolerates_an_empty_manifest():
    """A missing section must not crash report generation."""
    a = build_analysis("normal", "", {}, {})
    assert a.of_type(ClaimType.MEASUREMENT)
    assert a.of_type(ClaimType.HYPOTHESIS)


# --- rendering ---------------------------------------------------------------


def test_markdown_has_a_heading_per_populated_bucket():
    md = render_markdown(_analysis())
    for heading in ("### Facts", "### Measurements", "### Interpretations", "### Hypotheses"):
        assert heading in md


def test_markdown_shows_confidence_and_falsification_for_interpretations():
    md = render_markdown(_analysis())
    assert "confidence: `high`" in md
    assert "would be refuted by: x" in md


def test_markdown_shows_values_units_and_sample_counts():
    a = Analysis(
        scenario="x",
        claims=[Claim(type=ClaimType.MEASUREMENT, text="t", value=1.0, unit="m", n_samples=42)],
    )
    md = render_markdown(a)
    assert "**1 m**" in md
    assert "(n=42)" in md


def test_markdown_omits_empty_buckets():
    a = Analysis(scenario="x", claims=[Claim(type=ClaimType.FACT, text="only a fact")])
    md = render_markdown(a)
    assert "### Facts" in md
    assert "### Measurements" not in md
    assert "### Hypotheses" not in md


def test_markdown_includes_the_description_and_limitations():
    md = render_markdown(_analysis())
    assert "a 15 s outage" in md
    assert "### Limitations of this analysis" in md
    assert "- only synthetic" in md


# --- validate_claims ---------------------------------------------------------


def test_validate_claims_accepts_well_typed_claims():
    assert validate_claims(_analysis().claims) == []


def test_validate_claims_catches_post_construction_mutation():
    """__post_init__ already rejects a bad Claim, so the only way one can exist
    is by being mutated afterwards. That is the case this guards."""
    c = Claim(type=ClaimType.MEASUREMENT, text="had a value", value=1.0)
    c.value = None
    problems = validate_claims([c])
    assert len(problems) == 1
    assert problems[0].startswith("claims[0]:")


def test_validate_claims_reports_the_offending_index():
    good = Claim(type=ClaimType.FACT, text="ok")
    bad = Claim(type=ClaimType.MEASUREMENT, text="had a value", value=1.0)
    bad.value = None
    problems = validate_claims([good, bad])
    assert len(problems) == 1
    assert problems[0].startswith("claims[1]:")


def test_validate_claims_reports_every_problem_not_just_the_first():
    a = Claim(type=ClaimType.MEASUREMENT, text="m", value=1.0)
    a.value = None
    b = Claim(type=ClaimType.INTERPRETATION, text="i", confidence="high", falsification_test="f")
    b.falsification_test = ""
    assert len(validate_claims([a, b])) == 2


def test_every_claim_built_by_build_analysis_passes_validation():
    """The library must not be able to emit an invalid claim."""
    for scenario in ("gnss_denied", "camera_drop", "normal"):
        a = build_analysis(scenario, "", MANIFEST, METRICS, {"baseline_ate_rmse_m": 0.1, "ate_rmse_m": 0.2})
        assert validate_claims(a.claims) == [], scenario
