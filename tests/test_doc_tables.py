"""Tests for the documentation table checker.

``scripts/check_doc_tables.py`` is the thing that makes the claim "no number on
this page is typed in by hand" checkable, so it needs to be tested for the two
ways it can be useless: passing vacuously when a table drifts, and failing on a
table that is correct.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_doc_tables.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_doc_tables", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_doc_tables = _load()


def _results() -> dict:
    return {
        "cases": [
            {
                "name": "gnss_only",
                "headline": {
                    "ate_rmse_m": 0.5030724,
                    "claimed_sigma_p_m": 0.2522110,
                    "nees_mean": 3.742905,
                    "coverage": {"2sigma": 1.0},
                },
            },
            {
                "name": "dead_reckoning",
                "headline": {"ate_rmse_m": 1.877, "claimed_sigma_p_m": None, "nees_mean": None, "coverage": None},
            },
            {
                "name": "vision_only",
                "headline": {
                    "ate_rmse_m": 2.309,
                    "claimed_sigma_p_m": 0.156,
                    "nees_mean": 331.0,
                    "coverage": {"2sigma": 0.007},
                },
            },
        ]
    }


MARKDOWN = """# Title

| Scenario | ATE RMSE (m) | Claimed 1-sigma (m) | Mean NEES | Coverage at 2 sigma | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| GNSS only (control) | 0.503 | 0.252 | 3.7 | 100.0% | mixed |
| Dead reckoning | 1.877 | n/a | n/a | n/a | no covariance |
| Vision only | 2.309 | 0.156 | 331.0 | 0.7% | overconfident |

Some prose after the table.
"""

HTML = """<table>
  <thead><tr><th>Scenario</th><th class="num">ATE RMSE (m)</th>
    <th class="num">Claimed 1&sigma; (m)</th><th class="num">Mean NEES</th>
    <th class="num">Coverage @ 2&sigma;</th><th>Verdict</th></tr></thead>
  <tbody>
    <tr><td>GNSS only (control)</td><td class="num">0.503</td><td class="num">0.252</td><td class="num">3.7</td><td class="num">100.0%</td><td>mixed</td></tr>
    <tr><td>Dead reckoning</td><td class="num">1.877</td><td class="num">n/a</td><td class="num">n/a</td><td class="num">n/a</td><td>no covariance</td></tr>
    <tr><td>Vision only</td><td class="num">2.309</td><td class="num">0.156</td><td class="num">331.0</td><td class="num">0.7%</td><td>overconfident</td></tr>
  </tbody>
</table>
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_markdown_table_is_read_in_order(tmp_path: Path) -> None:
    rows = check_doc_tables._markdown_cells(MARKDOWN)
    assert [r[0] for r in rows] == ["GNSS only (control)", "Dead reckoning", "Vision only"]
    assert rows[0][1] == "0.503"
    assert rows[1][2] == "n/a"


def test_html_table_is_read_in_order() -> None:
    rows = check_doc_tables._html_cells(HTML)
    assert len(rows) == 3
    assert rows[2][1] == "2.309"
    assert rows[0][4] == "100.0%"


def test_matching_documents_pass(tmp_path: Path) -> None:
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    readme = _write(tmp_path / "README.md", MARKDOWN)
    page = _write(tmp_path / "index.html", HTML)
    assert check_doc_tables.check(results, [readme, page]) == 0


def test_a_drifted_number_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The check must catch exactly the failure it exists to prevent."""
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    readme = _write(tmp_path / "README.md", MARKDOWN.replace("| 2.309 |", "| 2.999 |"))
    assert check_doc_tables.check(results, [readme]) == 1
    assert "2.999" in capsys.readouterr().err


def test_a_dropped_row_fails(tmp_path: Path) -> None:
    """A row deleted from the table is drift too, and must not pass silently."""
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    truncated = MARKDOWN.split("| Vision only |")[0]
    readme = _write(tmp_path / "README.md", truncated)
    assert check_doc_tables.check(results, [readme]) == 1


def test_an_invented_row_fails(tmp_path: Path) -> None:
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    extra = MARKDOWN.replace(
        "| Vision only | 2.309 | 0.156 | 331.0 | 0.7% | overconfident |",
        "| Vision only | 2.309 | 0.156 | 331.0 | 0.7% | overconfident |\n"
        "| Invented case | 0.100 | 0.100 | 3.0 | 99.2% | calibrated |",
    )
    readme = _write(tmp_path / "README.md", extra)
    assert check_doc_tables.check(results, [readme]) == 1


def test_a_missing_document_fails(tmp_path: Path) -> None:
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    assert check_doc_tables.check(results, [tmp_path / "nope.md"]) == 1


def test_n_a_row_is_required_for_an_uncalibrated_case(tmp_path: Path) -> None:
    """A case with no covariance must show n/a, not a fabricated zero."""
    results = _write(tmp_path / "results.json", json.dumps(_results()))
    readme = _write(
        tmp_path / "README.md", MARKDOWN.replace("| 1.877 | n/a | n/a | n/a |", "| 1.877 | 0.000 | 0.000 | 0.000 |")
    )
    assert check_doc_tables.check(results, [readme]) == 1


def test_the_real_documents_match_the_committed_benchmark() -> None:
    """Guard the shipped documents against the shipped results.

    Skipped when results/benchmark.json is absent, which is the normal state of
    a fresh clone because generated results are not committed. CI does not skip
    the check: the benchmark job regenerates the benchmark and runs
    ``scripts/check_doc_tables.py`` against it.
    """
    results = ROOT / "results" / "benchmark.json"
    if not results.exists():
        pytest.skip("results/benchmark.json not generated")
    assert check_doc_tables.check(results, [ROOT / "README.md", ROOT / "docs" / "index.html"]) == 0
