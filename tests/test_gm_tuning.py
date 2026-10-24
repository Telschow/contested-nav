"""The tuning run of the Gauss-Markov visual error model (ADR-0034): the grid, the selection rule, the decision, the
seed refusal, the CSV and the robustness diagnostic.

The pure parts are tested on hand-built tables, so that no case is run. Two tests run real cases on seeds 0 and 1 only,
to check that the evaluator is deterministic and wired to the gate of ADR-0030. No seed from 100 up is run anywhere.
The margin functions are the ones of the earlier tuning run and are imported, not copied; a test says so.
"""

from __future__ import annotations

import copy

import pytest

from navkit import candidate_gate as cg_run
from navkit import cli
from navkit import gm_tuning as gt
from navkit import scale_tuning as st
from test_scale_tuning import _cond, _scenario

#: ADR-0034's twelve points, written out here from the ADR: tau in {0.25, 0.5, 1, 2} s, rho in {0.5, 0.75, 0.9}.
ADR_POINTS = {(tau, rho) for tau in (0.25, 0.5, 1.0, 2.0) for rho in (0.5, 0.75, 0.9)}


def _point(tau: float, rho: float) -> gt.GridPoint:
    return gt.GridPoint(tau, rho)


def _result(point: gt.GridPoint, margin_s1: float, margin_s2: float | None = None, seeds=range(25)) -> gt.PointResult:
    return gt.PointResult(
        point=point,
        seeds=tuple(seeds),
        s1=_scenario(margin_s1),
        s2=_scenario(margin_s1 if margin_s2 is None else margin_s2),
    )


# ------------------------------------------------------------------------------------------------- the grid


def test_the_grid_is_the_twelve_points_of_adr_0034_and_no_others():
    assert len(gt.GRID) == 12
    assert {(p.tau_s, p.rho) for p in gt.GRID} == ADR_POINTS


def test_the_grid_axes_and_order_are_tau_then_rho():
    assert gt.GRID_TAU_S == (0.25, 0.5, 1.0, 2.0)
    assert gt.GRID_RHO == (0.5, 0.75, 0.9)
    keys = [(p.tau_s, p.rho) for p in gt.GRID]
    assert keys == sorted(keys)


def test_the_seed_blocks_are_the_development_seeds_of_the_adr_and_are_those_of_the_earlier_run():
    assert list(gt.GRID_SEEDS) == list(range(0, 25))
    assert gt.CONFIRMATION_BLOCKS is st.CONFIRMATION_BLOCKS
    assert {k: list(v) for k, v in gt.CONFIRMATION_BLOCKS.items()} == {
        "confirm 25-49": list(range(25, 50)),
        "confirm 50-74": list(range(50, 75)),
        "confirm 75-99": list(range(75, 100)),
    }
    assert list(gt.ROBUSTNESS_SEEDS) == list(range(25, 50))
    assert gt.ROBUSTNESS_CORR_TIMES_S == (0.0, 0.25, 0.5, 1.0, 2.0)


@pytest.mark.parametrize("point", gt.GRID, ids=lambda p: p.label)
def test_every_point_is_a_clone_with_the_model_on_and_no_preset_and_no_adaptive_scale(point):
    est = point.estimator()
    assert est == {
        "vision_model": "clone",
        "vision_gm_error": True,
        "vision_gm_tau_s": point.tau_s,
        "vision_gm_rho": point.rho,
    }
    assert "vision_noise_preset" not in est and "vision_adaptive_scale" not in est


def test_the_margin_and_check_functions_are_those_of_the_earlier_run_and_not_copies():
    assert gt.condition_margin is st.condition_margin
    assert gt.scenario_margin is st.scenario_margin
    assert gt.check_seeds is st.check_seeds


# ------------------------------------------------------------------------------------- score and selection


