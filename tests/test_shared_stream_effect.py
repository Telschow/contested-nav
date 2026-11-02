"""The shared-stream study (#259): the two seedings, the refusal of held-out seeds, the rows and the page."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import shared_stream_effect as sse
from navkit.report.page import splice_block

pytestmark = pytest.mark.docs_only


def _normals(seed: int, n: int = 453) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def test_shared_seeding_gives_gnss_and_vision_the_same_normals():
    gnss, vision = sse.stream_seeds(3, "shared")
    assert gnss == vision == 3
    assert np.array_equal(_normals(gnss), _normals(vision))


def test_independent_seeding_shares_no_normal_between_the_streams():
    for seed in (0, 1, 7):
        gnss, vision = sse.stream_seeds(seed, "independent")
        assert gnss == seed
        assert vision != gnss
        assert not set(_normals(gnss)) & set(_normals(vision))


def test_the_study_refuses_held_out_seeds():
    with pytest.raises(ValueError, match="held-out"):
        sse.run_study({}, [99, 100])


# ------------------------------------------------------------------------------------------ the committed files

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "shared_stream_effect.csv"
PAGE = ROOT / "docs" / "calibration.md"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return sse.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.mark.docs_only
def test_the_csv_has_one_row_per_case_and_development_seed_and_the_control_row(rows):
    assert [(r["case"], r["seed"]) for r in rows] == [(c, s) for c in sse.CASES for s in range(10)]
    assert sse.SINGLE_ANCHOR in sse.CASES


@pytest.mark.docs_only
def test_the_csv_text_is_what_the_writer_produces(rows):
    assert CSV.read_text(encoding="utf-8") == sse.csv_text(rows)


@pytest.mark.docs_only
def test_each_difference_is_independent_minus_shared(rows):
    for r in rows:
        for m in sse.METRICS:
            assert r[f"{m}_diff"] == pytest.approx(r[f"{m}_independent"] - r[f"{m}_shared"])


@pytest.mark.docs_only
def test_the_page_section_is_the_committed_csv_and_carries_the_label(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == splice_block(page, "shared-stream", sse.markdown_section(rows))
    assert sse.LABEL in sse.markdown_section(rows)


def test_compare_names_a_difference():
    base = [{f: (0.0 if f not in ("case", "seed") else "c" if f == "case" else 0) for f in sse.CSV_FIELDS}]
    assert sse.compare(base, [dict(base[0])]) == []
    assert sse.compare([{**base[0], "nees_mean_shared": 1.0}], base)


def test_the_independent_seeding_leaves_the_default_seeds_alone():
    assert sse.stream_seeds(5, "shared") == (5, 5)
    with pytest.raises(ValueError):
        sse.stream_seeds(5, "other")
