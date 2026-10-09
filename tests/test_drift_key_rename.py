"""The anchor drift strengths are named per square-root second, and the old per-second names still work (P5-05).

The value in the process noise is ``sigma^2 dt``, so the variance grows by ``sigma^2`` each second and the unit is
m per square-root second. The old names (``anchor_pos_drift_sigma_m_s``, ``anchor_rot_drift_sigma_deg_s``) said per
second. They are accepted, with a warning, by the constructor and as estimator keys.
"""

from __future__ import annotations

import dataclasses
import warnings

import numpy as np
import pytest

from navkit.benchmark import _eskf_config
from navkit.degrade.config import scenario_from_dict
from navkit.estimators.eskf import _IDX_CP, _IDX_CT, ErrorStateKalmanFilter, EskfConfig
from navkit.io.imu import ImuNoiseModel

NEW_POS, NEW_ROT = "anchor_pos_drift_sigma_m_sqrt_s", "anchor_rot_drift_sigma_deg_sqrt_s"
OLD_POS, OLD_ROT = "anchor_pos_drift_sigma_m_s", "anchor_rot_drift_sigma_deg_s"


def _cfg(**kw) -> EskfConfig:
    return EskfConfig(imu_noise=ImuNoiseModel(), **kw)


def test_the_new_names_are_the_fields_and_the_only_serialised_keys():
    c = _cfg(**{NEW_POS: 0.02, NEW_ROT: 0.5})
    assert (getattr(c, NEW_POS), getattr(c, NEW_ROT)) == (0.02, 0.5)
    d = c.as_dict()
    assert d[NEW_POS] == 0.02 and d[NEW_ROT] == 0.5 and OLD_POS not in d and OLD_ROT not in d
    assert {f.name for f in dataclasses.fields(EskfConfig)} >= {NEW_POS, NEW_ROT}
    assert not {OLD_POS, OLD_ROT} & {f.name for f in dataclasses.fields(EskfConfig)}


def test_the_old_constructor_names_still_work_and_warn():
    with pytest.warns(DeprecationWarning, match=f"{OLD_POS} is deprecated; use {NEW_POS}"):
        c = _cfg(**{OLD_POS: 0.03})
    assert getattr(c, NEW_POS) == 0.03
    with pytest.warns(DeprecationWarning, match=OLD_ROT):
        c = _cfg(**{OLD_ROT: 0.11})
    assert getattr(c, NEW_ROT) == 0.11


def test_an_old_and_a_new_name_with_different_values_are_refused_and_with_equal_values_are_accepted():
    with pytest.raises(TypeError, match="different values"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _cfg(**{NEW_POS: 0.1, OLD_POS: 0.2})
    with pytest.warns(DeprecationWarning):
        assert getattr(_cfg(**{NEW_POS: 0.1, OLD_POS: 0.1}), NEW_POS) == 0.1


def test_replace_works_without_a_warning_and_can_change_the_new_value():
    c = _cfg(**{NEW_POS: 0.02})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert getattr(dataclasses.replace(c, **{NEW_POS: 0.5}), NEW_POS) == 0.5
        assert getattr(dataclasses.replace(c), NEW_POS) == 0.02


def test_the_old_names_give_the_same_process_noise_as_the_new_ones():
    def q(cfg: EskfConfig) -> np.ndarray:
        return ErrorStateKalmanFilter(cfg)._process_noise(0.01)

    with pytest.warns(DeprecationWarning):
        old = q(_cfg(vision_enabled=True, **{OLD_POS: 0.05, OLD_ROT: 0.2}))
    new = q(_cfg(vision_enabled=True, **{NEW_POS: 0.05, NEW_ROT: 0.2}))
    assert np.array_equal(old, new)
    assert new[_IDX_CP, _IDX_CP][0, 0] == pytest.approx(0.05**2 * 0.01)
    assert new[_IDX_CT, _IDX_CT][0, 0] == pytest.approx(np.deg2rad(0.2) ** 2 * 0.01)


def test_the_unit_is_per_square_root_second():
    """Doubling the step doubles the variance added, so the strength has the unit of a random walk, m / sqrt(s)."""
    f = ErrorStateKalmanFilter(_cfg(**{NEW_POS: 0.1}))
    ratio = f._process_noise(0.02)[_IDX_CP, _IDX_CP][0, 0] / f._process_noise(0.01)[_IDX_CP, _IDX_CP][0, 0]
    assert ratio == pytest.approx(2.0)


def _scenario():
    s = scenario_from_dict({"name": "s"})
    assert s is not None
    return s


def test_the_estimator_keys_accept_the_new_names_the_old_names_with_a_warning_and_refuse_a_conflict():
    s = _scenario()
    assert getattr(_eskf_config(s, {NEW_POS: 0.04}), NEW_POS) == 0.04
    with pytest.warns(DeprecationWarning, match="estimator key"):
        assert getattr(_eskf_config(s, {OLD_ROT: 0.3}), NEW_ROT) == 0.3
    with pytest.raises(ValueError, match="different values"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _eskf_config(s, {NEW_POS: 0.1, OLD_POS: 0.2})
    assert getattr(_eskf_config(s, {}), NEW_POS) == 0.0


def test_reading_an_old_attribute_name_gives_none_and_is_documented_as_so():
    """The constructor takes the old name and does not store it, so a read returns the dataclass default."""
    assert getattr(_cfg(**{NEW_POS: 0.02}), OLD_POS) is None
