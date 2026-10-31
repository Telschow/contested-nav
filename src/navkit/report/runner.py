"""The shared command lifecycle of a study that writes a CSV or a page (ADR-0038).

A study supplies its table, a run step and a render step, and declares which of the shared flags it takes.
The runner parses them and runs the lifecycle: run or read the rows, then either write (``--csv``, ``--page``,
``--markdown``) or regenerate and compare (``--compare``, exit code 1 on a difference).
"""

from __future__ import annotations

import argparse
import sys
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


@dataclass(frozen=True)
class Study:
    table: Table
    run: Callable[[tuple[int, ...] | None], list[Row]]
    render: Callable[[list[Row]], str]
    page_name: str = ""
    flags: Flags = field(default_factory=Flags)


def _seeds(text: str) -> tuple[int, ...]:
    return tuple(int(s) for s in text.split(",") if s)


def build_parser(study: Study) -> argparse.ArgumentParser:
    f = study.flags
    ap = argparse.ArgumentParser()
    if f.csv:
        ap.add_argument("--csv", type=Path, default=None, help="write the rows here")
    if f.page:
        ap.add_argument(
            "--page", type=Path, default=None, help=f"write the block between the {study.page_name} markers"
        )
    if f.markdown:
        ap.add_argument("--markdown", action="store_true", help="print the block to stdout")
    if f.seeds:
        ap.add_argument("--seeds", type=_seeds, default=None, help="comma-separated seeds")
    if f.from_csv:
        ap.add_argument("--from-csv", type=Path, default=None, help="read the rows from this CSV instead of running")
    if f.compare:
        ap.add_argument(
            "--compare", type=Path, default=None, help="exit 1 if the output differs from the committed files"
        )
    return ap


def run_study(study: Study, argv: list[str] | None = None) -> int:
    args = build_parser(study).parse_args(argv)
    csv_path: Path | None = getattr(args, "csv", None)
    page_path: Path | None = getattr(args, "page", None)
    from_csv: Path | None = getattr(args, "from_csv", None)
    compare: Path | None = getattr(args, "compare", None)

    rows = study.table.read(from_csv) if from_csv is not None else study.run(getattr(args, "seeds", None))
    block = study.render(rows)

    if compare is not None:
        differs = False
        if not study.table.is_current(compare, rows):
            print(f"the rows differ from {compare}", file=sys.stderr)
            differs = True
        if page_path is not None and not block_is_current(page_path, study.page_name, block):
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
        write_block(page_path, study.page_name, block)
        print(f"wrote the block into {page_path}", file=sys.stderr)
    if getattr(args, "markdown", False):
        print(block)
    return 0
