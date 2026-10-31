"""The B1 gate on real cases, development seeds only.

Seeds 100 to 124 are the held-out set of ADR-0028 and are never run here. Every seed below is below 100.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit import b1_gate
from navkit import benchmark as bm
from navkit.eval.gate import evaluate_b1_gate
from navkit.report.page import splice_block

DEV_SEEDS = list(range(25))


@pytest.fixture(scope="module")
def doc():
    return b1_gate._document()


def test_no_test_seed_is_in_the_held_out_set():
    assert not b1_gate._touches_held_out(DEV_SEEDS)
    assert max(DEV_SEEDS) < min(b1_gate.HELD_OUT_SEEDS)


def test_the_candidate_is_the_adr_configuration(doc):
    case = b1_gate.candidate_case(doc["cases"])
    base = doc["cases"]["outage_visual"]
    assert case["estimator"]["vision_model"] == "clone"
    assert case["estimator"]["vision_noise_preset"] == "measured-front-end"
    assert case["estimator"]["vision_fuse"] is True
    assert case["scenario"] == base["scenario"]  # the scenario is outage_visual's, unchanged
    assert "vision_model" not in base.get("estimator", {})  # and the config's own case is not mutated
    assert doc["cases"][b1_gate.CONTROL]["estimator"]["vision_fuse"] is False


def test_the_candidate_runs_with_the_preset_the_adr_names(doc):
    from navkit.estimators.eskf import VISION_NOISE_PRESETS

    assert "measured-front-end" in VISION_NOISE_PRESETS
    box: dict = {}
    bm.run_case("c", b1_gate.candidate_case(doc["cases"]), doc["defaults"], seed=0, nees_out=box)
    assert box["error"].shape == box["sigma"].shape == (box["t"].size, 3)
    assert box["squared"].shape == box["t"].shape


def test_the_window_arrays_are_the_half_open_outage_window(doc):
    box: dict = {}
    bm.run_case("control", doc["cases"][b1_gate.CONTROL], doc["defaults"], seed=1, nees_out=box)
    arrays = b1_gate.window_arrays(box)
    ((start, end),) = box["windows"]
    inside = (box["t"] >= start) & (box["t"] < end)
    assert 0 < int(inside.sum()) < box["t"].size
    assert arrays["nees"].shape == (int(inside.sum()),)
    assert arrays["error"].shape == arrays["sigma"].shape == (int(inside.sum()), 3)
    assert float(arrays["ate"]) == pytest.approx(np.sqrt(np.mean(np.sum(box["error"][inside] ** 2, axis=1))))
    np.testing.assert_array_equal(arrays["nees"], box["squared"][inside])


def test_a_run_without_an_outage_has_no_window(doc):
    box: dict = {}
    bm.run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0, nees_out=box)
    with pytest.raises(ValueError, match="window"):
        b1_gate.window_arrays(box)


@pytest.fixture(scope="module")
def three_seed_rows():
    return b1_gate.run_gate([0, 1, 2])


def test_three_seeds_give_a_row_per_condition_for_the_candidate_and_both_diagnostics(three_seed_rows):
    rows = three_seed_rows
    assert [(r["role"], r["subject"]) for r in rows[::6]] == [
        ("candidate", "outage_visual+clone+measured-front-end"),
        ("DIAGNOSTIC", "outage_visual"),
        ("DIAGNOSTIC", "outage_visual_clone"),
    ]
    assert [r["condition"] for r in rows[:6]] == [
        "nees_upper",
        "nees_lower",
        "coverage",
        "ate_better",
        "ate_median",
        "ate_worst",
    ]
    assert {r["seeds"] for r in rows} == {"0-2"} and {r["n_runs"] for r in rows} == {3}
    for i in range(0, len(rows), 6):
        assert len({r["subject_passed"] for r in rows[i : i + 6]}) == 1
        assert rows[i]["subject_passed"] == all(r["passed"] for r in rows[i : i + 6])


def test_the_csv_round_trips_and_is_deterministic(three_seed_rows):
    text = b1_gate.csv_text(three_seed_rows)
    assert text.splitlines()[0] == ",".join(b1_gate.CSV_FIELDS)
    assert b1_gate.csv_text(b1_gate.parse_csv(text)) == text
    again = b1_gate.run_gate([0, 1, 2])
    assert b1_gate.csv_text(again) == text


def test_the_diagnostics_are_left_out_on_request(doc):
    rows = b1_gate.run_gate([0, 1], diagnostics=False)
    assert {r["role"] for r in rows} == {"candidate"}


def test_the_table_is_generated_from_the_rows(three_seed_rows):
    table = b1_gate.markdown_table(three_seed_rows)
    for label in b1_gate.CONDITION_LABELS.values():
        assert label in table
    assert table.count("DIAGNOSTIC") == 2 + 12
    page = "x\n<!-- b1-gate-dev:start -->\nSTALE\n<!-- b1-gate-dev:end -->\ny\n"
    out = splice_block(page, "b1-gate-dev", table)
    assert "STALE" not in out and table in out and out.startswith("x\n") and out.endswith("\ny\n")
    with pytest.raises(ValueError, match="needs the lines"):
        splice_block("no markers", "b1-gate-dev", table)


def test_the_anchor_diagnostic_fails_the_gate_on_the_development_seeds(doc):
    """The gate's own control: the single-anchor model is overconfident, and the gate has to be able to say no."""
    cases, defaults = doc["cases"], doc["defaults"]
    control = b1_gate.run_arrays(b1_gate.CONTROL, cases[b1_gate.CONTROL], defaults, DEV_SEEDS)
    anchor = b1_gate.run_arrays("outage_visual", cases["outage_visual"], defaults, DEV_SEEDS)
    result = evaluate_b1_gate(anchor["nees"], anchor["error"], anchor["sigma"], anchor["ate"], control["ate"])
    assert not result.passed
    assert not result.nees_upper.passed and not result.coverage.passed
    assert result.nees_upper.value > 10.0 * result.nees_upper.threshold
