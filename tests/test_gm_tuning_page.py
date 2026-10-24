"""The tuning sections of ``docs/calibration.md`` are the committed CSVs, the CSVs obey ADR-0034's rules, and the prose
says no more than the CSVs do.

This reads only the CSVs, the page and the source of the config, so it runs in a documentation-only pull request. The
functions are tested in ``test_gm_tuning.py``; this file recomputes the margins, the scores and the choice from the rows
without calling the selection function, so that the file is checked against the rule and not against itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from navkit import gm_tuning as gt
from navkit.estimators.eskf import EskfConfig
from navkit.io.imu import ImuNoiseModel

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "gm_tuning.csv"
ROB_CSV = ROOT / "docs" / "data" / "gm_tuning_robustness.csv"
PAGE = ROOT / "docs" / "calibration.md"
ADR = ROOT / "docs" / "adr" / "0034-a-gauss-markov-model-of-the-correlated-visual-error.md"
ESKF = ROOT / "src" / "navkit" / "estimators" / "eskf.py"
HEADING = "## The tuning run of the Gauss-Markov visual error model (ADR-0034)"
CONDITIONS = ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]
PLACEHOLDERS = (1.0, 0.5)


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return gt.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rob_rows() -> list[dict]:
    return gt.parse_robustness_csv(ROB_CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    page = PAGE.read_text(encoding="utf-8")
    start = page.index(HEADING)
    return " ".join(page[start:].split("\n## ", 1)[0].split())


def _points(rows, stage):
    seen = []
    for r in rows:
        key = (r["tau_s"], r["rho"])
        if r["stage"] == stage and key not in seen:
            seen.append(key)
    return seen


def _group(rows, stage, key):
    return [r for r in rows if r["stage"] == stage and (r["tau_s"], r["rho"]) == key]


# ------------------------------------------------------------------------------------------ the files


def test_the_page_tables_are_the_committed_csvs(rows, rob_rows):
    page = PAGE.read_text(encoding="utf-8")
    once = gt.splice_section(page, gt.markdown_section(rows), gt.START, gt.END)
    twice = gt.splice_section(once, gt.robustness_markdown(rob_rows), gt.ROB_START, gt.ROB_END)
    assert page == twice


def test_the_csvs_round_trip_to_the_same_bytes(rows, rob_rows):
    text = CSV.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(gt.CSV_FIELDS)
    assert gt.csv_text(rows) == text
    rob = ROB_CSV.read_text(encoding="utf-8")
    assert rob.splitlines()[0] == ",".join(gt.ROBUSTNESS_CSV_FIELDS)
    assert gt.robustness_csv_text(rob_rows) == rob


def test_the_adr_states_the_grid_that_the_module_runs():
    text = " ".join(ADR.read_text(encoding="utf-8").split())
    assert "tau in {0.25, 0.5, 1, 2} seconds and rho in {0.5, 0.75, 0.9}: twelve points, and no others" in text
    assert (gt.GRID_TAU_S, gt.GRID_RHO) == ((0.25, 0.5, 1.0, 2.0), (0.5, 0.75, 0.9))


def test_the_grid_stage_is_the_twelve_points_of_the_adr_on_seeds_0_to_24_with_every_condition(rows):
    grid = _points(rows, "grid")
    assert sorted(grid) == sorted((p.tau_s, p.rho) for p in gt.GRID)
    assert len(grid) == 12
    for key in grid:
        group = _group(rows, "grid", key)
        assert [(r["scenario"], r["condition"]) for r in group] == [(s, c) for s in ("S1", "S2") for c in CONDITIONS]
        assert {r["seeds"] for r in group} == {"0-24"}


def test_only_the_chosen_point_is_confirmed_and_only_on_the_three_blocks(rows):
    chosen = {(r["tau_s"], r["rho"]) for r in rows if r["chosen"] and r["stage"] == "grid"}
    assert len(chosen) <= 1
    stages = {r["stage"] for r in rows} - {"grid"}
    if not chosen:
        assert stages == set()
        return
    assert stages == set(gt.CONFIRMATION_BLOCKS)
    for label, seeds in gt.CONFIRMATION_BLOCKS.items():
        assert _points(rows, label) == list(chosen)
        group = _group(rows, label, next(iter(chosen)))
        assert {r["seeds"] for r in group} == {f"{seeds[0]}-{seeds[-1]}"}


def test_no_seed_from_100_up_appears_in_either_file(rows, rob_rows):
    for r in [*rows, *rob_rows]:
        lo, _, hi = r["seeds"].partition("-")
        assert int(hi or lo) < 100


def test_the_margins_scores_and_flags_follow_the_definitions(rows):
    for r in rows:
        thr, val = r["threshold"], r["value"]
        margin = (thr - val) / thr if r["relation"] == "<=" else (val - thr) / thr
        assert r["margin"] == pytest.approx(margin, rel=1e-9, abs=1e-12)
        assert r["holds"] == (val <= thr if r["relation"] == "<=" else val >= thr)
    for stage in {r["stage"] for r in rows}:
        for key in _points(rows, stage):
            group = _group(rows, stage, key)
            assert {r["score"] for r in group} == {min(r["margin"] for r in group)}
            assert {r["qualifies"] for r in group} == {all(r["holds"] for r in group)}


def test_the_chosen_point_is_what_the_rule_of_the_adr_picks_from_the_rows(rows):
    scored = []
    for key in _points(rows, "grid"):
        group = _group(rows, "grid", key)
        if all(r["holds"] for r in group):
            scored.append((-group[0]["score"], key[0], key[1], key))
    expected = {min(scored)[3]} if scored else set()
    assert {(r["tau_s"], r["rho"]) for r in rows if r["chosen"] and r["stage"] == "grid"} == expected


def test_the_stated_outcome_is_the_one_the_rows_give(rows, section):
    out = gt.outcome_from_rows(rows)
    chosen_rows = [r for r in rows if r["chosen"] and r["stage"] == "grid"]
    confirmed = all(
        any(r["stage"] == label for r in rows) and all(r["qualifies"] for r in rows if r["stage"] == label)
        for label in gt.CONFIRMATION_BLOCKS
    )
    assert out.passed == (bool(chosen_rows) and confirmed)
    sentence = next(ln for ln in gt.markdown_section(rows).splitlines() if ln.startswith("Outcome:"))
    assert " ".join(sentence.split()) in section


# --------------------------------------------------------------------------------- the diagnostic file


def test_the_diagnostic_rows_are_labelled_and_are_five_correlation_times_on_seeds_25_to_49(rob_rows):
    assert {r["stage"] for r in rob_rows} == {"DIAGNOSTIC"}
    assert {r["seeds"] for r in rob_rows} == {"25-49"}
    assert sorted({r["corr_time_s"] for r in rob_rows}) == [0.0, 0.25, 0.5, 1.0, 2.0]
    for t in gt.ROBUSTNESS_CORR_TIMES_S:
        assert [r["condition"] for r in rob_rows if r["corr_time_s"] == t] == CONDITIONS


def test_the_diagnostic_point_is_the_chosen_one_or_else_the_highest_score(rows, rob_rows):
    points = {(r["tau_s"], r["rho"]) for r in rob_rows}
    assert len(points) == 1
    chosen = {(r["tau_s"], r["rho"]) for r in rows if r["chosen"] and r["stage"] == "grid"}
    if chosen:
        assert points == chosen and {r["basis"] for r in rob_rows} == {"chosen"}
    else:
        best = min(
            ((-_group(rows, "grid", k)[0]["score"], k[0], k[1], k) for k in _points(rows, "grid")),
        )
        assert points == {best[3]} and {r["basis"] for r in rob_rows} == {"highest_score"}


def test_the_diagnostic_margins_follow_the_definitions(rob_rows):
    for r in rob_rows:
        thr, val = r["threshold"], r["value"]
        margin = (thr - val) / thr if r["relation"] == "<=" else (val - thr) / thr
        assert r["margin"] == pytest.approx(margin, rel=1e-9, abs=1e-12)
        assert r["holds"] == (val <= thr if r["relation"] == "<=" else val >= thr)


# ------------------------------------------------------------------------------------- the config


def _field_comment(name: str) -> str:
    lines = ESKF.read_text(encoding="utf-8").splitlines()
    index = next(i for i, ln in enumerate(lines) if re.match(rf"\s+{name}: float = ", ln))
    block = []
    for ln in reversed(lines[:index]):
        if not ln.strip().startswith("#:"):
            break
        block.append(ln.strip())
    return " ".join(reversed(block))


def test_the_config_defaults_follow_the_outcome_and_the_model_stays_off(rows):
    out = gt.outcome_from_rows(rows)
    cfg = EskfConfig(imu_noise=ImuNoiseModel())
    assert cfg.vision_gm_error is False
    defaults = (cfg.vision_gm_tau_s, cfg.vision_gm_rho)
    names = ("vision_gm_tau_s", "vision_gm_rho")
    if out.passed:
        assert out.chosen is not None
        assert defaults == (out.chosen.tau_s, out.chosen.rho)
        for name in names:
            comment = _field_comment(name)
            assert "PLACEHOLDER" not in comment
            assert "chosen by the tuning run of ADR-0034 (docs/data/gm_tuning.csv)" in comment
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


def test_the_section_labels_the_diagnostic_and_keeps_it_out_of_the_decision(section):
    assert "DIAGNOSTIC" in section
    assert "not a selection input" in section


def test_the_section_makes_no_claim_about_b1_and_has_no_dash(section):
    assert "B1" not in section
    assert chr(0x2014) not in section and chr(0x2013) not in section


def test_the_section_links_the_csvs_the_adrs_and_the_command(section):
    assert "(data/gm_tuning.csv)" in section and "(data/gm_tuning_robustness.csv)" in section
    assert "adr/0034-a-gauss-markov-model-of-the-correlated-visual-error.md" in section
    assert "navkit gate tune-gm --csv docs/data/gm_tuning.csv --page docs/calibration.md" in section


def test_a_frozen_candidate_records_its_freeze_commit_on_the_page(rows, section):
    if not gt.outcome_from_rows(rows).passed:
        pytest.skip("no candidate was frozen")
    assert re.search(r"freeze commit [0-9a-f]{7,40}", section)
