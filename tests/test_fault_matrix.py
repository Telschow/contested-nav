"""``navkit sweep faults`` and the claims ``docs/faults.md`` makes from its CSV."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from navkit import cli, fault_matrix
from navkit.benchmark import default_config_path, run_case
from navkit.types import GnssFix

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "fault_matrix.csv"
PAGE = ROOT / "docs" / "faults.md"


def _doc() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text())


# --- the hook and the injection -------------------------------------------------------------


def _fixes(available: list[bool] | None = None) -> GnssFix:
    t = np.arange(0.0, 5.0, 1.0)
    avail = None if available is None else np.array(available)
    return GnssFix(t=t, positions=np.zeros((5, 3)), cov=np.ones((5, 3)), available=avail)


def test_offset_window_moves_only_the_fixes_inside_the_window() -> None:
    out = fault_matrix.offset_window(1.0, 3.0, 5.0)(_fixes())
    assert out.positions[:, 0].tolist() == [0.0, 5.0, 5.0, 0.0, 0.0]
    assert not out.positions[:, 1:].any()


def test_offset_window_does_not_touch_its_input_or_resurrect_a_removed_fix() -> None:
    src = _fixes([True, True, False, True, True])
    out = fault_matrix.offset_window(0.0, 10.0, 5.0)(src)
    assert not src.positions.any()
    assert out.positions[:, 0].tolist() == [5.0, 5.0, 0.0, 5.0, 5.0]
    assert out.available is not None and out.available.tolist() == [True, True, False, True, True]


def test_the_hook_changes_what_the_filter_sees_and_not_the_scenario_hash() -> None:
    doc = _doc()
    case = doc["cases"]["gnss_only"]
    plain = run_case("gnss_only", case, doc["defaults"], seed=0, force_inject=True)
    hooked = run_case(
        "gnss_only",
        case,
        doc["defaults"],
        seed=0,
        force_inject=True,
        gnss_hook=fault_matrix.offset_window(10, 20, 10.0),
    )
    assert plain["config_hash"] == hooked["config_hash"]  # why a caller must record the fault itself
    assert plain["headline"]["ate_rmse_m"] != hooked["headline"]["ate_rmse_m"]


def test_a_scenario_that_sets_only_a_time_offset_is_ignored_unless_injection_is_forced() -> None:
    """Pins issue 56: the runner skips the injection layer when there is no outage or camera drop."""
    doc = _doc()
    fault = fault_matrix.BY_ID["gnss_time_offset"]
    case, _ = fault.build(doc["cases"]["gnss_only"], 0.5)
    base = run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0)
    skipped = run_case("gnss_only", case, doc["defaults"], seed=0)
    forced = run_case("gnss_only", case, doc["defaults"], seed=0, force_inject=True)
    assert skipped["headline"]["ate_rmse_m"] == base["headline"]["ate_rmse_m"]
    assert skipped["manifest"] == {}
    assert forced["headline"]["ate_rmse_m"] != base["headline"]["ate_rmse_m"]
    assert forced["manifest"]


def test_cases_without_an_outage_run_with_a_noiseless_imu() -> None:
    """Pins issue 56: four benchmark cases are not injected, so they have no IMU noise."""
    doc = _doc()
    injected = {
        name: bool(run_case(name, case, doc["defaults"], seed=0)["manifest"]) for name, case in doc["cases"].items()
    }
    assert injected == {
        "gnss_only": False,
        "dead_reckoning": False,
        "vision_anchor_in_measurement_noise": False,
        "vision_only": False,
        "outage_control": True,
        "outage_visual": True,
        "outage_visual_degraded_camera": True,
    }


def test_the_default_run_case_does_not_add_event_or_hook_fields() -> None:
    doc = _doc()
    rec = run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0)
    assert "fdir_events" not in rec
    assert (
        run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0, fdir_events=True)["fdir_events"] == []
    )


# --- the fault catalogue --------------------------------------------------------------------


def test_every_fault_builds_a_case_for_each_level_without_touching_the_base() -> None:
    doc = _doc()
    for fault in fault_matrix.FAULTS:
        base = doc["cases"][fault.base]
        before = yaml.safe_dump(base)
        for level in fault.levels:
            case, hook = fault.build(base, level)
            assert (case != base) or hook is not None, fault.id
        assert yaml.safe_dump(base) == before, fault.id


def test_a_scenario_edit_puts_the_level_where_the_fault_says() -> None:
    doc = _doc()
    case, _ = fault_matrix.BY_ID["imu_sample_loss"].build(doc["cases"]["gnss_only"], 2.0)
    assert case["scenario"]["imu_outages"] == [{"start_s": 10.0, "duration_s": 2.0, "reason": "fault"}]
    case, _ = fault_matrix.BY_ID["gnss_slow_bias"].build(doc["cases"]["gnss_only"], 3.0)
    assert case["scenario"]["gnss"]["multipath_sigma_m"] == 3.0


def test_detection_stats_reads_declarations_from_the_event_log_not_the_final_flag() -> None:
    record = {
        "stats": {"gnss_updates_rejected": 6.0, "gnss_fixes_seen": 100.0, "fdir_gnss_faulted": 0.0},
        "fdir_events": [
            {"t_s": 11.0, "sensor": "gnss", "status": "SENSOR_FAULT"},
            {"t_s": 12.0, "sensor": "gnss", "status": "REACCEPTED_WITH_INFLATION"},
        ],
    }
    out = fault_matrix.detection_stats(record, onset_s=10.0)
    assert out["detected"] and out["declared"] and out["granted"]
    assert out["latency_s"] == pytest.approx(1.0)
    assert out["declared_channels"] == ["gnss"]
    assert out["rejected_pct"] == pytest.approx(6.0)


def test_a_declaration_before_the_onset_has_no_latency() -> None:
    record = {
        "stats": {"gnss_fixes_seen": 10.0},
        "fdir_events": [{"t_s": 3.0, "sensor": "gnss", "status": "SENSOR_FAULT"}],
    }
    out = fault_matrix.detection_stats(record, onset_s=10.0)
    assert out["declared"] and out["latency_s"] is None


def test_a_clean_run_detects_nothing() -> None:
    out = fault_matrix.detection_stats({"stats": {"gnss_fixes_seen": 50.0}, "fdir_events": []}, None)
    assert not out["detected"] and not out["declared"] and out["rejected_pct"] == 0.0


# --- the command ----------------------------------------------------------------------------


def test_list_prints_every_fault(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sweep", "faults", "--list"]) == 0
    out = capsys.readouterr().out
    assert all(f.id in out for f in fault_matrix.FAULTS)


def test_the_command_runs_one_fault_and_writes_the_csv_json_and_page(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("a\n<!-- faults:start -->\nold\n<!-- faults:end -->\nb\n", encoding="utf-8")
    csv_path = tmp_path / "f.csv"
    code = cli.main(
        [
            "sweep",
            "faults",
            "--faults",
            "gnss_multipath_spike",
            "--seeds",
            "2",
            "--out",
            str(tmp_path / "f.json"),
            "--csv",
            str(csv_path),
            "--page",
            str(page),
        ]
    )
    assert code == 0
    rows = fault_matrix.read_csv(csv_path)
    assert [(r["fault"], r["level"]) for r in rows] == [("control", 0.0), ("gnss_multipath_spike", 20.0)]
    assert "old" not in page.read_text(encoding="utf-8")
    import json

    payload = json.loads((tmp_path / "f.json").read_text())
    assert payload["claim_type"] == "MEASUREMENT" and payload["data_class"] == "synthetic"
    assert "false_alarm" in payload["definitions"]


def test_the_command_refuses_bad_arguments() -> None:
    with pytest.raises(SystemExit, match="at least 2 seeds"):
        cli.main(["sweep", "faults", "--seeds", "1"])
    with pytest.raises(SystemExit, match="unknown fault"):
        cli.main(["sweep", "faults", "--faults", "nope", "--seeds", "2"])


def test_compare_exits_nonzero_when_the_result_differs(tmp_path: Path) -> None:
    csv_path = tmp_path / "f.csv"
    args = ["sweep", "faults", "--faults", "gnss_multipath_spike", "--seeds", "2"]
    assert cli.main([*args, "--out", str(tmp_path / "a.json"), "--csv", str(csv_path)]) == 0
    assert cli.main([*args, "--out", str(tmp_path / "b.json"), "--compare", str(csv_path)]) == 0
    rows = fault_matrix.read_csv(csv_path)
    rows[1]["declared_n"] += 1
    fault_matrix.write_csv(csv_path, rows)
    assert cli.main([*args, "--out", str(tmp_path / "c.json"), "--compare", str(csv_path)]) == 1


def test_compare_rows_tolerates_last_bit_differences_but_not_real_ones() -> None:
    row = dict.fromkeys(fault_matrix.CSV_FIELDS)
    row.update(fault="control", base="gnss_only", unit="", n_seeds=2, declared_channels="", ate_rmse_m_mean=1.0)
    near = {**row, "ate_rmse_m_mean": 1.0 + 1e-9}
    far = {**row, "ate_rmse_m_mean": 1.001}
    assert fault_matrix.compare_rows([near], [row]) == []
    assert fault_matrix.compare_rows([far], [row]) != []
    assert fault_matrix.compare_rows([row], [row, row]) != []


# --- the committed result and the page ------------------------------------------------------


def _cell(fault: str, level: float = 0.0, base: str | None = None) -> dict[str, Any]:
    for r in fault_matrix.read_csv(CSV):
        if r["fault"] == fault and r["level"] == level and (base is None or r["base"] == base):
            return r
    raise KeyError((fault, level))


def _control(base: str) -> dict[str, Any]:
    return _cell("control", 0.0, base)


def test_the_page_table_is_the_committed_csv() -> None:
    page = PAGE.read_text(encoding="utf-8")
    expected = fault_matrix.splice_table(page, fault_matrix.markdown_table(fault_matrix.read_csv(CSV)))
    assert page == expected


def test_a_page_without_markers_is_refused() -> None:
    with pytest.raises(ValueError, match="markers"):
        fault_matrix.splice_table("no markers", "x")


def test_the_csv_has_a_control_for_every_base_and_a_row_for_every_fault_level() -> None:
    rows = fault_matrix.read_csv(CSV)
    expected = {("control", 0.0, b) for b in fault_matrix.BASES}
    expected |= {(f.id, lv, f.base) for f in fault_matrix.FAULTS for lv in f.levels}
    assert {(r["fault"], r["level"], r["base"]) for r in rows} == expected
    assert {r["n_seeds"] for r in rows} == {5}


def test_claim_1_false_alarms_are_zero_on_two_controls_and_not_on_the_third() -> None:
    for base in ("gnss_only", "vision_only"):
        c = _control(base)
        assert c["detected_n"] == 0 and c["declared_n"] == 0 and c["rejected_pct_mean"] == 0.0
    c = _control("outage_visual")
    assert c["detected_n"] == c["n_seeds"] == 5
    assert c["declared_n"] == 3


@pytest.mark.parametrize("level", [10.0, 40.0])
def test_claim_2_a_large_sustained_spoof_is_declared_in_every_seed_at_five_fixes(level: float) -> None:
    c = _cell("gnss_spoof_sustained", level)
    assert c["declared_n"] == c["n_seeds"]
    assert c["latency_s_mean"] == pytest.approx(0.8)
    assert c["declared_channels"] == "gnss"


def test_claim_3_declaring_a_fault_is_not_protecting_the_estimate() -> None:
    base = _control("gnss_only")["ate_rmse_m_mean"]
    big, mid = _cell("gnss_spoof_sustained", 40.0), _cell("gnss_spoof_sustained", 10.0)
    assert mid["ate_rmse_m_mean"] > 5 * base
    assert mid["ate_rmse_m_mean"] > big["ate_rmse_m_mean"]
    assert mid["ate_rmse_m_hi"] - mid["ate_rmse_m_lo"] > 5.0  # the interval is wide


def test_claim_4_a_modest_sustained_spoof_is_rejected_and_mostly_not_declared_in_time() -> None:
    c, ctl = _cell("gnss_spoof_sustained", 3.0), _control("gnss_only")
    assert c["detected_n"] == c["n_seeds"]
    assert c["declared_n"] == 2
    assert c["latency_s_mean"] > fault_matrix.SPOOF_END_S - fault_matrix.SPOOF_START_S
    assert c["ate_rmse_m_mean"] > 4 * ctl["ate_rmse_m_mean"]
    assert c["nees_mean_mean"] > 20.0
    assert c["coverage_2sigma_pct_mean"] < 50.0


def test_claim_5_a_single_spike_is_rejected_never_declared_and_does_not_move_the_error() -> None:
    c, ctl = _cell("gnss_multipath_spike", 20.0), _control("gnss_only")
    assert c["detected_n"] == c["n_seeds"] and c["declared_n"] == 0
    assert c["ate_rmse_m_lo"] <= ctl["ate_rmse_m_hi"] and ctl["ate_rmse_m_lo"] <= c["ate_rmse_m_hi"]


def test_claim_6_a_slow_bias_is_mostly_invisible_and_makes_the_filter_overconfident() -> None:
    c, ctl = _cell("gnss_slow_bias", 1.0), _control("gnss_only")
    assert c["detected_n"] <= 1 and c["declared_n"] == 0
    assert c["nees_mean_mean"] > 10 * ctl["nees_mean_mean"]
    assert c["coverage_2sigma_pct_mean"] < 50.0
    assert _cell("gnss_slow_bias", 3.0)["detected_n"] == 5


def test_claim_7_a_gnss_timestamp_offset_degrades_calibration_without_detection() -> None:
    cells = [_cell("gnss_time_offset", lv) for lv in (0.05, 0.2, 0.5)]
    assert all(c["declared_n"] == 0 for c in cells)
    ate = [c["ate_rmse_m_mean"] for c in cells]
    cov = [c["coverage_2sigma_pct_mean"] for c in cells]
    assert ate == sorted(ate) and cov == sorted(cov, reverse=True)
    assert cells[2]["coverage_2sigma_pct_mean"] < 60.0 and cells[2]["detected_n"] == 2
    ctl = _control("gnss_only")
    assert cells[0]["ate_rmse_m_lo"] <= ctl["ate_rmse_m_hi"]  # 0.05 s is not visible


def test_claim_7b_a_vision_timestamp_offset_shows_nothing_on_an_uncalibrated_control() -> None:
    ctl = _control("vision_only")
    assert ctl["coverage_2sigma_pct_mean"] < 5.0
    for lv in (0.05, 0.2):
        c = _cell("vision_time_offset", lv)
        assert c["ate_rmse_m_lo"] <= ctl["ate_rmse_m_hi"] and ctl["ate_rmse_m_lo"] <= c["ate_rmse_m_hi"]


def test_claim_8_two_seconds_of_imu_loss_is_catastrophic_and_blames_the_healthy_gnss() -> None:
    c, ctl = _cell("imu_sample_loss", 2.0), _control("gnss_only")
    assert c["ate_rmse_m_mean"] > 100 * ctl["ate_rmse_m_mean"]
    assert c["declared_n"] == c["n_seeds"] and c["declared_channels"] == "gnss"
    short = _cell("imu_sample_loss", 0.5)
    assert short["declared_n"] == 0
    assert short["ate_rmse_m_mean"] > ctl["ate_rmse_m_mean"] and short["coverage_2sigma_pct_mean"] < 60.0


def test_claim_9_a_modest_spoof_after_an_outage_is_not_declared_beyond_the_controls_false_alarms() -> None:
    ctl = _control("outage_visual")
    for lv in (3.0, 10.0):
        assert _cell("gnss_spoof_after_outage", lv)["declared_n"] == ctl["declared_n"]
    assert _cell("gnss_spoof_after_outage", 10.0)["ate_rmse_m_mean"] > 1.5 * ctl["ate_rmse_m_mean"]
    big = _cell("gnss_spoof_after_outage", 22.0)
    assert big["declared_n"] == big["n_seeds"] and big["granted_n"] == 1
    assert big["ate_rmse_m_lo"] > ctl["ate_rmse_m_hi"]


def test_claim_10_vision_outages_raise_the_error_slowly_and_nothing_is_detected() -> None:
    ctl = _control("vision_only")
    errors = [ctl["ate_rmse_m_mean"]] + [_cell("vision_outage", lv)["ate_rmse_m_mean"] for lv in (2.0, 5.0)]
    assert errors == sorted(errors)
    assert all(_cell("vision_outage", lv)["detected_n"] == 0 for lv in (2.0, 5.0))


def test_the_track_a_restatement_counts_match_the_csv() -> None:
    faulted = [r for r in fault_matrix.read_csv(CSV) if r["fault"] != "control"]
    assert len(faulted) == 18
    always = [(r["fault"], r["level"]) for r in faulted if r["declared_n"] == r["n_seeds"]]
    assert sorted(always) == [
        ("gnss_spoof_after_outage", 22.0),
        ("gnss_spoof_sustained", 10.0),
        ("gnss_spoof_sustained", 40.0),
        ("imu_sample_loss", 2.0),
    ]
    assert math.ceil(math.log(0.05) / math.log(0.95)) == 59
