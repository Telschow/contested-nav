"""Every benchmark scenario goes through the injection layer (ADR-0012, issue 56)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from navkit.benchmark import default_config_path, run_case
from navkit.fault_matrix import BY_ID

ROOT = Path(__file__).resolve().parent.parent


def _doc() -> dict[str, Any]:
    return yaml.safe_load(default_config_path().read_text())


def test_every_benchmark_case_goes_through_the_injection_layer() -> None:
    """The runner used to skip the layer for a scenario with no outage or camera drop, which ran four
    cases with a noiseless IMU because the layer is what adds the IMU noise."""
    doc = _doc()
    for name, case in doc["cases"].items():
        record = run_case(name, case, doc["defaults"], seed=0)
        assert record["manifest"], f"{name} skipped the injection layer"


def test_a_scenario_that_sets_only_a_time_offset_changes_the_result() -> None:
    doc = _doc()
    case, _ = BY_ID["gnss_time_offset"].build(doc["cases"]["gnss_only"], 0.5)
    base = run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=0)
    offset = run_case("gnss_only", case, doc["defaults"], seed=0)
    assert offset["headline"]["ate_rmse_m"] != base["headline"]["ate_rmse_m"]


def test_a_scenario_that_sets_only_an_imu_noise_scale_changes_the_data() -> None:
    """Dead reckoning has no filter, so its error moves only if the IMU data does."""
    doc = _doc()
    case = doc["cases"]["dead_reckoning"]
    scaled = {**case, "scenario": {**case["scenario"], "imu_noise_scale": 0.0}}
    noisy = run_case("dead_reckoning", case, doc["defaults"], seed=0)["headline"]["ate_rmse_m"]
    clean = run_case("dead_reckoning", scaled, doc["defaults"], seed=0)["headline"]["ate_rmse_m"]
    assert clean < noisy


def test_the_dead_reckoning_control_starts_from_the_true_state_and_still_drifts() -> None:
    """The control starts at the true first pose, so its first-epoch error is zero, and the error then grows."""
    doc = _doc()
    record = run_case("dead_reckoning", doc["cases"]["dead_reckoning"], doc["defaults"], seed=0)
    position = record["ate"]["none"]["position_m"]
    assert position["min"] == pytest.approx(0.0, abs=1e-12)
    assert position["max"] > position["median"] > 0.0
    assert record["drift"]["growth"]["slope_m_per_s"] > 0.0
    assert record["drift"]["final_drift_pct_time"] > 0.0


def test_a_noiseless_imu_is_still_available_by_asking_for_it() -> None:
    """Scale 0 removes the injected noise and bias, so the control with the true start is nearly exact."""
    doc = _doc()
    case = doc["cases"]["dead_reckoning"]
    scaled = {**case, "scenario": {**case["scenario"], "imu_noise_scale": 0.0}}
    noisy = run_case("dead_reckoning", case, doc["defaults"], seed=0)["headline"]["ate_rmse_m"]
    clean = run_case("dead_reckoning", scaled, doc["defaults"], seed=0)["headline"]["ate_rmse_m"]
    assert clean < 0.1 * noisy
