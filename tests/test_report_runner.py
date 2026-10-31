"""Lifecycle test for the study-runner module."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pytest

from navkit.report.runner import Flags, Study, build_parser, run_study
from navkit.report.table import Column, Table

TABLE = Table((Column("name", str), Column("value", float)), key="name")
PAGE = "intro\n<!-- demo:start -->\n\nold\n\n<!-- demo:end -->\noutro\n"


def make_study(calls: list[tuple[int, ...]], scale: float = 1.0) -> Study:
    def run(seeds: tuple[int, ...] | None) -> list[dict[str, object]]:
        calls.append(seeds or ())
        return [{"name": "a", "value": 1.0 * scale}, {"name": "b", "value": 2.5 * scale}]

    def render(rows: list[dict[str, object]]) -> str:
        return "\n".join(f"{r['name']}={r['value']}" for r in rows)

    return Study(
        table=TABLE,
        run=run,
        render=render,
        page_name="demo",
        flags=Flags(csv=True, page=True, markdown=True, seeds=True, from_csv=True, compare=True),
    )


def test_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "r.csv"
    page = tmp_path / "p.md"
    page.write_text(PAGE, encoding="utf-8")
    calls: list[tuple[int, ...]] = []
    study = make_study(calls)

    # run, write the CSV, splice the page
    assert run_study(study, ["--csv", str(csv_path), "--page", str(page), "--seeds", "3,4"]) == 0
    assert calls == [(3, 4)]
    assert "a=1.0\nb=2.5" in page.read_text(encoding="utf-8")
    assert TABLE.read(csv_path)[1]["value"] == 2.5

    # from-csv reads instead of running; markdown prints the block
    capsys.readouterr()
    assert run_study(study, ["--from-csv", str(csv_path), "--markdown"]) == 0
    assert calls == [(3, 4)]
    assert capsys.readouterr().out.strip() == "a=1.0\nb=2.5"

    # compare equal
    assert run_study(study, ["--compare", str(csv_path)]) == 0
    assert run_study(study, ["--from-csv", str(csv_path), "--page", str(page), "--compare", str(csv_path)]) == 0

    # compare different gives exit 1
    assert run_study(make_study(calls, scale=2.0), ["--compare", str(csv_path)]) == 1


def test_page_drift_gives_exit_1(tmp_path: Path) -> None:
    csv_path = tmp_path / "r.csv"
    page = tmp_path / "p.md"
    page.write_text(PAGE, encoding="utf-8")
    study = make_study([])
    assert run_study(study, ["--csv", str(csv_path)]) == 0
    # the page still holds "old", so regenerate-and-compare differs
    assert run_study(study, ["--from-csv", str(csv_path), "--page", str(page), "--compare", str(csv_path)]) == 1


def test_undeclared_flag_is_refused() -> None:
    study = make_study([])
    study = Study(table=study.table, run=study.run, render=study.render, flags=Flags(csv=True))
    with pytest.raises(SystemExit):
        run_study(study, ["--page", "x.md"])


def test_extra_flags_blocks_and_default_print(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[int] = []

    def add(ap: argparse.ArgumentParser) -> None:
        ap.add_argument("--n", type=int, default=2)

    def run(args: argparse.Namespace) -> list[dict[str, object]]:
        seen.append(args.n)
        return [{"name": "a", "value": float(args.n)}]

    study = Study(
        table=TABLE,
        run_args=run,
        blocks=lambda rows, args: {"one": f"n={rows[0]['value']}", "two": "second"},
        flags=Flags(csv=True, page=True, markdown=True, from_csv=True, print_default=True),
        add_arguments=add,
        prog="demo",
        help={"csv": "write one row per run"},
    )
    assert run_study(study, ["--n", "5"]) == 0
    assert seen == [5]
    assert capsys.readouterr().out == "n=5.0\n\nsecond\n"

    page = tmp_path / "p.md"
    markers = "<!-- one:start -->\n\n<!-- one:end -->\n<!-- two:start -->\n\n<!-- two:end -->\n"
    page.write_text(markers, encoding="utf-8")
    assert run_study(study, ["--csv", str(tmp_path / "r.csv"), "--page", str(page)]) == 0
    assert capsys.readouterr().out == ""
    assert "n=2.0" in page.read_text(encoding="utf-8")
    assert "write one row per run" in build_parser(study).format_help()

    # a page without the markers is an error exit, not a traceback
    bare = tmp_path / "bare.md"
    bare.write_text("nothing\n", encoding="utf-8")
    assert run_study(study, ["--page", str(bare)]) == 1


def test_compare_with_a_tolerance(tmp_path: Path) -> None:
    csv_path = tmp_path / "r.csv"

    def close(got: list[dict[str, object]], want: list[dict[str, object]]) -> list[str]:
        return [f"{g['name']}" for g, w in zip(got, want, strict=True) if abs(g["value"] - w["value"]) > 0.1]  # type: ignore[operator]

    def study(scale: float) -> Study:
        return replace(make_study([], scale=scale), compare_rows=close)

    assert run_study(study(1.0), ["--csv", str(csv_path)]) == 0
    assert run_study(study(1.0), ["--compare", str(csv_path)]) == 0
    # 1.01 differs as text but is inside the tolerance
    assert run_study(study(1.01), ["--compare", str(csv_path)]) == 0
    assert run_study(study(2.0), ["--compare", str(csv_path)]) == 1
