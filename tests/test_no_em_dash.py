"""The writing rule "no em dashes" holds in every text file the repository tracks.

The character is written as an escape here so that this file passes its own check. No tracked file legitimately
contains it, so nothing is excluded; add an exclusion with its reason below if one ever does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
EM_DASH = "—"
#: Path prefixes that may contain the character, each with the reason. Empty on purpose.
EXCLUDED: dict[str, str] = {}


def em_dash_lines(text: str) -> list[int]:
    """The 1-based numbers of the lines of ``text`` that hold an em dash."""
    return [n for n, line in enumerate(text.splitlines(), start=1) if EM_DASH in line]


def test_the_scanner_reports_the_line_of_each_em_dash() -> None:
    assert em_dash_lines(f"fine\nbad {EM_DASH} here\nfine\n{EM_DASH}") == [2, 4]


def test_the_scanner_accepts_hyphens_and_en_dashes() -> None:
    en_dash = chr(0x2013)
    assert em_dash_lines(f"a - b\n2020{en_dash}2021\n--") == []


def _tracked_text_files() -> list[Path]:
    run = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    names = [n for n in run.stdout.decode().split("\0") if n and not n.startswith(tuple(EXCLUDED))]
    return [ROOT / n for n in names if (ROOT / n).is_file()]


def test_no_tracked_text_file_holds_an_em_dash() -> None:
    hits = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # a binary file
        hits.extend(f"{path.relative_to(ROOT)}:{n}" for n in em_dash_lines(text))
    assert not hits, "em dash (write a comma, colon or a new sentence): " + ", ".join(hits)
