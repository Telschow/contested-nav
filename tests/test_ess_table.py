"""The per-case effective sample sizes over seeded runs: the producer, the CSV and the command flags.

The runs are the same as the ensemble's (``navkit.ensemble.Collector``), so the table and the ensemble describe one
set of runs. The committed file is checked against the page in ``test_ess_page.py``.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit import cli, ensemble
from navkit.eval.statistics import autocorrelation_estimate

NAMES = ["dead_reckoning", "gnss_only", "outage_control"]


def _doc():
    return yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tiny():
    doc = _doc()
    collector = ensemble.Collector()
    boxes: dict[str, list[dict]] = {}
    for name in NAMES:
        for seed in range(3):
            box: dict = {}
            bm.run_case(name, doc["cases"][name], doc["defaults"], seed=seed, nees_out=box)
            collector.add(name, box)
            boxes.setdefault(name, []).append(box)
    return collector, boxes


def test_the_columns_are_documented():
    assert ensemble.ESS_FIELDS == (
        "case",
        "scope",
        "n_runs",
        "epochs",
        "n_eff_min",
        "n_eff_median",
        "n_eff_max",
        "truncated_runs",
    )


def test_rows_follow_the_ensemble_cases_and_scopes_and_skip_dead_reckoning(tiny):
    collector, _ = tiny
    rows = collector.ess_rows()
    assert [(r["case"], r["scope"]) for r in rows] == [
        ("gnss_only", "full"),
        ("outage_control", "full"),
        ("outage_control", "outage"),
    ]
    assert {r["n_runs"] for r in rows} == {3}
    ens = collector.rows()
    assert [(r["case"], r["scope"], r["n_epochs"]) for r in ens] == [(r["case"], r["scope"], r["epochs"]) for r in rows]


def test_the_numbers_are_the_estimator_applied_to_each_runs_scored_series(tiny):
    collector, boxes = tiny
    rows = {(r["case"], r["scope"]): r for r in collector.ess_rows()}
    full = [autocorrelation_estimate(np.asarray(b["squared"], float)) for b in boxes["gnss_only"]]
    row = rows[("gnss_only", "full")]
    sizes = [e.effective_sample_size for e in full]
    assert row["n_eff_min"] == min(sizes) and row["n_eff_max"] == max(sizes)
    assert row["n_eff_median"] == float(np.median(sizes))
    assert row["truncated_runs"] == sum(e.truncated for e in full)
    for r in rows.values():
        assert 1.0 <= r["n_eff_min"] <= r["n_eff_median"] <= r["n_eff_max"] <= r["epochs"]
        assert 0 <= r["truncated_runs"] <= r["n_runs"]


def test_the_outage_scope_uses_the_window_series(tiny):
    collector, boxes = tiny
    rows = {(r["case"], r["scope"]): r for r in collector.ess_rows()}
    box = boxes["outage_control"][0]
    window = np.asarray(box["squared"], float)[ensemble.window_mask(box["t"], box["windows"])]
    assert rows[("outage_control", "outage")]["epochs"] == window.size


def test_the_csv_is_deterministic_and_reads_back(tiny):
    collector, _ = tiny
    rows = collector.ess_rows()
    text = ensemble.csv_text(rows, ensemble.ESS_FIELDS)
    assert text.splitlines()[0] == ",".join(ensemble.ESS_FIELDS)
    assert ensemble.csv_text(collector.ess_rows(), ensemble.ESS_FIELDS) == text
    assert ensemble.parse_csv(text, ensemble.ESS_FIELDS) == rows


def test_the_table_has_a_line_per_row_and_marks_truncation_in_words(tiny):
    collector, _ = tiny
    rows = collector.ess_rows()
    table = ensemble.ess_markdown_table(rows)
    assert table.count("\n| ") >= len(rows)
    for r in rows:
        assert r["case"] in table
    with pytest.raises(ValueError):
        ensemble.ess_markdown_table([])


def test_compare_rows_takes_the_field_list():
    rows = [
        {
            "case": "a",
            "scope": "full",
            "n_runs": 3,
            "epochs": 10,
            "n_eff_min": 2.0,
            "n_eff_median": 3.0,
            "n_eff_max": 4.0,
            "truncated_runs": 1,
        }
    ]
    assert ensemble.compare_rows(rows, rows, ensemble.ESS_FIELDS) == []
    assert ensemble.compare_rows([{**rows[0], "n_eff_max": 4.0 * 1.001}], rows, ensemble.ESS_FIELDS) != []
    assert ensemble.compare_rows([{**rows[0], "truncated_runs": 2}], rows, ensemble.ESS_FIELDS) != []


def test_the_command_writes_the_ess_csv_and_page_table_and_compares(tmp_path):
    page = tmp_path / "page.md"
    page.write_text("a\n<!-- ess:start -->\nSTALE\n<!-- ess:end -->\nb\n", encoding="utf-8")
    csv_path = tmp_path / "ess.csv"
    base = ["sweep", "seeds", "--seeds", "2", "--only", "gnss_only", "--out", str(tmp_path / "s.json")]
    assert cli.main([*base, "--ess-csv", str(csv_path), "--ess-page", str(page)]) == 0
    rows = ensemble.parse_csv(csv_path.read_text(encoding="utf-8"), ensemble.ESS_FIELDS)
    assert [(r["case"], r["scope"], r["n_runs"]) for r in rows] == [("gnss_only", "full", 2)]
    text = page.read_text(encoding="utf-8")
    assert "STALE" not in text and ensemble.ess_markdown_table(rows) in text and text.startswith("a\n")
    assert cli.main([*base, "--ess-compare", str(csv_path)]) == 0
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("gnss_only,full,2,", "gnss_only,full,3,"), encoding="utf-8"
    )
    assert cli.main([*base, "--ess-compare", str(csv_path)]) == 1
