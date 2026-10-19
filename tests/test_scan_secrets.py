"""The secret scanner: rules, redaction, tree and history scans, and the known-history list.

Sample secrets are built at run time from pieces so this file does not itself contain a
credential-shaped string that the scanner (and every other scanner) would flag.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("scan_secrets", ROOT / "scripts" / "scan_secrets.py")
assert _spec and _spec.loader
scan = importlib.util.module_from_spec(_spec)
sys.modules["scan_secrets"] = scan
_spec.loader.exec_module(scan)


def _samples() -> dict[str, str]:
    return {
        "provider-key": "freellmapi-" + "k" * 24,
        "github-token": "ghp_" + "A1" * 20,
        "github-fine-grained-token": "github_pat_" + "B" * 30,
        "aws-access-key-id": "AKIA" + "Z" * 16,
        "private-key-block": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "provider-secret-key": "sk-" + "c" * 40,
    }


@pytest.mark.parametrize("rule", sorted(scan.RULES))
def test_each_rule_fires_on_its_own_shape_and_names_the_rule(rule: str) -> None:
    hits = scan.scan_text(f"token = {_samples()[rule]}\n", "f.txt")
    assert [h[2] for h in hits] == [rule]


def test_the_report_redacts_the_value() -> None:
    ((where, line, rule, prefix),) = scan.scan_text(_samples()["provider-key"], "f.txt")
    assert (where, line, rule) == ("f.txt", 1, "provider-key")
    assert prefix == "free..."
    assert "k" * 8 not in prefix


@pytest.mark.parametrize(
    "text",
    [
        "export FREELLMAPI_API_KEY=...",  # the documented environment variable, not a key
        "provider key shape: freellmapi- followed by a token",  # prose naming the shape
        "freellmapi-short",  # too short to be a key
        "ghp_tooshort",
        "sk-learn is a library",
    ],
)
def test_ordinary_text_that_mentions_the_shapes_is_not_flagged(text: str) -> None:
    assert scan.scan_text(text, "f.txt") == []


def _git(repo: Path, *args: str) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, env={**env, "PATH": "/usr/bin:/bin:/usr/local/bin"}
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_tree_scan_finds_a_tracked_secret_and_ignores_untracked_files(repo: Path) -> None:
    (repo / "config.txt").write_text(f"key={_samples()['github-token']}\n")
    (repo / "untracked.txt").write_text(f"key={_samples()['aws-access-key-id']}\n")
    _git(repo, "add", "config.txt")
    found = scan.scan_files(scan.tracked_files(repo), repo)
    assert [(w, r) for w, _, r, _ in found] == [("config.txt", "github-token")]


def test_history_scan_finds_a_secret_that_was_later_removed(repo: Path) -> None:
    f = repo / "doc.md"
    f.write_text(f"apiKey: {_samples()['provider-key']}\n")
    _git(repo, "add", "doc.md")
    _git(repo, "commit", "-q", "-m", "add")
    f.write_text("apiKey: <redacted>\n")
    _git(repo, "commit", "-q", "-am", "redact")
    assert scan.scan_files(scan.tracked_files(repo), repo) == []
    found = scan.scan_history(repo)
    assert [r for _, _, r, _ in found] == ["provider-key"]


def test_known_history_is_accepted_only_for_its_commit_and_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mechanism is tested with a made-up entry, not with a real incident."""
    monkeypatch.setattr(scan, "KNOWN_HISTORY", {("abc1234", "github-token"): "a made-up accepted finding"})
    assert scan.is_known("commit abc1234def5678", "github-token")
    assert not scan.is_known("commit abc1234def5678", "provider-key")
    assert not scan.is_known("commit 0123456789ab", "github-token")


def test_the_shipped_known_history_is_empty() -> None:
    """Adding an accepted finding must be a visible change that a reviewer reads."""
    assert scan.KNOWN_HISTORY == {}


def test_history_scan_command_exits_nonzero_on_a_key_shaped_line(repo: Path) -> None:
    (repo / "doc.md").write_text(f"apiKey: {_samples()['provider-key']}\n")
    _git(repo, "add", "doc.md")
    _git(repo, "commit", "-q", "-m", "add")
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "scan_secrets.py"), "--history", "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert "provider-key" in run.stderr
    assert "k" * 8 not in run.stderr


def test_main_exits_nonzero_on_a_new_finding_and_zero_when_clean(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "ok.txt").write_text("nothing here\n")
    _git(repo, "add", "ok.txt")
    assert scan.main(["--root", str(repo)]) == 0
    (repo / "bad.txt").write_text(_samples()["provider-secret-key"] + "\n")
    _git(repo, "add", "bad.txt")
    assert scan.main(["--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "provider-secret-key" in err
    assert "c" * 8 not in err


def test_the_repository_itself_has_no_secret_in_its_tracked_files() -> None:
    assert scan.main(["--root", str(ROOT)]) == 0


#: The first characters of a provider key, as a document might quote them. The scanner needs 16
#: characters of token; this catches a shorter quoted start in Markdown.
KEY_PREFIX = re.compile(r"freellmapi-[0-9a-z]{3,}", re.IGNORECASE)
SKIP_PARTS = {".venv", "site", ".git", ".hypothesis", "node_modules"}


def test_no_document_quotes_the_start_of_a_provider_key() -> None:
    root = Path(__file__).resolve().parent.parent
    docs = [p for p in root.rglob("*.md") if not SKIP_PARTS & set(p.relative_to(root).parts)]
    hits = [
        f"{p.relative_to(root)}: {m.group(0)}" for p in docs for m in KEY_PREFIX.finditer(p.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_the_prefix_pattern_catches_a_quoted_start_and_not_prose() -> None:
    assert KEY_PREFIX.search('apiKey: "freellmapi-e4a9..."')
    assert not KEY_PREFIX.search("a key of the shape freellmapi- followed by a token")