def test_the_score_of_a_point_is_the_smallest_margin_in_both_scenarios_and_not_the_largest():
    r = _result(_point(1.0, 0.5), 0.9, 0.2)
    assert r.score == pytest.approx(0.2) and r.score != pytest.approx(0.9)
    assert _result(_point(1.0, 0.5), 0.2, 0.9).score == pytest.approx(0.2)


def test_a_point_qualifies_only_when_the_gate_passes_in_both_scenarios():
    assert _result(_point(1.0, 0.5), 0.5, 0.5).qualifies
    assert not _result(_point(1.0, 0.5), 0.5, -0.1).qualifies
    assert not _result(_point(1.0, 0.5), -0.1, 0.5).qualifies


def test_the_chosen_point_is_the_qualifying_one_with_the_largest_score():
    a, b, c = _result(_point(1.0, 0.5), 0.3), _result(_point(2.0, 0.5), 0.6), _result(_point(0.5, 0.5), 0.1)
    assert gt.select_point([a, b, c]) is b


def test_a_point_that_does_not_qualify_is_never_chosen_whatever_its_score():
    low = _result(_point(1.0, 0.5), 0.2)
    failing = _result(_point(2.0, 0.5), 5.0, -0.01)  # a huge margin in S1, a failure in S2
    assert gt.select_point([low, failing]) is low


def test_a_tie_goes_to_the_smaller_tau():
    a, b = _result(_point(0.5, 0.75), 0.4), _result(_point(1.0, 0.75), 0.4)
    assert gt.select_point([b, a]) is a


def test_a_tie_on_tau_goes_to_the_smaller_rho():
    a, b = _result(_point(1.0, 0.5), 0.4), _result(_point(1.0, 0.9), 0.4)
    assert gt.select_point([b, a]) is a


def test_the_tie_rule_applies_in_the_order_tau_then_rho():
    a, b, c = _result(_point(0.5, 0.9), 0.4), _result(_point(1.0, 0.5), 0.4), _result(_point(1.0, 0.75), 0.4)
    assert gt.select_point([c, b, a]) is a  # the smaller tau wins over the smaller rho


def test_a_score_that_differs_in_the_last_place_is_not_a_tie():
    a, b = _result(_point(1.0, 0.5), 0.4), _result(_point(0.25, 0.5), 0.4 - 1e-12)
    assert gt.select_point([a, b]) is a


def test_no_qualifying_point_gives_no_choice():
    assert gt.select_point([_result(_point(1.0, 0.5), -0.1), _result(_point(2.0, 0.9), 0.5, -0.2)]) is None
    assert gt.select_point([]) is None


# ------------------------------------------------------------------------------------------ the decision

ALL_PASS = ("confirm 25-49", "confirm 50-74", "confirm 75-99")


def _confirmations(point: gt.GridPoint, margins: dict[str, float]) -> dict[str, gt.PointResult]:
    return {label: _result(point, margins[label], seeds=gt.CONFIRMATION_BLOCKS[label]) for label in ALL_PASS}


def test_no_qualifying_point_is_failed_on_development_seeds():
    out = gt.decide([_result(_point(1.0, 0.5), -0.2)], None)
    assert not out.passed and out.chosen is None and out.kind == "no_point_qualified"


def test_a_chosen_point_that_passes_every_block_is_qualified_and_confirmed():
    p = _point(2.0, 0.9)
    out = gt.decide([_result(p, 0.3)], _confirmations(p, dict.fromkeys(ALL_PASS, 0.2)))
    assert out.passed and out.chosen == p and out.kind == "qualified_and_confirmed"


@pytest.mark.parametrize("bad", ALL_PASS)
def test_a_chosen_point_that_fails_one_block_is_failed_whichever_block_it_is(bad):
    p = _point(2.0, 0.9)
    margins = {**dict.fromkeys(ALL_PASS, 0.2), bad: -0.05}
    out = gt.decide([_result(p, 0.3)], _confirmations(p, margins))
    assert not out.passed and out.chosen == p and out.failed_blocks == (bad,) and out.kind == "failed_confirmation"


