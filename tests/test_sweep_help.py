"""``navkit sweep <name> --help`` lists the same flags as before the move onto navkit.report.runner (#228)."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data" / "sweep_help"
STUDIES = ("attribution", "separability", "slow_ramp", "vision_ramp", "fault_classification")


@pytest.mark.parametrize("name", STUDIES)
def test_help_is_unchanged(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    parser = import_module(f"navkit.{name}").build_parser()
    assert parser.format_help() == (DATA / f"{name}.txt").read_text(encoding="utf-8")
