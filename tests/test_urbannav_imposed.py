"""Imposed outages on Deep-Urban-1 (issue #245): known answers on a synthetic fixture, and the committed CSVs."""

from __future__ import annotations

import csv
import hashlib
import itertools
from pathlib import Path

import numpy as np
import pytest

from navkit import urbannav_imposed as ui
from navkit.recorded import SequenceError
from navkit.types import GnssFix

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
CSVS = ("urbannav_data.csv", "urbannav_fix_errors.csv", "urbannav_run.csv")
#: sha256 prefix of the rows of each committed CSV, taken before this module existed.
GOLDEN_CSV = {
    "urbannav_data.csv": "e3b79616e8bc7416",
    "urbannav_fix_errors.csv": "f2816b4f29f72817",
    "urbannav_run.csv": "a1749a8a37c7af26",
}


def _fixes(n: int = 100) -> tuple[GnssFix, dict]:
    t = np.arange(n, dtype=float)
    gnss = GnssFix(t=t, positions=np.column_stack([t, 2 * t, 0 * t]), cov=np.full((n, 3), 4.0))
    info = {"sigma_h": 2.0, "fix_t": t, "fix_difference_m": t * 0.1, "fix_sigma_h_m": t + 1.0}
    return gnss, info


def test_the_outages_are_declared_in_code_with_a_reason_for_each():
    spans = ui.IMPOSED["deepurban1"]
    assert len(spans) >= 2
    for o in spans:
        assert o.start_s >= 0 and o.duration_s > 0 and o.reason
    ordered = sorted(spans, key=lambda o: o.start_s)
    for a, b in itertools.pairwise(ordered):
        assert a.start_s + a.duration_s < b.start_s


def test_the_fixes_inside_an_outage_are_removed_and_no_others():
    gnss, info = _fixes()
    out, out_info = ui.impose(gnss, info, [(10.0, 15.0), (50.0, 51.0)])
    removed = np.setdiff1d(gnss.t, out.t)
    np.testing.assert_array_equal(removed, [10, 11, 12, 13, 14, 50])  # start <= t < end
    keep = np.isin(gnss.t, out.t)
    np.testing.assert_array_equal(out.positions, gnss.positions[keep])
    np.testing.assert_array_equal(out.cov, gnss.cov[keep])
    np.testing.assert_array_equal(out_info["fix_t"], out.t)
    np.testing.assert_array_equal(out_info["fix_difference_m"], info["fix_difference_m"][keep])
    np.testing.assert_array_equal(out_info["fix_sigma_h_m"], info["fix_sigma_h_m"][keep])
    assert out_info["sigma_h"] == 2.0


def test_no_outage_leaves_the_fixes_unchanged_and_the_input_is_not_modified():
    gnss, info = _fixes()
    t_before = gnss.t.copy()
    out, _ = ui.impose(gnss, info, [])
    np.testing.assert_array_equal(out.t, gnss.t)
    ui.impose(gnss, info, [(0.0, 10.0)])
    np.testing.assert_array_equal(gnss.t, t_before)


def test_an_outage_that_removes_no_fix_is_an_error():
    gnss, info = _fixes(20)
    with pytest.raises(SequenceError):
        ui.impose(gnss, info, [(500.0, 10.0)])


def test_rows_are_named_apart_from_the_receivers_own_sequence():
    assert ui.row_sequence("deepurban1", ui.IMPOSED["deepurban1"][0]) != "deepurban1"
    names = {ui.row_sequence("deepurban1", o) for o in ui.IMPOSED["deepurban1"]}
    assert len(names) == len(ui.IMPOSED["deepurban1"])
    assert all(n.startswith("deepurban1_imposed") for n in names)


def test_the_docstring_states_its_scope():
    doc = ui.__doc__ or ""
    assert "one sequence" in doc and "one receiver" in doc
    assert "not the receiver's own" in doc


def test_the_oracle_variants_are_not_run():
    assert not set(ui.VARIANTS) & set(ui.ORACLE_VARIANTS)


def _digest(path: Path) -> str:
    with path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if "imposed" not in r["sequence"]]
    return hashlib.sha256(repr(rows).encode()).hexdigest()[:16]


@pytest.mark.parametrize("name", CSVS)
def test_existing_csv_rows_are_unchanged(name):
    assert _digest(DATA / name) == GOLDEN_CSV[name]


def test_the_run_gives_rows_under_the_imposed_name_on_a_fixture(tmp_path):
    from navkit import euroc_eval as ee

    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=60.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    t0 = float(seq.imu.t[0])
    t = np.arange(t0 + 1.0, float(seq.imu.t[-1]) - 1.0, 0.5)
    pos = np.column_stack([np.interp(t, seq.truth.t, seq.truth.positions[:, k]) for k in range(3)])
    gnss = GnssFix(t=t, positions=pos, cov=np.full((len(t), 3), 1.0))
    info = {
        "sigma_h": 1.0,
        "fix_difference_m": np.zeros(len(t)),
        "fix_sigma_h_m": np.ones(len(t)),
        "fix_t": t,
        "epochs_not_valid": 0,
        "fixes_variance_unusable": 0,
        "fixes_variance_below_floor": 0,
    }
    o = ui.Outage(start_s=25.0, duration_s=10.0, reason="test")
    rows = ui.rows_for_outage("syn", o, seq, gnss, [], info, seeds=(0,))
    assert {r["sequence"] for r in rows} == {ui.row_sequence("syn", o)}
    assert {r["variant"] for r in rows} == set(ui.VARIANTS)


def test_the_imposed_command_refuses_a_sequence_without_declared_outages(capsys):
    assert ui.main(["--sequence", "tunnel1"]) == 1
    assert "no imposed outages are declared" in capsys.readouterr().err
