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


@pytest.mark.parametrize("page", ["no markers", "<!-- t:start -->\nonly start", "only end\n<!-- t:end -->"])
def test_missing_marker_raises(page: str) -> None:
    with pytest.raises(ValueError, match="in that order"):
        splice_block(page, "t", "new")


def test_reversed_markers_raise() -> None:
    with pytest.raises(ValueError, match="<!-- t:start --> and <!-- t:end -->, in that order"):
        splice_block("<!-- t:end -->\nx\n<!-- t:start -->", "t", "new")


def test_write_block(tmp_path) -> None:
    path = tmp_path / "p.md"
    path.write_text(PAGE, encoding="utf-8")
    write_block(path, "t", "new")
    assert path.read_text(encoding="utf-8") == splice_block(PAGE, "t", "new")


def test_write_block_error_names_the_file(tmp_path) -> None:
    path = tmp_path / "p.md"
    path.write_text("nothing", encoding="utf-8")
    with pytest.raises(ValueError, match=r"p\.md"):
        write_block(path, "t", "new")
    assert path.read_text(encoding="utf-8") == "nothing"


def test_block_is_current(tmp_path) -> None:
    path = tmp_path / "p.md"
    path.write_text(splice_block(PAGE, "t", "new"), encoding="utf-8")
    assert block_is_current(path, "t", "new")
    assert not block_is_current(path, "t", "different")


@pytest.mark.parametrize(
    ("module", "func", "name"),
    [
        ("start_draw_study", "splice_section", "start-draw"),
        ("correlated_gnss_study", "splice_section", "correlated-gnss"),
        ("b1_gate", "splice_table", "b1-gate-dev"),
        ("scale_tuning", "splice_section", "scale-tuning"),
        ("candidate_gate", "splice_table", "candidate-gate-dev"),
        ("mismatch_ensemble", "splice_table", "mismatch-ensemble"),
    ],
)
def test_strict_page_wrappers_use_the_shared_splice(module: str, func: str, name: str) -> None:
    import importlib

    splice = getattr(importlib.import_module(f"navkit.{module}"), func)
    page = f"a\n<!-- {name}:start -->\n\nold\n\n<!-- {name}:end -->\nb\n"
    assert splice(page, "new") == splice_block(page, name, "new")
    reversed_page = f"<!-- {name}:end -->\n<!-- {name}:start -->"
    with pytest.raises(ValueError, match="in that order") as exc:
        splice(reversed_page, "new")
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    assert str(exc.value) == f"the page needs the lines {start} and {end}, in that order"
