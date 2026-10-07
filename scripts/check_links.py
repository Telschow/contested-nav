#!/usr/bin/env python
"""Check that every relative link and anchor in the Markdown files points at something real.

    python scripts/check_links.py              # README.md, CONTRIBUTING.md, ... and docs/
    python scripts/check_links.py README.md    # specific files

What it checks: links and images whose target is a path in the repository (the file or
directory must exist), and ``#anchor`` fragments (the heading must exist in the target
Markdown file, using GitHub's slug rules). What it does not check: ``http(s)`` links, which
need the network and are flaky; the weekly link workflow covers those with lychee.

Fenced code blocks and inline code are ignored, and the audit snapshots under
``docs/audit/0*`` are skipped because they are frozen history.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
HTML_ANCHOR = re.compile(r"""<a\s+[^>]*?(?:name|id)=["']([^"']+)["']""")
SKIP_PREFIXES = ("docs/audit/01", "docs/audit/02", "docs/audit/03", "docs/audit/04", "docs/audit/05", "docs/audit/06")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", heading)
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors_of(path: Path) -> set[str]:
    """Every anchor a Markdown file defines, with GitHub's ``-1``, ``-2`` suffixes for duplicates."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            base = slug(m.group(2))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
        out.update(HTML_ANCHOR.findall(line))
    return out


def links_in(path: Path) -> list[tuple[int, str]]:
    found = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in LINK.finditer(INLINE_CODE.sub("", line)):
            found.append((number, m.group(1)))
    return found


def _shown(path: Path, root: Path) -> Path:
    """The path relative to ``root`` when it is inside it, else as given."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def check_file(path: Path, root: Path = ROOT) -> list[str]:
    problems = []
    for number, target in links_in(path):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):  # http:, https:, mailto:, ...
            continue
        file_part, _, fragment = target.partition("#")
        dest = path if not file_part else (path.parent / file_part.split("?")[0]).resolve()
        where = f"{_shown(path, root)}:{number}"
        if not dest.exists():
            problems.append(f"{where}: {target}: no such file or directory")
            continue
        if fragment and dest.is_file() and dest.suffix.lower() == ".md" and fragment.lower() not in anchors_of(dest):
            problems.append(f"{where}: {target}: no heading or anchor '{fragment}' in {_shown(dest, root)}")
    return problems


def default_files(root: Path = ROOT) -> list[Path]:
    files = sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md")) + sorted((root / ".github").rglob("*.md"))
    return [f for f in files if not str(f.relative_to(root)).startswith(SKIP_PREFIXES)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="Markdown files (default: the repository's)")
    args = ap.parse_args(argv)
    files = [f.resolve() for f in args.files] if args.files else default_files()
    problems = [p for f in files for p in check_file(f)]
    for p in problems:
        print(p, file=sys.stderr)
    print(f"checked {len(files)} files, {len(problems)} broken link(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
