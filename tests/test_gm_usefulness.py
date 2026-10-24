"""The usefulness diagnostic in scenario S2 (``navkit gate usefulness-s2``).

It runs a few Gauss-Markov subjects and the plain clone through the gate of ADR-0030 in S2 on development seeds and
reports, next to the six conditions, how the candidate compares with the no-vision control seed by seed. The functions
are tested here with an injected runner (no case is run) and once with a tiny real run for determinism. The committed
CSV and the page section are checked in ``test_gm_usefulness_page.py``.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from navkit import gm_usefulness as gu
from navkit.scale_tuning import SEED_LIMIT

CONDITIONS = ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]
N = 25
K = 40
CONTROL_ATE = np.full(N, 10.0)


def _arrays(y_mean: float, ratios: np.ndarray, seed: int = 0) -> dict[str, np.ndarray]:
    """Gate inputs: per-run mean NEES near ``y_mean`` (3 dof, effective sample size 6), unit errors against unit sigma,
    and a window ATE equal to the control's times ``ratios``."""
    rng = np.random.default_rng(seed)
    return {
        "y": y_mean * rng.chisquare(18, N) / 18,
        "n_eff": np.full(N, 6.0),
        "err": rng.normal(0.0, 1.0, (N, K, 3)),
        "sigma": np.ones((N, K, 3)),
        "ate": CONTROL_ATE * ratios,
    }


GOOD_RATIOS = np.full(N, 0.4)
#: Better than the control in only 19 of 25 seeds and one seed far worse: the usefulness conditions fail.
WEAK_RATIOS = np.concatenate([np.full(19, 0.4), np.full(5, 1.3), [2.7]])


def fake_runner(gm_099_ratios: np.ndarray = WEAK_RATIOS):
    """The plain clone is overconfident (y about 40); both Gauss-Markov subjects are consistent."""

    def run(estimator: dict, seeds: list[int]) -> dict[str, np.ndarray]:
        if not estimator.get("vision_gm_error"):
            return _arrays(40.0, np.full(N, 0.7), seed=1)
        ratios = gm_099_ratios if estimator["vision_gm_rho"] == 0.99 else WEAK_RATIOS
        return _arrays(3.0, ratios, seed=2)

    return run


def _rows(runner=None):
    return gu.run_usefulness(runner=runner or fake_runner(), control_ate=CONTROL_ATE)


def test_the_defaults_are_the_three_subjects_on_the_development_seeds():
    assert list(gu.SEEDS) == list(range(25, 50))
    assert [s.estimator for s in gu.SUBJECTS] == [
        {"vision_model": "clone"},
        {"vision_model": "clone", "vision_gm_error": True, "vision_gm_tau_s": 2.0, "vision_gm_rho": 0.9},
        {"vision_model": "clone", "vision_gm_error": True, "vision_gm_tau_s": 2.0, "vision_gm_rho": 0.99},
    ]


def test_every_subject_has_the_six_conditions_and_the_comparison_with_the_control():
    rows = _rows()
    assert len(rows) == 3 * 6
    for subject in {r["subject"] for r in rows}:
        group = [r for r in rows if r["subject"] == subject]
        assert [r["condition"] for r in group] == CONDITIONS
        first = group[0]
        assert first["scenario"] == "S2" and first["seeds"] == "25-49" and first["runs"] == N
        assert first["control_ate_median_m"] == 10.0
        assert len({r["better_count"] for r in group}) == 1  # the same summary on each of the subject's rows


def test_the_summary_is_computed_from_the_per_seed_ratios():
    rows = _rows()
    weak = next(r for r in rows if r["subject"] == gu.SUBJECTS[2].label)
    assert weak["better_count"] == 19
    assert weak["ratio_max"] == pytest.approx(2.7)
    assert weak["ratio_median"] == pytest.approx(0.4)
    assert weak["ratio_p90"] == pytest.approx(float(np.percentile(WEAK_RATIOS, 90)))
    assert weak["candidate_ate_median_m"] == pytest.approx(4.0)


def test_the_conditions_come_from_the_gate_of_adr_0030():
    rows = _rows()
    plain = {r["condition"]: r for r in rows if r["subject"] == gu.SUBJECTS[0].label}
    gm = {r["condition"]: r for r in rows if r["subject"] == gu.SUBJECTS[1].label}
    assert not plain["upper"]["holds"]
    assert all(gm[c]["holds"] for c in ("upper", "lower", "coverage"))
    assert not gm["better"]["holds"] and not gm["worst_ratio"]["holds"]
    assert not gm["better"]["scenario_passed"]
    assert gm["better"]["threshold"] == 20 and gm["worst_ratio"]["threshold"] == 1.5


def test_the_csv_round_trips_and_is_deterministic():
    rows = _rows()
    text = gu.csv_text(rows)
    assert text == gu.csv_text(_rows())
    assert gu.parse_csv(text) == rows
    assert text.splitlines()[0] == ",".join(gu.CSV_FIELDS)


def test_a_seed_from_100_is_refused_before_any_case_runs():
    def never(estimator, seeds):
        raise AssertionError("a case was run")

    for seeds in (
        range(SEED_LIMIT - 2, SEED_LIMIT + 2),
        [SEED_LIMIT + 25, SEED_LIMIT + 26],
        [SEED_LIMIT, SEED_LIMIT + 1],
    ):
        with pytest.raises(ValueError, match="development seed"):
            gu.run_usefulness(runner=never, seeds=seeds, control_ate=np.ones(len(list(seeds))))


def test_the_command_takes_no_seed_option():
    with pytest.raises(SystemExit):
        gu.build_parser().parse_args(["--csv", "x.csv", "--seeds", "100-124"])


def test_the_sentences_follow_the_rows_and_hedge():
    text = " ".join(gu.sentences(_rows()).split())
    assert "for the plain clone (no model): the NEES conditions do not all hold" in text
    assert "NEES conditions hold" in text and "usefulness conditions are not met" in text
    assert "does not change which conditions hold" in text
    assert "does not show that no estimator" in text


def test_the_sentence_about_a_more_exact_model_changes_when_the_rows_do():
    better = np.full(N, 0.4)  # the near-exact subject now meets the usefulness conditions
    text = " ".join(gu.sentences(_rows(fake_runner(better))).split())
    assert "changes which conditions hold" in text and "does not change which conditions hold" not in text


def test_the_sentences_use_none_of_the_words_the_page_tests_forbid():
    low = (gu.sentences(_rows()) + gu.markdown_section(_rows())).lower()
    assert not re.search(r"\bcalibrated\b", low)
    for forbidden in ("b1 is closed", "gate passes", "gate fails", "meets the gate"):
        assert forbidden not in low, forbidden


def test_a_tiny_real_run_is_deterministic():
    seeds = [25, 26, 27]
    subjects = gu.SUBJECTS[:2]
    a = gu.run_usefulness(seeds=seeds, subjects=subjects)
    b = gu.run_usefulness(seeds=seeds, subjects=subjects)
    assert gu.csv_text(a) == gu.csv_text(b)
    assert {r["runs"] for r in a} == {3} and {r["seeds"] for r in a} == {"25-27"}
