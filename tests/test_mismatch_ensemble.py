"""The mismatch sweep as an ensemble over seeds: ``navkit sweep mismatch --ensemble-csv``.

The producer is tested here on a tiny sweep (two factors, three seeds) and on synthetic input with a known answer. The
committed CSV and the page that is generated from it are tested in ``test_mismatch_ensemble_page.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from navkit import cli, mismatch_ensemble, mismatch_sweep
from navkit.benchmark import default_config_path, run_case
from navkit.eval.calibration import ensemble_nees, ensemble_nees_band
from navkit.report.page import splice_block

FIELDS = (
    "case",
    "factor",
    "scope",
    "n_runs",
    "dof",
    "epochs",
    "grand_mean",
    "band_low",
    "band_high",
    "fraction_inside",
    "fraction_below",
    "fraction_above",
)
FIRST_SEED, RUNS, FACTORS = 25, 3, (0.5, 1.0)


# --- a known synthetic input -------------------------------------------------------------------------------------


def _box(values: list[float], windows: list[tuple[float, float]] | None = None) -> dict[str, Any]:
    """What ``run_case(..., nees_out=box)`` fills, for a run whose per-epoch NEES is ``values`` on 1 s epochs."""
    return {
        "squared": np.asarray(values, dtype=float),
        "dof": 3,
        "t": np.arange(len(values), dtype=float),
        "windows": windows,
    }


def _known_boxes(windows: list[tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    # Every run has the same series, so the ensemble mean is the series: 4 epochs below the 25-run band, 4 inside it
    # and 2 above it. A NEES of 5 is above the band; its square root (a sigma) would be inside it.
    values = [1.0] * 4 + [3.0] * 4 + [5.0] * 2
    return [_box(values, windows) for _ in range(25)]


def test_a_known_input_is_scored_against_the_band_for_n_runs_and_three_dof() -> None:
    (row,) = mismatch_ensemble.score_cell("gnss_only", 0.5, _known_boxes())
    low, high = ensemble_nees_band(25, 3)
    assert (row["case"], row["factor"], row["scope"]) == ("gnss_only", 0.5, "full")
    assert (row["n_runs"], row["dof"], row["epochs"]) == (25, 3, 10)
    assert (row["band_low"], row["band_high"]) == (low, high)
    assert row["grand_mean"] == pytest.approx(2.6)
    assert row["fraction_below"] == pytest.approx(0.4)
    assert row["fraction_inside"] == pytest.approx(0.4)
    assert row["fraction_above"] == pytest.approx(0.2)


def test_the_known_input_agrees_with_ensemble_nees_on_the_stacked_series() -> None:
    boxes = _known_boxes()
    (row,) = mismatch_ensemble.score_cell("gnss_only", 1.0, boxes)
    want = ensemble_nees(np.vstack([b["squared"] for b in boxes]), dof=3)
    assert row["grand_mean"] == want.grand_mean
    assert (row["fraction_inside"], row["fraction_below"], row["fraction_above"]) == (
        want.fraction_inside,
        want.fraction_below,
        want.fraction_above,
    )


def test_a_case_with_an_outage_also_gets_a_row_scored_over_the_half_open_window_only() -> None:
    full, outage = mismatch_ensemble.score_cell("outage_control", 2.0, _known_boxes(windows=[(4.0, 8.0)]))
    assert (full["scope"], outage["scope"]) == ("full", "outage")
    assert outage["epochs"] == 4  # t = 4, 5, 6, 7
    assert outage["grand_mean"] == pytest.approx(3.0 * 0.0 + (3.0 * 4) / 4)
    assert outage["fraction_inside"] == 1.0
    assert (outage["factor"], outage["case"]) == (2.0, "outage_control")


def test_a_run_with_no_covariance_gives_no_row() -> None:
    assert mismatch_ensemble.score_cell("dead_reckoning", 1.0, [{} for _ in range(25)]) == []


# --- the file ----------------------------------------------------------------------------------------------------


def test_the_csv_columns_are_the_documented_ones_in_order() -> None:
    assert mismatch_ensemble.CSV_FIELDS == FIELDS


def test_the_csv_round_trips_and_is_text_stable() -> None:
    rows = mismatch_ensemble.score_cell("outage_control", 0.7, _known_boxes(windows=[(4.0, 8.0)]))
    text = mismatch_ensemble.csv_text(rows)
    assert text.splitlines()[0] == ",".join(FIELDS)
    assert mismatch_ensemble.parse_csv(text) == rows
    assert mismatch_ensemble.csv_text(mismatch_ensemble.parse_csv(text)) == text


def test_compare_rows_tolerates_the_last_bits_but_not_a_changed_share_or_factor() -> None:
    rows = mismatch_ensemble.score_cell("gnss_only", 0.5, _known_boxes())
    near = [{**rows[0], "grand_mean": rows[0]["grand_mean"] * (1 + 1e-9)}]
    assert mismatch_ensemble.compare_rows(near, rows) == []
    assert mismatch_ensemble.compare_rows([{**rows[0], "fraction_above": 0.3}], rows)
    assert mismatch_ensemble.compare_rows([{**rows[0], "factor": 0.6}], rows)
    assert mismatch_ensemble.compare_rows(rows + rows, rows)


# --- the command, on a tiny sweep ------------------------------------------------------------------------------


def _command(tmp_path: Path, tag: str, *extra: str) -> list[str]:
    return [
        "sweep",
        "mismatch",
        "--cases",
        "outage_control",
        "--scales",
        *[str(f) for f in FACTORS],
        "--seeds",
        "2",
        "--out",
        str(tmp_path / f"{tag}.json"),
        "--csv",
        str(tmp_path / f"{tag}_single.csv"),
        *extra,
    ]


@pytest.fixture(scope="module")
def tiny(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The tiny sweep twice with the ensemble flags and once without them."""
    tmp = tmp_path_factory.mktemp("tiny")
    out: dict[str, Path] = {}
    for tag in ("a", "b"):
        csv_path = tmp / f"{tag}.csv"
        code = cli.main(_command(tmp, tag, "--ensemble-csv", str(csv_path), "--ensemble-seeds", str(RUNS)))
        assert code == 0
        out[tag] = csv_path
        out[f"{tag}_json"] = tmp / f"{tag}.json"
        out[f"{tag}_single"] = tmp / f"{tag}_single.csv"
    assert cli.main(_command(tmp, "plain")) == 0
    out["plain_json"], out["plain_single"] = tmp / "plain.json", tmp / "plain_single.csv"
    return out


