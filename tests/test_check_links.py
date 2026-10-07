"""The Markdown link checker finds broken relative links and anchors, and ignores what it should."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check_links.py")
assert _spec and _spec.loader
cl = importlib.util.module_from_spec(_spec)
sys.modules["check_links"] = cl
_spec.loader.exec_module(cl)


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Status and limits", "status-and-limits"),
        ("What is in the filter", "what-is-in-the-filter"),
        ("`navkit` CLI & friends", "navkit-cli--friends"),
        ("The [outage sweep](x.md) result", "the-outage-sweep-result"),
        ("Q&A: why 3 sigma?", "qa-why-3-sigma"),
    ],
)
def test_slug_follows_github(heading: str, expected: str) -> None:
    assert cl.slug(heading) == expected


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_links_pass(tmp_path: Path) -> None:
    _write(tmp_path, "docs/other.md", "# Other\n\n## Sub heading\n")
    page = _write(
        tmp_path,
        "README.md",
        "# Title\n\n[a](docs/other.md) [b](docs/other.md#sub-heading) [c](#title) [d](docs/) "
        "![img](docs/other.md) [e](https://example.org/x) [f](mailto:a@b.c)\n",
    )
    assert cl.check_file(page, tmp_path) == []


def test_a_missing_file_and_a_missing_anchor_are_reported_with_their_line(tmp_path: Path) -> None:
    _write(tmp_path, "docs/other.md", "# Other\n")
    page = _write(tmp_path, "README.md", "# T\n\n[x](docs/nope.md)\n[y](docs/other.md#gone)\n[z](#missing)\n")
    problems = cl.check_file(page, tmp_path)
    assert len(problems) == 3
    assert problems[0].startswith("README.md:3:") and "no such file" in problems[0]
    assert problems[1].startswith("README.md:4:") and "'gone'" in problems[1]
    assert problems[2].startswith("README.md:5:")


def test_links_in_code_are_ignored(tmp_path: Path) -> None:
    page = _write(tmp_path, "README.md", "# T\n\n`[x](nope.md)`\n\n```\n[y](nope.md)\n```\n")
    assert cl.check_file(page, tmp_path) == []


def test_duplicate_headings_get_numbered_anchors(tmp_path: Path) -> None:
    page = _write(tmp_path, "README.md", "# T\n\n## Same\n\n## Same\n\n[a](#same) [b](#same-1) [c](#same-2)\n")
    problems = cl.check_file(page, tmp_path)
    assert len(problems) == 1 and "same-2" in problems[0]


def test_html_anchors_count(tmp_path: Path) -> None:
    page = _write(tmp_path, "README.md", '# T\n\n<a name="custom"></a>\n\n[a](#custom)\n')
    assert cl.check_file(page, tmp_path) == []


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _write(tmp_path, "good.md", "# T\n")
    bad = _write(tmp_path, "bad.md", "# T\n\n[x](missing.md)\n")
    assert cl.main([str(good)]) == 0
    assert cl.main([str(bad)]) == 1
    assert "missing.md" in capsys.readouterr().err


def test_the_repository_has_no_broken_relative_links() -> None:
    assert cl.main([]) == 0
