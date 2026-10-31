#!/usr/bin/env python
"""Write the held-out decision of ADR-0028 into the documents, from ``docs/data/b1_gate_heldout.csv`` only.

The held-out run is single use, so this never runs a case. It reads the committed CSV and writes two generated blocks:

* the table between the ``b1-gate-heldout`` markers of ``docs/calibration.md``;
* the status line between the ``b1-heldout-status`` markers of ``CONSTRAINTS.md``.

The status line is one of two fixed texts, chosen by whether every condition of the candidate row holds. The
conditions that failed are named from the CSV. ``--check`` fails when a document differs from what the CSV gives.

    python scripts/render_b1_heldout.py --write
    python scripts/render_b1_heldout.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navkit import b1_gate
from navkit.report.page import splice_block

CSV = ROOT / "docs" / "data" / "b1_gate_heldout.csv"
PAGE = ROOT / "docs" / "calibration.md"
CONSTRAINTS = ROOT / "CONSTRAINTS.md"

PAGE_BLOCK = "b1-gate-heldout"
STATUS_BLOCK = "b1-heldout-status"

#: Which condition of the ADR-0028 Decision each row of the table is.
ADR_CONDITION = {
    "nees_upper": "1",
    "nees_lower": "2",
    "coverage": "3",
    "ate_better": "4",
    "ate_median": "4",
    "ate_worst": "4",
}

PASSED = (
    "Status: the gate of ADR-0028 passed on the held-out seeds 100 to 124 for the candidate configuration (the "
    "stochastic clone with the measured-front-end noise preset). The single-anchor model fails it (diagnostic). "
    "vision_enabled stays False: changing the default is a separate maintainer decision, not part of the gate. "
    "What this does not show: synthetic data only, one trajectory family, visual errors independent in this "
    "scenario, and the noise preset rests on one measured front end (ADR-0024)."
)
FAILED = (
    "Status: closed as characterised, not solved (ADR-0036). The gate of ADR-0028 failed on the held-out "
    "seeds 100 to 124 for the candidate configuration "
    "on condition {conditions}. Any change to the candidate is tested on a new held-out set, starting at seed 125 "
    "(ADR-0028). vision_enabled stays False."
)


def candidate_rows(rows: list[dict]) -> list[dict]:
    mine = [r for r in rows if r["role"] == "candidate"]
    if not mine:
        raise ValueError("the CSV has no candidate row")
    if {r["seeds"] for r in mine} != {"100-124"}:
        raise ValueError("the candidate rows are not the held-out seeds 100-124")
    return mine


def status_text(rows: list[dict]) -> str:
    mine = candidate_rows(rows)
    failed = [r for r in mine if not r["passed"]]
    if not failed:
        return PASSED
    named = "; ".join(f"{ADR_CONDITION[r['condition']]} ({b1_gate.CONDITION_LABELS[r['condition']]})" for r in failed)
    return FAILED.format(conditions=named)


def render(rows: list[dict], page: str, constraints: str) -> tuple[str, str]:
    return (
        splice_block(page, PAGE_BLOCK, b1_gate.markdown_table(rows)),
        splice_block(constraints, STATUS_BLOCK, status_text(rows)),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    rows = b1_gate.parse_csv(CSV.read_text(encoding="utf-8"))
    page, constraints = PAGE.read_text(encoding="utf-8"), CONSTRAINTS.read_text(encoding="utf-8")
    new_page, new_constraints = render(rows, page, constraints)
    if args.write:
        PAGE.write_text(new_page, encoding="utf-8")
        CONSTRAINTS.write_text(new_constraints, encoding="utf-8")
        print("wrote the held-out blocks into docs/calibration.md and CONSTRAINTS.md")
        return 0
    stale = [p.name for p, a, b in ((PAGE, page, new_page), (CONSTRAINTS, constraints, new_constraints)) if a != b]
    if stale:
        print(f"differs from docs/data/b1_gate_heldout.csv: {', '.join(stale)}", file=sys.stderr)
        return 1
    print("the held-out blocks match docs/data/b1_gate_heldout.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
