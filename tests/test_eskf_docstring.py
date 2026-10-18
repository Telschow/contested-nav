"""The estimator's documentation must not contradict its code or the generated results.

The module docstring of ``navkit.estimators.eskf`` once carried measured figures that went stale, a Jacobian that
the update code does not use, and a "default" that named two values. These tests pin the three that a reader
trips over first. Measured figures belong in ``docs/results.md`` and the README table, which are generated.
"""

from __future__ import annotations

import re
from pathlib import Path

from navkit.estimators import eskf

SOURCE = Path(eskf.__file__).read_text(encoding="utf-8")


def _module_docstring() -> str:
    doc = eskf.__doc__
    assert doc
    return doc


def _bullet(doc: str, title: str) -> str:
    """The text of the ``* **title**`` bullet, up to the next bullet or blank line group."""
    start = doc.index(f"* **{title}**")
    rest = doc[start + 1 :]
    stop = re.search(r"\n\* \*\*|\n\n", rest)
    return doc[start : start + 1 + (stop.start() if stop else len(rest))]


def test_eskf_module_docstring_has_no_typed_results() -> None:
    """A decimal number in the module docstring is a typed copy of a result, and it goes stale."""
    typed = re.findall(r"\d+\.\d+", _module_docstring())
    assert typed == [], f"decimal numbers in the module docstring: {typed}; point to docs/results.md instead"


def test_eskf_rotation_jacobian_names_r_rel_pred() -> None:
    """The rotation block of the visual Jacobian is ``R_rel_pred``, not the identity (see ``_vision_update``)."""
    item = _bullet(_module_docstring(), "Visual relative rotation")
    assert "R_rel_pred" in item
    assert "H = [I 0 0 0 0]" not in item


def test_vision_keyframe_interval_comment_names_one_default() -> None:
    """The comment above ``vision_keyframe_interval`` said both ``None`` and ``1`` were the default."""
    lines = SOURCE.splitlines()
    field_line = next(i for i, line in enumerate(lines) if line.startswith("    vision_keyframe_interval:"))
    assert "= 1" in lines[field_line], "the default in the code changed: update the comment and this test"
    block = []
    for line in reversed(lines[:field_line]):
        if not line.lstrip().startswith("#:"):
            break
        block.append(line)
    comment = " ".join(reversed(block))
    assert comment, "no comment block above vision_keyframe_interval"
    assert comment.count("the default") == 1, comment
