"""The two attribution variants (issue #243), on a fixture written here: each changes only what it names.

The variants are declared in code before any run. The real UrbanNav data is not needed (S2); the existing variants
must give the rows they gave before, which a hash of the synthetic rows pins.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from navkit import euroc_eval as ee
from navkit import urbannav_run as ur
from navkit.types import GnssFix, interpolate_trajectory

#: sha256 prefixes of ``json.dumps(rows_for(...))`` for seed 0 on the fixture below, taken before the variants existed.
GOLDEN = {
    "declared": "ebefa94b6f72cbc7",
    "per_fix": "7e1090ae0ac17e40",
    "oracle_attitude": "d2a82d1a8cdc0c9e",
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("fixture")
    ee.write_fixture(root, "MH_01_easy", duration_s=60.0, seed=1)
    seq = ee.load_sequence(root, "MH_01_easy")
    t = np.arange(float(seq.imu.t[0]) + 1.0, float(seq.imu.t[-1]) - 1.0, 0.5)
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
    t0 = float(seq.imu.t[0])
    return seq, gnss, [(t0 + 25.0, t0 + 35.0)], info


def _digest(rows):
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


@pytest.mark.parametrize("variant", sorted(GOLDEN))
def test_the_existing_variants_give_the_rows_they_gave_before(world, variant):
    seq, gnss, spans, info = world
    rows = ur.rows_for("syn", [ur.run_once(seq, gnss, spans, info, 0, variant)])
    assert _digest(rows) == GOLDEN[variant]


def test_the_attribution_variants_are_declared_apart_from_the_committed_ones():
    for v in ur.ATTRIBUTION_VARIANTS:
        assert f"variant: {v}" in ur.ATTRIBUTION_DECLARED
        assert v not in ur.ALL_VARIANTS
        assert f"variant: {v}" not in ur.DECLARED
    assert "reference" in ur.ATTRIBUTION_DECLARED["variant: start_attitude"][1]
    assert "static start estimate" in ur.ATTRIBUTION_DECLARED["variant: held_gyro_bias"][0]
    assert ur.variants_for([(1.0, 2.0)]) == ur.ALL_VARIANTS
    assert ur.variants_for([]) == ur.VARIANTS
    assert ur.variants_for([], attribution=True) == ur.variants_for([(1.0, 2.0)], attribution=True)


def test_the_start_attitude_variant_replaces_only_the_start_rotation(world):
    seq, _, _, _ = world
    opts = ee.RunOptions(seed=3, init_bias="static")
    cfg = ee.EskfConfig(imu_noise=seq.noise)
    t0 = float(seq.imu.t[0])
    original = ee._initial_state
    declared = ee._initial_state(seq, opts, cfg, t0, "static", seq.imu)
    with ur.reference_start_attitude(seq):
        better = ee._initial_state(seq, opts, cfg, t0, "static", seq.imu)
    assert ee._initial_state is original
    ref_r = interpolate_trajectory(seq.truth, np.array([t0])).rotations[0]
    assert not np.allclose(declared.R, ref_r)
    np.testing.assert_allclose(better.R, ref_r)
    for name in ("p", "v", "b_a", "b_g"):
        np.testing.assert_array_equal(getattr(better, name), getattr(declared, name))


def test_the_start_attitude_patch_is_removed_even_when_the_run_fails(world):
    seq, _, _, _ = world
    original = ee._initial_state
    with pytest.raises(RuntimeError), ur.reference_start_attitude(seq):
        raise RuntimeError("boom")
    assert ee._initial_state is original


def test_the_held_variant_changes_only_the_gyro_bias_walk(world):
    seq, *_ = world
    held = ur.with_held_gyro_bias(seq)
    assert held.noise.gyro_bias_rw == 0.0
    assert seq.noise.gyro_bias_rw > 0.0
    assert held.imu is seq.imu and held.truth is seq.truth
    for name in ("gyro_noise_density", "accel_noise_density", "accel_bias_rw", "gyro_bias_sigma", "accel_bias_sigma"):
        assert getattr(held.noise, name) == getattr(seq.noise, name)


def test_the_held_variant_keeps_the_gyro_bias_and_still_estimates_the_accelerometer_bias(world):
    seq, gnss, _, _ = world
    opts = ee.RunOptions(gnss_sigma_m=1.0, init_bias="static")

    def biases(s):
        log: list = []
        ee.run_sequence(s, opts, bias_out=log, gnss_override=gnss)
        return np.array([b_g for _, b_g, _ in log]), np.array([b_a for _, _, b_a in log])

    g_free, _ = biases(seq)
    g_held, a_held = biases(ur.with_held_gyro_bias(seq))
    assert np.ptp(g_held, axis=0).max() == 0.0
    assert np.ptp(g_free, axis=0).max() > 0.0
    assert np.ptp(a_held, axis=0).max() > 0.0


@pytest.mark.parametrize("variant", ur.ATTRIBUTION_VARIANTS)
@pytest.mark.parametrize("outage", [True, False])
def test_each_variant_is_reported_with_effective_sample_sizes_with_or_without_an_outage(world, variant, outage):
    seq, gnss, spans, info = world
    rows = ur.rows_for("syn", [ur.run_once(seq, gnss, spans if outage else [], info, 0, variant)])
    got = {r["quantity"]: r["value"] for r in rows}
    assert set(got) == {k for k, _, _ in ur.ATTRIBUTION_QUANTITIES}
    assert float(got["att_nees_ess"]) >= 1.0 and float(got["hor_nees_ess"]) >= 1.0
    assert {r["variant"] for r in rows} == {variant}
    assert not ur.is_aided(rows)
