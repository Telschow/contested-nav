"""``scripts/metrics.py`` keeps the counts the documents quote tied to one JSON file."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "metrics.py"


def _load():
    spec = importlib.util.spec_from_file_location("quoted_metrics_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["quoted_metrics_script"] = module
    spec.loader.exec_module(module)
    return module


metrics = _load()

GOOD = {
    "adr_count": 2,
    "tests_collected": 10,
    "coverage_percent": 91.26,
    "coverage_lines_hit": 100,
    "coverage_lines_total": 110,
    "coverage_python": "3.13",
}


def marker(key: str, value: str) -> str:
    return f"<!-- metric:{key} -->{value}<!-- /metric -->"


def make_tree(tmp_path: Path, readme: str = "", adrs: tuple[str, ...] = ("0001-a.md", "0002-b.md")) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "data").mkdir()
    for name in adrs:
        (tmp_path / "docs" / "adr" / name).write_text("# ADR\n", encoding="utf-8")
    (tmp_path / "docs" / "adr" / "index.md").write_text("\n".join(adrs), encoding="utf-8")
    (tmp_path / "docs" / "data" / "metrics.json").write_text(json.dumps(GOOD), encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return tmp_path


class TestRender:
    def test_percent_has_one_decimal_and_counts_are_plain(self):
        assert metrics.render("coverage_percent", GOOD) == "91.3"
        assert metrics.render("tests_collected", GOOD) == "10"

    def test_rewrite_replaces_a_stale_value_and_leaves_other_text(self):
        old = f"We have {marker('tests_collected', '7')} tests in all."
        new = metrics.rewrite(old, GOOD)
        assert new == f"We have {marker('tests_collected', '10')} tests in all."

    def test_rewrite_is_idempotent(self):
        text = f"{marker('adr_count', '2')} and {marker('coverage_percent', '1.0')}%"
        once = metrics.rewrite(text, GOOD)
        assert metrics.rewrite(once, GOOD) == once


class TestCheck:
    def test_a_matching_tree_passes(self, tmp_path):
        root = make_tree(tmp_path, f"{marker('tests_collected', '10')} tests collected")
        assert metrics.check(root, collected=10) == []

    def test_a_stale_marker_is_reported(self, tmp_path):
        root = make_tree(tmp_path, f"{marker('tests_collected', '9')} tests collected")
        problems = metrics.check(root, collected=10)
        assert any("tests_collected reads 9" in p for p in problems)

    def test_a_hand_typed_count_is_reported(self, tmp_path):
        root = make_tree(tmp_path, "There are 12 ADRs and 884 passed here.")
        problems = metrics.check(root, collected=10)
        assert any("12 ADRs" in p for p in problems)
        assert any("884 passed" in p for p in problems)

    def test_a_hand_typed_line_coverage_is_reported(self, tmp_path):
        root = make_tree(tmp_path, "Reached 92.86% line coverage.")
        assert any("line coverage" in p for p in metrics.check(root, collected=10))

    def test_other_percentages_are_not_counts(self, tmp_path):
        root = make_tree(tmp_path, "2-sigma coverage is 20.0% and the floor is 75%.")
        assert metrics.check(root, collected=10) == []

    def test_an_unknown_key_is_reported(self, tmp_path):
        root = make_tree(tmp_path, marker("nonsense", "1"))
        assert any("unknown metric" in p for p in metrics.check(root, collected=10))

    def test_the_collected_count_must_match_pytest(self, tmp_path):
        root = make_tree(tmp_path)
        assert any("pytest collects 11" in p for p in metrics.check(root, collected=11))

    def test_the_adr_count_must_match_the_files(self, tmp_path):
        root = make_tree(tmp_path, adrs=("0001-a.md", "0002-b.md", "0003-c.md"))
        assert any("adr_count is 2, docs/adr has 3" in p for p in metrics.check(root, collected=10))

    def test_an_adr_missing_from_the_index_is_reported(self, tmp_path):
        root = make_tree(tmp_path)
        (root / "docs" / "adr" / "index.md").write_text("0001-a.md", encoding="utf-8")
        assert any("0002-b.md" in p for p in metrics.check(root, collected=10))

    def test_history_documents_may_keep_their_old_counts(self, tmp_path):
        root = make_tree(tmp_path)
        (root / "docs" / "audit").mkdir()
        (root / "docs" / "audit" / "01-x.md").write_text("567 tests", encoding="utf-8")
        (root / "docs" / "ENGINEERING_BASELINE.md").write_text("629 tests", encoding="utf-8")
        assert metrics.check(root, collected=10) == []


class TestCoverage:
    def test_within_tolerance_passes(self):
        measured = {"coverage_percent": 91.0, "coverage_python": "3.13"}
        assert metrics.coverage_problems(GOOD, measured)[0] == []

    def test_a_drop_beyond_tolerance_fails(self):
        measured = {"coverage_percent": 90.0, "coverage_python": "3.13"}
        problems, _ = metrics.coverage_problems(GOOD, measured)
        assert problems and "metrics.py --write --coverage" in problems[0]

    def test_a_rise_beyond_tolerance_also_fails(self):
        measured = {"coverage_percent": 93.0, "coverage_python": "3.13"}
        assert metrics.coverage_problems(GOOD, measured)[0]

    def test_another_interpreter_is_not_compared(self):
        measured = {"coverage_percent": 87.6, "coverage_python": "3.14"}
        problems, note = metrics.coverage_problems(GOOD, measured)
        assert problems == [] and "not compared" in note

    def test_coverage_is_read_from_the_report_file(self, tmp_path):
        report = tmp_path / "coverage.json"
        report.write_text(
            json.dumps({"python": "3.13.16 (cpython)", "modules": [{"hit": 9, "exec": 10}, {"hit": 1, "exec": 10}]}),
            encoding="utf-8",
        )
        got = metrics.coverage_from(report)
        assert got["coverage_percent"] == 50.0
        assert (got["coverage_lines_hit"], got["coverage_lines_total"]) == (10, 20)
        assert got["coverage_python"] == "3.13"


class TestRepository:
    def test_the_recorded_adr_count_matches_the_records(self):
        recorded = metrics.read_metrics()
        assert recorded["adr_count"] == len(metrics.adr_files())

    def test_every_adr_is_in_the_index(self):
        assert metrics.adr_problems() == []

    def test_the_live_documents_quote_the_recorded_values(self):
        recorded = metrics.read_metrics()
        problems = []
        for path in metrics.live_documents():
            problems.extend(metrics.marker_problems(path.read_text(encoding="utf-8"), recorded, path.name))
        assert problems == []

    def test_every_key_is_recorded(self):
        assert set(metrics.KEYS) <= set(metrics.read_metrics())

    @pytest.mark.parametrize("name", ["README.md", "CONSTRAINTS.md", "ROADMAP.md", "CONTRIBUTING.md"])
    def test_the_live_files_are_in_scope(self, name):
        assert (ROOT / name) in metrics.live_documents()
