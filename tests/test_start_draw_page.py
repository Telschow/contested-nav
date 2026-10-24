"""The start-draw section of ``docs/results.md`` is the committed CSV, and each sentence in it holds for the rows.

The study is ``navkit sweep start-draw`` (issue #168). This file reads the CSV and the page, so it runs in a
documentation-only pull request. It recomputes every statement from the rows and does not trust the page's own
words. The mechanism is not tested here and the page must say so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from navkit import start_draw_study as sds
from navkit.estimators.eskf import EskfConfig

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "start_draw_study.csv"
PAGE = ROOT / "docs" / "results.md"
CONFIG = ROOT / "configs" / "benchmark.yaml"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return sds.parse_csv(CSV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def section() -> str:
    page = PAGE.read_text(encoding="utf-8")
    inner = page.split(sds.START, 1)[1].split(sds.END, 1)[0]
    return " ".join(inner.split())


# ------------------------------------------------------------------------------------------ the file


def test_the_csv_has_one_row_per_case_variant_and_development_seed(rows):
    keys = [(r["case"], r["variant"], r["seed"]) for r in rows]
    assert keys == [(c, v, s) for c in sds.CASES for v in sds.VARIANTS for s in range(10)]
    assert max(r["seed"] for r in rows) < sds.HELD_OUT_FROM


def test_the_csv_text_is_what_the_writer_produces(rows):
    assert CSV.read_text(encoding="utf-8") == sds.csv_text(rows)


def test_the_page_section_is_the_committed_csv(rows):
    page = PAGE.read_text(encoding="utf-8")
    assert page == sds.splice_section(page, sds.markdown_section(rows))


def test_every_cell_of_the_table_is_recomputed_from_the_rows(rows, section):
    for case in sds.CASES:
        medians = [f"{sds.median_ate(rows, case, v):.2f} m" for v in sds.VARIANTS]
        full, without = sds.series(rows, case, "full"), sds.series(rows, case, "no_attitude")
        k = sum(full[s] > without[s] for s in range(10))
        assert f"| `{case}` | {' | '.join(medians)} | {k} of 10 |" in section, case


def test_a_fresh_run_of_seed_zero_matches_the_committed_rows(rows):
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    fresh = sds.run_study(doc, [0])
    committed = [r for r in rows if r["seed"] == 0]
    assert sds.compare(fresh, committed) == []


# ------------------------------------------------------------------------------------------ the sentences


def test_the_single_anchor_median_is_several_times_larger_with_the_attitude_drawn(rows, section):
    assert "several times larger with the attitude drawn than without it" in section
    for case in sds.SINGLE_ANCHOR:
        ratio = sds.median_ate(rows, case, "full") / sds.median_ate(rows, case, "no_attitude")
        assert ratio >= sds.SEVERAL, (case, ratio)


def test_with_only_the_attitude_drawn_the_median_is_close_to_the_full_draw(rows, section):
    assert "with only the attitude drawn it is close to the full-draw median" in section
    for case in sds.SINGLE_ANCHOR:
        full, only = sds.median_ate(rows, case, "full"), sds.median_ate(rows, case, "attitude_only")
        assert abs(only - full) / full <= sds.CLOSE, case


def test_the_attitude_part_is_what_the_single_anchor_ate_depends_on(rows):
    """Removing the attitude moves the median far more than removing position and velocity does."""
    for case in sds.SINGLE_ANCHOR:
        full = sds.median_ate(rows, case, "full")
        without_attitude = sds.median_ate(rows, case, "no_attitude")
        attitude_only = sds.median_ate(rows, case, "attitude_only")
        assert abs(full - without_attitude) > 4 * abs(full - attitude_only), case


def test_without_vision_the_attitude_draw_moves_the_median_by_less_than_a_factor_of_two(rows, section):
    assert "by less than a factor of two" in section
    medians = [sds.median_ate(rows, "outage_control", v) for v in sds.VARIANTS]
    assert max(medians) / min(medians) < 2.0


def test_the_clone_stays_within_a_quarter_of_its_mean_in_every_seed(rows, section):
    assert "within a quarter of their mean" in section
    assert sds.CLONE_TOLERANCE == 0.25
    assert sds.clone_spread(rows, "ate_rmse_m") < sds.CLONE_TOLERANCE
    assert sds.clone_spread(rows, "nees_mean") < sds.CLONE_TOLERANCE


def test_the_attitude_prior_quoted_is_the_one_the_filter_declares(section):
    assert f"{EskfConfig.__dataclass_fields__['initial_rot_sigma_deg'].default:g} degrees per axis" in section


def test_the_mechanism_is_called_a_hypothesis_and_is_not_claimed(section):
    assert "HYPOTHESIS" in section and "was not tested here" in section
    for word in ("because", "caused by", "proves", "demonstrates"):
        assert word not in section


# ------------------------------------------------------------------------------------------ the code


def test_the_study_refuses_held_out_seeds():
    with pytest.raises(ValueError, match="held-out"):
        sds.run_study({}, [99, 100])
    with pytest.raises(SystemExit):
        sds.main(["--csv", "unused.csv", "--seeds", "98-101"])


def test_the_variants_change_only_the_parts_they_name():
    import numpy as np

    from navkit.benchmark import StartError

    err = StartError(dp=np.ones(3), dv=2 * np.ones(3), dtheta=3 * np.ones(3))
    a = sds.HOOKS["no_attitude"](err)
    assert np.array_equal(a.dtheta, np.zeros(3)) and np.array_equal(a.dp, err.dp) and np.array_equal(a.dv, err.dv)
    b = sds.HOOKS["attitude_only"](err)
    assert np.array_equal(b.dtheta, err.dtheta) and not b.dp.any() and not b.dv.any()
    assert sds.HOOKS["full"](err) is err


def test_compare_names_a_difference():
    base = [{"case": "c", "variant": "full", "seed": 0, "ate_rmse_m": 1.0, "nees_mean": 2.0}]
    assert sds.compare(base, [dict(base[0])]) == []
    changed = [{**base[0], "ate_rmse_m": 1.1}]
    assert sds.compare(changed, base)
