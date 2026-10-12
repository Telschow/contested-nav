"""The named assumption for the opt-in clone's visual noise (ADR-0024)."""

from __future__ import annotations

import pytest

from navkit import euroc_eval as ee
from navkit import vo_error as ve
from navkit.benchmark import _eskf_config
from navkit.degrade.config import Scenario
from navkit.estimators.eskf import VISION_NOISE_PRESETS

CLONE = {"vision_fuse": True, "vision_model": "clone"}


def _scenario() -> Scenario:
    return Scenario(name="s")


def test_the_preset_is_four_times_the_noise_the_wider_measurement_found_to_hold():
    assert VISION_NOISE_PRESETS == {"measured-front-end": 4.0}
    scales = {name: scale for name, _, scale in ve.WIDE_SCALES}
    assert VISION_NOISE_PRESETS["measured-front-end"] == scales["clone x4"]


def test_the_preset_equals_the_number_it_names():
    named = _eskf_config(_scenario(), {**CLONE, "vision_noise_preset": "measured-front-end"})
    numeric = _eskf_config(_scenario(), {**CLONE, "vision_sigma_scale": 4.0})
    assert named.as_dict() == numeric.as_dict()
    plain = _eskf_config(_scenario(), CLONE)
    assert named.vision_trans_sigma_m == pytest.approx(4.0 * plain.vision_trans_sigma_m)
    assert named.vision_rot_sigma_deg == pytest.approx(4.0 * plain.vision_rot_sigma_deg)


def test_without_the_preset_nothing_changes():
    base = _eskf_config(_scenario(), CLONE)
    assert base.vision_trans_sigma_m == _scenario().vision.trans_sigma_m


def test_a_preset_is_refused_when_it_is_unknown_doubled_or_not_for_the_clone():
    with pytest.raises(ValueError, match="unknown vision_noise_preset"):
        _eskf_config(_scenario(), {**CLONE, "vision_noise_preset": "bogus"})
    with pytest.raises(ValueError, match="not both"):
        _eskf_config(_scenario(), {**CLONE, "vision_noise_preset": "measured-front-end", "vision_sigma_scale": 2.0})
    with pytest.raises(ValueError, match="stochastic clone"):
        _eskf_config(_scenario(), {"vision_fuse": True, "vision_noise_preset": "measured-front-end"})


def test_recorded_data_options_resolve_the_preset(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    common = {"seed": 0, "vision": "clone", "outages": ((10.0, 10.0),)}
    named = ee.run_sequence(seq, ee.RunOptions(vision_noise_preset="measured-front-end", **common))
    numeric = ee.run_sequence(seq, ee.RunOptions(vision_noise_scale=4.0, **common))
    keys = ("vision_trans_sigma_m", "vision_rot_sigma_deg")
    assert {k: named["estimator"][k] for k in keys} == {k: numeric["estimator"][k] for k in keys}
    assert named["options"]["vision"]["preset"] == "measured-front-end"
    assert "preset" not in numeric["options"]["vision"]


def test_recorded_data_options_refuse_a_doubled_unknown_or_misplaced_preset(tmp_path):
    ee.write_fixture(tmp_path, "MH_01_easy", duration_s=40.0, seed=1)
    seq = ee.load_sequence(tmp_path, "MH_01_easy")
    with pytest.raises(ee.SequenceError, match="not both"):
        ee.run_sequence(
            seq, ee.RunOptions(vision="clone", vision_noise_preset="measured-front-end", vision_noise_scale=2.0)
        )
    with pytest.raises(ee.SequenceError, match="unknown vision_noise_preset"):
        ee.run_sequence(seq, ee.RunOptions(vision="clone", vision_noise_preset="bogus"))
    with pytest.raises(ee.SequenceError, match="stochastic clone"):
        ee.run_sequence(seq, ee.RunOptions(vision="anchor", vision_noise_preset="measured-front-end"))
