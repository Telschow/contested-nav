"""The ensemble section of ``docs/mismatch.md`` is generated from the committed CSVs; each sentence follows from them.

This reads only the CSVs and the page, so it runs in a documentation-only pull request. The producer is tested in
``test_mismatch_ensemble.py``. The sentence rules are tested first on a small synthetic CSV whose answer is known, then
the committed page is compared with what the rules give for the committed CSVs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from navkit import ensemble, mismatch_ensemble, mismatch_sweep
from navkit.eval.calibration import ensemble_nees_band

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "mismatch_ensemble.csv"
SINGLE_CSV = ROOT / "docs" / "data" / "mismatch_sweep.csv"
BENCHMARK_CSV = ROOT / "docs" / "data" / "ensemble_nees.csv"
PAGE = ROOT / "docs" / "mismatch.md"


def _row(case: str, factor: float, inside: float, below: float, above: float, scope: str = "full") -> dict[str, Any]:
    return {
        "case": case,
        "factor": factor,
        "scope": scope,
        "n_runs": 25,
        "dof": 3,
        "epochs": 100,
        "grand_mean": 3.0,
        "band_low": 2.0,
        "band_high": 4.0,
        "fraction_inside": inside,
        "fraction_below": below,
        "fraction_above": above,
    }


def _single(case: str, scale: float, verdicts: str) -> dict[str, Any]:
    return {"case": case, "scale": scale, "n_seeds": 5, "verdicts": verdicts}


#: Factor 1 is inside the band. 0.8 is above it for 90% of epochs, 0.9 for 20%, and 1.25 is below it for 95%.
ROWS = [
    _row("c", 0.5, 0.0, 0.0, 1.0),
    _row("c", 0.8, 0.1, 0.0, 0.9),
    _row("c", 0.9, 0.8, 0.0, 0.2),
    _row("c", 1.0, 0.9, 0.1, 0.0),
    _row("c", 1.25, 0.05, 0.95, 0.0),
    _row("c", 2.0, 0.1, 0.9, 0.0),
]
#: One run: 0.8 not resolved (2 of 5 overconfident), 0.9 resolved (5 of 5), 1.25 resolved (5 of 5 underconfident bulk).
SINGLE = [
    _single("c", 0.5, "overconfident=5"),
    _single("c", 0.8, "consistent=3;overconfident=2"),
    _single("c", 0.9, "overconfident=5"),
    _single("c", 1.0, "consistent=5"),
    _single("c", 1.25, "mixed(bulk=underconfident, tail=consistent)=5"),
    _single("c", 2.0, "mixed(bulk=underconfident, tail=consistent)=5"),
]


def _text(rows: list[dict[str, Any]], single: list[dict[str, Any]]) -> str:
    return " ".join(" ".join(mismatch_ensemble.findings(rows, single)).split())


def test_the_bulk_word_of_a_verdict_is_counted_for_plain_and_mixed_verdicts() -> None:
    verdicts = "consistent=1;mixed(bulk=overconfident, tail=consistent)=2;overconfident=2"
    assert mismatch_ensemble.bulk_count(verdicts, "overconfident") == 4
    assert mismatch_ensemble.bulk_count(verdicts, "consistent") == 1
    assert mismatch_ensemble.bulk_count(verdicts, "underconfident") == 0


def test_a_direction_sentence_gives_the_shares_by_factor_and_how_they_grow_with_the_size() -> None:
    text = _text(ROWS, SINGLE)
    assert (
        "c: with the assumed noise below the true noise, the ensemble mean is above the band for 100.0%, 90.0% and "
        "20.0% of the scored epochs at factors 0.5, 0.8 and 0.9, a share that rises or stays level as the mismatch "
        "grows." in text
    )
    assert (
        "c: with the assumed noise above the true noise, the ensemble mean is below the band for 95.0% and 90.0% "
        "of the scored epochs at factors 1.25 and 2, a share that does not keep rising as the mismatch grows." in text
    )


def test_a_share_that_is_the_same_at_every_factor_is_called_level_not_rising() -> None:
    rows = [r for r in ROWS if r["factor"] != 2.0] + [_row("c", 4.0, 0.05, 0.95, 0.0)]
    assert "95.0% and 95.0% of the scored epochs at factors 1.25 and 4, a share that is level." in _text(rows, SINGLE)


def test_the_true_noise_sentence_gives_the_three_shares_and_warns_when_it_is_not_inside_the_band() -> None:
    assert (
        "c: at the true noise (factor 1) the ensemble mean is inside the band for 90.0% of the scored epochs, below "
        "it for 10.0% and above it for 0.0%." in _text(ROWS, SINGLE)
    )
    assert "not inside the band for most" not in _text(ROWS, SINGLE)
    rows = [r if r["factor"] != 1.0 else _row("c", 1.0, 0.3, 0.7, 0.0) for r in ROWS]
    assert "not inside the band for most epochs, so for this case read the factors against each other" in _text(
        rows, SINGLE
    )


def test_a_mild_factor_is_resolved_when_outside_the_band_on_the_predicted_side_for_most_epochs_and_more_than_at_1() -> (
    None
):
    text = _text(ROWS, SINGLE)
    assert "c: of the mild factors 0.8, 0.9 and 1.25, the ensemble resolves 0.8 and 1.25 and not 0.9." in text
    # Below half of the epochs is not resolved, however far it is from the true noise; the same share at the
    # true noise is not resolved either.
    same_as_true = [r if r["factor"] != 0.8 else _row("c", 0.8, 0.0, 0.1, 0.9) for r in ROWS]
    same_as_true = [r if r["factor"] != 1.0 else _row("c", 1.0, 0.1, 0.0, 0.9) for r in same_as_true]
    assert "the ensemble resolves 1.25 and not 0.8 and 0.9." in _text(same_as_true, SINGLE)


def test_the_comparison_with_one_run_names_who_resolves_what() -> None:
    text = _text(ROWS, SINGLE)
    assert (
        "Against the single-run table, c, mild factors: both resolve 1.25; only the ensemble resolves 0.8; only one "
        "run resolves 0.9." in text
    )
    assert "neither resolves" not in text


def test_when_the_ensemble_resolves_nothing_the_page_says_so() -> None:
    flat = [_row("c", f, 0.9, 0.05, 0.05) for f in (0.8, 0.9, 1.0, 1.25)]
    single = [_single("c", f, "consistent=5") for f in (0.8, 0.9, 1.0, 1.25)]
    text = _text(flat, single)
    assert "the ensemble resolves none of them." in text
    assert "neither resolves 0.8, 0.9 and 1.25." in text
    assert "The ensemble does not resolve every mild mismatch" in text
    assert "resolves some mild mismatch that one run does not" not in text


def test_the_closing_sentences_list_what_the_ensemble_adds_and_what_it_misses() -> None:
    text = _text(ROWS, SINGLE)
    assert "The ensemble resolves some mild mismatch that one run does not: c at 0.8." in text
    assert "The ensemble does not resolve every mild mismatch: c at 0.9." in text
    assert "One run resolves some mild mismatch that the ensemble does not: c at 0.9." in text


def test_the_outage_scope_gets_its_own_sentences_and_no_comparison_with_one_run() -> None:
    rows = ROWS + [_row("c", f, 0.9, 0.05, 0.05, scope="outage") for f in (0.8, 0.9, 1.0, 1.25)]
    text = _text(rows, SINGLE)
    assert "c (outage scope): of the mild factors 0.8, 0.9 and 1.25, the ensemble resolves none of them." in text
    assert text.count("Against the single-run table") == 1


def test_a_factor_missing_from_the_single_run_table_is_left_out_of_the_comparison() -> None:
    single = [s for s in SINGLE if s["scale"] != 0.8]
    text = _text(ROWS, single)
    assert "both resolve 1.25; only one run resolves 0.9." in text


def test_a_sweep_with_no_mild_factor_has_no_resolution_sentences() -> None:
    rows = [r for r in ROWS if r["factor"] in (0.5, 1.0, 2.0)]
    text = _text(rows, SINGLE)
    assert "mild factors" not in text and "Against the single-run table" not in text


def test_the_block_is_the_table_then_the_rules_then_the_sentences() -> None:
    block = mismatch_ensemble.page_block(ROWS, SINGLE)
    table = mismatch_ensemble.markdown_table(ROWS)
    assert block.startswith(table + "\n\n")
    assert "My rule for resolved" in block
    assert block.endswith(mismatch_ensemble.findings(ROWS, SINGLE)[-1])
    assert all(f"- {line}" in block for line in mismatch_ensemble.findings(ROWS, SINGLE))


# --- the committed files -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return mismatch_ensemble.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def single() -> list[dict[str, Any]]:
    return mismatch_sweep.read_csv(SINGLE_CSV)


def test_the_page_block_is_what_the_rules_give_for_the_committed_csvs(rows, single) -> None:
    page = PAGE.read_text(encoding="utf-8")
    assert page == mismatch_ensemble.splice_table(page, mismatch_ensemble.page_block(rows, single))


def test_the_committed_file_is_the_documented_ensemble_on_seeds_25_to_49(rows) -> None:
    assert CSV.read_text(encoding="utf-8").splitlines()[0] == ",".join(mismatch_ensemble.CSV_FIELDS)
    assert {(r["n_runs"], r["dof"]) for r in rows} == {(25, 3)}
    assert all((r["band_low"], r["band_high"]) == ensemble_nees_band(25, 3) for r in rows)
    assert (mismatch_ensemble.FIRST_SEED, mismatch_ensemble.N_RUNS) == (25, 25)


def test_the_ensemble_grid_is_the_single_run_grid(rows, single) -> None:
    assert {(r["case"], r["factor"]) for r in rows} == {(r["case"], r["scale"]) for r in single}
    assert {r["case"] for r in rows if r["scope"] == "outage"} == {"outage_control"}


def test_the_page_describes_the_ensemble_without_the_word_calibrated() -> None:
    text = PAGE.read_text(encoding="utf-8")
    start = text.index("## The ensemble over seeds")
    section = text[start : text.index("## What this does not show")]
    assert not re.search(r"\bcalibrated\b", section.lower())


def test_the_page_does_not_say_the_ensemble_is_the_tool_that_can_resolve_a_mild_mismatch() -> None:
    text = " ".join(PAGE.read_text(encoding="utf-8").split())
    assert "is the tool that can resolve a mild mismatch" not in text
    assert "(calibration.md#the-ensemble-over-seeds)" in text


def test_the_ensemble_resolves_a_mild_mismatch_one_run_does_not_and_misses_another(rows, single) -> None:
    """What the corrected claim on the page rests on, computed from the committed CSVs."""
    got = mismatch_ensemble.resolution(rows, single)
    assert got["only_ensemble"], "the page says the ensemble resolves some mild mismatch that one run does not"
    assert got["unresolved"], "the page says the ensemble does not resolve every mild mismatch"


def test_the_true_noise_row_of_outage_control_depends_on_the_seeds(rows) -> None:
    """The page says it: on seeds 25 to 49 the outage scope at the true noise is below the band, on 0 to 24 inside."""
    here = next(r for r in rows if (r["case"], r["factor"], r["scope"]) == ("outage_control", 1.0, "outage"))
    there = next(
        r
        for r in ensemble.parse_csv(BENCHMARK_CSV.read_text(encoding="utf-8"))
        if (r["case"], r["scope"]) == ("outage_control", "outage")
    )
    assert here["fraction_below"] > 0.5
    assert there["fraction_inside"] > 0.9
    text = " ".join(PAGE.read_text(encoding="utf-8").split())
    assert "depends on the seeds" in text
