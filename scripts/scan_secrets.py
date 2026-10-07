#!/usr/bin/env python
"""Scan tracked files, and optionally the whole git history, for credential-shaped strings.

    python scripts/scan_secrets.py              # tracked files
    python scripts/scan_secrets.py --history    # every line ever added, on every ref

Why this exists next to a generic scanner: the repository once carried a provider API key
in a local config file, so the shape of that key is a rule of its own (``freellmapi-``
followed by a long token). The other rules are a short list of high-signal formats. This
is a tripwire, not a guarantee; it finds well-known shapes and will miss an arbitrary
high-entropy string.

A finding prints the file or commit, the line number, the rule and the first four
characters, never the value. The exit status is 1 if anything is found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

#: Rule name to pattern. Keep this list short and high-signal: a noisy rule trains people to
#: ignore the tool.
RULES: dict[str, re.Pattern[str]] = {
    "freellmapi-key": re.compile(r"freellmapi-[A-Za-z0-9_-]{16,}"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "github-fine-grained-token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    "aws-access-key-id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private-key-block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "provider-secret-key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b"),
}

#: Findings in history that are already understood. Each entry is a commit prefix, the rule,
#: and why it is accepted; a finding that matches is reported as known and does not fail the
#: scan, and anything else does. Adding an entry is a decision to make in review, so the reason
#: has to be written down here.
KNOWN_HISTORY: dict[tuple[str, str], str] = {
    ("fbeb429", "freellmapi-key"): (
        "a provider key committed in docs/PUBLICATION_READINESS.md on 2026-09-29, redacted in ccb812a "
        "on 2026-09-30, and rotated by the maintainer. It remains in git history."
    ),
}

#: Files that are binary or generated and would only produce noise.
SKIP_SUFFIXES = (".png", ".gif", ".jpg", ".pdf", ".lock")


def scan_text(text: str, where: str) -> list[tuple[str, int, str, str]]:
    """Return ``(where, line_number, rule, redacted_prefix)`` for each match in ``text``."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in RULES.items():
            match = pattern.search(line)
            if match:
                found.append((where, number, rule, match.group(0)[:4] + "..."))
    return found


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    return [root / p for p in out.decode().split("\0") if p and not p.endswith(SKIP_SUFFIXES)]


def scan_files(paths: Iterable[Path], root: Path) -> list[tuple[str, int, str, str]]:
    found = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        found.extend(scan_text(text, str(path.relative_to(root))))
    return found


def added_lines(root: Path) -> Iterator[tuple[str, int, str]]:
    """Yield ``(commit, line_number_in_diff, text)`` for every added line on every ref."""
    proc = subprocess.Popen(
        ["git", "log", "--all", "-p", "--no-color", "--format=commit %H"],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    commit, n = "", 0
    for raw in proc.stdout:
        n += 1
        if raw.startswith("commit ") and len(raw.strip()) == 47:
            commit = raw.split()[1][:12]
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            yield commit, n, raw[1:]
    proc.wait()


def scan_history(root: Path) -> list[tuple[str, int, str, str]]:
    found = []
    for commit, n, text in added_lines(root):
        for _, _, rule, prefix in scan_text(text, f"commit {commit}"):
            found.append((f"commit {commit}", n, rule, prefix))
    return found


def is_known(where: str, rule: str) -> bool:
    """Whether a history finding is one of the understood ones in :data:`KNOWN_HISTORY`."""
    commit = where.removeprefix("commit ")
    return any(commit.startswith(c) and rule == r for (c, r) in KNOWN_HISTORY)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", action="store_true", help="scan every added line on every ref instead of the tree")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)

    found = scan_history(args.root) if args.history else scan_files(tracked_files(args.root), args.root)
    known = [f for f in found if args.history and is_known(f[0], f[2])]
    new = [f for f in found if f not in known]
    for where, line, rule, prefix in known:
        print(f"{where}:{line}: {rule} ({prefix}) KNOWN, accepted: see KNOWN_HISTORY", file=sys.stderr)
    for where, line, rule, prefix in new:
        print(f"{where}:{line}: {rule} ({prefix})", file=sys.stderr)
    scope = "history" if args.history else "tracked files"
    if new:
        print(f"{len(new)} possible secret(s) in {scope}. Do not push; rotate anything real.", file=sys.stderr)
        return 1
    suffix = f" ({len(known)} known and accepted)" if known else ""
    print(f"no new credential-shaped strings in {scope}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
