"""The fast documentation gate is wired to the Makefile and to pre-commit, and skips only the re-run tests."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent


def test_make_docs_fast_checks_the_counts_and_runs_the_page_tests_except_reruns() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\ndocs-fast:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/metrics.py --check" in recipe
    assert '-m "docs_only and not rerun"' in recipe


def test_pre_commit_runs_the_gate_when_a_markdown_file_is_staged() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = config.split("- id: docs-fast", 1)[1].split("- id:", 1)[0]
    assert "entry: make docs-fast" in hook
    assert "types: [markdown]" in hook
    assert "pass_filenames: false" in hook


def test_the_rerun_marker_is_registered() -> None:
    assert '"rerun:' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
