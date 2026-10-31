"""The multipath signature function, and the study page against its committed CSVs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import multipath_study as ms
from navkit.fault_classification import features
from navkit.fdir import multipath as mp

pytestmark = pytest.mark.docs_only

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "multipath.md"


@pytest.fixture(scope="module")
def floor():
    return ms.CSV_TABLE.read(ROOT / "docs" / "data" / "multipath_detector.csv")


@pytest.fixture(scope="module")
def fresh():
    return ms.CSV_TABLE.read(ROOT / "docs" / "data" / "multipath_fresh.csv")


def _window(scale=1.0, offset=0.0, n=100, seed=0):
    rng = np.random.default_rng(seed)
    s = np.eye(3)
    return [(35.0 + i * 0.2, rng.standard_normal(3) * scale + np.array([offset, 0.0, 0.0]), s) for i in range(n)]


def test_white_noise_of_large_size_is_multipath():
    sig = mp.signature(_window(scale=5.0))
    assert sig is not None and sig.multipath and sig.specific and sig.sensitive


def test_healthy_noise_is_not_multipath():
    sig = mp.signature(_window(scale=1.0))
    assert sig is not None and not sig.sensitive and not sig.specific


def test_a_persistent_offset_is_not_multipath_however_large():
    sig = mp.signature(_window(scale=1.0, offset=10.0))
    assert sig is not None and sig.nis > mp.NIS_MIN_SPECIFIC and sig.ac1 > mp.AC1_MAX and not sig.multipath


def test_a_short_window_gives_no_call():
    assert mp.signature(_window(n=5)) is None
    assert mp.is_multipath(_window(n=5)) is False


def test_the_two_rules_differ_in_the_nis_they_need():
    assert mp.call(3.0, 0.0, "sensitive") and not mp.call(3.0, 0.0, "specific")
    assert mp.call(7.0, 0.0, "specific") and not mp.call(7.0, 0.9, "specific")
    with pytest.raises(ValueError):
        mp.call(3.0, 0.0, "bogus")
    assert mp.is_multipath(_window(scale=2.0), "sensitive") and not mp.is_multipath(_window(scale=2.0), "specific")


def test_statistics_agree_with_the_classification_study_features():
    inn = _window(scale=3.0, seed=4)
    bias = [(34.0, np.zeros(3), np.zeros(3)), (54.0, np.zeros(3), np.zeros(3))]
    f = features(inn, bias, 35.0)
    sig = mp.signature(inn)
    assert f is not None and sig is not None
    assert sig.nis == pytest.approx(f["nis"]) and sig.ac1 == pytest.approx(f["ac1"])


def test_page_blocks_match_the_csvs(floor, fresh):
    text = PAGE.read_text(encoding="utf-8")
    for fn in ms.BLOCKS.values():
        assert fn(floor, fresh) in text


def test_the_criteria_were_met_by_the_specific_rule_only(fresh):
    res = ms.criteria_results(fresh)
    assert res["specific"]["met"] and not res["sensitive"]["met"]
    assert res["specific"]["recall"] == 1.0 and res["specific"]["false_call_rate"] == 0.0
    assert res["sensitive"]["false_call_rate"] > ms.CRITERIA["false_call_rate_other"]


def test_the_criteria_are_the_ones_written_before_the_runs():
    assert ms.CRITERIA == {"recall_at_3m_and_above": 0.95, "false_call_rate_other": 0.02}


def test_no_control_run_in_any_set_is_called_multipath(floor, fresh):
    controls = [r for r in floor + fresh + ms.confirm_rows() if r["kind"] == "none"]
    assert len(controls) == 136
    assert not any(ms.called(r, rule) for r in controls for rule in mp.RULES)


def test_the_specific_rule_floor(floor, fresh):
    def share(rows, level):
        return ms._share([r for r in rows if r["kind"] == "multipath" and float(r["level"]) == level], "specific")

    assert share(floor, 0.5) == 0.0 and share(floor, 1.0) == 0.0 and share(floor, 1.5) < 0.1
    assert 0.6 < share(fresh, 2.0) < 0.7
    assert share(fresh, 3.0) == 1.0 and share(fresh, 5.0) == 1.0


def test_the_sensitive_rule_calls_about_two_thirds_of_the_five_metre_steps(fresh):
    sel = [r for r in fresh if r["kind"] == "step" and float(r["level"]) == 5.0]
    assert 0.6 < ms._share(sel, "sensitive") < 0.7 and ms._share(sel, "specific") == 0.0


@pytest.mark.rerun
def test_run_case_and_sweep_on_a_synthetic_sequence(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    noisy = ms.run_case(seq, "walk10", 0, "multipath", 30.0)
    control = ms.run_case(seq, "walk10", 0, "none", 0.0)
    assert noisy is not None and control is not None
    assert noisy["nis"] > 5.0 * control["nis"]
    got = ms.sweep_rows("euroc", tmp_path, (("none", 0.0), ("multipath", 30.0)), (1,))
    assert [r["kind"] for r in got] == ["none", "multipath"]
    short = tmp_path / "s"
    ee.write_fixture(short, "MH_01_easy", duration_s=40.0, seed=1)
    assert ms.run_case(ee.load_sequence(short, "MH_01_easy"), "walk10", 0, "none", 0.0) is None
    assert ms.floor_cases()[0] == ("none", 0.0)


def test_csv_round_trip_cli_and_missing_markers(floor, tmp_path, capsys):
    out = tmp_path / "again.csv"
    ms.CSV_TABLE.write(out, floor)
    assert ms.CSV_TABLE.read(out) == [{k: r[k] for k in ms.CSV_TABLE.header} for r in floor]
    assert ms.main(["--markdown"]) == 0
    assert "Specific rule" in capsys.readouterr().out
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert ms.main(["--page", str(page)]) == 1
