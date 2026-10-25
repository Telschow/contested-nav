"""Put a generated block between a pair of marker lines in a page.

The module owns the marker syntax, the rule that both markers are present and in order,
the blank-line framing and the one error message.
"""

from __future__ import annotations

from pathlib import Path


def markers(name: str) -> tuple[str, str]:
    return f"<!-- {name}:start -->", f"<!-- {name}:end -->"


def splice_block(page: str, name: str, block: str) -> str:
    """Return ``page`` with the block between the ``name`` markers replaced by ``block``."""
    start, end = markers(name)
    if start not in page or end not in page or page.index(start) > page.index(end):
        raise ValueError(f"the page needs the lines {start} and {end}, in that order")
    head, rest = page.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n\n{block}\n\n{end}{tail}"


def write_block(path: str | Path, name: str, block: str) -> None:
    """Replace the ``name`` block in the file at ``path``."""
    page = Path(path)
    try:
        text = splice_block(page.read_text(encoding="utf-8"), name, block)
    except ValueError as exc:
        raise ValueError(f"{page}: {exc}") from exc
    page.write_text(text, encoding="utf-8")


def block_is_current(path: str | Path, name: str, block: str) -> bool:
    """Regenerate and compare: True if the page already holds ``block`` in the ``name`` markers."""
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    return splice_block(text, name, block) == text
