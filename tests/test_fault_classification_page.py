"""docs/fault_classification.md against the committed CSV. The sweep takes half an hour, so CI does not rerun it."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import fault_classification as fc
from navkit.types import GnssFix, ImuSample

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "fault_classification.md"
CSV = ROOT / "docs" / "data" / "fault_classification.csv"


@pytest.fixture(scope="module")
def rows():
    return fc.rows_from_csv(CSV)


@pytest.fixture(scope="module")
def scored(rows):
    return fc.with_predictions(rows)


@pytest.fixture(scope="module")
def scored_five(rows):
    return fc.with_predictions(rows, fc.BASE_FEATURES)


def _share(scored, pick, called):
    sel = [r for r in scored if pick(r)]
    return sum(r["predicted"] == called(r) for r in sel) / len(sel)


def test_blocks_match_csv(rows):
    text = PAGE.read_text(encoding="utf-8")
    for fn in fc.BLOCKS.values():
        assert fn(rows) in text


def test_multipath_is_called_correctly_at_every_size(scored, scored_five):
    for sc in (scored, scored_five):
        for level in (3.0, 10.0, 30.0):
            pick = lambda r, level=level: r["kind"] == "multipath" and float(r["level"]) == level  # noqa: E731
            assert _share(sc, pick, lambda r: "multipath") >= 0.95
    assert _share(scored, lambda r: r["cls"] == "multipath", lambda r: "multipath") >= 0.985


def test_the_control_false_alarm_rate_is_not_zero_and_did_not_improve(scored, scored_five):
    far = {
        n: 1.0 - _share(sc, lambda r: r["cls"] == "control", lambda r: "control")
        for n, sc in (("five", scored_five), ("ten", scored))
    }
    assert 0.0 < far["five"] < 0.2 and 0.0 < far["ten"] < 0.2
    assert far["ten"] >= far["five"]


def test_the_added_features_raise_spoofing_from_under_half_to_about_three_quarters(scored, scored_five):
    spoof = lambda r: r["cls"] == "spoofing"  # noqa: E731
    assert _share(scored_five, spoof, lambda r: "spoofing") < 0.5
    assert 0.7 < _share(scored, spoof, lambda r: "spoofing") < 0.8


def test_the_added_features_fix_the_ten_metre_step(scored, scored_five):
    pick = lambda r: r["kind"] == "step" and float(r["level"]) == 10.0  # noqa: E731
    assert _share(scored_five, pick, lambda r: "multipath") > 0.5
    assert _share(scored, pick, lambda r: "multipath") == 0.0
    step = lambda r: r["kind"] == "step"  # noqa: E731
    assert _share(scored, step, lambda r: "spoofing") == 1.0


def test_a_five_metre_ramp_goes_from_missed_to_mostly_called(scored, scored_five):
    pick = lambda r: r["kind"] == "ramp" and float(r["level"]) == 5.0  # noqa: E731
    assert _share(scored_five, pick, lambda r: "spoofing") < 0.15
    assert _share(scored, pick, lambda r: "spoofing") > 0.85


def test_weak_faults_are_often_missed_and_strong_ones_are_not(scored):
    def detected(kind, level):
        pick = lambda r: r["kind"] == kind and float(r["level"]) == level  # noqa: E731
        return 1.0 - _share(scored, pick, lambda r: "control")

    assert detected("ramp", 0.5) < 0.5
    assert 0.6 < detected("accel_bias", 0.2) < 0.7
    for kind, level in (("multipath", 3.0), ("step", 10.0), ("step", 50.0), ("accel_bias", 1.0), ("gyro_bias", 0.05)):
        assert detected(kind, level) >= 0.95


def test_large_degradation_is_called_degradation(scored):
    weak = {("accel_bias", 0.2), ("gyro_bias", 0.01)}
    pick = lambda r: r["cls"] == "degradation" and (r["kind"], float(r["level"])) not in weak  # noqa: E731
    assert _share(scored, pick, lambda r: "degradation") >= 0.98


def test_the_track_a_exit_test_is_not_met(scored):
    recalls = [_share(scored, lambda r, c=c: r["cls"] == c, lambda r, c=c: c) for c in fc.FAULT_CLASSES]
    far = 1.0 - _share(scored, lambda r: r["cls"] == "control", lambda r: "control")
    assert not (min(recalls) >= 0.95 and far == 0.0)


def test_predictions_never_use_the_held_out_sequence(rows):
    one = fc.cross_validate(rows)
    assert len(one) == len(rows)
    assert set(one) <= set(fc.CLASSES)


def test_the_new_features_separate_a_persistent_offset_from_white_noise():
    rng = np.random.default_rng(1)
    s = np.eye(3)
    bias = [(34.0, np.zeros(3), np.zeros(3)), (54.0, np.zeros(3), np.zeros(3))]
    noise = [(35.0 + i * 0.2, rng.standard_normal(3) * 5.0, s) for i in range(100)]
    offset = [(35.0 + i * 0.2, np.array([10.0, 0.0, 0.0]) + rng.standard_normal(3), s) for i in range(100)]
    fn, fo = fc.features(noise, bias, 35.0), fc.features(offset, bias, 35.0)
    assert fn is not None and fo is not None
    assert fn["ac1"] < 0.2 < 0.8 < fo["ac1"]
    assert fn["axis_conc"] < 0.5 < fo["axis_conc"]


def test_a_transient_decays_and_a_constant_offset_does_not():
    s = np.eye(3)
    bias = [(34.0, np.zeros(3), np.zeros(3)), (54.0, np.zeros(3), np.zeros(3))]
    transient = [(35.0 + i * 0.2, np.array([10.0 * np.exp(-i * 0.2), 0.0, 0.0]), s) for i in range(100)]
    constant = [(35.0 + i * 0.2, np.array([10.0, 0.0, 0.0]), s) for i in range(100)]
    ft, fk = fc.features(transient, bias, 35.0), fc.features(constant, bias, 35.0)
    assert ft is not None and fk is not None
    assert ft["decay"] < 0.1 and fk["decay"] == pytest.approx(1.0)


def test_the_tree_separates_a_toy_problem():
    x = np.array([[0.0], [1.0], [10.0], [11.0]])
    y = np.array([0, 0, 1, 1])
    tree = fc.fit_tree(x, y, np.ones(4), 2)
    assert [fc.predict(tree, row) for row in x] == [0, 0, 1, 1]


def test_features_need_enough_fixes():
    s = np.eye(3)
    few = [(36.0 + i * 0.2, np.zeros(3), s) for i in range(5)]
    assert fc.features(few, [(35.0, np.zeros(3), np.zeros(3))], 35.0) is None


def test_features_of_unit_noise_are_near_the_healthy_values():
    rng = np.random.default_rng(0)
    s = np.eye(3)
    inn = [(35.0 + i * 0.2, rng.standard_normal(3), s) for i in range(100)]
    bias = [(34.0, np.zeros(3), np.zeros(3)), (54.0, np.zeros(3), np.zeros(3))]
    f = fc.features(inn, bias, 35.0)
    assert f is not None
    assert 0.7 < f["nis"] < 1.3 and f["bias_accel"] == 0.0 and f["mean_shift"] < 5.0


def _streams():
    t = np.arange(0.0, 100.0, 0.2)
    return GnssFix(t=t, positions=np.zeros((len(t), 3))), ImuSample(
        t=np.arange(0.0, 100.0, 0.01), accel=np.zeros((10000, 3)), gyro=np.zeros((10000, 3))
    )


@pytest.mark.parametrize(
    ("kind", "level"), [("multipath", 5.0), ("ramp", 1.0), ("step", 20.0), ("accel_bias", 0.5), ("gyro_bias", 0.1)]
)
def test_each_fault_changes_the_right_stream(kind, level):
    gnss, imu = _streams()
    opts = ee.RunOptions(fault=(kind, 35.0, level))
    out = ee._inject_fault(imu, gnss, opts, 0.0)
    if kind in ("accel_bias", "gyro_bias"):
        changed = out.accel if kind == "accel_bias" else out.gyro
        assert np.allclose(changed[out.t < 35.0], 0.0)
        assert np.linalg.norm(changed[-1]) == pytest.approx(level)
        assert not np.any(gnss.positions)
    else:
        assert np.any(gnss.positions)
        assert not np.any(gnss.positions[gnss.t < 35.0])
        assert np.allclose(out.accel, 0.0)


def test_multipath_ends_after_its_window():
    gnss, imu = _streams()
    ee._inject_fault(imu, gnss, ee.RunOptions(fault=("multipath", 35.0, 5.0)), 0.0)
    assert not np.any(gnss.positions[gnss.t >= 35.0 + ee.FAULT_WINDOW_S])


def test_unknown_fault_is_rejected_and_serialised_only_when_set():
    gnss, imu = _streams()
    with pytest.raises(ee.SequenceError):
        ee._inject_fault(imu, gnss, ee.RunOptions(fault=("bogus", 1.0, 1.0)), 0.0)
    assert "fault" not in ee.RunOptions().as_dict()
    assert ee.RunOptions(fault=("ramp", 35.0, 1.0)).as_dict()["fault"] == ["ramp", 35.0, 1.0]


def test_run_case_on_a_synthetic_sequence(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    control = fc.run_case(seq, "walk10", 0, fc.CASES[0])
    noisy = fc.run_case(seq, "walk10", 0, ("multipath", "multipath", 30.0))
    assert control is not None and noisy is not None
    assert noisy["nis"] > 5.0 * control["nis"]
    short = tmp_path / "short"
    ee.write_fixture(short, "MH_01_easy", duration_s=40.0, seed=1)
    assert fc.run_case(ee.load_sequence(short, "MH_01_easy"), "walk10", 0, fc.CASES[1]) is None


def test_sweep_rows_runs_every_case(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "CASES", fc.CASES[:2])
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=80.0, seed=1)
    got = fc.sweep_rows("euroc", tmp_path, seeds=1)
    assert [r["kind"] for r in got] == ["none", "multipath"]


def test_model_text_names_both_stages(rows):
    text = fc.model_text(rows)
    assert "stage 1" in text and "stage 2" in text


def test_csv_round_trip_cli_rebuild_and_missing_markers(rows, tmp_path, capsys):
    out = tmp_path / "again.csv"
    fc.write_csv(out, rows)
    assert fc.rows_from_csv(out) == rows
    assert fc.main(["--from-csv", str(out), "--markdown"]) == 0
    assert "True class" in capsys.readouterr().out
    page = tmp_path / "p.md"
    page.write_text("no markers\n", encoding="utf-8")
    assert fc.main(["--from-csv", str(out), "--page", str(page)]) == 1
