"""The tuning run of the adaptive visual scale (ADR-0031): the grid, the margins, the selection rule, the decision, the
seed refusal and the CSV.

The pure parts are tested on hand-built tables, so that no case is run. Two tests run real cases on seeds 0 and 1 only,
to check that the evaluator is deterministic and wired to the gate of ADR-0030. No seed from 100 up is run anywhere.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from navkit import candidate_gate as cg_run
from navkit import cli
from navkit import scale_tuning as st
from navkit.estimators.eskf import EskfConfig
from navkit.eval.candidate_gate import ScenarioGateResult
from navkit.eval.gate import Condition
from navkit.io.imu import ImuNoiseModel
from navkit.report.page import splice_block

#: ADR-0031's twelve points, written out here from the ADR: tau in {2, 5, 10} s, s_min in {0.25, 0.5}, s_max in {8, 16}.
ADR_POINTS = {
    (2.0, 0.25, 8.0),
    (2.0, 0.25, 16.0),
    (2.0, 0.5, 8.0),
    (2.0, 0.5, 16.0),
    (5.0, 0.25, 8.0),
    (5.0, 0.25, 16.0),
    (5.0, 0.5, 8.0),
    (5.0, 0.5, 16.0),
    (10.0, 0.25, 8.0),
    (10.0, 0.25, 16.0),
    (10.0, 0.5, 8.0),
    (10.0, 0.5, 16.0),
}


# ------------------------------------------------------------------------------------------------ builders


def _cond(name: str, relation: str, value: float, threshold: float) -> Condition:
    ok = value <= threshold if relation == "<=" else value >= threshold
    return Condition(name, value, threshold, relation, ok)


def _scenario(margin: float, others: float = 0.5) -> ScenarioGateResult:
    """A scenario result whose smallest margin is ``margin`` (on ``upper``) and whose other margins are ``others``."""
    conditions = (
        _cond("upper", "<=", 1.0 - margin, 1.0),
        _cond("lower", ">=", 1.0 + others, 1.0),
        _cond("coverage", ">=", 0.95 * (1.0 + others), 0.95),
        _cond("better", ">=", 20.0 * (1.0 + others), 20.0),
        _cond("median_ratio", "<=", 0.8 * (1.0 - others), 0.8),
        _cond("worst_ratio", "<=", 1.5 * (1.0 - others), 1.5),
    )
    return ScenarioGateResult(
        *conditions,
        passed=all(c.passed for c in conditions),
        n_runs=25,
        m=4.0,
        upper_quantile=0.975,
        dof=3,
    )


def _result(point: st.GridPoint, margin_s1: float, margin_s2: float | None = None, seeds=range(25)) -> st.PointResult:
    return st.PointResult(
        point=point,
        seeds=tuple(seeds),
        s1=_scenario(margin_s1),
        s2=_scenario(margin_s1 if margin_s2 is None else margin_s2),
    )


def _point(tau: float, s_min: float, s_max: float) -> st.GridPoint:
    return st.GridPoint(tau, s_min, s_max)


# ------------------------------------------------------------------------------------------------- the grid


def test_the_grid_is_the_twelve_points_of_adr_0031_and_no_others():
    assert len(st.GRID) == 12
    assert {(p.tau_s, p.s_min, p.s_max) for p in st.GRID} == ADR_POINTS


def test_the_grid_axes_are_the_values_the_adr_states():
    # The sentence of the ADR itself is checked in test_scale_tuning_page.py, which reads the documents.
    assert st.GRID_TAU_S == (2.0, 5.0, 10.0)
    assert st.GRID_S_MIN == (0.25, 0.5)
    assert st.GRID_S_MAX == (8.0, 16.0)


def test_the_grid_order_is_tau_then_s_min_then_s_max():
    keys = [(p.tau_s, p.s_min, p.s_max) for p in st.GRID]
    assert keys == sorted(keys)


def test_the_seed_blocks_are_the_development_seeds_of_the_adr():
    assert list(st.GRID_SEEDS) == list(range(0, 25))
    assert {k: list(v) for k, v in st.CONFIRMATION_BLOCKS.items()} == {
        "confirm 25-49": list(range(25, 50)),
        "confirm 50-74": list(range(50, 75)),
        "confirm 75-99": list(range(75, 100)),
    }
    every = [*st.GRID_SEEDS, *(s for block in st.CONFIRMATION_BLOCKS.values() for s in block)]
    assert max(every) < 100
    assert len(set(every)) == len(every)


@pytest.mark.parametrize("point", st.GRID, ids=lambda p: p.label)
def test_every_point_is_a_clone_with_the_scale_on_and_no_preset(point):
    est = point.estimator()
    assert est == {
        "vision_model": "clone",
        "vision_adaptive_scale": True,
        "vision_scale_tau_s": point.tau_s,
        "vision_scale_min": point.s_min,
        "vision_scale_max": point.s_max,
    }
    assert "vision_noise_preset" not in est
    cfg = EskfConfig(imu_noise=ImuNoiseModel(), **est)  # the constructor refuses a setting the filter would refuse
    assert cfg.vision_adaptive_scale and cfg.vision_model == "clone"


# ----------------------------------------------------------------------------------------------- margins


def test_the_margin_of_an_at_most_condition_is_the_distance_below_the_threshold_in_units_of_the_threshold():
    assert st.condition_margin(_cond("upper", "<=", 3.0, 4.0)) == pytest.approx(0.25)
    assert st.condition_margin(_cond("worst_ratio", "<=", 1.2, 1.5)) == pytest.approx(0.2)


def test_the_margin_of_an_at_least_condition_is_the_distance_above_the_threshold_in_units_of_the_threshold():
    assert st.condition_margin(_cond("lower", ">=", 2.0, 1.32)) == pytest.approx((2.0 - 1.32) / 1.32)


def test_the_margin_of_the_count_condition_is_the_count_minus_twenty_over_twenty():
    assert st.condition_margin(_cond("better", ">=", 25.0, 20.0)) == pytest.approx(0.25)
    assert st.condition_margin(_cond("better", ">=", 20.0, 20.0)) == 0.0
    assert st.condition_margin(_cond("better", ">=", 19.0, 20.0)) == pytest.approx(-0.05)


def test_the_margin_of_the_coverage_condition_is_the_value_minus_095_over_095():
    assert st.condition_margin(_cond("coverage", ">=", 0.97, 0.95)) == pytest.approx((0.97 - 0.95) / 0.95)
    assert st.condition_margin(_cond("coverage", ">=", 0.9, 0.95)) < 0.0


def test_a_failed_condition_has_a_negative_margin_and_a_condition_on_its_threshold_has_zero():
    assert st.condition_margin(_cond("upper", "<=", 5.0, 4.0)) == pytest.approx(-0.25)
    assert st.condition_margin(_cond("upper", "<=", 4.0, 4.0)) == 0.0


@pytest.mark.parametrize("threshold", [0.0, -1.0, math.inf, math.nan])
def test_a_margin_with_no_usable_threshold_is_refused_and_not_invented(threshold):
    with pytest.raises(ValueError, match="margin"):
        st.condition_margin(Condition("upper", 1.0, threshold, "<=", False))


def test_a_margin_of_a_value_that_is_not_finite_is_refused():
    with pytest.raises(ValueError, match="margin"):
        st.condition_margin(Condition("upper", math.nan, 1.0, "<=", False))


def test_an_unknown_relation_is_refused():
    with pytest.raises(ValueError, match="relation"):
        st.condition_margin(Condition("upper", 1.0, 1.0, "==", True))


def test_the_scenario_margin_is_the_smallest_of_its_six_margins():
    assert st.scenario_margin(_scenario(0.3, others=0.5)) == pytest.approx(0.3)
    assert st.scenario_margin(_scenario(0.9, others=0.5)) == pytest.approx(0.5)


def test_the_score_of_a_point_is_the_smallest_margin_in_both_scenarios_and_not_the_largest():
    r = _result(_point(5, 0.5, 8), margin_s1=0.4, margin_s2=0.1)
    assert r.score == pytest.approx(0.1)
    r = _result(_point(5, 0.5, 8), margin_s1=0.1, margin_s2=0.4)
    assert r.score == pytest.approx(0.1)
    r = _result(_point(5, 0.5, 8), margin_s1=0.45, margin_s2=0.49)
    assert r.score == pytest.approx(0.45)


def test_a_point_qualifies_only_when_the_gate_passes_in_both_scenarios():
    p = _point(5, 0.5, 8)
    assert _result(p, 0.2, 0.2).qualifies
    assert not _result(p, 0.2, -0.1).qualifies
    assert not _result(p, -0.1, 0.2).qualifies
    assert not _result(p, -0.1, -0.1).qualifies


# --------------------------------------------------------------------------------------------- selection


def test_the_chosen_point_is_the_qualifying_one_with_the_largest_score():
    a, b, c = _point(2, 0.5, 8), _point(5, 0.5, 8), _point(10, 0.5, 8)
    results = [_result(a, 0.10), _result(b, 0.30), _result(c, 0.20)]
    assert st.select_point(results).point == b


def test_a_point_that_does_not_qualify_is_never_chosen_whatever_its_score():
    a, b = _point(2, 0.5, 8), _point(5, 0.5, 8)
    failing = _result(a, 0.30, -0.01)  # a high score in S1 does not help: the score is the smaller one, and it fails
    assert not failing.qualifies
    assert st.select_point([failing, _result(b, 0.05)]).point == b


def test_a_tie_goes_to_the_smaller_tau():
    results = [_result(_point(10, 0.5, 8), 0.2), _result(_point(2, 0.5, 8), 0.2), _result(_point(5, 0.5, 8), 0.2)]
    assert st.select_point(results).point == _point(2, 0.5, 8)


def test_a_tie_on_tau_goes_to_the_larger_s_min():
    results = [_result(_point(5, 0.25, 8), 0.2), _result(_point(5, 0.5, 8), 0.2)]
    assert st.select_point(results).point == _point(5, 0.5, 8)


def test_a_tie_on_tau_and_s_min_goes_to_the_smaller_s_max():
    results = [_result(_point(5, 0.5, 16), 0.2), _result(_point(5, 0.5, 8), 0.2)]
    assert st.select_point(results).point == _point(5, 0.5, 8)


def test_the_tie_rule_applies_in_the_order_tau_then_s_min_then_s_max():
    # all tied: the smaller tau wins even though its s_min is smaller and its s_max larger
    results = [_result(_point(5, 0.5, 8), 0.2), _result(_point(2, 0.25, 16), 0.2)]
    assert st.select_point(results).point == _point(2, 0.25, 16)
    # tied on tau: the larger s_min wins even though its s_max is larger
    results = [_result(_point(5, 0.5, 16), 0.2), _result(_point(5, 0.25, 8), 0.2)]
    assert st.select_point(results).point == _point(5, 0.5, 16)


def test_a_score_that_differs_in_the_last_place_is_not_a_tie():
    low = _result(_point(2, 0.5, 8), 0.2)
    high = _result(_point(10, 0.25, 16), math.nextafter(0.2, 1.0))
    assert high.score > low.score
    assert st.select_point([low, high]).point == _point(10, 0.25, 16)


def test_no_qualifying_point_gives_no_choice():
    results = [_result(_point(2, 0.5, 8), -0.1), _result(_point(5, 0.5, 8), 0.2, -0.2)]
    assert st.select_point(results) is None
    assert st.select_point([]) is None


# ---------------------------------------------------------------------------------------------- decision


def _confirmations(point: st.GridPoint, margins: dict[str, float]) -> dict[str, st.PointResult]:
    return {label: _result(point, margins[label], seeds=st.CONFIRMATION_BLOCKS[label]) for label in margins}


ALL_PASS = {"confirm 25-49": 0.1, "confirm 50-74": 0.1, "confirm 75-99": 0.1}


def test_no_qualifying_point_is_failed_on_development_seeds():
    results = [_result(p, -0.1) for p in st.GRID]
    out = st.decide(results, None)
    assert not out.passed
    assert out.chosen is None
    assert out.kind == "no_point_qualified"
    assert out.failed_blocks == ()


def test_a_chosen_point_that_passes_every_block_is_qualified_and_confirmed():
    best = _point(5, 0.5, 8)
    results = [_result(p, 0.05) for p in st.GRID if p != best] + [_result(best, 0.3)]
    out = st.decide(results, _confirmations(best, ALL_PASS))
    assert out.passed and out.chosen == best
    assert out.kind == "qualified_and_confirmed"


@pytest.mark.parametrize("bad", sorted(ALL_PASS))
def test_a_chosen_point_that_fails_one_block_is_failed_whichever_block_it_is(bad):
    best = _point(5, 0.5, 8)
    results = [_result(best, 0.3)]
    out = st.decide(results, _confirmations(best, {**ALL_PASS, bad: -0.05}))
    assert not out.passed
    assert out.chosen == best
    assert out.kind == "failed_confirmation"
    assert out.failed_blocks == (bad,)


def test_a_chosen_point_that_fails_two_blocks_lists_both_in_order():
    best = _point(5, 0.5, 8)
    margins = {"confirm 25-49": -0.1, "confirm 50-74": 0.1, "confirm 75-99": -0.1}
    out = st.decide([_result(best, 0.3)], _confirmations(best, margins))
    assert out.failed_blocks == ("confirm 25-49", "confirm 75-99")


def test_a_missing_confirmation_block_is_an_error_and_not_a_pass():
    best = _point(5, 0.5, 8)
    partial = _confirmations(best, {"confirm 25-49": 0.1, "confirm 50-74": 0.1})
    with pytest.raises(ValueError, match="confirm 75-99"):
        st.decide([_result(best, 0.3)], partial)
    with pytest.raises(ValueError, match="confirm"):
        st.decide([_result(best, 0.3)], None)


def test_a_confirmation_that_is_not_the_chosen_point_is_refused():
    best, other = _point(5, 0.5, 8), _point(2, 0.5, 8)
    with pytest.raises(ValueError, match="chosen"):
        st.decide([_result(best, 0.3)], _confirmations(other, ALL_PASS))


# ----------------------------------------------------------------------------------------- the loop


class Recorder:
    """An evaluator that runs no case: it records what it was asked and returns a table made by ``margins``."""

    def __init__(self, margins):
        self.margins = margins
        self.calls: list[tuple[st.GridPoint, tuple[int, ...]]] = []

    def __call__(self, point: st.GridPoint, seeds) -> st.PointResult:
        self.calls.append((point, tuple(seeds)))
        return _result(point, self.margins(point, tuple(seeds)), seeds=seeds)


def test_the_loop_runs_each_grid_point_once_on_seeds_0_to_24_and_nothing_else_when_none_qualifies():
    rec = Recorder(lambda p, s: -0.1)
    run = st.run_tuning(evaluate=rec)
    assert [c[0] for c in rec.calls] == list(st.GRID)
    assert {c[1] for c in rec.calls} == {tuple(range(25))}
    assert not run.outcome.passed and run.outcome.kind == "no_point_qualified"
    assert run.confirmations == {}


def test_the_loop_confirms_only_the_chosen_point_and_only_on_the_three_blocks():
    best = _point(5, 0.5, 16)
    rec = Recorder(lambda p, s: 0.4 if p == best else 0.1)
    run = st.run_tuning(evaluate=rec)
    grid_calls = rec.calls[:12]
    confirm_calls = rec.calls[12:]
    assert [c[0] for c in grid_calls] == list(st.GRID)
    assert confirm_calls == [
        (best, tuple(range(25, 50))),
        (best, tuple(range(50, 75))),
        (best, tuple(range(75, 100))),
    ]
    assert run.outcome.passed and run.outcome.chosen == best
    assert list(run.confirmations) == list(st.CONFIRMATION_BLOCKS)


def test_the_loop_reports_a_failed_confirmation_and_does_not_look_for_another_point():
    best = _point(5, 0.5, 16)

    def margins(p, seeds):
        if p == best and seeds[0] == 50:
            return -0.2
        return 0.4 if p == best else 0.1

    rec = Recorder(margins)
    run = st.run_tuning(evaluate=rec)
    assert not run.outcome.passed
    assert run.outcome.kind == "failed_confirmation"
    assert run.outcome.failed_blocks == ("confirm 50-74",)
    assert len(rec.calls) == 12 + 3  # no second point is tried, no point is added


def test_the_loop_calls_progress_once_per_evaluation():
    seen: list[str] = []
    st.run_tuning(evaluate=Recorder(lambda p, s: -0.1), progress=seen.append)
    assert len(seen) == 12


def test_the_rows_of_a_run_are_the_grid_then_the_confirmation_of_the_chosen_point_only():
    best = _point(5, 0.5, 16)
    run = st.run_tuning(evaluate=Recorder(lambda p, s: 0.4 if p == best else 0.1))
    rows = run.rows()
    assert [r["stage"] for r in rows[: 12 * 12]] == ["grid"] * (12 * 12)
    tail = rows[12 * 12 :]
    assert len(tail) == 3 * 12
    assert {r["stage"] for r in tail} == set(st.CONFIRMATION_BLOCKS)
    assert {(r["tau_s"], r["s_min"], r["s_max"]) for r in tail} == {(5.0, 0.5, 16.0)}
    chosen_rows = [r for r in rows if r["chosen"]]
    assert {(r["tau_s"], r["s_min"], r["s_max"]) for r in chosen_rows if r["stage"] == "grid"} == {(5.0, 0.5, 16.0)}


# ----------------------------------------------------------------------------------------- seed refusal


@pytest.mark.parametrize(
    "seeds",
    [[100], [124], [125], [149], [10**6], [*range(100), 100], [5, 99, 100], [-1], [0, 1, 1000]],
)
def test_a_seed_that_may_not_be_run_is_refused(seeds):
    with pytest.raises(ValueError, match=r"development seed|negative"):
        st.check_seeds(seeds)


def test_every_development_seed_is_accepted():
    st.check_seeds(list(range(100)))


def test_the_refusal_happens_before_any_case_runs(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a case was run")

    monkeypatch.setattr(cg_run, "run_scenario", boom)
    monkeypatch.setattr(cg_run, "run_control", boom)
    monkeypatch.setattr(st, "run_case", boom, raising=False)
    evaluate = st.make_evaluator(doc={})
    for seeds in ([100], [124], [125], list(range(95, 105))):
        with pytest.raises(ValueError):
            evaluate(st.GRID[0], seeds)


def test_the_loop_checks_the_seeds_of_every_stage_and_has_no_way_to_widen_them(monkeypatch):
    # An evaluator is given the seeds; if the stage constants ever held a seed from 100 up, the loop must stop first.
    monkeypatch.setattr(st, "GRID_SEEDS", range(75, 125))
    rec = Recorder(lambda p, s: 0.1)
    with pytest.raises(ValueError):
        st.run_tuning(evaluate=rec)
    assert rec.calls == []
    monkeypatch.undo()
    monkeypatch.setitem(st.CONFIRMATION_BLOCKS, "confirm 75-99", range(100, 125))
    rec = Recorder(lambda p, s: 0.1)
    with pytest.raises(ValueError):
        st.run_tuning(evaluate=rec)
    assert rec.calls == []


def test_the_command_takes_no_seed_and_no_held_out_flag():
    ap = st.build_parser()
    for extra in (["--seeds", "100-124"], ["--seeds", "0-24"], ["--held-out"]):
        with pytest.raises(SystemExit):
            ap.parse_args(["--csv", "x.csv", *extra])
    ns = ap.parse_args(["--csv", "x.csv", "--page", "p.md"])
    assert ns.csv == Path("x.csv") and ns.page == Path("p.md")
    assert set(vars(ns)) == {"csv", "page"}


def test_the_router_knows_tune_scale(capsys):
    assert cli.main(["gate", "--help"]) == 0
    assert "tune-scale" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------- the CSV


def _tiny_run() -> st.TuningRun:
    best = _point(5, 0.5, 16)
    return st.run_tuning(evaluate=Recorder(lambda p, s: 0.4 if p == best else 0.1))


def test_the_csv_has_the_documented_columns():
    assert st.CSV_FIELDS == (
        "stage",
        "tau_s",
        "s_min",
        "s_max",
        "scenario",
        "seeds",
        "condition",
        "relation",
        "value",
        "threshold",
        "margin",
        "holds",
        "score",
        "qualifies",
        "chosen",
    )
    text = st.csv_text(_tiny_run().rows())
    assert text.splitlines()[0] == ",".join(st.CSV_FIELDS)


def test_the_csv_has_one_row_per_stage_point_scenario_and_condition():
    rows = _tiny_run().rows()
    keys = [(r["stage"], r["tau_s"], r["s_min"], r["s_max"], r["scenario"], r["condition"]) for r in rows]
    assert len(keys) == len(set(keys)) == (12 + 3) * 2 * 6
    assert {r["scenario"] for r in rows} == {"S1", "S2"}
    assert {r["condition"] for r in rows} == {"upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"}


def test_the_rows_carry_the_margin_the_score_and_the_flags():
    rows = _tiny_run().rows()
    for r in rows:
        assert r["margin"] == pytest.approx(
            (r["threshold"] - r["value"]) / r["threshold"]
            if r["relation"] == "<="
            else (r["value"] - r["threshold"]) / r["threshold"]
        )
        assert r["holds"] == (r["margin"] >= 0.0)
    by_point: dict[tuple, list[dict]] = {}
    for r in rows:
        by_point.setdefault((r["stage"], r["tau_s"], r["s_min"], r["s_max"]), []).append(r)
    for group in by_point.values():
        assert {r["score"] for r in group} == {min(r["margin"] for r in group)}
        assert {r["qualifies"] for r in group} == {all(r["holds"] for r in group)}


def test_the_csv_text_is_the_same_on_two_runs_and_round_trips_to_the_same_bytes():
    a = st.csv_text(_tiny_run().rows())
    b = st.csv_text(_tiny_run().rows())
    assert a == b
    assert st.csv_text(st.parse_csv(a)) == a
    assert "true" in a and "false" in a
    assert "nan" not in a and "inf" not in a


def test_the_csv_parser_refuses_a_file_with_other_columns():
    with pytest.raises(ValueError, match="columns"):
        st.parse_csv("stage,tau_s\ngrid,2.0\n")


def test_the_csv_writer_refuses_a_non_finite_value():
    rows = _tiny_run().rows()
    rows[0]["value"] = math.nan
    with pytest.raises(ValueError, match="finite"):
        st.csv_text(rows)


def test_the_outcome_is_read_back_from_the_rows_alone():
    best = _point(5, 0.5, 16)
    ok = _tiny_run()
    assert st.outcome_from_rows(ok.rows()) == ok.outcome
    none = st.run_tuning(evaluate=Recorder(lambda p, s: -0.1))
    assert st.outcome_from_rows(none.rows()) == none.outcome
    assert none.outcome.kind == "no_point_qualified"
    failed = st.run_tuning(evaluate=Recorder(lambda p, s: (-0.2 if s[0] == 75 else 0.4) if p == best else 0.1))
    assert st.outcome_from_rows(failed.rows()) == failed.outcome
    assert failed.outcome.kind == "failed_confirmation" and failed.outcome.failed_blocks == ("confirm 75-99",)


# ------------------------------------------------------------------------------------------ the page


def test_the_section_marks_the_chosen_point_and_states_the_outcome_in_one_plain_sentence():
    run = _tiny_run()
    text = st.markdown_section(run.rows())
    grid_lines = [ln for ln in text.splitlines() if ln.startswith("| ") and ln.endswith("| chosen |")]
    assert len(grid_lines) == 1
    assert grid_lines[0].startswith("| 5 | 0.5 | 16 |")
    assert chr(0x2014) not in text and chr(0x2013) not in text
    sentences = [ln for ln in text.splitlines() if ln.startswith("Outcome:")]
    assert len(sentences) == 1
    assert "qualified on the development seeds and passed" in sentences[0]


def test_the_section_for_no_qualifying_point_says_failed_on_development_seeds():
    run = st.run_tuning(evaluate=Recorder(lambda p, s: -0.1))
    text = st.markdown_section(run.rows())
    assert "Outcome: failed on development seeds. No point of the grid passed the gate in both scenarios" in text
    assert "| Block |" not in text  # nothing was confirmed, so there is no confirmation table


def test_the_section_for_a_failed_confirmation_names_the_block():
    best = _point(5, 0.5, 16)
    run = st.run_tuning(evaluate=Recorder(lambda p, s: (-0.2 if s[0] == 50 else 0.4) if p == best else 0.1))
    text = st.markdown_section(run.rows())
    assert "Outcome: failed on development seeds." in text
    assert "seeds 50 to 74" in text


def test_splice_section_replaces_only_what_is_between_the_markers():
    page = f"head\n{st.START}\nold\n{st.END}\ntail\n"
    out = splice_block(page, "scale-tuning", "NEW")
    assert out == f"head\n{st.START}\n\nNEW\n\n{st.END}\ntail\n"
    assert splice_block(out, "scale-tuning", "NEW") == out


def test_splice_section_needs_both_markers_in_order():
    with pytest.raises(ValueError, match="needs"):
        splice_block("no markers", "scale-tuning", "x")
    with pytest.raises(ValueError, match="needs"):
        splice_block(f"{st.END}\n{st.START}", "scale-tuning", "x")


# --------------------------------------------------------------------------------- real cases, seeds 0, 1


def test_the_evaluator_is_deterministic_and_applies_the_gate_of_adr_0030_on_two_development_seeds():
    point = st.GRID[0]
    evaluate = st.make_evaluator()
    a = evaluate(point, [0, 1])
    b = st.make_evaluator()(point, [0, 1])
    assert a.point == point and a.seeds == (0, 1)
    assert st.csv_text(a.rows("grid", chosen=False)) == st.csv_text(b.rows("grid", chosen=False))
    assert [c.name for c in a.s1.conditions] == ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]
    assert a.s1.upper_quantile == a.s2.upper_quantile == 0.975
    assert a.s1.n_runs == a.s2.n_runs == 2


def test_the_evaluator_reuses_the_control_for_a_seed_list(monkeypatch):
    calls: list[tuple[int, ...]] = []
    real = cg_run.run_control

    def counting(key, seeds, doc=None):
        calls.append(tuple(seeds))
        return real(key, seeds, doc)

    monkeypatch.setattr(cg_run, "run_control", counting)
    evaluate = st.make_evaluator()
    evaluate(st.GRID[0], [0, 1])
    evaluate(st.GRID[1], [0, 1])
    assert calls == [(0, 1)]
