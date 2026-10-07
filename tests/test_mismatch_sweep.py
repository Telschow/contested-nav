"""``navkit sweep mismatch`` and the claims ``docs/mismatch.md`` makes from its CSV."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from navkit import cli, mismatch_sweep
from navkit.benchmark import _eskf_config, default_config_path, run_case
from navkit.degrade import scenario_from_dict

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "docs" / "data" / "mismatch_sweep.csv"
PAGE = ROOT / "docs" / "mismatch.md"


def _doc() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text())


def _scenario():
    return scenario_from_dict(_doc()["cases"]["outage_visual"]["scenario"])


# --- the filter config ---------------------------------------------------------------------


def test_the_default_scale_leaves_the_filter_sigmas_untouched() -> None:
    sc = _scenario()
    cfg = _eskf_config(sc, {})
    assert cfg.gnss_position_sigma_m == sc.gnss.sigma_m
    assert cfg.vision_rot_sigma_deg == sc.vision.rot_sigma_deg
    assert cfg.vision_trans_sigma_m == sc.vision.trans_sigma_m


def test_the_scales_multiply_only_what_the_filter_assumes() -> None:
    sc = _scenario()
    cfg = _eskf_config(sc, {"gnss_sigma_scale": 2.0, "vision_sigma_scale": 0.5})
    assert cfg.gnss_position_sigma_m == pytest.approx(2.0 * sc.gnss.sigma_m)
    assert cfg.vision_rot_sigma_deg == pytest.approx(0.5 * sc.vision.rot_sigma_deg)
    assert cfg.vision_trans_sigma_m == pytest.approx(0.5 * sc.vision.trans_sigma_m)
    assert sc.gnss.sigma_m == _scenario().gnss.sigma_m  # the generator's sigma is not touched


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_non_positive_or_non_finite_scale_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="gnss_sigma_scale"):
        _eskf_config(_scenario(), {"gnss_sigma_scale": bad})


def test_a_scale_of_one_reproduces_the_benchmark_record_exactly() -> None:
    doc = _doc()
    case = doc["cases"]["gnss_only"]
    plain = run_case("gnss_only", case, doc["defaults"])
    scaled = run_case("gnss_only", mismatch_sweep.with_scale(case, 1.0, "both"), doc["defaults"])
    for rec in (plain, scaled):
        for key in ("runtime_s", "wall_s", "realtime_factor"):
            rec.pop(key, None)
            rec["stats"].pop(key, None)
            rec["summary"].pop(key, None)
    assert json.dumps(plain, default=str, sort_keys=True) == json.dumps(scaled, default=str, sort_keys=True)


def test_the_generator_keeps_the_true_noise_while_the_filter_is_told_otherwise() -> None:
    doc = _doc()
    case = mismatch_sweep.with_scale(doc["cases"]["gnss_only"], 2.0, "both")
    rec = run_case("gnss_only", case, doc["defaults"], seed=0)
    true_sigma = doc["cases"]["gnss_only"]["scenario"]["gnss"]["sigma_m"]
    assert rec["scenario"]["gnss"]["sigma_m"] == true_sigma
    assert rec["estimator"]["gnss_position_sigma_m"] == pytest.approx(2.0 * true_sigma)


# --- with_scale ----------------------------------------------------------------------------


def test_with_scale_touches_only_the_requested_channel_and_leaves_the_input_alone() -> None:
    case = {"estimator": {"vision_fuse": True}}
    before = copy.deepcopy(case)
    gnss = mismatch_sweep.with_scale(case, 0.5, "gnss")
    vision = mismatch_sweep.with_scale(case, 0.5, "vision")
    both = mismatch_sweep.with_scale(case, 0.5, "both")
    assert case == before
    assert gnss["estimator"] == {"vision_fuse": True, "gnss_sigma_scale": 0.5}
    assert vision["estimator"] == {"vision_fuse": True, "vision_sigma_scale": 0.5}
    assert set(both["estimator"]) == {"vision_fuse", "gnss_sigma_scale", "vision_sigma_scale"}


def test_with_scale_refuses_a_bad_channel_or_scale() -> None:
    with pytest.raises(ValueError, match="channel"):
        mismatch_sweep.with_scale({}, 1.0, "imu")
    with pytest.raises(ValueError, match="positive"):
        mismatch_sweep.with_scale({}, 0.0, "gnss")


# --- the command ---------------------------------------------------------------------------


def test_the_command_is_routed_and_runs_a_small_grid(tmp_path: Path) -> None:
    out = tmp_path / "m.json"
    csv_path = tmp_path / "m.csv"
    code = cli.main(
        [
            "sweep",
            "mismatch",
            "--cases",
            "gnss_only",
            "--scales",
            "0.5",
            "1",
            "--seeds",
            "2",
            "--out",
            str(out),
            "--csv",
            str(csv_path),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["claim_type"] == "MEASUREMENT"
    assert payload["data_class"] == "synthetic"
    assert "min_coverage_note" in payload
    rows = mismatch_sweep.read_csv(csv_path)
    assert [r["scale"] for r in rows] == [0.5, 1.0]
    # An optimistic noise model makes the gate reject healthy fixes; the true one does not.
    assert rows[0]["gnss_rejected_pct_mean"] > 0.0
    assert rows[1]["gnss_rejected_pct_mean"] == 0.0


def test_the_command_renders_the_figure_and_rewrites_the_page_block(tmp_path: Path) -> None:
    figure = tmp_path / "fig.png"
    page = tmp_path / "page.md"
    page.write_text("intro\n<!-- mismatch:start -->\nold\n<!-- mismatch:end -->\noutro\n", encoding="utf-8")
    code = cli.main(
        [
            "sweep",
            "mismatch",
            "--cases",
            "gnss_only",
            "--scales",
            "0.5",
            "1",
            "--seeds",
            "2",
            "--out",
            str(tmp_path / "m.json"),
            "--figure",
            str(figure),
            "--page",
            str(page),
        ]
    )
    assert code == 0
    assert figure.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    text = page.read_text(encoding="utf-8")
    assert text.startswith("intro\n") and text.endswith("outro\n")
    assert "old" not in text and "| gnss_only | 0.5 |" in text


def test_the_command_refuses_a_bad_grid() -> None:
    with pytest.raises(SystemExit, match="at least 2 seeds"):
        cli.main(["sweep", "mismatch", "--seeds", "1"])
    with pytest.raises(SystemExit, match="positive"):
        cli.main(["sweep", "mismatch", "--scales", "0", "--seeds", "2"])
    with pytest.raises(SystemExit, match="unknown case"):
        cli.main(["sweep", "mismatch", "--cases", "nope", "--seeds", "2"])


def test_compare_exits_nonzero_when_the_result_differs(tmp_path: Path) -> None:
    csv_path = tmp_path / "m.csv"
    args = ["sweep", "mismatch", "--cases", "gnss_only", "--scales", "1", "--seeds", "2"]
    assert cli.main([*args, "--out", str(tmp_path / "a.json"), "--csv", str(csv_path)]) == 0
    assert cli.main([*args, "--out", str(tmp_path / "b.json"), "--compare", str(csv_path)]) == 0
    rows = mismatch_sweep.read_csv(csv_path)
    rows[0]["ate_rmse_m_mean"] *= 1.5
    mismatch_sweep.write_csv(csv_path, rows)
    assert cli.main([*args, "--out", str(tmp_path / "c.json"), "--compare", str(csv_path)]) == 1


def test_compare_rows_tolerates_last_bit_differences_but_not_real_ones() -> None:
    row = dict.fromkeys(mismatch_sweep.CSV_FIELDS)
    row.update(case="c", channel="both", n_seeds=2, verdicts="v", scale=1.0, ate_rmse_m_mean=1.0)
    near = {**row, "ate_rmse_m_mean": 1.0 + 1e-9}
    far = {**row, "ate_rmse_m_mean": 1.001}
    assert mismatch_sweep.compare_rows([near], [row]) == []
    assert mismatch_sweep.compare_rows([far], [row]) != []
    assert mismatch_sweep.compare_rows([row], [row, row]) != []


def test_csv_round_trips_through_text() -> None:
    rows = mismatch_sweep.read_csv(CSV)
    assert rows and all(r["n_seeds"] >= 2 for r in rows)


# --- the committed result and the page -----------------------------------------------------


def _by(case: str) -> dict[float, dict[str, Any]]:
    return {r["scale"]: r for r in mismatch_sweep.read_csv(CSV) if r["case"] == case}


def test_the_page_table_is_the_committed_csv() -> None:
    page = PAGE.read_text(encoding="utf-8")
    expected = mismatch_sweep.splice_table(page, mismatch_sweep.markdown_table(mismatch_sweep.read_csv(CSV)))
    assert page == expected


def test_a_page_without_markers_is_refused() -> None:
    with pytest.raises(ValueError, match="markers"):
        mismatch_sweep.splice_table("no markers", "x")


def test_the_grid_has_the_scale_one_row_for_each_case() -> None:
    for case in ("gnss_only", "outage_control"):
        assert 1.0 in _by(case)


@pytest.mark.parametrize("case", ["gnss_only", "outage_control"])
def test_claim_1_an_optimistic_model_makes_the_gate_reject_fixes_and_the_error_grow(case: str) -> None:
    rows = _by(case)
    true_noise, worst = rows[1.0], rows[min(rows)]
    assert true_noise["gnss_rejected_pct_mean"] == 0.0
    assert worst["gnss_rejected_pct_mean"] > 50.0
    assert worst["ate_rmse_m_mean"] > (10.0 if case == "gnss_only" else 2.0) * true_noise["ate_rmse_m_mean"]


@pytest.mark.parametrize("case", ["gnss_only", "outage_control"])
def test_claim_2_coverage_leaves_the_90_percent_band_between_0_7_and_0_8(case: str) -> None:
    rows = _by(case)
    assert rows[0.7]["coverage_2sigma_pct_mean"] < 90.0 <= rows[0.8]["coverage_2sigma_pct_mean"]
    assert rows[0.7]["gnss_rejected_pct_mean"] < 10.0


def test_claim_3_a_pessimistic_model_is_benign_for_gnss_only_accuracy_and_loose_in_its_claim() -> None:
    rows = _by("gnss_only")
    base = rows[1.0]
    for scale in (2.0, 4.0):
        r = rows[scale]
        assert r["ate_rmse_m_lo"] <= base["ate_rmse_m_hi"] and base["ate_rmse_m_lo"] <= r["ate_rmse_m_hi"]
        assert r["coverage_2sigma_pct_mean"] == 100.0
        assert r["nees_mean_mean"] < 3.0
    assert rows[4.0]["claimed_sigma_p_m_mean"] > rows[2.0]["claimed_sigma_p_m_mean"] > base["claimed_sigma_p_m_mean"]


@pytest.mark.parametrize("case", ["gnss_only", "outage_control"])
def test_claim_4_with_the_true_noise_the_mean_nees_is_above_three_but_not_by_much(case: str) -> None:
    rows = _by(case)
    assert rows[1.0]["nees_mean_mean"] > 3.0
    assert rows[1.0]["nees_mean_lo"] <= 3.0
    assert rows[1.25]["nees_mean_mean"] < 3.0


def test_claim_5_outage_control_error_falls_as_the_assumed_noise_grows() -> None:
    rows = _by("outage_control")
    scales = sorted(rows)
    errors = [rows[s]["ate_rmse_m_mean"] for s in scales]
    assert errors == sorted(errors, reverse=True)
    assert rows[4.0]["ate_rmse_m_hi"] < rows[1.0]["ate_rmse_m_lo"]


def test_the_default_grid_includes_every_factor_the_page_discusses() -> None:
    assert {0.7, 0.8, 1.0, 1.25, 2.0, 4.0} <= set(mismatch_sweep.DEFAULT_SCALES)
