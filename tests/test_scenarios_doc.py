"""``docs/scenarios.md`` lists every benchmark case, and only those."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_the_scenarios_page_has_a_section_for_each_case_and_nothing_else() -> None:
    cases = list(yaml.safe_load((ROOT / "configs" / "benchmark.yaml").read_text())["cases"])
    page = (ROOT / "docs" / "scenarios.md").read_text()
    assert re.findall(r"^## (\S+)$", page, flags=re.MULTILINE) == cases


def test_each_section_carries_the_description_from_the_config() -> None:
    cases = yaml.safe_load((ROOT / "configs" / "benchmark.yaml").read_text())["cases"]
    page = (ROOT / "docs" / "scenarios.md").read_text()
    for name, case in cases.items():
        assert " ".join(case["description"].split()) in page, name
