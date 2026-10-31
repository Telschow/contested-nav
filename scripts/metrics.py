#!/usr/bin/env python
"""One source for the numbers the documents quote: a rounded test count, ADRs, line coverage, and two headline values.

``docs/data/metrics.json`` holds them. A document quotes one as

    more than <!-- metric:tests_collected_floor -->800<!-- /metric --> tests

and this script rewrites that value from the JSON (``--write``) or fails when it differs
(``--check``). The comment markers are invisible when the page is rendered.

* ``adr_count`` is the number of ``docs/adr/NNNN-*.md`` files, and every one must be listed in
  ``docs/adr/index.md``.
* ``tests_collected_floor`` is the count that ``pytest --collect-only`` reports, rounded down to a hundred. The exact
  count is not stored, because it changes in every pull request that adds a test and so made every open pull request
  conflict. ``--check`` counts the tests afresh and fails when the recorded floor or a marker differs, so a pull
  request that crosses a hundred runs ``--write`` and one that does not needs nothing.
* ``outage_visual_window_nees`` and ``outage_visual_window_coverage_percent`` are the mean NEES and the 2-sigma
  coverage of ``outage_visual`` over the GNSS outage window. They are read from the committed golden snapshot,
  ``tests/golden/benchmark.json``, by ``--write``, and ``--check`` fails when the JSON differs from the snapshot.
  The full-run values and every other case are in the generated tables, which ``scripts/check_doc_tables.py`` checks.
* ``coverage_percent`` comes from ``scripts/coverage_report.py``, which takes minutes, so it is
  refreshed only by ``--write --coverage`` and compared by ``--check-coverage`` within
  ``COVERAGE_TOLERANCE`` points. Coverage depends on the interpreter, so the comparison is made
  only when the run used the Python minor version recorded in the JSON.

A count typed by hand next to the word ``tests``, ``ADRs``, ``passed`` or ``line coverage`` in a
live document, outside a marker, is reported too. Passing counts are not generated: skips depend
on the machine, so the documents say that all collected tests pass except the declared xfails.

    python scripts/metrics.py --check
    python scripts/metrics.py --write
    python scripts/coverage_report.py && python scripts/metrics.py --write --coverage
    python scripts/metrics.py --check-coverage
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = ROOT / "docs" / "data" / "metrics.json"
COVERAGE_PATH = ROOT / "coverage.json"

#: Percentage points the recorded coverage may differ from a fresh measurement. A change of a few
#: lines moves the figure by less than this, so only a real drop or a forgotten refresh fails.
COVERAGE_TOLERANCE = 0.5

KEYS = (
    "adr_count",
    "tests_collected_floor",
    "coverage_percent",
    "coverage_lines_hit",
    "coverage_lines_total",
    "coverage_python",
    "outage_visual_window_nees",
    "outage_visual_window_coverage_percent",
)

#: The test count is quoted rounded down to a multiple of this.
TESTS_ROUNDING = 100

#: Keys shown with one decimal.
ONE_DECIMAL = ("coverage_percent", "outage_visual_window_nees", "outage_visual_window_coverage_percent")

#: The two headline values that prose quotes, read from the committed golden snapshot of the benchmark. The golden
#: file is regenerated with ``python tests/test_golden_benchmark.py --update`` whenever a benchmark number moves, so
#: these follow it. The full table is in README.md and is checked by ``scripts/check_doc_tables.py``.
GOLDEN_PATH = ("tests", "golden", "benchmark.json")
HEADLINE_CASE = "outage_visual"

#: Documents that quote counts. History is left out: the changelog and the dated release
#: notes record what was true when they were written.
LIVE_FILES = ("README.md", "CONSTRAINTS.md", "ROADMAP.md", "CONTRIBUTING.md", "CLAUDE.md", "RISKS.md", "SECURITY.md")
LIVE_DIRS = ("docs",)
HISTORY = ("docs/releases/",)

MARKER = re.compile(r"<!--\s*metric:(\w+)\s*-->(.*?)<!--\s*/metric\s*-->")
# A number after a hyphen is part of an identifier ("ADR-0028, ADR-0030"), not a count.
HAND_TYPED = re.compile(
    r"(?<![\w-])\d[\d,]*\s+(?:tests?\b|ADRs?\b|collected\b|passed\b|passing\b)|\b\d+(?:\.\d+)?%\s+line coverage",
    re.IGNORECASE,
)


def live_documents(root: Path = ROOT) -> list[Path]:
    """The Markdown files whose counts must come from the JSON."""
    paths = [root / name for name in LIVE_FILES if (root / name).is_file()]
    for directory in LIVE_DIRS:
        paths.extend(sorted((root / directory).rglob("*.md")))
    out = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if not any(rel == h or (h.endswith("/") and rel.startswith(h)) for h in HISTORY):
            out.append(path)
    return out


def adr_files(root: Path = ROOT) -> list[Path]:
    return sorted((root / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))


def adr_problems(root: Path = ROOT) -> list[str]:
    """Every ADR file is linked from the index."""
    index = (root / "docs" / "adr" / "index.md").read_text(encoding="utf-8")
    return [f"docs/adr/index.md does not list {p.name}" for p in adr_files(root) if p.name not in index]


def tests_floor(count: int) -> int:
    """``count`` rounded down to a multiple of :data:`TESTS_ROUNDING`."""
    return count // TESTS_ROUNDING * TESTS_ROUNDING


def count_collected(root: Path = ROOT) -> int:
    """Tests pytest collects, from its own summary line."""
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"(\d+) tests? collected", run.stdout)
    if not match:
        raise SystemExit(f"could not read the collected count from pytest:\n{run.stdout[-400:]}{run.stderr[-400:]}")
    return int(match.group(1))


def read_metrics(path: Path = METRICS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def coverage_from(path: Path = COVERAGE_PATH) -> dict[str, Any]:
    """Coverage figures from the file ``coverage_report.py`` wrote."""
    data = json.loads(path.read_text(encoding="utf-8"))
    hit = sum(r["hit"] for r in data["modules"])
    total = sum(r["exec"] for r in data["modules"])
    minor = ".".join(str(data["python"]).split()[0].split(".")[:2])
    return {
        "coverage_percent": round(100.0 * hit / total, 2),
        "coverage_lines_hit": hit,
        "coverage_lines_total": total,
        "coverage_python": minor,
    }


def headline_from_golden(root: Path = ROOT) -> dict[str, float]:
    """The outage-window NEES and 2-sigma coverage of the headline case, from the golden snapshot."""
    golden = json.loads(root.joinpath(*GOLDEN_PATH).read_text(encoding="utf-8"))
    window = golden["cases"][HEADLINE_CASE]["outage_calibration"]
    return {
        "outage_visual_window_nees": round(float(window["nees_mean"]), 2),
        "outage_visual_window_coverage_percent": round(100.0 * float(window["coverage_2sigma"]), 2),
    }


def render(key: str, metrics: dict[str, Any]) -> str:
    """How a value is shown in a document."""
    value = metrics[key]
    return f"{value:.1f}" if key in ONE_DECIMAL else str(value)


def rewrite(text: str, metrics: dict[str, Any]) -> str:
    """``text`` with every marker holding the current value."""

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in KEYS:
            return m.group(0)
        return f"<!-- metric:{key} -->{render(key, metrics)}<!-- /metric -->"

    return MARKER.sub(sub, text)


def marker_problems(text: str, metrics: dict[str, Any], name: str) -> list[str]:
    problems = []
    for m in MARKER.finditer(text):
        key, shown = m.group(1), m.group(2)
        if key not in KEYS:
            problems.append(f"{name}: unknown metric {key!r}")
        elif shown != render(key, metrics):
            problems.append(f"{name}: {key} reads {shown}, the JSON has {render(key, metrics)}")
    stripped = MARKER.sub("", text)
    for m in HAND_TYPED.finditer(stripped):
        problems.append(f"{name}: hand-typed count {m.group(0)!r}; quote it with a metric marker or drop it")
    return problems


def check(root: Path = ROOT, collected: int | None = None) -> list[str]:
    """Problems with the JSON and the documents. ``collected`` is injected by tests."""
    problems: list[str] = []
    metrics = read_metrics(root / "docs" / "data" / "metrics.json")
    missing = [k for k in KEYS if k not in metrics]
    if missing:
        return [f"metrics.json lacks {', '.join(missing)}"]
    if metrics["adr_count"] != len(adr_files(root)):
        problems.append(f"adr_count is {metrics['adr_count']}, docs/adr has {len(adr_files(root))} records")
    problems.extend(adr_problems(root))
    seen = count_collected(root) if collected is None else collected
    if metrics["tests_collected_floor"] != tests_floor(seen):
        problems.append(
            f"tests_collected_floor is {metrics['tests_collected_floor']}, pytest collects {seen} "
            f"(floor {tests_floor(seen)}): run python scripts/metrics.py --write"
        )
    for key, value in headline_from_golden(root).items():
        if metrics[key] != value:
            problems.append(f"{key} is {metrics[key]}, the golden snapshot has {value}: run scripts/metrics.py --write")
    for path in live_documents(root):
        problems.extend(marker_problems(path.read_text(encoding="utf-8"), metrics, path.relative_to(root).as_posix()))
    return problems


def coverage_problems(metrics: dict[str, Any], measured: dict[str, Any]) -> tuple[list[str], str]:
    """Problems and a one-line note. Nothing is compared across Python minor versions."""
    if measured["coverage_python"] != metrics.get("coverage_python"):
        return [], (
            f"coverage measured on Python {measured['coverage_python']}, recorded for "
            f"{metrics.get('coverage_python')}: not compared"
        )
    gap = abs(measured["coverage_percent"] - metrics["coverage_percent"])
    if gap > COVERAGE_TOLERANCE:
        return [
            f"coverage is {measured['coverage_percent']}%, metrics.json records {metrics['coverage_percent']}% "
            f"(allowed gap {COVERAGE_TOLERANCE} points): run scripts/metrics.py --write --coverage"
        ], ""
    return [], f"coverage {measured['coverage_percent']}% within {COVERAGE_TOLERANCE} points of the recorded value"


def write(root: Path = ROOT, with_coverage: bool = False, collected: int | None = None) -> dict[str, Any]:
    """Regenerate the JSON and the markers. ``collected`` is injected by tests."""
    path = root / "docs" / "data" / "metrics.json"
    metrics: dict[str, Any] = read_metrics(path) if path.is_file() else {}
    metrics["adr_count"] = len(adr_files(root))
    metrics.pop("tests_collected", None)
    metrics["tests_collected_floor"] = tests_floor(count_collected(root) if collected is None else collected)
    metrics.update(headline_from_golden(root))
    if with_coverage:
        metrics.update(coverage_from(root / "coverage.json"))
    if not all(k in metrics for k in KEYS):
        raise SystemExit("no coverage recorded yet: run scripts/coverage_report.py, then --write --coverage")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(metrics.items())), indent=2) + "\n", encoding="utf-8")
    for doc in live_documents(root):
        old = doc.read_text(encoding="utf-8")
        new = rewrite(old, metrics)
        if new != old:
            doc.write_text(new, encoding="utf-8")
    return metrics


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the JSON and the markers")
    mode.add_argument("--check", action="store_true", help="fail if the JSON or a document is stale")
    mode.add_argument("--check-coverage", action="store_true", help="compare coverage.json with the JSON")
    ap.add_argument("--coverage", action="store_true", help="with --write: take coverage from coverage.json")
    args = ap.parse_args(argv)

    if args.write:
        m = write(with_coverage=args.coverage)
        print(
            f"wrote docs/data/metrics.json: more than {m['tests_collected_floor']} tests collected, "
            f"{m['adr_count']} ADRs, {m['coverage_percent']}% line coverage (Python {m['coverage_python']})"
        )
        return 0
    if args.check_coverage:
        problems, note = coverage_problems(read_metrics(), coverage_from())
        if note:
            print(note)
    else:
        problems = check()
        note = "metrics.json and every marker in the documents match"
    if problems:
        print(f"{len(problems)} metrics problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    if args.check:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
