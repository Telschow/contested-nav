"""A documentation-only pull request skips the test jobs, so every test that reads a page must run in the lint job.

``ci.yml`` lists those tests in the "Documentation tests" step. This reads that list and every test file, and fails if
a test that opens a documentation page, or a Markdown file at the root, is not in the list.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: Tests that read a page and are deliberately not in the list, each with the reason.
EXCLUDED: dict[str, str] = {
    # It checks the README and docs/results.md against a freshly generated benchmark, which a documentation-only
    # run does not have. Those pages, and docs/index.md, count as code in the `changes` job, so a change to one of
    # them runs the benchmark job, which does the same check.
    "test_doc_tables.py": "needs a fresh benchmark; the pages it reads count as code",
}

#: How a test names a real page: a path built from ROOT, or a glob over the Markdown files of the tree.
_PAGE_PATH = re.compile(r"""\b(?:ROOT|root)\s*/\s*(?:"[\w.\-]+"\s*/\s*)*"[\w.\-]+\.md\"""")
_PAGE_GLOB = re.compile(r"""\b(?:rglob|glob)\(\s*["']\*\.md["']\s*\)""")


def _documentation_step() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["lint"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Documentation tests")


def listed() -> set[str]:
    return {Path(p).name for p in re.findall(r"tests/test_\w+\.py", _documentation_step())}


def readers() -> set[str]:
    out = set()
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:  # this file quotes the patterns it looks for
            continue
        text = path.read_text(encoding="utf-8")
        if _PAGE_PATH.search(text) or _PAGE_GLOB.search(text):
            out.add(path.name)
    return out


def test_every_test_that_reads_a_page_runs_in_a_documentation_only_pull_request() -> None:
    missing = sorted(readers() - listed() - set(EXCLUDED))
    assert missing == [], f"add to the Documentation tests step of ci.yml, or exclude with a reason: {missing}"


def test_the_list_names_only_tests_that_exist() -> None:
    assert sorted(n for n in listed() if not (TESTS / n).is_file()) == []


def test_every_exclusion_names_a_test_that_reads_a_page() -> None:
    assert sorted(set(EXCLUDED) - readers()) == []
    assert all(EXCLUDED.values())


def test_the_detector_sees_the_page_readers_it_is_meant_to() -> None:
    found = readers()
    assert {"test_multipath.py", "test_risks_doc.py", "test_timing_page.py", "test_doc_tables.py"} <= found
    assert _PAGE_PATH.search('PAGE = ROOT / "docs" / "faults.md"')
    assert _PAGE_PATH.search('TEXT = (ROOT / "RISKS.md").read_text()')
    assert _PAGE_GLOB.search('docs = [p for p in root.rglob("*.md")]')
    assert not _PAGE_PATH.search('page = tmp_path / "p.md"')
