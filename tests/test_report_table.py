"""Known-answer tests for the results-table module."""

from __future__ import annotations

from pathlib import Path

import pytest

from navkit.report.table import Column, Table

TABLE = Table(
    (
        Column("sequence", str),
        Column("frames", int),
        Column("rmse_m", float),
        Column("note", str, optional=True),
        Column("lag_s", float, optional=True),
    ),
    key="sequence",
)


def row(seq: str, frames: int, rmse: float, lag: float | None = None) -> dict[str, object]:
    return {"sequence": seq, "frames": frames, "rmse_m": rmse, "note": None, "lag_s": lag}


def test_round_trip_types_and_missing(tmp_path: Path) -> None:
    rows = [row("a", 3, 0.1 + 0.2, 1.5), row("b", 10, 2.0)]
    path = tmp_path / "t.csv"
    TABLE.write(path, rows)
    back = TABLE.read(path)
    assert back == rows
    assert isinstance(back[0]["frames"], int)
    assert isinstance(back[1]["rmse_m"], float)
    assert back[1]["lag_s"] is None


def test_write_uses_plain_str(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    TABLE.write(path, [row("a", 3, 0.5)])
    assert path.read_text(encoding="utf-8").splitlines() == [
        "sequence,frames,rmse_m,note,lag_s",
        "a,3,0.5,,",
    ]


def test_missing_required_value_raises(tmp_path: Path) -> None:
    bad = row("a", 3, 0.5)
    bad["rmse_m"] = None
    with pytest.raises(ValueError, match="rmse_m"):
        TABLE.write(tmp_path / "t.csv", [bad])


def test_merge_replaces_run_sequences_and_keeps_others(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    TABLE.write(path, [row("a", 1, 1.0), row("b", 2, 2.0), row("a", 3, 3.0)])
    TABLE.merge(path, [row("a", 9, 9.0), row("c", 4, 4.0)])
    back = TABLE.read(path)
    assert [(r["sequence"], r["frames"]) for r in back] == [("a", 9), ("b", 2), ("c", 4)]


def test_merge_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "t.csv"
    TABLE.merge(path, [row("a", 1, 1.0)])
    assert TABLE.read(path) == [row("a", 1, 1.0)]


def test_merge_refuses_changed_header_and_leaves_file(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("sequence,frames\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        TABLE.merge(path, [row("a", 2, 2.0)])
    assert path.read_text(encoding="utf-8") == "sequence,frames\na,1\n"


def test_compare_equal_and_different(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    rows = [row("a", 1, 1.0), row("b", 2, 2.0)]
    TABLE.write(path, rows)
    assert TABLE.is_current(path, rows)
    assert not TABLE.is_current(path, [row("a", 1, 1.0), row("b", 2, 2.5)])
    assert not TABLE.is_current(path, rows[:1])


def test_write_ends_lines_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    TABLE.write(path, [row("a", 3, 0.5)])
    assert b"\r" not in path.read_bytes()


def test_write_with_crlf_line_terminator(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    Table(TABLE.columns, key=TABLE.key, lineterminator="\r\n").write(path, [row("a", 3, 0.5)])
    assert path.read_bytes().count(b"\r\n") == 2
