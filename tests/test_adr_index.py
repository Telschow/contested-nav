"""The ADR index and the ADR files give the same status for every record."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ADR_DIR / "index.md"


def statuses_from_files() -> dict[str, str]:
    statuses = {}
    for path in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        match = re.search(r"^- Status:\s*(.+)$", path.read_text(encoding="utf-8"), re.M)
        assert match is not None, f"{path.name} has no Status line"
        statuses[path.name[:4]] = match.group(1).strip()
    return statuses


def statuses_from_index() -> dict[str, str]:
    text = INDEX.read_text(encoding="utf-8")
    rows = re.findall(r"\| \[ADR-(\d{4})\]\([^)]*\) \| [^|]+ \| ([^|]+) \|", text)
    return {number: status.strip() for number, status in rows}


def test_every_adr_file_has_the_index_status() -> None:
    files = statuses_from_files()
    index = statuses_from_index()
    assert {number: index.get(number) for number in files} == files
