"""The tuning section of ``docs/calibration.md`` is the committed CSV, the CSV obeys ADR-0031's rules, and the prose
says no more than the CSV does.

This reads only the CSV, the page and the source of the config, so it runs in a documentation-only pull request. The
functions are tested in ``test_scale_tuning.py``; this file recomputes the margins, the scores and the choice from the
rows without calling the selection function, so that the file is checked against the rule and not against itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from navkit import scale_tuning as st
from navkit.estimators.eskf import EskfConfig
from navkit.io.imu import ImuNoiseModel
from navkit.report.page import splice_block

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "adaptive_scale_tuning.csv"
PAGE = ROOT / "docs" / "calibration.md"
ADR = ROOT / "docs" / "adr" / "0031-an-adaptive-visual-noise-scale.md"
ESKF = ROOT / "src" / "navkit" / "estimators" / "eskf.py"
HEADING = "## The tuning run of the adaptive visual scale (ADR-0031)"
CONDITIONS = ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]
PLACEHOLDERS = (5.0, 0.5, 8.0)


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return st.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    page = PAGE.read_text(encoding="utf-8")
    start = page.index(HEADING)
    return " ".join(page[start:].split("\n## ", 1)[0].split())


def _points(rows, stage):
    seen = []
    for r in rows:
        key = (r["tau_s"], r["s_min"], r["s_max"])
        if r["stage"] == stage and key not in seen:
            seen.append(key)
    return seen


def _group(rows, stage, key):
    return [r for r in rows if r["stage"] == stage and (r["tau_s"], r["s_min"], r["s_max"]) == key]


# ------------------------------------------------------------------------------------------ the file


def test_the_page_table_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "scale-tuning", st.markdown_section(rows))


def test_the_csv_round_trips_to_the_same_bytes(rows):
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(st.CSV_FIELDS)
    assert st.csv_text(rows) == text


def test_the_adr_states_the_grid_that_the_module_runs():
    text = " ".join(ADR.read_text(encoding="utf-8").split())
    assert "tau in {2, 5, 10} seconds, s_min in {0.25, 0.5}, s_max in {8, 16}: twelve points" in text
    assert (st.GRID_TAU_S, st.GRID_S_MIN, st.GRID_S_MAX) == ((2.0, 5.0, 10.0), (0.25, 0.5), (8.0, 16.0))


def test_the_grid_stage_is_the_twelve_points_of_the_adr_on_seeds_0_to_24_with_every_condition(rows):
    grid = _points(rows, "grid")
    assert sorted(grid) == sorted((p.tau_s, p.s_min, p.s_max) for p in st.GRID)
    assert len(grid) == 12
    for key in grid:
        group = _group(rows, "grid", key)
        assert [(r["scenario"], r["condition"]) for r in group] == [(s, c) for s in ("S1", "S2") for c in CONDITIONS]
        assert {r["seeds"] for r in group} == {"0-24"}


def test_only_the_chosen_point_is_confirmed_and_only_on_the_three_blocks(rows):
    chosen = {(r["tau_s"], r["s_min"], r["s_max"]) for r in rows if r["chosen"] and r["stage"] == "grid"}
    assert len(chosen) <= 1
    stages = {r["stage"] for r in rows} - {"grid"}
    if not chosen:
        assert stages == set()
        return
    assert stages == set(st.CONFIRMATION_BLOCKS)
    for label, seeds in st.CONFIRMATION_BLOCKS.items():
        assert _points(rows, label) == list(chosen)
        group = _group(rows, label, next(iter(chosen)))
        assert {r["seeds"] for r in group} == {f"{seeds[0]}-{seeds[-1]}"}
        assert all(r["chosen"] for r in group)


def test_no_seed_from_100_up_appears_in_the_file(rows):
    for r in rows:
        lo, _, hi = r["seeds"].partition("-")
        assert int(hi or lo) < 100


def test_the_margins_scores_and_flags_follow_the_definitions(rows):
    for r in rows:
        thr, val = r["threshold"], r["value"]
        margin = (thr - val) / thr if r["relation"] == "<=" else (val - thr) / thr
        assert r["margin"] == pytest.approx(margin, rel=1e-9, abs=1e-12)
        assert r["holds"] == (val <= thr if r["relation"] == "<=" else val >= thr)
    stages = {r["stage"] for r in rows}
    for stage in stages:
        for key in _points(rows, stage):
            group = _group(rows, stage, key)
            assert {r["score"] for r in group} == {min(r["margin"] for r in group)}
            assert {r["qualifies"] for r in group} == {all(r["holds"] for r in group)}


def test_the_chosen_point_is_what_the_rule_of_the_adr_picks_from_the_rows(rows):
    scored = []
    for key in _points(rows, "grid"):
        group = _group(rows, "grid", key)
        if all(r["holds"] for r in group):
            tau, s_min, s_max = key
            scored.append((-group[0]["score"], tau, -s_min, s_max, key))
    expected = {min(scored)[4]} if scored else set()
    flagged = {(r["tau_s"], r["s_min"], r["s_max"]) for r in rows if r["chosen"] and r["stage"] == "grid"}
    assert flagged == expected


def test_the_stated_outcome_is_the_one_the_rows_give(rows, section):
    out = st.outcome_from_rows(rows)
    chosen_rows = [r for r in rows if r["chosen"] and r["stage"] == "grid"]
    confirmed = all(
        all(r["qualifies"] for r in rows if r["stage"] == label) and any(r["stage"] == label for r in rows)
        for label in st.CONFIRMATION_BLOCKS
    )
    assert out.passed == (bool(chosen_rows) and confirmed)
    sentence = next(ln for ln in st.markdown_section(rows).splitlines() if ln.startswith("Outcome:"))
    assert " ".join(sentence.split()) in section


# ------------------------------------------------------------------------------------- the config


def _field_comment(name: str) -> str:
    """The comment block above ``name`` in the source of ``EskfConfig``."""
    lines = ESKF.read_text(encoding="utf-8").splitlines()
    index = next(i for i, ln in enumerate(lines) if re.match(rf"\s+{name}: float = ", ln))
    block = []
    for ln in reversed(lines[:index]):
        if not ln.strip().startswith("#:"):
            break
        block.append(ln.strip())
    return " ".join(reversed(block))


def test_the_config_defaults_follow_the_outcome_and_the_scale_stays_off(rows):
    out = st.outcome_from_rows(rows)
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.vision_adaptive_scale is False
    defaults = (cfg.vision_scale_tau_s, cfg.vision_scale_min, cfg.vision_scale_max)
    names = ("vision_scale_tau_s", "vision_scale_min", "vision_scale_max")
    if out.passed:
        assert out.chosen is not None
        assert defaults == (out.chosen.tau_s, out.chosen.s_min, out.chosen.s_max)
        for name in names:
            comment = _field_comment(name)
            assert "PLACEHOLDER" not in comment
            assert "chosen by the tuning run of ADR-0031 (docs/data/adaptive_scale_tuning.csv)" in comment
    else:
        assert defaults == PLACEHOLDERS
        for name in names:
            assert "PLACEHOLDER" in _field_comment(name)


# ------------------------------------------------------------------------------------------- the prose


def test_the_section_says_what_the_outcome_does_not_show(section):
    for phrase in (
        "synthetic",
        "development seeds",
        "held-out",
        "has not been evaluated",
        "vision_enabled",
        "unchanged",
    ):
        assert phrase in section, phrase


def test_the_section_makes_no_claim_about_b1_and_has_no_dash(section):
    # The framing guard (test_framing.py) already covers the wording of every tracked file, this section included.
    assert "B1" not in section
    assert chr(0x2014) not in section and chr(0x2013) not in section


def test_the_section_links_the_csv_and_the_two_adrs(section):
    assert "(data/adaptive_scale_tuning.csv)" in section
    assert "adr/0031-an-adaptive-visual-noise-scale.md" in section
    assert "adr/0032-the-adaptive-visual-scale-takes-every-visual-update.md" in section
    assert "navkit gate tune-scale --csv docs/data/adaptive_scale_tuning.csv --page docs/calibration.md" in section
