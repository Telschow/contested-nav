"""The correlated-GNSS section of ``docs/urbannav.md`` is the committed CSV, and each sentence in it holds for the rows.

The study is ``navkit sweep correlated-gnss`` (issue #183). This file reads the CSV and the page, so it runs in a
documentation-only pull request. It recomputes every number and the verdict from the rows and does not trust the page's
own words. The page must not claim a mechanism or a result on the real receiver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit import correlated_gnss_study as cg
from navkit.report.page import splice_block

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "correlated_gnss.csv"
PAGE = ROOT / "docs" / "urbannav.md"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return cg.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    inner = PAGE.read_text(encoding="utf-8").split(cg.START, 1)[1].split(cg.END, 1)[0]
    return " ".join(inner.split())


def test_the_csv_has_one_row_per_case_and_development_seed(rows):
    assert [(r["case"], r["seed"]) for r in rows] == [(c, s) for c in cg.CASES for s in range(10)]
    assert max(r["seed"] for r in rows) < cg.HELD_OUT_FROM


def test_the_csv_text_is_what_the_writer_produces(rows):
    assert CSV.read_text(encoding="utf-8") == cg.csv_text(rows)


def test_the_page_section_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "correlated-gnss", cg.markdown_section(rows))


def test_every_cell_of_the_table_is_recomputed_from_the_rows(rows, section):
    for case in cg.CASES:
        mine = [r for r in rows if r["case"] == case]
        seen, rejected = sum(r["fixes_seen"] for r in mine), sum(r["fixes_rejected"] for r in mine)
        nis = sum(r["mean_nis"] for r in mine) / len(mine)
        nees = sum(r["nees_mean"] for r in mine) / len(mine)
        assert f"| {cg.LABELS[case]} | {seen} | {rejected} (" in section, case
        assert f"| {nis:.2f} | {nees:.1f} |" in section, case


def test_the_verdict_sentence_follows_the_declared_criteria(rows, section):
    c = cg.summarise(rows)["correlated"]
    expected = "met" if cg.gate_is_blind(c) else "not met"
    assert f"The criteria were {expected}." in section
    assert f"rejected {c['rejected']} of {c['seen']} fixes" in section


def test_the_declared_size_and_time_are_on_the_page(section):
    assert f"{cg.CORR_SIGMA_M:g} m" in section and f"{cg.CORR_TAU_S:g} s" in section
    assert "declared before the run" in section


def test_the_page_claims_no_mechanism_and_no_result_on_the_real_receiver(section):
    assert "Synthetic, not the real receiver" in section
    assert "why Deep-Urban-1 behaved as it did" in section
    assert "overconfident control" in section  # the single-anchor row is kept and labelled
