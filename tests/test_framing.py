"""Framing guard: no career wording anywhere, no defence-role wording outside docs/defense/.

This file is the only place the word lists may live.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parents[1]

CAREER = re.compile(
    r"\b(portfolio|showcase\w*|interview\w*|recruit\w*|hiring|employers?)\b",
    re.IGNORECASE,
)
DEFENCE_ROLE = re.compile(
    r"\b(loitering|munitions?|recon)\b|short-denial\s+intercept",
    re.IGNORECASE,
)


def _tracked() -> list[str]:
    try:
        proc = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git checkout: tracked files cannot be listed")
        return []
    return [p for p in proc.stdout.decode().split("\0") if p]


def _text(path: str) -> str | None:
    data = (ROOT / path).read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _hits(pattern: re.Pattern[str], skip_defense_dir: bool) -> list[str]:
    found = []
    for path in _tracked():
        if path == "tests/test_framing.py":
            continue
        if skip_defense_dir and path.startswith("docs/defense/"):
            continue
        if not (ROOT / path).is_file():
            continue
        text = _text(path)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path}:{n}: {line.strip()[:100]}")
    return found


def test_no_career_wording_in_any_tracked_file():
    assert _hits(CAREER, skip_defense_dir=False) == []


def test_no_defence_role_wording_outside_docs_defense():
    assert _hits(DEFENCE_ROLE, skip_defense_dir=True) == []


def test_bare_intercept_is_not_flagged():
    assert not DEFENCE_ROLE.search("the intercept of the regression line")
    assert not DEFENCE_ROLE.search("Reconsider when measured")
    assert DEFENCE_ROLE.search("Class 2 Recon UAS")
