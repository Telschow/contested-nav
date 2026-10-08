"""This is a one-person project: no document may name a team or a manager as an owner."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A table cell that is a team or a manager: "Estimator team", "Release manager".
INVENTED_OWNER = re.compile(r"\|\s*[A-Z][\w/ -]*\b(?:team|manager)\s*\|", re.IGNORECASE)
#: The first characters of a provider key, as a document might quote them.
KEY_PREFIX = re.compile(r"freellmapi-[0-9a-z]{3,}", re.IGNORECASE)

SKIP_PARTS = {".venv", "site", ".git", ".hypothesis", "node_modules"}


def _documents() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not SKIP_PARTS & set(p.relative_to(ROOT).parts)]


def test_no_table_names_a_team_or_manager_as_owner():
    hits = [
        f"{p.relative_to(ROOT)}:{n}: {m.group(0).strip()}"
        for p in _documents()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        for m in [INVENTED_OWNER.search(line)]
        if m
    ]
    assert hits == []


def test_no_document_quotes_the_start_of_a_provider_key():
    hits = [
        f"{p.relative_to(ROOT)}: {m.group(0)}"
        for p in _documents()
        for m in KEY_PREFIX.finditer(p.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_the_patterns_catch_what_they_are_meant_to():
    assert INVENTED_OWNER.search("| N1: do it | Estimator team | evidence |")
    assert INVENTED_OWNER.search("| N4: lint | Release manager | evidence |")
    assert not INVENTED_OWNER.search("| N1: do it | Maintainer | evidence |")
    assert KEY_PREFIX.search('apiKey: "freellmapi-e4a9..."')
    assert not KEY_PREFIX.search("a key of the shape freellmapi- followed by a token")
