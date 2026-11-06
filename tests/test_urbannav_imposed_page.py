"""The statements of the "Imposed outages" section of docs/urbannav.md, each tied to the committed CSV.

The tests read the committed CSV, so CI runs them without the dataset (S2).
"""

from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path

import pytest

from navkit import urbannav_imposed as imp

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "docs" / "data" / "urbannav_imposed.csv"
PAGE = ROOT / "docs" / "urbannav.md"
VARIANTS = ("declared", "per_fix")
SEEDS = 5
SHORT, MIDDLE, LONG = (imp.row_sequence("deepurban1", o) for o in imp.IMPOSED["deepurban1"])


def _values(sequence: str, variant: str, quantity: str) -> list[float]:
    with CSV.open(newline="", encoding="utf-8") as f:
        v = [
            float(r["value"])
            for r in csv.DictReader(f)
            if r["sequence"] == sequence and r["variant"] == variant and r["quantity"] == quantity
        ]
    assert len(v) == SEEDS, f"{sequence} {variant} {quantity}: {len(v)} rows"
    return v


def _median(sequence: str, variant: str, quantity: str) -> float:
    return statistics.median(_values(sequence, variant, quantity))


def _section() -> str:
    return PAGE.read_text(encoding="utf-8").split("## Imposed outages", 1)[1].split("\n## ", 1)[0]


def test_the_csv_holds_only_the_three_declared_outages_and_the_two_variants() -> None:
    with CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["sequence"] for r in rows} == {SHORT, MIDDLE, LONG}
    assert {r["variant"] for r in rows} == set(VARIANTS)


def test_statement_the_short_outage_is_taken_back_without_a_rejection() -> None:
    for v in VARIANTS:
        assert _values(SHORT, v, "gnss_updates_rejected") == [0.0] * SEEDS
        assert _values(SHORT, v, "gnss_channel_faulted") == [0.0] * SEEDS
    assert "After the short outage the filter takes every returning fix, in both variants" in _section()


def test_statement_the_middle_outage_recovers_but_ends_with_an_error_above_the_claim() -> None:
    for v in VARIANTS:
        assert _values(MIDDLE, v, "gnss_updates_rejected") == [0.0] * SEEDS
        assert _median(MIDDLE, v, "hor_err_median_after_m") < 3 * _median(MIDDLE, v, "hor_err_median_before_m")
        assert _median(MIDDLE, v, "hor_err_at_end_m") > _median(MIDDLE, v, "hor_claimed_at_end_m")
    assert "ends the outage with a" in _section().replace("\n  ", " ")


def test_statement_the_long_outage_is_not_recovered_from_in_any_seed() -> None:
    for v in VARIANTS:
        assert _values(LONG, v, "gnss_channel_faulted") == [1.0] * SEEDS
        assert _values(LONG, v, "gnss_reaccepted") == [0.0] * SEEDS
        assert _values(LONG, v, "gnss_updates_rejected") == _values(LONG, v, "fixes_after_outage")
        for after, before in zip(
            _values(LONG, v, "hor_err_median_after_m"), _values(LONG, v, "hor_err_median_before_m"), strict=True
        ):
            assert after > 100 * before
    assert "rejects every returning fix, in both variants and in every seed" in _section()


def test_statement_the_error_at_the_end_of_the_outage_grows_with_its_length() -> None:
    for v in VARIANTS:
        e = [_median(s, v, "hor_err_at_end_m") for s in (SHORT, MIDDLE, LONG)]
        assert e[0] < e[1] < e[2]
    assert "grows with the length of the outage" in _section()


def test_the_section_states_its_scope_and_types_no_numbers() -> None:
    text = _section()
    for phrase in ("imposed and are not the receiver's own", "One sequence, one receiver", "why the long outage"):
        assert phrase in text
    prose = text.replace("issue #95", "").replace("Deep-Urban-1", "")
    assert not re.search(r"\d", prose), re.findall(r".{20}\d.{20}", prose)
