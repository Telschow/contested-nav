"""The committed OpenCode template: shape checks that do not need OpenCode installed.

OpenCode 1.19.0 drops unknown keys inside a ``provider`` entry without a warning, so a
``"disabled": true`` there leaves the provider switched on. ``disabled_providers`` is the
supported switch.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "opencode.example.json").read_text(encoding="utf-8"))


def test_default_model_names_a_declared_provider_and_model() -> None:
    provider, _, model = CONFIG["model"].partition("/")
    assert model in CONFIG["provider"][provider]["models"]


def test_providers_are_disabled_with_the_supported_key() -> None:
    for name, entry in CONFIG["provider"].items():
        assert "disabled" not in entry, f"{name}: use disabled_providers instead"
    assert isinstance(CONFIG.get("disabled_providers", []), list)


def test_api_key_comes_from_the_environment() -> None:
    for name, entry in CONFIG["provider"].items():
        key = entry.get("options", {}).get("apiKey")
        if key is not None:
            assert key.startswith("{env:") and key.endswith("}"), name
