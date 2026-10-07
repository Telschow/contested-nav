"""``scripts/check_release.py`` agrees a tag, two version strings, release notes and a changelog."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_release.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_release"] = module
    spec.loader.exec_module(module)
    return module


rel = _load()


def _repo(
    tmp_path: Path,
    *,
    pyproject: str = "1.2.3",
    init: str = "1.2.3",
    notes: str | None = "# notes\n",
    changelog: str = "## [1.2.3] - 2026\n",
) -> Path:
    (tmp_path / "src" / "navkit").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{pyproject}"\n')
    (tmp_path / "src" / "navkit" / "__init__.py").write_text(f'__version__ = "{init}"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n" + changelog)
    if notes is not None:
        (tmp_path / "docs" / "releases").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "releases" / f"{pyproject}.md").write_text(notes)
    return tmp_path


def test_a_ready_release_has_no_problems(tmp_path: Path) -> None:
    assert rel.problems(_repo(tmp_path), "v1.2.3") == []


def test_a_tag_that_disagrees_with_the_package_version_is_refused(tmp_path: Path) -> None:
    assert any("v1.2.4" in p and "pyproject" in p for p in rel.problems(_repo(tmp_path), "v1.2.4"))


def test_a_tag_that_is_not_a_version_is_refused(tmp_path: Path) -> None:
    assert any("not of the form" in p for p in rel.problems(_repo(tmp_path), "release-1"))
    assert any("not of the form" in p for p in rel.problems(_repo(tmp_path), "v1.2"))


def test_the_two_package_versions_must_agree(tmp_path: Path) -> None:
    problems = rel.problems(_repo(tmp_path, init="1.2.0"), "v1.2.3")
    assert any("navkit.__version__" in p for p in problems)


def test_missing_notes_are_refused(tmp_path: Path) -> None:
    assert any("does not exist" in p for p in rel.problems(_repo(tmp_path, notes=None), "v1.2.3"))


def test_notes_that_still_say_draft_are_refused(tmp_path: Path) -> None:
    draft = "# navkit 1.2.3\n\n> **DRAFT.** Not released.\n"
    assert any("DRAFT" in p for p in rel.problems(_repo(tmp_path, notes=draft), "v1.2.3"))


def test_a_draft_word_elsewhere_in_the_notes_is_not_the_banner(tmp_path: Path) -> None:
    notes = "# navkit 1.2.3\n\nThe release notes were a DRAFT once.\n"
    assert rel.problems(_repo(tmp_path, notes=notes), "v1.2.3") == []


def test_a_changelog_without_the_version_is_refused(tmp_path: Path) -> None:
    assert any("CHANGELOG" in p for p in rel.problems(_repo(tmp_path, changelog="## [1.2.2] - 2026\n"), "v1.2.3"))


def test_a_dry_run_reports_without_failing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path, notes=None)
    assert rel.main(["--dry-run", "--root", str(root)]) == 0
    assert "would block a release" in capsys.readouterr().err


def test_a_tag_run_fails_on_any_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path, notes=None)
    assert rel.main(["--tag", "v1.2.3", "--root", str(root)]) == 1
    assert "release check failed" in capsys.readouterr().err


def test_a_ready_tag_run_succeeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert rel.main(["--tag", "v1.2.3", "--root", str(_repo(tmp_path))]) == 0
    assert "release check OK" in capsys.readouterr().out


def test_one_mode_is_required() -> None:
    with pytest.raises(SystemExit):
        rel.main([])


def test_the_real_repository_reports_what_blocks_a_release_today() -> None:
    """Not a gate on the real repository: it states that the checker reads the real files."""
    pyproject, init = rel.package_versions(ROOT)
    assert pyproject == init