def test_the_tiny_sweep_writes_the_columns_and_is_deterministic(tiny: dict[str, Path]) -> None:
    first = tiny["a"].read_text(encoding="utf-8")
    assert first.splitlines()[0] == ",".join(FIELDS)
    assert first == tiny["b"].read_text(encoding="utf-8")
    rows = mismatch_ensemble.parse_csv(first)
    # outage_control has an outage window, so each factor has a full row and an outage row.
    assert [(r["case"], r["factor"], r["scope"]) for r in rows] == [
        ("outage_control", 0.5, "full"),
        ("outage_control", 0.5, "outage"),
        ("outage_control", 1.0, "full"),
        ("outage_control", 1.0, "outage"),
    ]
    assert {(r["n_runs"], r["dof"]) for r in rows} == {(RUNS, 3)}
    assert all((r["band_low"], r["band_high"]) == ensemble_nees_band(RUNS, 3) for r in rows)


def test_the_factor_reaches_the_filter_so_two_factors_give_two_results(tiny: dict[str, Path]) -> None:
    rows = mismatch_ensemble.parse_csv(tiny["a"].read_text(encoding="utf-8"))
    full = {r["factor"]: r for r in rows if r["scope"] == "full"}
    assert full[0.5]["grand_mean"] > 2.0 * full[1.0]["grand_mean"]  # a filter told too little noise is overconfident


