"""CSV read and write code lives in navkit.report.table (ADR-0038). A new copy elsewhere fails here."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.docs_only

SCANNED = (ROOT / "src" / "navkit", ROOT / "scripts")
OWN = ROOT / "src" / "navkit" / "report"
#: The integrity log has its own record type and format (ADR-0035).
ALLOWED = {("src/navkit/integrity.py", "write_csv")}
NAMES = {"write_csv", "read_csv"}


def csv_io_defs(source: str) -> list[str]:
    """Names of functions defined in ``source`` that are called ``write_csv`` or ``read_csv``."""
    return [n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name in NAMES]


def offenders() -> list[tuple[str, str]]:
    found = []
    for base in SCANNED:
        for path in sorted(base.rglob("*.py")):
            if OWN in path.parents:
                continue
            rel = path.relative_to(ROOT).as_posix()
            found += [(rel, n) for n in csv_io_defs(path.read_text(encoding="utf-8")) if (rel, n) not in ALLOWED]
    return found


def test_no_csv_io_function_outside_navkit_report() -> None:
    assert offenders() == []


def test_the_check_fails_on_a_deliberately_added_copy() -> None:
    copy = "def write_csv(path, rows):\n    pass\n\n\ndef read_csv(path):\n    return []\n"
    assert csv_io_defs(copy) == ["write_csv", "read_csv"]
    assert csv_io_defs("def render(path):\n    return path\n") == []
