#!/usr/bin/env python3
"""Verify that the tables in README.md and docs/index.html match the benchmark.

Both documents claim that their numbers are generated rather than typed. This
script is what makes that claim checkable: it re-reads the generated
``results/benchmark.json`` and compares every numeric cell of both tables
against it, so a re-run that moves a number cannot silently leave the prose
describing the old one.

The tables are the only hand-maintained part of the pipeline, and they are
exactly the part most likely to drift, because nothing else fails when they do.

Run after ``scripts/run_benchmark.py``::

    python scripts/check_doc_tables.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _fmt(value: float | None, *, percent: bool = False) -> str | None:
    """Format a generated value the way the documents display it."""
    if value is None:
        return None
    return f"{100.0 * value:.1f}%" if percent else f"{value:.3f}"


def _expected_rows(results: dict) -> list[list[str | None]]:
    """One row of four display strings per case, in table order."""
    rows = []
    for case in results["cases"]:
        head = case["headline"]
        coverage = head.get("coverage") or {}
        rows.append([
            _fmt(head.get("ate_rmse_m")),
            _fmt(head.get("claimed_sigma_p_m")),
            _fmt(head.get("nees_mean")) if head.get("nees_mean") is not None else None,
            _fmt(coverage.get("2sigma"), percent=True),
        ])
    return rows


def _markdown_cells(text: str) -> list[list[str]]:
    """Body rows of the benchmark table in README.md, as cell lists."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        cells = _split_pipe(line)
        if cells and cells[0].lower().startswith("scenario") and any("ate rmse" in c.lower() for c in cells):
            start = index + 2  # skip the header and the |---| separator
            break
    if start is None:
        return []
    rows = []
    for line in lines[start:]:
        cells = _split_pipe(line)
        if not cells:
            break
        if all(set(c) <= set("-: ") for c in cells):  # a second separator
            continue
        rows.append(cells)
    return rows


def _split_pipe(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _html_cells(text: str) -> list[list[str]]:
    """Body rows of the benchmark table in docs/index.html, as cell lists."""
    body = re.search(r"<tbody>(.*?)</tbody>", text, re.S)
    if not body:
        return []
    rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", body.group(1), re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("&sigma;", "sigma").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells:
            rows.append(cells)
    return rows


def _cell(rows: list[list[str]], index: int, column: int) -> str | None:
    try:
        return rows[index][column]
    except IndexError:
        return None


def _display(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    Documents passed with --document may live outside the repository, and a
    reporting helper must not raise while reporting a mismatch.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check(results_path: Path, documents: list[Path]) -> int:
    results = json.loads(results_path.read_text())
    expected = _expected_rows(results)
    failures: list[str] = []

    columns = ("ATE RMSE", "claimed 1 sigma", "mean NEES", "coverage")
    for document in documents:
        if not document.exists():
            failures.append(f"{document}: missing")
            continue
        text = document.read_text()
        found = _html_cells(text) if document.suffix == ".html" else _markdown_cells(text)
        name = _display(document)
        if len(found) != len(expected):
            failures.append(
                f"{name}: {len(found)} benchmark rows, expected {len(expected)}"
            )
            continue
        for index, want in enumerate(expected):
            case = results["cases"][index]["name"]
            for column, w in zip(columns, want):
                got = _cell(found, index, columns.index(column) + 1)
                if w is None:
                    # A case with no reported covariance shows "n/a" in the docs.
                    if got is not None and got not in ("n/a", "n.a"):
                        failures.append(f"{name}: {case} {column}: expected n/a, found {got}")
                    continue
                want_text = f"{float(w):.1f}" if column == "mean NEES" else w
                if got is None or not got.startswith(want_text):
                    failures.append(
                        f"{name}: {case} {column}: "
                        f"document says {got}, generated value is {want_text}"
                    )

    if failures:
        print("documentation tables disagree with the generated benchmark:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print(
            "\nregenerate with scripts/run_benchmark.py and update the tables by hand,\n"
            "or take the values from `python scripts/run_benchmark.py --markdown`.",
            file=sys.stderr,
        )
        return 1

    checked = ", ".join(_display(p) for p in documents)
    print(f"documentation tables match {_display(results_path)} ({len(expected)} cases) in {checked}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=ROOT / "results" / "benchmark.json")
    parser.add_argument("--document", type=Path, action="append", dest="documents")
    args = parser.parse_args(argv)

    if not args.results.exists():
        print(f"{args.results} not found; run scripts/run_benchmark.py first", file=sys.stderr)
        return 1
    documents = args.documents or [ROOT / "README.md", ROOT / "docs" / "index.html"]
    return check(args.results, documents)


if __name__ == "__main__":
    raise SystemExit(main())
