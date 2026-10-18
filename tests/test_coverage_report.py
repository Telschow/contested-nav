"""A failed test suite must fail the coverage script, with or without --ratchet."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("coverage_report", ROOT / "scripts" / "coverage_report.py")
assert _spec and _spec.loader
cr = importlib.util.module_from_spec(_spec)
sys.modules["coverage_report"] = cr
_spec.loader.exec_module(cr)


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No tracing, no writes into the repository, one small module to measure."""
    module = tmp_path / "src" / "m.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n")
    monkeypatch.setattr(cr, "SRC", tmp_path / "src")
    monkeypatch.setattr(cr, "ROOT", tmp_path)
    monkeypatch.setattr(cr, "COV", tmp_path / "coverage.json")
    monkeypatch.setattr(cr, "FLOORS", {})
    monkeypatch.chdir(tmp_path)
    return module


def _run(monkeypatch: pytest.MonkeyPatch, code: int, argv: list[str]) -> int:
    import pytest as pt

    monkeypatch.setattr(pt, "main", lambda *_a, **_k: code)
    monkeypatch.setattr(sys, "argv", ["coverage_report.py", *argv])
    return cr.main()


@pytest.mark.parametrize("argv", [[], ["--ratchet"]])
def test_a_failing_suite_fails_the_script(quiet, monkeypatch, capsys, argv) -> None:
    monkeypatch.setattr(cr, "TOTAL_FLOOR", 0.0)  # the floors are met, so only the suite can fail the script
    assert _run(monkeypatch, 1, argv) != 0
    out = capsys.readouterr()
    assert "ratchet OK" not in out.out
    assert "test suite FAILED" in out.err


def test_a_passing_suite_still_reaches_the_floor_check(quiet, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cr, "TOTAL_FLOOR", 101.0)  # unreachable, so the floor check must be what fails
    assert _run(monkeypatch, 0, ["--ratchet"]) == 1
    err = capsys.readouterr().err
    assert "TOTAL" in err
    assert "test suite FAILED" not in err


def test_a_passing_suite_with_met_floors_succeeds(quiet, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cr, "TOTAL_FLOOR", 0.0)
    assert _run(monkeypatch, 0, ["--ratchet"]) == 0
    assert "ratchet OK" in capsys.readouterr().out


def test_the_script_leaves_an_outer_tracer_in_place(quiet, monkeypatch) -> None:
    """The coverage run executes this test under its own tracer. Clearing it would blind every later test."""
    outer = lambda *_a: None  # noqa: E731
    previous = sys.gettrace()
    sys.settrace(outer)
    try:
        monkeypatch.setattr(cr, "TOTAL_FLOOR", 0.0)
        _run(monkeypatch, 0, ["--ratchet"])
        assert sys.gettrace() is outer
    finally:
        sys.settrace(previous)


def test_no_test_imports_another_through_the_tests_package() -> None:
    """``from tests.x import y`` works only when the repository root is on ``sys.path``.

    ``python -m pytest`` puts it there. ``scripts/coverage_report.py`` runs pytest in process from ``scripts/``,
    where it is not, so such a test passed everywhere except in the coverage step. Sibling test modules are
    importable by name, because pytest puts ``tests/`` on the path.
    """
    pattern = re.compile(r"^\s*(?:from\s+tests(?:\.|\s)|import\s+tests\b)", re.MULTILINE)
    offenders = [p.name for p in sorted((ROOT / "tests").glob("test_*.py")) if pattern.search(p.read_text("utf-8"))]
    assert offenders == []
