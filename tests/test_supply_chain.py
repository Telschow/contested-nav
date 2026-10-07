"""The supply-chain claims in ADR-0011 are properties of the files, so they are tested."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
SHA = re.compile(r"^[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _uses(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "uses" and isinstance(v, str):
                found.append(v)
            else:
                found.extend(_uses(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_uses(v))
    return found


def test_there_are_workflows_to_check() -> None:
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "release.yml", "security.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_third_party_action_is_pinned_to_a_commit_sha(path: Path) -> None:
    for ref in _uses(_load(path)):
        if ref.startswith("./"):
            continue
        name, _, version = ref.partition("@")
        assert SHA.match(version), f"{path.name}: {name} is pinned to {version!r}, not a commit SHA"


def test_the_dockerfile_base_image_is_pinned_by_digest() -> None:
    froms = re.findall(r"^FROM\s+(\S+)", (ROOT / "Dockerfile").read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert froms
    for image in froms:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{image} is not pinned by digest"


def test_dependabot_keeps_the_base_image_and_the_actions_current() -> None:
    cfg = _load(ROOT / ".github" / "dependabot.yml")
    assert {u["package-ecosystem"] for u in cfg["updates"]} >= {"docker", "github-actions", "pip"}


# --- the release workflow -------------------------------------------------------------------

RELEASE = _load(ROOT / ".github" / "workflows" / "release.yml")


def test_a_release_starts_only_from_a_version_tag_or_a_manual_dry_run() -> None:
    on = RELEASE.get("on", RELEASE.get(True))
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}


def test_the_workflow_is_read_only_by_default_and_only_the_release_job_can_write() -> None:
    assert RELEASE["permissions"] == {"contents": "read"}
    assert "permissions" not in RELEASE["jobs"]["build"]
    perms = RELEASE["jobs"]["release"]["permissions"]
    assert perms["contents"] == "write" and perms["id-token"] == "write" and perms["attestations"] == "write"


def test_the_release_job_runs_only_for_a_tag_so_a_manual_run_publishes_and_attests_nothing() -> None:
    assert RELEASE["jobs"]["release"]["if"] == "github.ref_type == 'tag'"
    assert RELEASE["jobs"]["release"]["needs"] == "build"
    build_uses = " ".join(_uses(RELEASE["jobs"]["build"]))
    assert "attest" not in build_uses


def test_the_attestation_covers_the_wheel_and_the_sdist() -> None:
    steps = RELEASE["jobs"]["release"]["steps"]
    attest = next(s for s in steps if "attest-build-provenance" in s.get("uses", ""))
    assert "*.whl" in attest["with"]["subject-path"] and "*.tar.gz" in attest["with"]["subject-path"]


def test_the_release_is_created_as_a_draft_from_the_versioned_notes() -> None:
    steps = RELEASE["jobs"]["release"]["steps"]
    create = next(s for s in steps if "gh release create" in s.get("run", ""))
    assert "--draft" in create["run"]
    assert "--notes-file" in create["run"] and "docs/releases/" in create["run"]
    assert "--verify-tag" in create["run"]


def test_the_build_checks_the_release_before_it_builds() -> None:
    steps = RELEASE["jobs"]["build"]["steps"]
    names = [s.get("name", "") for s in steps]
    check = next(i for i, n in enumerate(names) if "agree" in n)
    build = next(i for i, n in enumerate(names) if n.startswith("Build the sdist"))
    assert check < build
    assert "check_release.py --tag" in steps[check]["run"] and "--dry-run" in steps[check]["run"]