def test_a_missing_confirmation_block_is_an_error_and_not_a_pass():
    p = _point(2.0, 0.9)
    conf = _confirmations(p, dict.fromkeys(ALL_PASS, 0.2))
    del conf["confirm 75-99"]
    with pytest.raises(ValueError, match="confirm 75-99"):
        gt.decide([_result(p, 0.3)], conf)


def test_a_confirmation_that_is_not_the_chosen_point_is_refused():
    chosen, other = _point(2.0, 0.9), _point(1.0, 0.5)
    with pytest.raises(ValueError, match="not the chosen point"):
        gt.decide([_result(chosen, 0.3)], _confirmations(other, dict.fromkeys(ALL_PASS, 0.2)))


# ------------------------------------------------------------------------------------------------- the loop


class Recorder:
    """An evaluator that gives a table instead of running cases, and remembers what it was asked."""

    def __init__(self, margins: dict[tuple[float, float], float] | None = None, confirm: float = 0.2):
        self.margins, self.confirm, self.calls = margins or {}, confirm, []
        self.robustness_calls: list[tuple[gt.GridPoint, float, tuple[int, ...]]] = []

    def __call__(self, point: gt.GridPoint, seeds) -> gt.PointResult:
        self.calls.append((point, tuple(seeds)))
        grid = tuple(seeds) == tuple(gt.GRID_SEEDS)
        m = self.margins.get((point.tau_s, point.rho), -0.5) if grid else self.confirm
        return _result(point, m, seeds=seeds)

    def robustness(self, point: gt.GridPoint, corr_time_s: float, seeds) -> gt.RobustnessResult:
        self.robustness_calls.append((point, corr_time_s, tuple(seeds)))
        return gt.RobustnessResult(point, corr_time_s, tuple(seeds), _scenario(0.1 if corr_time_s >= 1.0 else -0.1))


def _run(rec: Recorder) -> gt.TuningRun:
    return gt.run_tuning(evaluate=rec, robustness=rec.robustness)


def test_the_loop_runs_each_grid_point_once_on_seeds_0_to_24_and_nothing_else_when_none_qualifies():
    rec = Recorder()
    run = _run(rec)
    assert [c[0] for c in rec.calls] == list(gt.GRID)
    assert {c[1] for c in rec.calls} == {tuple(range(25))}
    assert run.outcome.kind == "no_point_qualified" and not run.confirmations


def test_the_loop_confirms_only_the_chosen_point_and_only_on_the_three_blocks():
    rec = Recorder({(1.0, 0.75): 0.3, (2.0, 0.9): 0.6})
    run = _run(rec)
    assert len(rec.calls) == 12 + 3
    assert [c[0] for c in rec.calls[12:]] == [_point(2.0, 0.9)] * 3
    assert [c[1] for c in rec.calls[12:]] == [tuple(b) for b in gt.CONFIRMATION_BLOCKS.values()]
    assert run.outcome.passed and run.outcome.chosen == _point(2.0, 0.9)


def test_the_loop_reports_a_failed_confirmation_and_does_not_look_for_another_point():
    rec = Recorder({(1.0, 0.75): 0.3, (2.0, 0.9): 0.6}, confirm=-0.1)
    run = _run(rec)
    assert len(rec.calls) == 12 + 3  # no second candidate is tried
    assert not run.outcome.passed and run.outcome.chosen == _point(2.0, 0.9)
    assert run.outcome.failed_blocks == ALL_PASS


def test_the_loop_calls_progress_once_per_evaluation_and_per_robustness_scenario():
    rec, seen = Recorder({(2.0, 0.9): 0.6}), []
    gt.run_tuning(evaluate=rec, robustness=rec.robustness, progress=seen.append)
    assert len(seen) == 12 + 3 + len(gt.ROBUSTNESS_CORR_TIMES_S)


# --------------------------------------------------------------------------- the robustness diagnostic


