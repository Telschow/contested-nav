"""The run side of the candidate gate: seed refusals, the held-out ledger, the estimator option, the scenarios.

No case is run here, and no seed from 100 up is run anywhere in the package. The refusals are tested with the parser
and the ledger reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from navkit import b1_gate, cli
from navkit import candidate_gate as run
from navkit.benchmark import default_config_path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "data" / "heldout_ledger.csv"

FIRST_ROW = (
    "block,seeds,candidate,commit,date,outcome\n"
    "1,100-124,clone + measured-front-end (ADR-0028),4c88341,2026-10-20,failed condition 2\n"
)


def _ledger(tmp_path: Path, *extra: str) -> Path:
    path = tmp_path / "ledger.csv"
    path.write_text(FIRST_ROW + "".join(extra), encoding="utf-8")
    return path


def _parse(*argv: str):
    return run.build_parser().parse_args(["--csv", "x.csv", *argv])


# -------------------------------------------------------------------------------------------- the ledger


def test_the_committed_ledger_has_the_first_block_and_its_columns():
    text = LEDGER.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "block,seeds,candidate,commit,date,outcome"
    rows = run.parse_ledger(text)
    assert rows[0] == {
        "block": 1,
        "seeds": list(range(100, 125)),
        "candidate": "clone + measured-front-end (ADR-0028)",
        "commit": "4c88341",
        "date": "2026-10-20",
        "outcome": "failed condition 2",
    }


def test_the_ledger_is_read_not_written_by_the_command():
    assert not hasattr(run, "write_ledger") and not hasattr(run, "append_ledger")


def test_the_next_block_follows_the_last_row_in_blocks_of_twenty_five(tmp_path):
    assert run.next_block(run.parse_ledger(FIRST_ROW)) == list(range(125, 150))
    second = FIRST_ROW + "2,125-149,adaptive,abc1234,2026-11-01,passed\n"
    assert run.next_block(run.parse_ledger(second)) == list(range(150, 175))
    third = second + "3,150-174,gauss-markov,def5678,2026-11-09,failed (U) in S2\n"
    assert run.next_block(run.parse_ledger(third)) == list(range(175, 200))


def test_a_malformed_ledger_is_refused():
    with pytest.raises(ValueError):
        run.parse_ledger("block,seeds\n1,100-124\n")
    with pytest.raises(ValueError):
        run.parse_ledger(FIRST_ROW + "2,not-seeds,c,h,d,o\n")


# ------------------------------------------------------------------------------------------- refusals


@pytest.mark.parametrize("text", ["100-124", "0-124", "99-123", "110-134", "124-148", "100", "5,110,120,130"])
def test_seeds_in_the_spent_block_are_refused_with_and_without_the_flag(text, tmp_path, capsys):
    ledger = str(_ledger(tmp_path))
    for flags in ([], ["--held-out"]):
        with pytest.raises(SystemExit) as stop:
            _parse("--seeds", text, "--ledger", ledger, *flags)
        assert stop.value.code == 2
    assert "spent" in capsys.readouterr().err


def test_a_held_out_seed_needs_the_flag(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        _parse("--seeds", "125-149", "--ledger", str(_ledger(tmp_path)))
    assert stop.value.code == 2
    assert "--held-out" in capsys.readouterr().err


def test_the_next_unused_block_is_accepted_with_the_flag_and_says_it_is_single_use(tmp_path, capsys):
    args = _parse("--seeds", "125-149", "--held-out", "--ledger", str(_ledger(tmp_path)))
    assert args.seeds == list(range(125, 150)) and args.held_out is True
    assert "single use" in capsys.readouterr().err


def test_a_block_that_is_not_the_next_one_is_refused(tmp_path, capsys):
    ledger = str(_ledger(tmp_path))
    for text in ("150-174", "126-150", "125-148", "130-154", "175-199"):
        with pytest.raises(SystemExit) as stop:
            _parse("--seeds", text, "--held-out", "--ledger", ledger)
        assert stop.value.code == 2, text
    assert "next unused block" in capsys.readouterr().err


def test_a_block_that_overlaps_a_ledger_row_is_refused_for_that_reason(tmp_path, capsys):
    ledger = str(_ledger(tmp_path, "2,125-149,adaptive,abc1234,2026-11-01,passed\n"))
    with pytest.raises(SystemExit) as stop:
        _parse("--seeds", "125-149", "--held-out", "--ledger", ledger)
    assert stop.value.code == 2
    assert "overlap" in capsys.readouterr().err  # the usage line also names --ledger, so the word alone proves nothing
    assert _parse("--seeds", "150-174", "--held-out", "--ledger", ledger).seeds == list(range(150, 175))


def test_a_block_after_a_gap_in_the_ledger_is_still_the_next_block_after_the_last_row():
    ledger = run.parse_ledger(FIRST_ROW + "3,150-174,gauss-markov,def5678,2026-11-09,failed (U) in S2\n")
    run.check_seeds(list(range(175, 200)), True, ledger)
    with pytest.raises(ValueError, match="overlap"):
        run.check_seeds(list(range(150, 175)), True, ledger)
    with pytest.raises(ValueError, match="next unused block"):  # unused, but not the next one: blocks go in order
        run.check_seeds(list(range(125, 150)), True, ledger)


def test_the_ledger_decides_which_block_is_next(tmp_path):
    """Without the ledger the first block would be next; with a used block in it, it is not."""
    run.check_seeds(list(range(125, 150)), True, run.parse_ledger(FIRST_ROW))
    used = run.parse_ledger(FIRST_ROW + "2,125-149,adaptive,abc1234,2026-11-01,passed\n")
    with pytest.raises(ValueError):
        run.check_seeds(list(range(125, 150)), True, used)


def test_the_flag_is_not_for_development_seeds(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        _parse("--seeds", "25-49", "--held-out", "--ledger", str(_ledger(tmp_path)))
    assert stop.value.code == 2


@pytest.mark.parametrize("text", ["0-24", "25-49", "50-74", "75-99", "7,8,9"])
def test_development_seeds_need_no_flag(text, tmp_path):
    args = _parse("--seeds", text, "--ledger", str(_ledger(tmp_path)))
    assert args.held_out is False and max(args.seeds) < 100


def test_the_command_fixes_the_gate_at_twenty_five_seeds(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        run.main(["--seeds", "25-34", "--csv", str(tmp_path / "x.csv"), "--ledger", str(_ledger(tmp_path))])
    assert stop.value.code == 2
    assert "25" in capsys.readouterr().err


def test_the_check_function_is_the_one_the_parser_uses_and_runs_no_case(tmp_path):
    rows = run.parse_ledger(FIRST_ROW)
    run.check_seeds(list(range(25, 50)), False, rows)
    run.check_seeds(list(range(125, 150)), True, rows)
    for seeds, flag in ((list(range(100, 125)), True), (list(range(125, 150)), False), (list(range(150, 175)), True)):
        with pytest.raises(ValueError):
            run.check_seeds(seeds, flag, rows)


def test_run_candidate_gate_refuses_held_out_seeds_itself(tmp_path):
    rows = run.parse_ledger(FIRST_ROW)
    with pytest.raises(ValueError, match="spent"):
        run.run_candidate_gate(list(range(100, 125)), held_out=True, ledger=rows)
    with pytest.raises(ValueError, match="held-out"):
        run.run_candidate_gate(list(range(125, 150)), held_out=False, ledger=rows)


# ----------------------------------------------------------------------------------- the pool command


def test_the_pool_command_cannot_be_given_a_seed():
    ap = run.build_pool_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["--csv", "x.csv", "--seeds", "100-124"])
    assert list(range(25, 100)) == run.POOL_SEEDS


def test_the_router_knows_the_new_commands(capsys):
    assert cli.main(["gate", "--help"]) == 0
    err = capsys.readouterr().err
    assert "candidate" in err and "n-eff-pool" in err and "b1" in err


# ------------------------------------------------------------------------------------- the estimator


def test_the_default_estimator_is_the_candidate_of_adr_0028():
    assert run.DEFAULT_ESTIMATOR == b1_gate.CANDIDATE_ESTIMATOR


def test_the_estimator_option_parses_values_and_forces_vision_on():
    assert run.parse_estimator("vision_model=clone,vision_noise_preset=measured-front-end") == {
        "vision_model": "clone",
        "vision_noise_preset": "measured-front-end",
    }
    assert run.parse_estimator("vision_sigma_scale=2.5,vision_model=clone") == {
        "vision_sigma_scale": 2.5,
        "vision_model": "clone",
    }
    assert run.parse_estimator("") == {}
    for bad in ("novalue", "=x", "a=1,,b=2", "vision_fuse=false"):
        with pytest.raises(ValueError):
            run.parse_estimator(bad)


# ------------------------------------------------------------------------------------- the scenarios


def _cases():
    return yaml.safe_load(default_config_path().read_text(encoding="utf-8"))["cases"]


def _flat(d, p=""):
    out = {}
    for k, v in d.items():
        out.update(_flat(v, f"{p}{k}.") if isinstance(v, dict) else {f"{p}{k}": v})
    return out


def test_s2_differs_from_s1_only_by_the_correlation_time_of_the_visual_errors():
    cases = _cases()
    s1, s2 = _flat(cases[run.SCENARIOS["S1"]]["scenario"]), _flat(cases[run.SCENARIOS["S2"]]["scenario"])
    differing = {k for k in set(s1) | set(s2) if s1.get(k) != s2.get(k)} - {"name", "description"}
    assert differing == {"vision.noise_corr_s"}
    assert s2["vision.noise_corr_s"] > 0.0 and s1.get("vision.noise_corr_s") is None


def test_the_scenario_names_are_the_ones_of_the_adr():
    assert run.SCENARIOS == {"S1": "outage_visual", "S2": "outage_visual_clone_correlated"}
    assert run.CONTROL == "outage_control"


def test_the_candidate_estimator_is_applied_in_both_scenarios_and_the_scenario_block_is_kept():
    cases = _cases()
    est = {"vision_model": "clone", "vision_noise_preset": "measured-front-end"}
    for key, name in run.SCENARIOS.items():
        case = run.scenario_case(cases, key, est)
        assert case["estimator"] == {"vision_fuse": True, **est}, key
        assert case["scenario"] == cases[name]["scenario"], key
    assert "vision_model" not in cases[run.SCENARIOS["S1"]].get("estimator", {})  # the config is not mutated


def test_the_control_is_the_same_in_both_scenarios_and_has_no_vision():
    cases = _cases()
    assert cases[run.CONTROL]["estimator"]["vision_fuse"] is False


def test_an_unknown_scenario_is_refused():
    with pytest.raises(ValueError, match="scenario"):
        run.scenario_case(_cases(), "S3", {})


# ------------------------------------------------------------------------------------------- the CSV


def test_the_csv_columns_are_documented():
    assert run.CSV_FIELDS == (
        "role",
        "subject",
        "scenario",
        "seeds",
        "n_runs",
        "upper_quantile",
        "m",
        "condition",
        "relation",
        "value",
        "threshold",
        "passed",
        "scenario_passed",
        "subject_passed",
    )
