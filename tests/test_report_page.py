"""Known-answer tests for the page-splice module."""

from __future__ import annotations

import pytest

from navkit.report import block_is_current, splice_block, write_block

PAGE = "intro\n<!-- t:start -->\n\nold\n\n<!-- t:end -->\noutro\n"


def test_replace_block() -> None:
    assert splice_block(PAGE, "t", "new") == "intro\n<!-- t:start -->\n\nnew\n\n<!-- t:end -->\noutro\n"


def test_replace_twice_gives_same_text() -> None:
    once = splice_block(PAGE, "t", "new")
    assert splice_block(once, "t", "new") == once


def test_other_markers_are_left_alone() -> None:
    page = PAGE + "<!-- u:start -->\nkeep\n<!-- u:end -->\n"
    assert splice_block(page, "t", "new").endswith("<!-- u:start -->\nkeep\n<!-- u:end -->\n")
