"""The RICE table in ``docs/prioritisation.md`` is generated, and its arithmetic is right."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "rice_table.py"


def _load():
    spec = importlib.util.spec_from_file_location("rice_table", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rice_table"] = module
    spec.loader.exec_module(module)
    return module


rice = _load()


def _item(**kw):
    base = {
        "id": "X",
        "title": "t",
        "reach": 4,
        "impact": 2,
        "confidence": 50,
        "effort_days": 4,
        "source": "s",
        "depends_on": "",
        "rationale": "r",
    }
    base.update(kw)
    return rice.Item(**base)


def test_the_score_is_reach_times_impact_times_confidence_over_effort() -> None:
    assert _item().score == pytest.approx(4 * 2 * 0.5 / 4)


def test_a_tie_goes_to_the_cheaper_item_then_the_id() -> None:
    a = _item(id="A", reach=2, effort_days=2)
    b = _item(id="B", reach=4, effort_days=4)
    c = _item(id="C", reach=2, effort_days=2)
    assert [i.id for i in rice.ranked([b, c, a])] == ["A", "C", "B"]


def test_the_committed_document_matches_the_csv() -> None:
    doc = (ROOT / "docs" / "prioritisation.md").read_text(encoding="utf-8")
    assert rice.splice(doc, rice.generated_block(rice.load())) == doc


def test_the_inputs_use_the_documented_scales_and_unique_ids() -> None:
    with (ROOT / "docs" / "product_management" / "rice.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        assert 1 <= float(r["reach"]) <= 10, r["id"]
        assert float(r["impact"]) in rice.IMPACT_SCALE, r["id"]
        assert float(r["confidence"]) in rice.CONFIDENCE_SCALE, r["id"]
        assert float(r["effort_days"]) > 0, r["id"]
    known = set(ids)
    for r in rows:
        for dep in filter(None, (d.strip() for d in r["depends_on"].split(";"))):
            assert dep in known, f"{r['id']} depends on unknown {dep}"


def test_sensitivity_flags_a_ranking_that_a_small_error_would_flip() -> None:
    items = [_item(id=f"I{k}", reach=10, impact=3, confidence=100, effort_days=1) for k in range(2)]
    # Third place and the first item outside the top three are one effort step apart.
    items += [_item(id="C", effort_days=4), _item(id="D", effort_days=4.4)]
    changed = rice.sensitivity(items)["changed"]
    assert any(entry.startswith("D ") for entry in changed)


def test_sensitivity_reports_a_robust_ranking_as_unchanged() -> None:
    items = [_item(id=f"I{k}", reach=10, impact=3, confidence=100, effort_days=1) for k in range(3)]
    items += [_item(id=f"J{k}", reach=1, impact=0.25, confidence=50, effort_days=30) for k in range(3)]
    assert rice.sensitivity(items)["changed"] == []


def test_a_document_without_markers_is_refused() -> None:
    with pytest.raises(ValueError):
        rice.splice("no markers here", "x")
