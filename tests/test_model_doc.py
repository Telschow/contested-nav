"""``docs/MODEL.md`` must describe the code that exists.

The page documents every configuration key with a unit and a default, and the result
JSON with its keys. A reference that can drift is worse than none, because it is read
as authoritative. These tests fail when a field is added without a row, a row outlives
its field, a default changes without the page, or a unit cell is left empty. The
failure message prints the row to paste.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "MODEL.md"
GOLDEN = Path(__file__).resolve().parent / "golden" / "benchmark.json"

#: Documented dataclass to the module that defines it.
CONFIG_CLASSES = {
    "EskfConfig": "navkit.estimators.eskf",
    "FdirConfig": "navkit.fdir.config",
    "ImuNoiseModel": "navkit.io.imu",
    "SyntheticConfig": "navkit.synthetic",
    "GnssConfig": "navkit.sensors.models",
    "VisionConfig": "navkit.sensors.models",
    "CameraDropConfig": "navkit.degrade.config",
    "Outage": "navkit.degrade.config",
    "Scenario": "navkit.degrade.config",
}


def _table_after(marker: str) -> list[list[str]]:
    """Cells of the first table after ``<!-- marker -->``, without header and rule."""
    lines = DOC.read_text().splitlines()
    start = lines.index(f"<!-- {marker} -->")
    rows = []
    for line in lines[start + 1 :]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[2:]


def _default_text(field: dataclasses.Field) -> str:
    if field.default is not dataclasses.MISSING:
        return repr(field.default)
    if field.default_factory is not dataclasses.MISSING:
        return "factory"
    return "required"


@pytest.mark.parametrize("name", sorted(CONFIG_CLASSES))
def test_every_config_key_is_documented_with_its_default_and_a_unit(name: str) -> None:
    cls = getattr(importlib.import_module(CONFIG_CLASSES[name]), name)
    rows = {r[0].strip("`"): r for r in _table_after(f"table:{name}")}
    fields = {f.name: f for f in dataclasses.fields(cls)}

    missing = sorted(set(fields) - set(rows))
    stale = sorted(set(rows) - set(fields))
    assert not missing, (
        f"{name}: no row in docs/MODEL.md for {missing}; add `| \\`key\\` | unit | \\`default\\` | meaning |`"
    )
    assert not stale, f"{name}: docs/MODEL.md documents keys that no longer exist: {stale}"

    for key, field in fields.items():
        _, unit, default, meaning = rows[key][:4]
        assert unit, f"{name}.{key}: empty unit"
        assert meaning, f"{name}.{key}: empty meaning"
        assert default == f"`{_default_text(field)}`", (
            f"{name}.{key}: doc says {default}, code says `{_default_text(field)}`"
        )


def _documented_keys(marker: str) -> set[str]:
    keys: set[str] = set()
    for row in _table_after(marker):
        keys.update(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", row[0]))
    return keys


def test_the_result_top_level_keys_match_the_golden_snapshot() -> None:
    golden = json.loads(GOLDEN.read_text())
    # The snapshot omits `environment` on purpose: it describes the machine, not the filter.
    assert _documented_keys("keys:top") == set(golden) | {"environment"}


def test_the_case_record_keys_match_the_golden_snapshot() -> None:
    golden = json.loads(GOLDEN.read_text())
    # `outage_visual` has every optional section. `runtime_s` is a timing key the snapshot strips.
    assert _documented_keys("keys:case") == set(golden["cases"]["outage_visual"]) | {"runtime_s"}


def test_the_page_has_no_em_dashes() -> None:
    assert "—" not in DOC.read_text()
