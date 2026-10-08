#!/usr/bin/env python
"""Check that a version is ready to be released, before the release workflow publishes anything.

A release needs four things to agree: the tag, the version in ``pyproject.toml``, the version in
``navkit.__version__``, and a written release. The written part is ``docs/releases/<version>.md``
without its DRAFT banner, and a ``## [<version>]`` section in ``CHANGELOG.md``.

    python scripts/check_release.py --tag v0.2.0     # the release workflow: any problem fails
    python scripts/check_release.py --dry-run        # a manual run: reports what would block, exits 0

The check is about agreement, not quality: it does not read the notes.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")
DRAFT_RE = re.compile(r"^>\s*\*\*DRAFT\.?\*\*", re.MULTILINE)


def package_versions(root: Path) -> tuple[str, str]:
    """The version in ``pyproject.toml`` and the one in ``src/navkit/__init__.py``."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init = (root / "src" / "navkit" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init, flags=re.MULTILINE)
    return pyproject, m.group(1) if m else ""


def problems(root: Path, tag: str | None) -> list[str]:
    """Everything that stops a release. ``tag`` is the pushed tag, or ``None`` for a dry run."""
    out: list[str] = []
    pyproject, init = package_versions(root)
    if pyproject != init:
        out.append(f"pyproject.toml says {pyproject} and navkit.__version__ says {init or 'nothing'}")
    version = pyproject
    if tag is not None:
        m = TAG_RE.match(tag)
        if not m:
            out.append(f"the tag {tag!r} is not of the form vMAJOR.MINOR.PATCH")
        elif m.group(1) != pyproject:
            out.append(f"the tag is {tag} and pyproject.toml says {pyproject}")
        elif init and m.group(1) != init:
            out.append(f"the tag is {tag} and navkit.__version__ says {init}")
        if m:
            version = m.group(1)
    notes = root / "docs" / "releases" / f"{version}.md"
    if not notes.is_file():
        out.append(f"docs/releases/{version}.md does not exist")
    elif DRAFT_RE.search(notes.read_text(encoding="utf-8")):
        out.append(f"docs/releases/{version}.md still carries its DRAFT banner")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, flags=re.MULTILINE):
        out.append(f"CHANGELOG.md has no '## [{version}]' section")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tag", help="the pushed tag, vMAJOR.MINOR.PATCH; any problem fails")
    mode.add_argument("--dry-run", action="store_true", help="report what would block a release and exit 0")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    found = problems(args.root, None if args.dry_run else args.tag)
    version = package_versions(args.root)[0]
    if not found:
        print(f"release check OK: {version} is ready")
        return 0
    label = "would block a release" if args.dry_run else "release check failed"
    print(f"{label} ({len(found)}):", file=sys.stderr)
    for p in found:
        print(f"  {p}", file=sys.stderr)
    return 0 if args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
