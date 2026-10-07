#!/usr/bin/env python
"""Check the system requirements traceability matrix against the repository.

``docs/product_management/01_system_requirements_spec.md`` lists requirements (``TR-nn``) and
acceptance criteria (``AC-nn``), each with a verdict. This script makes the links checkable. The
evidence for each id is in ``docs/product_management/srs_trace.csv``, one row per id:

* ``tests``: pytest references, ``path::name`` or ``path::Class::name``, that must exist;
* ``config``: values the requirement quotes, checked against the repository
  (``yaml:file:dotted.key=value``, ``py:module:Attr.path=value``, ``fn:module:function.param=value``,
  ``file:path``), separated by ``;``;
* ``gap``: a stated reason there is no test, for a requirement that has none.

It fails when

* an id in the document has no row in the CSV, or a row has no id in the document;
* a row has no tests, no config check and no gap (silence);
* a MET or PASS verdict rests on a gap alone;
* a referenced test does not exist, or a configured value is not what the document says;
* the verdict is not one of the document's legend;
* the roll-up table in section 2.1 disagrees with the verdicts it summarises.

    python scripts/check_srs_trace.py
    python scripts/check_srs_trace.py --summary

The check is structural. It does not re-run a test or re-measure a number, and it does not read
prose: a number written in a paragraph can still go stale.
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib
import inspect
import math
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SRS_PATH = ROOT / "docs" / "product_management" / "01_system_requirements_spec.md"
TRACE_PATH = ROOT / "docs" / "product_management" / "srs_trace.csv"
FIELDS = ("id", "tests", "config", "gap")

#: Longest first, so "NOT VERIFIED" is not read as "NOT MET" or "MET".
VERDICTS = ("NOT VERIFIED", "NOT MET", "CONTRADICTED", "PARTIAL", "MET", "PASS", "FAIL")
GOOD = ("MET", "PASS")


def verdict_of(cell: str) -> str | None:
    """The legend word a verdict cell starts with, or ``None``."""
    text = cell.replace("*", "").strip().upper()
    for word in VERDICTS:
        if text == word or text.startswith(word + " ") or text.startswith(word + ","):
            return word
    return None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_srs(text: str) -> tuple[dict[str, str | None], set[str]]:
    """Verdict per ``TR-nn`` and ``AC-nn`` id, and the set of every id the document names in a table.

    An ``AC`` id appears in the criteria table without a verdict and in the status table with one;
    the verdict is taken from the row that has one.
    """
    verdicts: dict[str, str | None] = {}
    ids: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*((?:TR|AC)-\d+)\s*\|", line)
        if not m:
            continue
        rid = m.group(1)
        ids.add(rid)
        found = verdict_of(_cells(line)[-1])
        if found is not None or rid not in verdicts:
            verdicts[rid] = found if found is not None else verdicts.get(rid)
    return verdicts, ids


def expand(cell: str) -> list[str]:
    """``TR-20…TR-25, TR-28`` to the list of ids it names."""
    out: list[str] = []
    for m in re.finditer(r"TR-(\d+)(?:\s*(?:…|\.\.\.)\s*TR-(\d+))?", cell):
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        out.extend(f"TR-{n:02d}" for n in range(lo, hi + 1))
    return out


def parse_rollup(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(OUN-\d+)[^|]*\|", line)
        if not m:
            continue
        cells = _cells(line)
        if len(cells) < 5:
            continue
        nums = []
        for c in cells[2:5]:
            n = re.match(r"\s*(\d+)", c.replace("*", ""))
            nums.append(int(n.group(1)) if n else None)
        rows.append({"oun": m.group(1), "ids": expand(cells[1]), "claimed": tuple(nums)})
    return rows


def check_rollup(rollup: list[dict[str, Any]], verdicts: dict[str, str | None]) -> list[str]:
    problems = []
    for row in rollup:
        missing = [i for i in row["ids"] if i not in verdicts]
        if missing:
            problems.append(f"roll-up {row['oun']} names {', '.join(missing)}, which are not in the matrix")
            continue
        vs = [verdicts[i] for i in row["ids"]]
        got = (
            sum(1 for v in vs if v in GOOD),
            sum(1 for v in vs if v == "NOT MET"),
            sum(1 for v in vs if v in ("NOT VERIFIED", "CONTRADICTED")),
        )
        if row["claimed"] != got:
            problems.append(
                f"roll-up {row['oun']} says met/not met/not verified-or-contradicted = "
                f"{'/'.join(str(c) for c in row['claimed'])}, the verdicts give {'/'.join(str(g) for g in got)}"
            )
    return problems


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise SystemExit(f"{path} must have the columns {', '.join(FIELDS)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _test_exists(ref: str, root: Path) -> str | None:
    """``None`` if the reference resolves, else the reason it does not."""
    parts = ref.split("::")
    if len(parts) not in (2, 3):
        return f"{ref}: expected path::name or path::Class::name"
    file = root / parts[0]
    if not file.is_file():
        return f"{ref}: {parts[0]} does not exist"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    if len(parts) == 2:
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        return None if parts[1] in names else f"{ref}: no top-level function {parts[1]}"
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == parts[1]:
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
            return None if parts[2] in methods else f"{ref}: class {parts[1]} has no method {parts[2]}"
    return f"{ref}: no class {parts[1]}"


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=0.0)
    return bool(a == b)


def _lookup(obj: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        obj = obj[key] if isinstance(obj, dict) else getattr(obj, key)
    return obj


def _check_value(expr: str, root: Path) -> str | None:
    """Evaluate one ``config`` expression; ``None`` if it holds, else why not."""
    kind, _, rest = expr.partition(":")
    if kind == "file":
        return None if (root / rest).exists() else f"{expr}: no such file"
    if "=" not in rest:
        return f"{expr}: expected kind:target=value"
    target, _, literal = rest.rpartition("=")
    try:
        want = ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        return f"{expr}: {literal!r} is not a literal"
    try:
        if kind == "yaml":
            path, _, dotted = target.partition(":")
            got = _lookup(yaml.safe_load((root / path).read_text(encoding="utf-8")), dotted)
        elif kind == "py":
            module, _, dotted = target.partition(":")
            got = _lookup(importlib.import_module(module), dotted)
        elif kind == "fn":
            module, _, dotted = target.partition(":")
            func, _, param = dotted.partition(".")
            got = inspect.signature(getattr(importlib.import_module(module), func)).parameters[param].default
        else:
            return f"{expr}: unknown kind {kind!r}"
    except Exception as err:  # a missing key or module is a finding, not a crash
        return f"{expr}: {type(err).__name__}: {err}"
    return None if _same(got, want) else f"{expr}: the repository has {got!r}"


def check(srs_text: str, trace: list[dict[str, str]], root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    verdicts, ids = parse_srs(srs_text)

    tr_ids = sorted(i for i in ids if i.startswith("TR-"))
    if tr_ids != [f"TR-{n:02d}" for n in range(1, len(tr_ids) + 1)]:
        problems.append("the TR ids are not consecutive from TR-01")

    rows: dict[str, dict[str, str]] = {}
    for r in trace:
        if r["id"] in rows:
            problems.append(f"{r['id']}: more than one row in the trace file")
        rows[r["id"]] = r
    for rid in sorted(ids - rows.keys()):
        problems.append(f"{rid}: in the document but has no row in the trace file")
    for rid in sorted(rows.keys() - ids):
        problems.append(f"{rid}: in the trace file but not in the document")

    for rid in sorted(ids & rows.keys()):
        r, verdict = rows[rid], verdicts.get(rid)
        if verdict is None:
            problems.append(f"{rid}: the verdict is not one of {', '.join(VERDICTS)}")
        tests = [t.strip() for t in r["tests"].split(";") if t.strip()]
        config = [c.strip() for c in r["config"].split(";") if c.strip()]
        if not (tests or config or r["gap"]):
            problems.append(f"{rid}: no test, no config check and no declared gap")
        if verdict in GOOD and not (tests or config):
            problems.append(f"{rid}: {verdict} rests on a declared gap alone, which is not evidence")
        for ref in tests:
            why = _test_exists(ref, root)
            if why:
                problems.append(f"{rid}: {why}")
        for expr in config:
            why = _check_value(expr, root)
            if why:
                problems.append(f"{rid}: {why}")

    problems.extend(check_rollup(parse_rollup(srs_text), verdicts))
    return problems


def summary(srs_text: str, trace: list[dict[str, str]]) -> str:
    verdicts, _ = parse_srs(srs_text)
    lines = ["| ID | Verdict | Tests | Config checks | Declared gap |", "|---|---|---:|---:|---|"]
    by_id = {r["id"]: r for r in trace}
    for rid in sorted(verdicts):
        r = by_id.get(rid, dict.fromkeys(FIELDS, ""))
        n_t = len([t for t in r["tests"].split(";") if t.strip()])
        n_c = len([c for c in r["config"].split(";") if c.strip()])
        lines.append(f"| {rid} | {verdicts[rid] or '?'} | {n_t} | {n_c} | {'yes' if r['gap'] else ''} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", type=Path, default=SRS_PATH)
    ap.add_argument("--trace", type=Path, default=TRACE_PATH)
    ap.add_argument("--summary", action="store_true", help="print one line per requirement")
    args = ap.parse_args(argv)
    text = args.srs.read_text(encoding="utf-8")
    trace = read_trace(args.trace)
    if args.summary:
        print(summary(text, trace))
    problems = check(text, trace)
    if problems:
        print(f"{len(problems)} traceability problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    verdicts, _ = parse_srs(text)
    print(f"traceability OK: {len(verdicts)} requirements and criteria, each with evidence or a declared gap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
