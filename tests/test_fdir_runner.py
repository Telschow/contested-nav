"""``navkit sweep fdir`` on the study runner: same flags as before, and ``--compare`` exits 1 on a difference (#230).

``fdir`` compares by parsing the CSV text back into typed rows and checking numbers to 1e-6 relative (ADR-0009).
A reduced run is checked against the full committed file. The record in ``tests/data/sweep_help/fdir.json`` was
taken from the old parser.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from navkit import fdir_false_alarm as fa
from navkit.report.runner import run_study

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
RECORD = json.loads((Path(__file__).parent / "data" / "sweep_help" / "fdir.json").read_text())


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


def test_flags_are_unchanged() -> None:
    parser = fa.build_parser()
    assert parser.prog == RECORD["prog"]
    assert parser.description == RECORD["description"]
    assert json.loads(json.dumps(_actions(parser))) == RECORD["actions"]


CASES = [("rate", "fdir_false_alarm.csv", "mean_nis"), ("sensitivity", "fdir_sensitivity.csv", "detected_n")]


@pytest.mark.parametrize(("part", "name", "column"), CASES, ids=[c[0] for c in CASES])
def test_compare_exit_codes(part: str, name: str, column: str) -> None:
    study = fa.STUDIES[part]
    committed = DATA / name

    def with_rows(by: float = 0) -> Any:
        rows = study.table.read(committed)
        if by:
            rows[0][column] = rows[0][column] + by
        return replace(study, run_args=lambda args: rows)

    argv = [part, "--compare", str(committed)]
    assert run_study(with_rows(), argv) == 0
    if part == "rate":  # counts are integers and must match exactly; floats get 1e-6 relative
        assert run_study(with_rows(1e-9), argv) == 0
    assert run_study(with_rows(1), argv) == 1


@pytest.mark.parametrize(("part", "name", "_"), CASES, ids=[c[0] for c in CASES])
def test_csv_round_trips_byte_identical(part: str, name: str, _: str, tmp_path: Path) -> None:
    table = fa.STUDIES[part].table
    out = tmp_path / name
    table.write(out, table.read(DATA / name))
    assert out.read_bytes() == (DATA / name).read_bytes()


def test_csv_is_still_written_under_compare(tmp_path: Path) -> None:
    """The CI reproducibility leg runs ``--csv`` with ``--compare`` twice and ``cmp`` the two files."""
    study = replace(
        fa.STUDIES["rate"], run_args=lambda args: fa._write_under_compare(args, fa.RATE_TABLE.read(DATA / CASES[0][1]))
    )
    out = tmp_path / "x.csv"
    assert run_study(study, ["rate", "--csv", str(out), "--compare", str(DATA / CASES[0][1])]) == 0
    assert out.read_bytes() == (DATA / CASES[0][1]).read_bytes()
