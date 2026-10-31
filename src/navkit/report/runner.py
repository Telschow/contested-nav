"""The shared command lifecycle of a study that writes a CSV or a page (ADR-0038).

A study supplies its table, a run step and a render step, and declares which of the shared flags it takes.
The runner parses them and runs the lifecycle: run or read the rows, then either write (``--csv``, ``--page``,
``--markdown``) or regenerate and compare (``--compare``, exit code 1 on a difference).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .page import block_is_current, write_block
from .table import Row, Table


@dataclass(frozen=True)
class Flags:
    """Which of the shared flags a study takes. All are opt-in."""

    csv: bool = False
    page: bool = False
    markdown: bool = False
    seeds: bool = False
    from_csv: bool = False
    compare: bool = False
    #: Print the blocks when neither ``--csv`` nor ``--page`` is given, as well as under ``--markdown``.
    print_default: bool = False


@dataclass(frozen=True)
class Study:
    """One study. ``run`` takes the seeds; ``run_args`` takes all parsed flags and wins when both are set.

    ``render`` gives the one block of ``page_name``. ``blocks`` gives several by marker name, from the rows and
    the parsed flags, and wins. ``add_arguments`` adds the study's own flags before the shared ones, ``help``
    replaces the help of a shared flag by its name, and ``read`` replaces ``table.read`` for ``--from-csv``.
    """

    table: Table
    run: Callable[[tuple[int, ...] | None], list[Row]] | None = None
    render: Callable[[list[Row]], str] | None = None
    page_name: str = ""
    flags: Flags = field(default_factory=Flags)
    run_args: Callable[[argparse.Namespace], list[Row]] | None = None
    blocks: Callable[[list[Row], argparse.Namespace], dict[str, str]] | None = None
    add_arguments: Callable[[argparse.ArgumentParser], None] | None = None
    read: Callable[[Path], list[Row]] | None = None
    prog: str | None = None
    description: str | None = None
    help: dict[str, str] = field(default_factory=dict)
    #: Replaces the exact CSV compare. Takes the rows as a reader of the CSV sees them and the committed rows,
    #: and returns the differences. For a study whose numbers may differ in the last bits across platforms.
    compare_rows: Callable[[list[Row], list[Row]], list[str]] | None = None


def _seeds(text: str) -> tuple[int, ...]:
    return tuple(int(s) for s in text.split(",") if s)


def build_parser(study: Study) -> argparse.ArgumentParser:
    f = study.flags
    ap = argparse.ArgumentParser(prog=study.prog, description=study.description)
    if study.add_arguments is not None:
        study.add_arguments(ap)

    def h(name: str, text: str) -> str:
        return study.help.get(name, text)

    if f.csv:
        ap.add_argument("--csv", type=Path, default=None, help=h("csv", "write the rows here"))
    if f.from_csv:
        ap.add_argument(
            "--from-csv",
            type=Path,
            default=None,
            help=h("from_csv", "read the rows from this CSV instead of running"),
        )
    if f.page:
        ap.add_argument(
            "--page",
            type=Path,
            default=None,
            help=h("page", f"write the block between the {study.page_name} markers"),
        )
    if f.markdown:
        ap.add_argument("--markdown", action="store_true", help=h("markdown", "print the block to stdout"))
    if f.seeds:
        ap.add_argument("--seeds", type=_seeds, default=None, help=h("seeds", "comma-separated seeds"))
    if f.compare:
        ap.add_argument(
            "--compare",
            type=Path,
            default=None,
            help=h("compare", "exit 1 if the output differs from the committed files"),
        )
    return ap


def _blocks(study: Study, rows: list[Row], args: argparse.Namespace) -> dict[str, str]:
    if study.blocks is not None:
        return study.blocks(rows, args)
    assert study.render is not None, "a study needs render or blocks"
    return {study.page_name: study.render(rows)}


def _rows(study: Study, args: argparse.Namespace) -> list[Row]:
    from_csv: Path | None = getattr(args, "from_csv", None)
    if from_csv is not None:
        return study.read(from_csv) if study.read is not None else study.table.read(from_csv)
    if study.run_args is not None:
        return study.run_args(args)
    assert study.run is not None, "a study needs run or run_args"
    return study.run(getattr(args, "seeds", None))


def _csv_differences(study: Study, compare: Path, rows: list[Row]) -> list[str]:
    if study.compare_rows is None:
        return [] if study.table.is_current(compare, rows) else [f"the rows differ from {compare}"]
    # Compare what a reader of the CSV would see, so a number that survives the round trip through text is checked.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rows.csv"
        study.table.write(path, rows)
        problems = study.compare_rows(study.table.read(path), study.table.read(compare))
    if problems:
        return [f"the rows differ from {compare}:", *(f"  {p}" for p in problems[:10])]
    return []


def run_study(study: Study, argv: list[str] | None = None) -> int:
    args = build_parser(study).parse_args(argv)
    csv_path: Path | None = getattr(args, "csv", None)
    page_path: Path | None = getattr(args, "page", None)
    compare: Path | None = getattr(args, "compare", None)

    rows = _rows(study, args)
    blocks = _blocks(study, rows, args)

    if compare is not None:
        differs = False
        problems = _csv_differences(study, compare, rows)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            differs = True
        if page_path is not None and not all(block_is_current(page_path, n, t) for n, t in blocks.items()):
            print(f"the block in {page_path} differs", file=sys.stderr)
            differs = True
        if differs:
            return 1
        print(f"the output matches {compare}", file=sys.stderr)
        return 0

    if csv_path is not None:
        study.table.write(csv_path, rows)
        print(f"wrote {csv_path}", file=sys.stderr)
    if page_path is not None:
        try:
            for name, text in blocks.items():
                write_block(page_path, name, text)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote the block into {page_path}", file=sys.stderr)
    if getattr(args, "markdown", False) or (study.flags.print_default and csv_path is None and page_path is None):
        print("\n\n".join(blocks.values()))
    return 0
