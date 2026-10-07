"""``RISKS.md`` keeps one table row and one detail section per risk, with valid ratings."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "RISKS.md").read_text(encoding="utf-8")
LEVELS = {"Low", "Medium", "High"}
STATUSES = {"Occurred", "Open", "Mitigated", "Accepted"}


def _rows() -> list[list[str]]:
    rows = []
    for line in TEXT.splitlines():
        if re.match(r"^\| R\d+ \|", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def test_ids_are_unique_and_consecutive() -> None:
    ids = [r[0] for r in _rows()]
    assert ids == [f"R{n}" for n in range(1, len(ids) + 1)]


def test_every_row_uses_the_documented_vocabulary() -> None:
    for rid, _risk, likelihood, impact, status in _rows():
        assert likelihood in LEVELS, rid
        assert impact in LEVELS, rid
        assert status in STATUSES, rid


def test_every_risk_has_a_detail_section_in_the_same_order() -> None:
    table_ids = [r[0] for r in _rows()]
    detail_ids = re.findall(r"^### (R\d+)\.", TEXT, flags=re.MULTILINE)
    assert detail_ids == table_ids


def test_an_occurred_risk_points_at_evidence() -> None:
    sections = re.split(r"^### ", TEXT, flags=re.MULTILINE)[1:]
    by_id = {s.split(".", 1)[0]: s for s in sections}
    for rid, _risk, _l, _i, status in _rows():
        if status == "Occurred":
            body = by_id[rid]
            assert "What happened" in body, rid
