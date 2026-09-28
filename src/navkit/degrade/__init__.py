"""Degradation injection: scenario schema, validation and deterministic noise."""

from .config import (
    VALID_SCENARIOS,
    CameraDropConfig,
    ConfigError,
    Outage,
    Scenario,
    scenario_from_dict,
)
from .inject import (
    InjectedStreams,
    apply_camera_drop,
    apply_gnss_outage,
    apply_imu_outage,
    config_hash,
    inject,
    mark_outages,
)

__all__ = [
    "VALID_SCENARIOS",
    "CameraDropConfig",
    "ConfigError",
    "Outage",
    "Scenario",
    "scenario_from_dict",
    "InjectedStreams",
    "apply_camera_drop",
    "apply_gnss_outage",
    "apply_imu_outage",
    "config_hash",
    "inject",
    "mark_outages",
]
