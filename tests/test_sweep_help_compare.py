"""``navkit sweep faults|mismatch|start-draw --help`` lists the same flags as before the move onto the runner (#229).

The record in ``tests/data/sweep_help/compare_studies.json`` was taken from the old parsers. The order of the
flags may differ, so the actions are compared sorted by flag.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

RECORD = json.loads((Path(__file__).parent / "data" / "sweep_help" / "compare_studies.json").read_text())


def _actions(parser: Any) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "flags": a.option_strings,
                "help": a.help,
                "default": repr(a.default),
                "required": a.required,
                "choices": a.choices and list(a.choices),
                "nargs": a.nargs,
                "type": getattr(a.type, "__name__", None),
                "action": type(a).__name__,
            }
            for a in parser._actions
        ),
        key=lambda d: d["flags"],
    )


@pytest.mark.parametrize("name", sorted(RECORD))
def test_flags_are_unchanged(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["navkit"])
    parser = import_module(f"navkit.{name}").build_parser()
    assert parser.description == RECORD[name]["description"]
    assert json.loads(json.dumps(_actions(parser))) == RECORD[name]["actions"]
