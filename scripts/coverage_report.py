#!/usr/bin/env python3
"""Line-coverage report and ratchet check, with no third-party dependencies.

Why not ``pytest-cov``: constraint S1 keeps the runtime to NumPy, and a
quality gate that cannot be run because a plugin is missing is not a gate.
This uses :mod:`dis` to enumerate executable lines and a line-event tracer to
record which ones execute, then compares the result against the floors
declared in ``CONSTRAINTS.md``.

Usage::

    python scripts/coverage_report.py            # report
    python scripts/coverage_report.py --ratchet  # exit 1 if a floor regressed
    python scripts/coverage_report.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import dis
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
COV = ROOT / "coverage.json"

# Floors from CONSTRAINTS.md, in percent. A module absent from this table is
# reported but not gated.
FLOORS: dict[str, float] = {
    "src/navkit/io/trajectory.py": 85.0,
    "src/navkit/analysis/findings.py": 80.0,
    "src/navkit/config.py": 80.0,
    "src/navkit/eval/metrics.py": 60.0,
    "src/navkit/eval/thresholds.py": 60.0,
    "src/navkit/geometry/align.py": 60.0,
    "src/navkit/estimators/eskf.py": 80.0,
    # These four were declared in CONSTRAINTS.md but missing here, so the
    # security-relevant modules carried no enforced floor at all. A floor that
    # is documented but absent from this table is not a floor.
    "src/navkit/fdir/gating.py": 70.0,
    "src/navkit/fdir/fdir_manager.py": 70.0,
    # config.py and records.py were part of fdir_manager.py, and so under its 70% floor,
    # until they were split out. They keep the same floor.
    "src/navkit/fdir/config.py": 70.0,
    "src/navkit/fdir/records.py": 70.0,
    "src/navkit/fdir/nis_monitor.py": 80.0,
    # The two sweeps and the figure script were under scripts/, outside this measurement,
    # until they moved into the package behind `navkit sweep` and `navkit figures`.
    "src/navkit/seed_sweep.py": 75.0,
    "src/navkit/scene_sweep.py": 80.0,
    "src/navkit/figures.py": 70.0,
    "src/navkit/degrade/config.py": 50.0,
    "src/navkit/degrade/inject.py": 50.0,
}
# Total floor, matching the "Line coverage 75%" ratchet in CONSTRAINTS.md. The
# two must agree: a gate lower than the documented floor is not the documented
# gate, and CONSTRAINTS.md claims every ratchet here is enforced.
# The total floor is 75% because that is what CONSTRAINTS.md declares. Note the
# consequence, which is deliberate: this is a floor, not a ratchet. On the CI
# matrix's newest interpreter (CPython 3.13) the total measures 91.61%, so
# roughly 16 points of coverage can be deleted before this fails. Tightening it
# is a judgement call about how much slack a refactor should be allowed, and it
# is tracked in ROADMAP.md rather than changed silently.
TOTAL_FLOOR = 75.0


def executable_lines(path: pathlib.Path) -> set[int]:
    """Line numbers that can emit a line event, found by walking all code objects."""
    src = path.read_text()
    top = compile(src, str(path), "exec")
    lines: set[int] = set()
    stack = [top]
    while stack:
        code = stack.pop()
        lines.update(ln for _, ln in dis.findlinestarts(code) if ln)
        stack.extend(c for c in code.co_consts if hasattr(c, "co_code"))
    return {ln for ln in lines if 0 < ln <= src.count("\n") + 1}


def instrumented(targets: dict[str, set[int]]) -> dict[str, set[int]]:
    """Run pytest under a line tracer, returning the executed lines per file."""
    seen: dict[str, set[int]] = {k: set() for k in targets}

    def tracer(frame, event, _arg):
        name = frame.f_code.co_filename
        if name in seen:
            if event == "line":
                seen[name].add(frame.f_lineno)
            return tracer
        return None

    import pytest

    os.chdir(ROOT)
    sys.settrace(tracer)
    try:
        pytest.main(["-q", "--no-header", "-p", "no:cacheprovider"])
    finally:
        sys.settrace(None)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ratchet", action="store_true", help="exit 1 if a floor regressed")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    # Executable lines are enumerated with `dis`, so the denominator is a
    # function of the interpreter's bytecode and not only of the source.
    # Measured totals for this tree: CPython 3.11 -> 3674/4022 (91.35%),
    # 3.13 -> 3799/4147 (91.61%), 3.14 -> 3662/4181 (87.59%). Same tree, same
    # tests, four points apart. A quoted figure is therefore only meaningful
    # next to the interpreter that produced it, so it is recorded here in both
    # output modes. Floors are unaffected: all three totals clear 75%, and every
    # per-module floor sits far enough below its measured figure that the
    # interpreter swing cannot flip the ratchet.
    interp = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} ({sys.implementation.name})"
    # Printed before the suite runs, not after: `instrumented()` drives pytest
    # in-process, so anything emitted afterwards sits below a screenful of
    # progress dots and is effectively invisible.
    if not args.json:
        print(f"interpreter: {interp}")

    modules = {str(p.resolve()): executable_lines(p) for p in sorted(SRC.rglob("*.py"))}
    seen = instrumented(modules)

    rows = []
    for name, exec_lines in sorted(modules.items()):
        rel = str(pathlib.Path(name).relative_to(ROOT))
        hit = len(seen[name] & exec_lines)
        total = len(exec_lines)
        pct = round(100.0 * hit / total, 1) if total else 0.0
        rows.append({"module": rel, "hit": hit, "exec": total, "pct": pct})

    total_hit = sum(r["hit"] for r in rows)
    total_exec = sum(r["exec"] for r in rows)
    total_pct = round(100.0 * total_hit / total_exec, 2) if total_exec else 0.0

    COV.write_text(json.dumps({"modules": rows, "total_pct": total_pct, "python": interp}, indent=1))

    failures = []
    if args.ratchet:
        for r in rows:
            floor = FLOORS.get(r["module"])
            if floor is not None and r["pct"] < floor:
                failures.append(f"{r['module']}: {r['pct']}% < floor {floor}%")
        if total_pct < TOTAL_FLOOR:
            failures.append(f"TOTAL: {total_pct}% < floor {TOTAL_FLOOR}%")

    if args.json:
        print(
            json.dumps(
                {
                    "modules": rows,
                    "total_pct": total_pct,
                    "python": interp,
                    "failures": failures,
                },
                indent=1,
            )
        )
    else:
        gated = set(FLOORS)
        print(f"{'module':<40}{'hit':>7}{'exec':>7}{'  %':>7}  floor")
        for r in sorted(rows, key=lambda r: r["pct"]):
            floor = FLOORS.get(r["module"])
            mark = "" if floor is None else ("  ok" if r["pct"] >= floor else f"  FAIL(<{floor:g})")
            tag = " *" if r["module"] in gated else ""
            print(f"{r['module']:<40}{r['hit']:>7}{r['exec']:>7}{r['pct']:>6.1f}%{mark}{tag}")
        print(f"{'TOTAL':<40}{total_hit:>7}{total_exec:>7}{total_pct:>6.2f}%")

    if failures:
        print("\nratchet FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    if args.ratchet:
        print("\nratchet OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
