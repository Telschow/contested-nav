"""The SRS acceptance status rows for AC-01 to AC-04 agree with the committed benchmark snapshot."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_srs_status", ROOT / "scripts" / "check_srs_status.py")
assert spec is not None and spec.loader is not None
status = importlib.util.module_from_spec(spec)
sys.modules["check_srs_status"] = status
spec.loader.exec_module(status)

CASES = json.loads(status.GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]


def test_the_real_srs_matches_the_benchmark():
    assert status.check() == 0


def test_a_flipped_verdict_is_reported(tmp_path, capsys):
    text = status.SRS_PATH.read_text(encoding="utf-8")
    edited = text.replace("| 17.568 m | **FAIL** |", "| 17.568 m | **PASS** |")
    assert edited != text
    srs = tmp_path / "srs.md"
    srs.write_text(edited, encoding="utf-8")
    assert status.check(srs) == 1
    assert "AC-01" in capsys.readouterr().err


def test_a_stale_measured_value_is_reported(tmp_path):
    text = status.SRS_PATH.read_text(encoding="utf-8")
    srs = tmp_path / "srs.md"
    srs.write_text(text.replace("17.568 m", "2.322 m"), encoding="utf-8")
    assert status.check(srs) == 1


def test_the_tally_follows_the_verdicts():
    text = status.SRS_PATH.read_text(encoding="utf-8")
    start, end = status.section(text)
    rows = [line for line in text[start:end].split("\n") if line.startswith("| AC-")]
    passes = sum("**PASS" in r for r in rows)
    fails = sum("**FAIL" in r for r in rows)
    assert f"**{passes} pass, {fails} fail.**" in text


def test_ac04_says_the_statistic_is_pending():
    assert "statistic pending maintainer decision" in status.rows(CASES)["AC-04"]


def test_a_passing_benchmark_gives_a_pass_row():
    cases = json.loads(json.dumps(CASES))
    cases["outage_visual"]["headline"]["ate_rmse_m"] = 1.0
    assert status.rows(cases)["AC-01"].endswith("| **PASS** |")