def test_a_cell_is_the_sweeps_own_run_case_path_on_seeds_25_to_27(tiny: dict[str, Path]) -> None:
    doc = yaml.safe_load(default_config_path().read_text())
    case = mismatch_sweep.with_scale(doc["cases"]["outage_control"], 0.5, "both")
    series = []
    for seed in range(FIRST_SEED, FIRST_SEED + RUNS):
        box: dict[str, Any] = {}
        run_case("outage_control", case, doc["defaults"], seed=seed, nees_out=box)
        series.append(box["squared"])
    want = ensemble_nees(np.vstack(series), dof=3)
    got = next(
        r
        for r in mismatch_ensemble.parse_csv(tiny["a"].read_text(encoding="utf-8"))
        if r["factor"] == 0.5 and r["scope"] == "full"
    )
    assert got["grand_mean"] == pytest.approx(want.grand_mean, rel=1e-12)
    assert got["fraction_inside"] == pytest.approx(want.fraction_inside)
    assert got["epochs"] == want.n_epochs


def test_the_existing_sweep_outputs_do_not_change_when_the_ensemble_is_asked_for(tiny: dict[str, Path]) -> None:
    assert tiny["a_single"].read_bytes() == tiny["plain_single"].read_bytes()
    assert json.loads(tiny["a_json"].read_text()) == json.loads(tiny["plain_json"].read_text())


def test_the_ensemble_flags_are_checked(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(_command(tmp_path, "bad", "--ensemble-csv", str(tmp_path / "e.csv"), "--ensemble-seeds", "1"))


def test_the_page_block_is_rewritten_from_the_csv(tmp_path: Path) -> None:
    rows = mismatch_ensemble.score_cell("outage_control", 0.5, _known_boxes(windows=[(4.0, 8.0)]))
    page = f"head\n{mismatch_ensemble.START}\nold\n{mismatch_ensemble.END}\ntail\n"
    new = splice_block(page, "mismatch-ensemble", mismatch_ensemble.markdown_table(rows))
    assert new.startswith("head\n") and new.endswith("\ntail\n") and "old" not in new
    assert "| outage_control | 0.5 | outage |" in new
    with pytest.raises(ValueError, match="needs the lines"):
        splice_block("no markers", "mismatch-ensemble", "x")


def _one_factor(tmp_path: Path, tag: str, *extra: str) -> list[str]:
    argv = _command(tmp_path, tag, "--ensemble-seeds", str(RUNS), *extra)
    argv[argv.index("--scales") + 1 : argv.index("--seeds")] = ["1"]
    return argv


def test_compare_and_page_use_the_ensemble_csv(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(f"head\n{mismatch_ensemble.START}\nold\n{mismatch_ensemble.END}\ntail\n", encoding="utf-8")
    csv_path = tmp_path / "e.csv"
    argv = _one_factor(tmp_path, "c", "--ensemble-csv", str(csv_path), "--ensemble-page", str(page))
    assert cli.main(argv) == 0
    rows = mismatch_ensemble.parse_csv(csv_path.read_text(encoding="utf-8"))
    single = mismatch_sweep.TABLE.read(tmp_path / "c_single.csv")
    assert page.read_text(encoding="utf-8") == splice_block(
        f"head\n{mismatch_ensemble.START}\nold\n{mismatch_ensemble.END}\ntail\n",
        "mismatch-ensemble",
        mismatch_ensemble.page_block(rows, single),
    )
    # The same run matches its own file, and a file with one share changed does not.
    again = _one_factor(tmp_path, "d", "--ensemble-csv", str(tmp_path / "e2.csv"), "--ensemble-compare", str(csv_path))
    assert cli.main(again) == 0
    rows[0]["fraction_above"] = 0.123
    csv_path.write_text(mismatch_ensemble.csv_text(rows), encoding="utf-8")
    assert cli.main(again) == 1


def test_the_page_and_compare_flags_need_the_csv_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(_one_factor(tmp_path, "e", "--ensemble-page", str(tmp_path / "p.md")))