def test_the_diagnostic_runs_the_chosen_point_at_five_correlation_times_on_seeds_25_to_49():
    rec = Recorder({(1.0, 0.75): 0.3, (2.0, 0.9): 0.6})
    run = _run(rec)
    assert [(c[0], c[1], c[2]) for c in rec.robustness_calls] == [
        (_point(2.0, 0.9), t, tuple(range(25, 50))) for t in (0.0, 0.25, 0.5, 1.0, 2.0)
    ]
    assert run.robustness_basis == "chosen"


def test_when_no_point_qualified_the_diagnostic_uses_the_point_with_the_highest_score_and_says_so():
    rec = Recorder({(0.5, 0.5): -0.3, (1.0, 0.9): -0.1, (2.0, 0.5): -0.2})  # the others are -0.5
    run = _run(rec)
    assert {c[0] for c in rec.robustness_calls} == {_point(1.0, 0.9)}
    assert run.robustness_basis == "highest_score" and run.outcome.kind == "no_point_qualified"


def test_the_highest_score_has_the_same_tie_rule_as_the_choice():
    rec = Recorder({(0.5, 0.9): -0.1, (1.0, 0.5): -0.1})
    _run(rec)
    assert {c[0] for c in rec.robustness_calls} == {_point(0.5, 0.9)}


def test_the_diagnostic_never_changes_the_outcome_or_the_grid_rows():
    rec = Recorder({(1.0, 0.75): 0.3, (2.0, 0.9): 0.6})
    run = _run(rec)
    quiet = Recorder({(1.0, 0.75): 0.3, (2.0, 0.9): 0.6})

    def terrible(point, t, seeds):
        return gt.RobustnessResult(point, t, tuple(seeds), _scenario(-5.0))

    other = gt.run_tuning(evaluate=quiet, robustness=terrible)
    assert run.outcome == other.outcome and run.rows() == other.rows()


def test_the_robustness_rows_are_labelled_diagnostic_and_carry_the_margins():
    rec = Recorder({(2.0, 0.9): 0.6})
    run = _run(rec)
    rows = run.robustness_rows()
    assert len(rows) == 5 * 6
    assert {r["stage"] for r in rows} == {"DIAGNOSTIC"}
    assert {r["basis"] for r in rows} == {"chosen"}
    assert {r["seeds"] for r in rows} == {"25-49"}
    assert [r["corr_time_s"] for r in rows[::6]] == [0.0, 0.25, 0.5, 1.0, 2.0]
    for r in rows:
        assert r["margin"] == pytest.approx(
            st.condition_margin(_cond(r["condition"], r["relation"], r["value"], r["threshold"]))
        )


def test_the_correlation_time_is_set_in_a_copy_of_the_s2_scenario_block_and_the_document_is_not_changed():
    doc = {"cases": {"outage_visual_clone_correlated": {"scenario": {"vision": {"noise_corr_s": 2.0}}}}}
    before = copy.deepcopy(doc)
    out = gt.with_correlation_time(doc, 0.25)
    assert out["cases"]["outage_visual_clone_correlated"]["scenario"]["vision"]["noise_corr_s"] == 0.25
    assert doc == before
    with pytest.raises(ValueError, match="negative"):
        gt.with_correlation_time(doc, -1.0)


# ---------------------------------------------------------------------------------------- the seeds


@pytest.mark.parametrize("seeds", [[100], [124], [125], [149], [0, 1, 99, 100], [-1], range(90, 110)])
def test_a_seed_that_may_not_be_run_is_refused(seeds):
    with pytest.raises(ValueError, match=r"development seed|negative"):
        gt.check_seeds(list(seeds))


