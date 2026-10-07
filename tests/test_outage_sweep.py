"""The outage sweep: grid planning, window injection, summaries, output files and determinism."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from navkit import cli, outage_sweep
from navkit.benchmark import default_config_path
from navkit.outage_sweep import CSV_FIELDS, plan_grid, summarise_cell, with_outage

TIMING_AND_ENV = frozenset({"environment", "wall_s", "runtime_s"})


@pytest.fixture(scope="module")
def cases() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text())["cases"]


# ------------------------------------------------------------------ planning ---


def test_plan_grid_keeps_windows_that_fit_and_lists_the_rest() -> None:
    kept, skipped = plan_grid(["a", "b"], [5.0, 10.0], [10.0, 20.0], 30.0)
    # 10 + 20 == 30 fits exactly; nothing here overruns, so the grid is the full product.
    assert len(kept) == 2 * 2 * 2
    assert skipped == []
    kept, skipped = plan_grid(["a"], [5.0, 15.0], [10.0, 20.0], 30.0)
    assert skipped == [(15.0, 20.0)]
    assert ("a", 15.0, 20.0) not in kept
    assert len(kept) == 3


def test_plan_grid_can_be_empty() -> None:
    kept, skipped = plan_grid(["a"], [25.0], [10.0], 30.0)
    assert kept == []
    assert skipped == [(25.0, 10.0)]


def test_with_outage_replaces_the_window_and_leaves_the_original_alone(cases: dict[str, Any]) -> None:
    original = copy.deepcopy(cases["outage_visual"])
    changed = with_outage(cases["outage_visual"], 8.0, 6.0)
    assert changed["scenario"]["gnss_outages"] == [{"start_s": 8.0, "duration_s": 6.0, "reason": "contested"}]
    assert cases["outage_visual"] == original
    # Everything except the outage is untouched, so a difference between cells is the outage.
    stripped = copy.deepcopy(changed)
    stripped["scenario"]["gnss_outages"] = original["scenario"]["gnss_outages"]
    assert stripped == original


# ----------------------------------------------------------------- summaries ---


def _row(seed: int, ate: float, nees: float | None, cov: float | None, verdict: str) -> dict[str, Any]:
    return {
        "seed": seed,
        "ate_rmse_m": ate,
        "nees_mean": nees,
        "coverage_2sigma_pct": cov,
        "claimed_sigma_p_m": 0.3,
        "verdict": verdict,
    }


def test_summarise_cell_gives_mean_interval_and_verdict_counts() -> None:
    rows = [
        _row(0, 1.0, 3.0, 99.0, "calibrated"),
        _row(1, 3.0, 5.0, 100.0, "overconfident"),
        _row(2, 2.0, 4.0, 98.0, "calibrated"),
    ]
    cell = summarise_cell(rows)
    assert cell["n_seeds"] == 3
    assert cell["ate_rmse_m"]["mean"] == pytest.approx(2.0)
    assert cell["ate_rmse_m"]["lo"] <= 2.0 <= cell["ate_rmse_m"]["hi"]
    assert cell["verdicts"] == {"calibrated": 2, "overconfident": 1}


def test_summarise_cell_marks_unmeasured_metrics_as_none() -> None:
    cell = summarise_cell([_row(0, 1.0, None, None, "n/a"), _row(1, 2.0, None, None, "n/a")])
    assert cell["nees_mean"] is None
    assert cell["coverage_2sigma_pct"] is None
    assert cell["ate_rmse_m"]["mean"] == pytest.approx(1.5)


# ------------------------------------------------------------------- the CLI ---


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in TIMING_AND_ENV}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


@pytest.fixture(scope="module")
def small_sweep(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Two seeds of the control over two short windows, written with every output enabled."""
    root = tmp_path_factory.mktemp("outage")
    paths = {"json": root / "a.json", "csv": root / "a.csv", "png": root / "a.png"}
    argv = [
        "sweep", "outages", "--cases", "outage_control", "--starts", "5", "--durations", "5", "10",
        "--seeds", "2", "--out", str(paths["json"]), "--csv", str(paths["csv"]), "--figure", str(paths["png"]),
    ]  # fmt: skip
    assert cli.main(argv) == 0
    return paths


def test_the_json_carries_the_synthetic_disclaimer_and_the_grid(small_sweep: dict[str, Path]) -> None:
    payload = json.loads(small_sweep["json"].read_text())
    assert payload["schema"] == "navkit-outage-sweep/1"
    assert payload["data_class"] == "synthetic"
    assert "must not be presented as such" in payload["disclaimer"]
    assert payload["config_file"] == "configs/benchmark.yaml"
    assert [(c["start_s"], c["duration_s"]) for c in payload["summary"]] == [(5.0, 5.0), (5.0, 10.0)]
    assert len(payload["runs"]) == 2 * 2


def test_the_csv_has_one_row_per_cell_with_the_documented_columns(small_sweep: dict[str, Path]) -> None:
    with small_sweep["csv"].open() as f:
        rows = list(csv.DictReader(f))
    assert tuple(rows[0]) == CSV_FIELDS
    assert [(r["start_s"], r["duration_s"], r["end_s"]) for r in rows] == [
        ("5.0", "5.0", "10.0"),
        ("5.0", "10.0", "15.0"),
    ]
    assert all(float(r["ate_rmse_m_lo"]) <= float(r["ate_rmse_m_mean"]) <= float(r["ate_rmse_m_hi"]) for r in rows)


def test_the_figure_is_written(small_sweep: dict[str, Path]) -> None:
    assert small_sweep["png"].stat().st_size > 10_000


def test_a_longer_outage_means_a_larger_error_without_vision(small_sweep: dict[str, Path]) -> None:
    """The control integrates the IMU alone through the outage, so more outage is more drift."""
    short, long = json.loads(small_sweep["json"].read_text())["summary"]
    assert long["ate_rmse_m"]["mean"] > short["ate_rmse_m"]["mean"]


def test_the_sweep_is_reproducible(small_sweep: dict[str, Path], tmp_path: Path) -> None:
    again = tmp_path / "b.json"
    argv = [
        "sweep", "outages", "--cases", "outage_control", "--starts", "5", "--durations", "5", "10",
        "--seeds", "2", "--out", str(again),
    ]  # fmt: skip
    assert cli.main(argv) == 0
    first = _strip(json.loads(small_sweep["json"].read_text()))
    assert _strip(json.loads(again.read_text())) == first


def test_markdown_table_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["sweep", "outages", "--cases", "outage_control", "--starts", "5", "--durations", "5"]
    argv += ["--seeds", "2", "--markdown", "--out", str(tmp_path / "m.json")]
    assert cli.main(argv) == 0
    assert "| outage_control | 5 | 5 |" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--seeds", "1"], "at least 2 seeds"),
        (["--cases", "nope"], "unknown case"),
        (["--durations", "0"], "durations > 0"),
        (["--starts", "-1"], "starts must be >= 0"),
        (["--starts", "29", "--durations", "5"], "overruns"),
    ],
)
def test_bad_arguments_are_refused(argv: list[str], message: str, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=message):
        outage_sweep.main([*argv, "--out", str(tmp_path / "x.json")])
