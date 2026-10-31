"""Page-splice code lives in navkit.report.page (ADR-0038). A new copy elsewhere fails here."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.docs_only

SCANNED = (ROOT / "src" / "navkit", ROOT / "scripts")
OWN = ROOT / "src" / "navkit" / "report"
#: The block carries its own markers and no blank-line framing, so it cannot use splice_block.
ALLOWED = {("scripts/rice_table.py", "splice")}
NAME = re.compile(r"splice|write_block|block_is_current|write_page_block")


def page_splice_defs(source: str) -> list[str]:
    """Names of functions defined in ``source`` that look like a page-splice function."""
    return [n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and NAME.search(n.name)]


def offenders() -> list[tuple[str, str]]:
    found = []
    for base in SCANNED:
        for path in sorted(base.rglob("*.py")):
            if OWN in path.parents:
                continue
            rel = path.relative_to(ROOT).as_posix()
            found += [(rel, n) for n in page_splice_defs(path.read_text(encoding="utf-8")) if (rel, n) not in ALLOWED]
    return found


def test_no_page_splice_function_outside_navkit_report() -> None:
    assert offenders() == []


def test_the_check_fails_on_a_deliberately_added_copy() -> None:
    copy = "def splice_table(page, table):\n    return page\n\n\ndef write_block(path, name, block):\n    pass\n"
    assert page_splice_defs(copy) == ["splice_table", "write_block"]
    assert page_splice_defs("def render(page):\n    return page\n") == []
