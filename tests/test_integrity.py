"""The integrity status record of ADR-0035: the usable rule on every state, and the runner's emission."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import numpy.linalg as la
import pytest

from navkit import integrity as ig
from navkit.degrade.config import Outage
from navkit.degrade.inject import apply_gnss_outage
from navkit.estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from navkit.fdir.nis_monitor import NisWindowMonitor
from navkit.io.imu import ImuNoiseModel
from navkit.sensors.models import GnssConfig, VisionConfig, gnss_fixes, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_imu, synthetic_trajectory

# ------------------------------------------------------------------ NIS state


def monitor_with(outcomes: dict[str, list[bool]]) -> NisWindowMonitor:
    m = NisWindowMonitor()
    for channel, accepted in outcomes.items():
        for ok in accepted:
            m.add_sample(channel, 1.0 if ok else 50.0, ok)
    return m


def test_no_history_on_any_channel_is_unknown_and_not_monitored() -> None:
    assert ig.nis_state(NisWindowMonitor()) == (ig.NIS_UNKNOWN, False)


def test_history_without_a_run_of_rejections_is_ok_and_monitored() -> None:
    assert ig.nis_state(monitor_with({"gnss": [True, False, True, True]})) == (ig.NIS_OK, True)


def test_three_rejections_in_a_row_on_any_channel_is_diverging() -> None:
    m = monitor_with({"gnss": [True, True], "vision_trans": [True, False, False, False]})
    assert ig.nis_state(m) == (ig.NIS_DIVERGING, True)


def test_a_channel_cleared_of_history_is_not_monitored() -> None:
    m = monitor_with({"gnss": [True]})
    m.reset_channel("gnss")
    assert ig.nis_state(m) == (ig.NIS_UNKNOWN, False)


# ------------------------------------------------------------------ usable rule


@pytest.mark.parametrize(
    ("sigma_h", "sigma_v", "state", "aiding", "usable", "reason"),
    [
        (0.5, 0.5, ig.NIS_OK, ("gnss",), True, ig.REASON_OK),
        (0.5, 0.5, ig.NIS_UNKNOWN, (), True, ig.REASON_OK),  # GNSS denied, vision off: nothing could be checked
        (0.5, 0.5, ig.NIS_UNKNOWN, ("gnss",), True, ig.REASON_OK),
        (0.5, 0.5, ig.NIS_DIVERGING, ("gnss",), False, ig.REASON_NIS_DIVERGING),
        (0.5, 0.5, ig.NIS_OK, ("gnss", "vision"), False, ig.REASON_AIDING_NOT_CALIBRATED),
        (0.5, 0.5, ig.NIS_OK, ("vision",), False, ig.REASON_AIDING_NOT_CALIBRATED),
        (math.nan, 0.5, ig.NIS_OK, ("gnss",), False, ig.REASON_SIGMA_NOT_FINITE),
        (0.5, math.inf, ig.NIS_OK, ("gnss",), False, ig.REASON_SIGMA_NOT_FINITE),
    ],
)
def test_each_state_and_aiding_configuration_maps_to_the_documented_value(
    sigma_h: float, sigma_v: float, state: str, aiding: tuple[str, ...], usable: bool, reason: str
) -> None:
    assert ig.usable_rule(sigma_h, sigma_v, state, aiding) == (usable, reason)


def test_the_first_failing_condition_names_the_reason() -> None:
    assert ig.usable_rule(math.nan, 1.0, ig.NIS_DIVERGING, ("vision",))[1] == ig.REASON_SIGMA_NOT_FINITE
    assert ig.usable_rule(1.0, 1.0, ig.NIS_DIVERGING, ("vision",))[1] == ig.REASON_NIS_DIVERGING


def test_vision_is_usable_only_when_its_calibration_gate_was_passed() -> None:
    assert ig.usable_rule(1.0, 1.0, ig.NIS_OK, ("gnss", "vision"), frozenset({"vision"})) == (True, ig.REASON_OK)


def test_a_confidently_wrong_filter_that_passes_the_nis_check_is_still_not_usable_with_vision_on() -> None:
    m = monitor_with({"vision_trans": [True] * 10})  # innovations pulled toward the measurements: all accepted
    status = ig.make_status(5.0, (0.0, 0.0, 0.0), 0.01, 0.01, m, 2.0, ("gnss", "vision"))
    assert status.nis_state == ig.NIS_OK and not status.usable
    assert status.reason == ig.REASON_AIDING_NOT_CALIBRATED


def test_the_record_is_frozen_and_carries_the_schema_version() -> None:
    status = ig.make_status(0.0, (1, 2, 3), 1.0, 2.0, NisWindowMonitor(), 0.0, ("vision", "gnss"))
    assert status.schema_version == ig.SCHEMA_VERSION and status.aiding == ("gnss", "vision")
    with pytest.raises(AttributeError):
        status.usable = False  # type: ignore[misc]


def test_the_csv_has_one_row_per_epoch_with_the_documented_columns(tmp_path: Path) -> None:
    rows = [ig.make_status(t, (t, 0.0, 0.0), 1.0, 1.0, NisWindowMonitor(), t, ("gnss",)) for t in (0.0, 0.5)]
    out = tmp_path / "integrity.csv"
    ig.write_csv(out, rows)
    with out.open(newline="", encoding="utf-8") as fh:
        read = list(csv.DictReader(fh))
    assert tuple(read[0]) == ig.CSV_COLUMNS and len(read) == 2
    assert {r["schema_version"] for r in read} == {str(ig.SCHEMA_VERSION)}
    assert read[1]["aiding"] == "gnss" and read[1]["usable"] == "1" and read[1]["reason"] == "ok"


# ------------------------------------------------------------------ the runner

DURATION_S = 20.0
NOISE = ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)


@pytest.fixture(scope="module")
def truth():
    gt = synthetic_trajectory(SyntheticConfig(duration_s=DURATION_S, rate_hz=100.0))
    return gt.transformed(la.inv(gt.poses[0]))


@pytest.fixture(scope="module")
def imu():
    return synthetic_imu(SyntheticConfig(duration_s=DURATION_S, rate_hz=100.0), rate_hz=200.0)


def run(imu, truth, *, vision: bool, gnss_outage: Outage | None):
    cfg = EskfConfig(imu_noise=NOISE, gnss_position_sigma_m=0.1, initial_bias_sigma=0.01, vision_enabled=vision)
    fixes = gnss_fixes(truth, GnssConfig(sigma_m=0.1, rate_hz=5.0))
    if gnss_outage is not None:
        fixes = apply_gnss_outage(fixes, [gnss_outage], True)
    updates = visual_updates(truth, VisionConfig()) if vision else None
    return ErrorStateKalmanFilter(cfg).run(imu, gnss=fixes, vision=updates)


def test_the_runner_emits_one_record_per_epoch_in_time_order(imu, truth) -> None:
    records = run(imu, truth, vision=False, gnss_outage=None).trajectory.metadata["integrity"]
    assert len(records) == len(imu) and [r.t for r in records] == sorted(r.t for r in records)
    assert records[0].aiding == ("gnss",)


def test_gnss_aided_with_vision_off_is_usable_and_monitored_once_fixes_arrive(imu, truth) -> None:
    records = run(imu, truth, vision=False, gnss_outage=None).trajectory.metadata["integrity"]
    assert records[-1].usable and records[-1].monitored and records[-1].nis_state == ig.NIS_OK
    assert records[-1].seconds_since_absolute_fix < 1.0


def test_gnss_denied_with_vision_off_is_usable_and_not_monitored_with_a_growing_age(imu, truth) -> None:
    records = run(imu, truth, vision=False, gnss_outage=Outage(start_s=2.0, duration_s=DURATION_S)).trajectory.metadata[
        "integrity"
    ]
    last = records[-1]
    assert last.usable and last.reason == ig.REASON_OK
    assert last.seconds_since_absolute_fix > 10.0
    assert records[-1].sigma_h > records[0].sigma_h or math.isfinite(last.sigma_h)


def test_the_overconfident_single_anchor_control_is_not_usable_with_vision_on(imu, truth) -> None:
    records = run(imu, truth, vision=True, gnss_outage=Outage(start_s=2.0, duration_s=DURATION_S)).trajectory.metadata[
        "integrity"
    ]
    assert not records[-1].usable and records[-1].reason in {ig.REASON_AIDING_NOT_CALIBRATED, ig.REASON_NIS_DIVERGING}
    assert "vision" in records[-1].aiding


def test_the_age_counts_from_the_start_when_no_fix_was_ever_accepted(imu, truth) -> None:
    records = run(
        imu, truth, vision=False, gnss_outage=Outage(start_s=0.0, duration_s=DURATION_S + 1.0)
    ).trajectory.metadata["integrity"]
    assert records[-1].seconds_since_absolute_fix == pytest.approx(records[-1].t - records[0].t)


def test_sigma_is_the_claimed_standard_deviation_of_the_position(imu, truth) -> None:
    result = run(imu, truth, vision=False, gnss_outage=None)
    records = result.trajectory.metadata["integrity"]
    cov = result.position_cov[-1]
    assert records[-1].sigma_h == pytest.approx(math.sqrt((cov[0, 0] + cov[1, 1]) / 2.0))
    assert records[-1].sigma_v == pytest.approx(math.sqrt(cov[2, 2]))
    assert np.isfinite(records[-1].position).all()