def test_the_refusal_happens_before_any_case_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(cg_run, "run_scenario", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(cg_run, "run_control", lambda *a, **k: calls.append(a))
    evaluate = gt.make_evaluator({"cases": {}, "defaults": {}})
    with pytest.raises(ValueError, match="development seed"):
        evaluate(_point(1.0, 0.5), [98, 99, 100])
    robustness = gt.make_robustness_evaluator({"cases": {}, "defaults": {}})
    with pytest.raises(ValueError, match="development seed"):
        robustness(_point(1.0, 0.5), 0.5, [99, 100])
    assert calls == []


def test_the_loop_checks_the_seeds_of_every_stage_and_has_no_way_to_widen_them(monkeypatch):
    monkeypatch.setattr(gt, "ROBUSTNESS_SEEDS", range(95, 105))
    rec = Recorder()
    with pytest.raises(ValueError, match="development seed"):
        _run(rec)
    assert rec.calls == [] and rec.robustness_calls == []  # before the first case


def test_the_command_takes_no_seed_and_no_held_out_flag():
    help_text = gt.build_parser().format_help()
    for word in ("--seed", "--held", "--override"):
        assert word not in help_text
    with pytest.raises(SystemExit):
        gt.build_parser().parse_args(["--csv", "x.csv", "--seeds", "100-124"])
    with pytest.raises(SystemExit):
        gt.build_parser().parse_args(["--csv", "x.csv", "--held-out"])


def test_the_router_knows_tune_gm(capsys):
    assert cli.main(["gate"]) == 2
    assert "tune-gm" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------- the CSV


def _tiny_run() -> gt.TuningRun:
    rec = Recorder({(2.0, 0.9): 0.6, (1.0, 0.75): 0.3})
    return _run(rec)


def test_the_csv_has_the_documented_columns():
    assert gt.CSV_FIELDS == (
        "stage",
        "tau_s",
        "rho",
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
    assert gt.csv_text(_tiny_run().rows()).splitlines()[0] == ",".join(gt.CSV_FIELDS)
    assert gt.ROBUSTNESS_CSV_FIELDS == (
        "stage",
        "basis",
        "tau_s",
        "rho",
        "corr_time_s",
        "seeds",
        "condition",
        "relation",
        "value",
        "threshold",
        "margin",
        "holds",
        "scenario_passed",
    )


def test_the_csv_has_one_row_per_stage_point_scenario_and_condition():
    run = _tiny_run()
    rows = run.rows()
    assert len(rows) == (12 + 3) * 2 * 6
    assert [r["stage"] for r in rows[: 12 * 12 : 12]] == ["grid"] * 12
    assert {r["stage"] for r in rows} == {"grid", *gt.CONFIRMATION_BLOCKS}


def test_the_rows_carry_the_margin_the_score_and_the_flags():
    for r in _tiny_run().rows():
        c = _cond(r["condition"], r["relation"], r["value"], r["threshold"])
        assert r["margin"] == pytest.approx(st.condition_margin(c))
        assert r["holds"] is c.passed
    grid = [r for r in _tiny_run().rows() if r["stage"] == "grid" and r["tau_s"] == 2.0 and r["rho"] == 0.9]
    assert {r["chosen"] for r in grid} == {True} and {r["qualifies"] for r in grid} == {True}


def test_the_csv_text_is_the_same_on_two_runs_and_round_trips_to_the_same_bytes():
    a, b = gt.csv_text(_tiny_run().rows()), gt.csv_text(_tiny_run().rows())
    assert a == b and gt.csv_text(gt.parse_csv(a)) == a
    ra, rb = (
        gt.robustness_csv_text(_tiny_run().robustness_rows()),
        gt.robustness_csv_text(_tiny_run().robustness_rows()),
    )
    assert ra == rb and gt.robustness_csv_text(gt.parse_robustness_csv(ra)) == ra


def test_the_csv_parsers_refuse_a_file_with_other_columns():
    with pytest.raises(ValueError, match="columns"):
        gt.parse_csv("a,b\n1,2\n")
    with pytest.raises(ValueError, match="columns"):
        gt.parse_robustness_csv(gt.csv_text(_tiny_run().rows()))


def test_the_csv_writer_refuses_a_non_finite_value():
    rows = _tiny_run().rows()
    rows[0]["value"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        gt.csv_text(rows)


def test_the_outcome_is_read_back_from_the_rows_alone():
    assert gt.outcome_from_rows(_tiny_run().rows()) == _tiny_run().outcome
    bad = _run(Recorder({(2.0, 0.9): 0.6}, confirm=-0.1))
    assert gt.outcome_from_rows(bad.rows()) == bad.outcome
    none = _run(Recorder())
    assert gt.outcome_from_rows(none.rows()) == none.outcome


# --------------------------------------------------------------------------------------------- the page


def test_the_section_marks_the_chosen_point_and_states_the_outcome_in_one_plain_sentence():
    text = gt.markdown_section(_tiny_run().rows())
    assert "| 2 | 0.9 |" in text and text.count("chosen") >= 1
    outcome = [ln for ln in text.splitlines() if ln.startswith("Outcome:")]
    assert len(outcome) == 1 and "qualified on the development seeds" in outcome[0]
    assert "tau = 2 s, rho = 0.9" in outcome[0]
    assert "Confirmation" in text


def test_the_section_for_no_qualifying_point_says_failed_on_development_seeds():
    text = gt.markdown_section(_run(Recorder()).rows())
    assert "Outcome: failed on development seeds. No point of the grid passed the gate" in text
    assert "Confirmation" not in text


def test_the_section_for_a_failed_confirmation_names_the_block():
    text = gt.markdown_section(_run(Recorder({(2.0, 0.9): 0.6}, confirm=-0.1)).rows())
    assert "Outcome: failed on development seeds. The chosen point (tau = 2 s, rho = 0.9)" in text


def test_the_robustness_table_is_labelled_diagnostic_and_is_not_a_pass_or_fail():
    text = gt.robustness_markdown(_tiny_run().robustness_rows())
    assert "DIAGNOSTIC" in text
    assert "not a selection input" in text and "not a pass or fail" in text
    assert text.count("| 0 |") >= 1 or "| 0 " in text
    none = gt.robustness_markdown(_run(Recorder()).robustness_rows())
    assert "highest score" in none and "no point qualified" in none


def test_splice_section_replaces_only_what_is_between_the_markers():
    page = f"head\n{gt.START}\nold\n{gt.END}\ntail\n"
    out = gt.splice_section(page, "new", gt.START, gt.END)
    assert out == f"head\n{gt.START}\n\nnew\n\n{gt.END}\ntail\n"
    assert gt.splice_section(out, "new", gt.START, gt.END) == out


def test_splice_section_needs_both_markers_in_order():
    for page in ("no markers", f"{gt.END}\n{gt.START}", gt.START):
        with pytest.raises(ValueError, match="needs the lines"):
            gt.splice_section(page, "x", gt.START, gt.END)


# --------------------------------------------------------------------------------------- the evaluator


def test_the_evaluator_is_deterministic_and_applies_the_gate_of_adr_0030_on_two_development_seeds():
    evaluate = gt.make_evaluator()
    p = _point(2.0, 0.9)
    a, b = evaluate(p, [0, 1]), evaluate(p, [0, 1])
    assert a == b
    assert a.s1.n_runs == 2 and a.s2.n_runs == 2
    assert [c.name for c in a.s1.conditions] == ["upper", "lower", "coverage", "better", "median_ratio", "worst_ratio"]


def test_the_robustness_evaluator_runs_s2_at_the_given_correlation_time():
    ev = gt.make_robustness_evaluator()
    p = _point(2.0, 0.9)
    at_two, at_zero = ev(p, 2.0, [0, 1]), ev(p, 0.0, [0, 1])
    assert at_two.seeds == (0, 1) and at_two.corr_time_s == 2.0
    assert at_two.scenario.conditions[0].value != at_zero.scenario.conditions[0].value
    assert ev(p, 2.0, [0, 1]) == at_two
