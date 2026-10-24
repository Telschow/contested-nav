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
    "tests_collected_floor": 100,
    "coverage_percent": 91.26,
    "coverage_lines_hit": 100,
    "coverage_lines_total": 110,
    "coverage_python": "3.13",
    "outage_visual_window_nees": 478.63,
    "outage_visual_window_coverage_percent": 0.0,
}

#: What the golden snapshot holds for the two headline values, in the shape of ``tests/golden/benchmark.json``.
GOLDEN = {"cases": {"outage_visual": {"outage_calibration": {"nees_mean": 478.63, "coverage_2sigma": 0.0}}}}


def marker(key: str, value: str) -> str:
    return f"<!-- metric:{key} -->{value}<!-- /metric -->"


def make_tree(tmp_path: Path, readme: str = "", adrs: tuple[str, ...] = ("0001-a.md", "0002-b.md")) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "data").mkdir()
    for name in adrs:
        (tmp_path / "docs" / "adr" / name).write_text("# ADR\n", encoding="utf-8")
    (tmp_path / "docs" / "adr" / "index.md").write_text("\n".join(adrs), encoding="utf-8")
    (tmp_path / "docs" / "data" / "metrics.json").write_text(json.dumps(GOOD), encoding="utf-8")
    (tmp_path / "tests" / "golden").mkdir(parents=True)
    (tmp_path / "tests" / "golden" / "benchmark.json").write_text(json.dumps(GOLDEN), encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return tmp_path


class TestRender:
    def test_percent_has_one_decimal_and_counts_are_plain(self):
        assert metrics.render("coverage_percent", GOOD) == "91.3"
        assert metrics.render("tests_collected_floor", GOOD) == "100"

    def test_rewrite_replaces_a_stale_value_and_leaves_other_text(self):
        old = f"We have {marker('tests_collected_floor', '70')} tests in all."
        new = metrics.rewrite(old, GOOD)
        assert new == f"We have {marker('tests_collected_floor', '100')} tests in all."

    def test_rewrite_is_idempotent(self):
        text = f"{marker('adr_count', '2')} and {marker('coverage_percent', '1.0')}%"
        once = metrics.rewrite(text, GOOD)
        assert metrics.rewrite(once, GOOD) == once


class TestCheck:
    def test_a_matching_tree_passes(self, tmp_path):
        root = make_tree(tmp_path, f"{marker('tests_collected_floor', '100')} tests collected")
        assert metrics.check(root, collected=150) == []

    def test_a_stale_marker_is_reported(self, tmp_path):
        root = make_tree(tmp_path, f"{marker('tests_collected_floor', '90')} tests collected")
        problems = metrics.check(root, collected=150)
        assert any("tests_collected_floor reads 90" in p for p in problems)

    def test_a_hand_typed_count_is_reported(self, tmp_path):
        root = make_tree(tmp_path, "There are 12 ADRs and 884 passed here.")
        problems = metrics.check(root, collected=150)
        assert any("12 ADRs" in p for p in problems)
        assert any("884 passed" in p for p in problems)

    def test_a_hand_typed_line_coverage_is_reported(self, tmp_path):
        root = make_tree(tmp_path, "Reached 92.86% line coverage.")
        assert any("line coverage" in p for p in metrics.check(root, collected=150))

    def test_other_percentages_are_not_counts(self, tmp_path):
        root = make_tree(tmp_path, "2-sigma coverage is 20.0% and the floor is 75%.")
        assert metrics.check(root, collected=150) == []

    def test_an_unknown_key_is_reported(self, tmp_path):
        root = make_tree(tmp_path, marker("nonsense", "1"))
        assert any("unknown metric" in p for p in metrics.check(root, collected=150))

    def test_the_collected_floor_must_match_pytest(self, tmp_path):
        root = make_tree(tmp_path)
        problems = metrics.check(root, collected=250)
        assert any("pytest collects 250" in p and "floor 200" in p for p in problems)
        assert any("python scripts/metrics.py --write" in p for p in problems)

    def test_a_json_holding_a_different_floor_is_reported(self, tmp_path):
        root = make_tree(tmp_path, f"more than {marker('tests_collected_floor', '100')} tests")
        (root / "docs" / "data" / "metrics.json").write_text(
            json.dumps({**GOOD, "tests_collected_floor": 200}), encoding="utf-8"
        )
        problems = metrics.check(root, collected=150)
        assert any("tests_collected_floor is 200" in p for p in problems)

    def test_the_exact_count_is_not_stored(self):
        assert "tests_collected" not in metrics.KEYS
        assert "tests_collected" not in metrics.read_metrics()

    def test_the_adr_count_must_match_the_files(self, tmp_path):
        root = make_tree(tmp_path, adrs=("0001-a.md", "0002-b.md", "0003-c.md"))
        assert any("adr_count is 2, docs/adr has 3" in p for p in metrics.check(root, collected=150))

    def test_an_adr_missing_from_the_index_is_reported(self, tmp_path):
        root = make_tree(tmp_path)
        (root / "docs" / "adr" / "index.md").write_text("0001-a.md", encoding="utf-8")
        assert any("0002-b.md" in p for p in metrics.check(root, collected=150))

    def test_history_documents_may_keep_their_old_counts(self, tmp_path):
        root = make_tree(tmp_path)
        (root / "docs" / "releases").mkdir()
        (root / "docs" / "releases" / "0.1.0.md").write_text("567 tests", encoding="utf-8")
        assert metrics.check(root, collected=150) == []


class TestFloor:
    @pytest.mark.parametrize("count, floor", [(2199, 2100), (2200, 2200), (2299, 2200), (99, 0), (100, 100)])
    def test_the_floor_rounds_down_to_a_hundred(self, count, floor):
        assert metrics.tests_floor(count) == floor


class TestWrite:
    def _tree(self, tmp_path):
        text = f"more than {marker('tests_collected_floor', '0')} tests\n"
        root = make_tree(tmp_path, text)
        (root / "docs" / "data" / "metrics.json").write_text(json.dumps(GOOD), encoding="utf-8")
        return root

    def _snapshot(self, root):
        return {p: p.read_bytes() for p in (root / "README.md", root / "docs" / "data" / "metrics.json")}

    def test_write_regenerates_the_markers_and_the_json_with_the_floor(self, tmp_path):
        root = self._tree(tmp_path)
        metrics.write(root, collected=2263)
        assert metrics.read_metrics(root / "docs" / "data" / "metrics.json")["tests_collected_floor"] == 2200
        assert marker("tests_collected_floor", "2200") in (root / "README.md").read_text(encoding="utf-8")
        assert metrics.check(root, collected=2263) == []

    def test_a_second_write_changes_nothing(self, tmp_path):
        root = self._tree(tmp_path)
        metrics.write(root, collected=2263)
        first = self._snapshot(root)
        metrics.write(root, collected=2263)
        assert self._snapshot(root) == first

    def test_more_tests_inside_the_same_hundred_change_no_tracked_file(self, tmp_path):
        root = self._tree(tmp_path)
        metrics.write(root, collected=2263)
        first = self._snapshot(root)
        metrics.write(root, collected=2268)
        assert self._snapshot(root) == first
        assert metrics.check(root, collected=2268) == []

    def test_crossing_a_hundred_fails_the_check_until_write_runs(self, tmp_path):
        root = self._tree(tmp_path)
        metrics.write(root, collected=2299)
        assert metrics.check(root, collected=2301)
        metrics.write(root, collected=2301)
        assert metrics.check(root, collected=2301) == []


class TestHeadline:
    """The two values prose quotes from the benchmark come from the committed golden snapshot."""

    def test_the_values_are_read_from_the_golden_snapshot(self, tmp_path):
        got = metrics.headline_from_golden(make_tree(tmp_path))
        assert got == {"outage_visual_window_nees": 478.63, "outage_visual_window_coverage_percent": 0.0}

    def test_each_is_shown_with_one_decimal(self):
        assert metrics.render("outage_visual_window_nees", GOOD) == "478.6"
        assert metrics.render("outage_visual_window_coverage_percent", GOOD) == "0.0"

    def test_a_marker_holding_the_current_value_passes(self, tmp_path):
        text = f"NEES {marker('outage_visual_window_nees', '478.6')} over the window"
        assert metrics.check(make_tree(tmp_path, text), collected=150) == []

    def test_a_stale_marker_is_reported(self, tmp_path):
        text = f"NEES {marker('outage_visual_window_nees', '286.1')} over the window"
        problems = metrics.check(make_tree(tmp_path, text), collected=150)
        assert any("outage_visual_window_nees reads 286.1" in p for p in problems)

    def test_a_recorded_value_that_differs_from_the_golden_snapshot_is_reported(self, tmp_path):
        root = make_tree(tmp_path)
        moved = {"cases": {"outage_visual": {"outage_calibration": {"nees_mean": 500.0, "coverage_2sigma": 0.0}}}}
        (root / "tests" / "golden" / "benchmark.json").write_text(json.dumps(moved), encoding="utf-8")
        problems = metrics.check(root, collected=150)
        assert any("outage_visual_window_nees" in p and "golden" in p for p in problems)


def test_every_live_file_exists():
    missing = [p for p in metrics.LIVE_FILES if not (ROOT / p).is_file()]
    assert missing == [], f"LIVE_FILES entries that no longer exist: {missing}"


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

    @pytest.mark.parametrize(
        "name", ["README.md", "CONSTRAINTS.md", "ROADMAP.md", "CONTRIBUTING.md", "RISKS.md", "SECURITY.md"]
    )
    def test_the_live_files_are_in_scope(self, name):
        assert (ROOT / name) in metrics.live_documents()

    def test_the_recorded_headline_values_match_the_golden_snapshot(self):
        recorded = metrics.read_metrics()
        for key, value in metrics.headline_from_golden().items():
            assert recorded[key] == value, key
