"""The held-out decision of ADR-0028 as the documents state it, checked against ``docs/data/b1_gate_heldout.csv``.

This reads only the committed CSV, the page and ``CONSTRAINTS.md``. It never runs a case: the held-out seeds are
single use, and the one decision run is already committed.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from navkit import b1_gate
from navkit.eval import gate

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "b1_gate_heldout.csv"
PAGE = ROOT / "docs" / "calibration.md"
CONSTRAINTS = ROOT / "CONSTRAINTS.md"

CONDITIONS = ["nees_upper", "nees_lower", "coverage", "ate_better", "ate_median", "ate_worst"]


def _load_renderer():
    spec = importlib.util.spec_from_file_location("render_b1_heldout", ROOT / "scripts" / "render_b1_heldout.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load_renderer()


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return b1_gate.parse_csv(CSV.read_text(encoding="utf-8"))


def test_the_committed_file_is_the_held_out_decision_for_the_candidate_only(rows):
    assert {r["seeds"] for r in rows} == {"100-124"}
    assert {r["n_runs"] for r in rows} == {b1_gate.GATE_RUNS}
    assert {(r["role"], r["subject"]) for r in rows} == {("candidate", "outage_visual+clone+measured-front-end")}
    assert [r["condition"] for r in rows] == CONDITIONS
    assert b1_gate.csv_text(rows) == CSV.read_text(encoding="utf-8")


def test_the_thresholds_are_the_adr_constants_and_the_flags_follow_the_relations(rows):
    t = {r["condition"]: r["threshold"] for r in rows}
    dof = rows[0]["dof"]
    assert t["nees_lower"] == gate.B1_LOWER_BOUND_PER_DOF * dof
    assert t["coverage"] == gate.B1_COVERAGE_MIN
    assert t["ate_median"] == gate.B1_MEDIAN_RATIO_MAX and t["ate_worst"] == gate.B1_WORST_RATIO_MAX
    assert t["ate_better"] == math.ceil(round(gate.B1_BETTER_FRACTION_MIN * rows[0]["n_runs"], 9))
    assert rows[0]["degrees_of_freedom"] == math.floor(dof * rows[0]["sum_n_eff"])
    for r in rows:
        holds = r["value"] <= r["threshold"] if r["relation"] == "<=" else r["value"] >= r["threshold"]
        assert holds == r["passed"], r["condition"]
        assert r["subject_passed"] == all(x["passed"] for x in rows)


def test_the_page_block_and_the_status_line_are_what_the_csv_gives(rows):
    page, constraints = PAGE.read_text(encoding="utf-8"), CONSTRAINTS.read_text(encoding="utf-8")
    assert render.render(rows, page, constraints) == (page, constraints)


def test_every_value_and_threshold_is_in_the_page_table(rows):
    page = PAGE.read_text(encoding="utf-8")
    for r in rows:
        assert b1_gate._format_value(r["condition"], r["value"]) in page
        assert b1_gate._format_threshold(r["condition"], r["relation"], r["threshold"]) in page


def test_the_status_is_exactly_one_of_the_two_texts_and_the_right_one(rows):
    constraints = CONSTRAINTS.read_text(encoding="utf-8")
    block = constraints.split(render.STATUS_MARKERS[0], 1)[1].split(render.STATUS_MARKERS[1], 1)[0].strip()
    failed = [r["condition"] for r in rows if not r["passed"]]
    if failed:
        assert block.startswith("Status: open. The gate of ADR-0028 failed on the held-out seeds 100 to 124")
        assert "Any change to the candidate is tested on a new held-out set, starting at seed 125 (ADR-0028)." in block
        assert block.endswith("vision_enabled stays False.")
        for name in CONDITIONS:
            label = b1_gate.CONDITION_LABELS[name]
            assert (label in block) == (name in failed), name
        assert render.PASSED not in constraints
    else:
        assert block == render.PASSED
        assert "Status: open." not in block


def test_the_old_gate_stays_as_dated_history_and_is_marked_superseded():
    text = CONSTRAINTS.read_text(encoding="utf-8")
    b1 = text[text.index("**B1: Visual fusion") :]
    assert "History (superseded gate), 2026-10." in b1
    assert "supersedes" in b1 and "[ADR-0028]" in b1
    assert "Current status." in b1
    assert b1.index("Current status.") < b1.index("History (superseded gate), 2026-10.")
    history = b1[b1.index("History (superseded gate), 2026-10.") :]
    assert "B1 was open for the shipped configuration" in history  # the old text is still there
    assert "The superseded gate is one-sided" in history
    assert "meets the current gate" not in b1


def test_the_page_says_when_how_often_and_with_what_code_it_was_run():
    page = PAGE.read_text(encoding="utf-8")
    section = " ".join(page[page.index("## The B1 gate: the decision run") : page.index("## Worked example")].split())
    for phrase in (
        "It was run once, with the code at commit 4c88341 on 2026-10-20",
        "it is not run again",
        "it was a check and not a second decision",
        "The DIAGNOSTIC rows are not computed on the held-out seeds",
        "It does not change `vision_enabled`",
    ):
        assert phrase in section, phrase


def test_the_renderer_refuses_a_csv_that_is_not_the_held_out_set(rows):
    dev = [{**r, "seeds": "0-24"} for r in rows]
    with pytest.raises(ValueError, match="held-out"):
        render.status_text(dev)
    with pytest.raises(ValueError, match="needs the lines"):
        render.splice("no markers", render.PAGE_MARKERS, "x")
