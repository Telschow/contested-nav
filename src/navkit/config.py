"""Experiment configuration: loading, validation and reproducibility hashing.

A run is fully described by one YAML file: the dataset, the estimator, the
scenarios to replay, the quality thresholds and the output layout. The parsed
config carries a SHA-256 of its own canonical serialisation, which goes into
every result file, so a number in a report can always be traced back to the
exact configuration that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .degrade.config import ConfigError, Scenario, scenario_from_dict
from .eval.thresholds import ThresholdSet
from .io.imu import DEFAULT_NOISE

KNOWN_TOP_LEVEL = {
    "name",
    "description",
    "dataset",
    "estimator",
    "scenarios",
    "thresholds",
    "evaluation",
    "output",
    "seed",
}


@dataclass
class DatasetConfig:
    """Where the reference trajectory comes from."""

    kind: str = "synthetic"
    groundtruth_path: str | None = None
    groundtruth_format: str = "auto"
    imu_path: str | None = None
    imu_rate_hz: float = 200.0
    synthetic: dict[str, Any] = field(default_factory=dict)
    trim: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "groundtruth_path": self.groundtruth_path,
            "groundtruth_format": self.groundtruth_format,
            "imu_path": self.imu_path,
            "imu_rate_hz": self.imu_rate_hz,
            "synthetic": self.synthetic,
            "trim": self.trim,
        }


@dataclass
class EstimatorConfig:
    """Which baseline to run, and its tuning."""

    kind: str = "eskf"
    gnss_position_sigma_m: float = 0.8
    vision_rot_sigma_deg: float = 0.35
    vision_trans_sigma_m: float = 0.05
    gate_sigma: float = 5.0
    use_gnss: bool = True
    use_vision: bool = True
    initial_pos_sigma_m: float = 1.0
    initial_vel_sigma_m_s: float = 0.5
    initial_rot_sigma_deg: float = 2.0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class EvaluationConfig:
    """Which metrics to compute."""

    association: str = "interpolate"
    rpe_deltas: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"delta": 1.0, "unit": "s"},
            {"delta": 10.0, "unit": "s"},
            {"delta": 1.0, "unit": "m"},
            {"delta": 10.0, "unit": "m"},
        ]
    )
    alignment_variants: list[str] = field(default_factory=lambda: ["none", "rigid", "rigid_start", "similarity"])
    recovery_threshold_m: float = 0.25
    recovery_hold_s: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "association": self.association,
            "rpe_deltas": self.rpe_deltas,
            "alignment_variants": self.alignment_variants,
            "recovery_threshold_m": self.recovery_threshold_m,
            "recovery_hold_s": self.recovery_hold_s,
        }


@dataclass
class Config:
    """A complete experiment definition."""

    name: str = "experiment"
    description: str = ""
    seed: int = 0
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    estimator: EstimatorConfig = field(default_factory=EstimatorConfig)
    scenarios: list[Scenario] = field(default_factory=list)
    thresholds: ThresholdSet = field(default_factory=ThresholdSet)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    output_dir: str = "outputs"
    source_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- serialisation -------------------------------------------------------

    def canonical_dict(self) -> dict[str, Any]:
        # Keys must match KNOWN_TOP_LEVEL exactly, so that to_yaml() emits a
        # document load_config() accepts. Emitting a flat "output_dir" here
        # produced configs that could be written but not read back.
        return {
            "name": self.name,
            "description": self.description,
            "seed": self.seed,
            "dataset": self.dataset.as_dict(),
            "estimator": self.estimator.as_dict(),
            "thresholds": self.thresholds.as_dict(),
            "evaluation": self.evaluation.as_dict(),
            "output": {"dir": self.output_dir},
            "scenarios": [s.as_dict() for s in self.scenarios],
        }

    def config_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["config_hash"] = self.config_hash()
        d["source_path"] = self.source_path
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.canonical_dict(), sort_keys=False, default_flow_style=False)

    def scenario(self, name: str) -> Scenario:
        for s in self.scenarios:
            if s.name == name:
                return s
        raise KeyError(f"no scenario named {name!r}; have {[s.name for s in self.scenarios]}")


def load_config(path: str) -> Config:
    """Load and validate a YAML experiment configuration."""
    if not os.path.isfile(path):
        raise ConfigError([f"config file not found: {path}"])
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        raise ConfigError([f"{path}: file is empty"])
    if not isinstance(data, dict):
        raise ConfigError([f"{path}: top level must be a mapping"])
    problems: list[str] = []
    unknown = set(data) - KNOWN_TOP_LEVEL
    if unknown:
        problems.append(f"unknown top-level keys: {sorted(unknown)}")
    if not data.get("scenarios"):
        problems.append("config must define at least one entry under 'scenarios'")
    if problems:
        raise ConfigError(problems)

    ds_raw = data.get("dataset") or {}
    if not isinstance(ds_raw, dict):
        raise ConfigError(["dataset must be a mapping"])
    dataset = DatasetConfig(
        kind=str(ds_raw.get("kind", "synthetic")),
        groundtruth_path=ds_raw.get("groundtruth_path"),
        groundtruth_format=str(ds_raw.get("groundtruth_format", "auto")),
        imu_path=ds_raw.get("imu_path"),
        imu_rate_hz=float(ds_raw.get("imu_rate_hz", 200.0)),
        synthetic=dict(ds_raw.get("synthetic") or {}),
        trim={k: float(v) for k, v in (ds_raw.get("trim") or {}).items()},
    )
    if dataset.kind not in ("synthetic", "file"):
        problems.append(f"dataset.kind must be 'synthetic' or 'file', got {dataset.kind!r}")
    if dataset.kind == "file" and not dataset.groundtruth_path:
        problems.append("dataset.kind='file' requires dataset.groundtruth_path")
    if dataset.kind == "file" and dataset.groundtruth_path and not os.path.isfile(dataset.groundtruth_path):
        problems.append(f"dataset.groundtruth_path does not exist: {dataset.groundtruth_path}")
    if dataset.imu_path and not os.path.isfile(dataset.imu_path):
        problems.append(f"dataset.imu_path does not exist: {dataset.imu_path}")
    if dataset.imu_rate_hz <= 0:
        problems.append("dataset.imu_rate_hz must be > 0")
    if dataset.groundtruth_format not in ("auto", "tum", "euroc", "csv_xyz_qw", "euroc_txt"):
        problems.append(f"dataset.groundtruth_format unknown: {dataset.groundtruth_format}")

    est_raw = data.get("estimator") or {}
    estimator = EstimatorConfig(
        kind=str(est_raw.get("kind", "eskf")),
        gnss_position_sigma_m=float(est_raw.get("gnss_position_sigma_m", 0.8)),
        vision_rot_sigma_deg=float(est_raw.get("vision_rot_sigma_deg", 0.35)),
        vision_trans_sigma_m=float(est_raw.get("vision_trans_sigma_m", 0.05)),
        gate_sigma=float(est_raw.get("gate_sigma", 5.0)),
        use_gnss=bool(est_raw.get("use_gnss", True)),
        use_vision=bool(est_raw.get("use_vision", True)),
        initial_pos_sigma_m=float(est_raw.get("initial_pos_sigma_m", 1.0)),
        initial_vel_sigma_m_s=float(est_raw.get("initial_vel_sigma_m_s", 0.5)),
        initial_rot_sigma_deg=float(est_raw.get("initial_rot_sigma_deg", 2.0)),
    )
    if estimator.kind not in ("eskf", "dead_reckoning"):
        problems.append(f"estimator.kind must be 'eskf' or 'dead_reckoning', got {estimator.kind!r}")
    for key in (
        "gnss_position_sigma_m",
        "vision_rot_sigma_deg",
        "vision_trans_sigma_m",
        "initial_pos_sigma_m",
        "initial_vel_sigma_m_s",
        "initial_rot_sigma_deg",
    ):
        if getattr(estimator, key) <= 0.0:
            problems.append(f"estimator.{key} must be > 0, got {getattr(estimator, key)}")
    if estimator.gate_sigma < 0.0:
        problems.append("estimator.gate_sigma must be >= 0 (0 disables gating)")

    thr_raw = data.get("thresholds") or {}
    unknown_thr = set(thr_raw) - set(ThresholdSet().as_dict())
    if unknown_thr:
        problems.append(f"unknown threshold keys: {sorted(unknown_thr)}")
    thresholds = ThresholdSet(**{k: float(v) for k, v in thr_raw.items() if k in ThresholdSet().as_dict()})
    problems.extend(f"thresholds.{p}" for p in thresholds.violations())

    ev_raw = data.get("evaluation") or {}
    evaluation = EvaluationConfig(
        association=str(ev_raw.get("association", "interpolate")),
        rpe_deltas=list(ev_raw.get("rpe_deltas") or EvaluationConfig().rpe_deltas),
        alignment_variants=list(ev_raw.get("alignment_variants") or EvaluationConfig().alignment_variants),
        recovery_threshold_m=float(ev_raw.get("recovery_threshold_m", 0.25)),
        recovery_hold_s=float(ev_raw.get("recovery_hold_s", 1.0)),
    )
    if evaluation.association not in ("interpolate", "nearest"):
        problems.append(f"evaluation.association must be 'interpolate' or 'nearest', got {evaluation.association!r}")
    for variant in evaluation.alignment_variants:
        if variant not in ("none", "rigid", "rigid_start", "similarity"):
            problems.append(f"evaluation.alignment_variants contains unknown value {variant!r}")
    for d in evaluation.rpe_deltas:
        if not isinstance(d, dict) or "delta" not in d or "unit" not in d:
            problems.append("evaluation.rpe_deltas entries need 'delta' and 'unit'")
            continue
        if float(d["delta"]) <= 0.0:
            problems.append(f"evaluation.rpe_deltas delta must be > 0, got {d['delta']}")
        if d["unit"] not in ("s", "m"):
            problems.append(f"evaluation.rpe_deltas unit must be 's' or 'm', got {d['unit']!r}")

    out_raw = data.get("output") or {}
    if not isinstance(out_raw, dict):
        problems.append("output must be a mapping")
        out_raw = {}
    unknown_out = set(out_raw) - {"dir", "plots", "trajectories"}
    if unknown_out:
        problems.append(f"unknown output keys: {sorted(unknown_out)}")

    scenarios: list[Scenario] = []
    scen_raw = data["scenarios"]
    if isinstance(scen_raw, dict):
        items = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in scen_raw.items()]
    elif isinstance(scen_raw, list):
        items = scen_raw
    else:
        raise ConfigError(["scenarios must be a list or a mapping of name -> settings"])
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"scenarios[{i}] must be a mapping")
            continue
        problems.extend(f"scenarios[{i}]." + p for p in _scenario_problems(item))
        scenarios.append(scenario_from_dict(item, []))

    names = [s.name for s in scenarios]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        problems.append(f"duplicate scenario names: {sorted(dupes)}")
    if "normal" not in names:
        problems.append(
            "scenarios must include a 'normal' baseline: a degraded run without a baseline "
            "is a number without a reference"
        )

    if problems:
        raise ConfigError(problems)

    return Config(
        name=str(data.get("name", "experiment")),
        description=str(data.get("description", "")),
        seed=int(data.get("seed", 0)),
        dataset=dataset,
        estimator=estimator,
        scenarios=scenarios,
        thresholds=thresholds,
        evaluation=evaluation,
        output_dir=str(out_raw.get("dir", "outputs")),
        source_path=os.path.abspath(path),
        raw=data,
    )


def _scenario_problems(item: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    scenario_from_dict(item, problems)
    return problems


def default_noise_dict() -> dict[str, float]:
    return DEFAULT_NOISE.as_dict()


def validate_config_dict(data: dict[str, Any]) -> list[str]:
    """Validate an in-memory config mapping. Used by the tests."""
    problems: list[str] = []
    unknown = set(data) - KNOWN_TOP_LEVEL
    if unknown:
        problems.append(f"unknown top-level keys: {sorted(unknown)}")
    for item in data.get("scenarios") or []:
        problems.extend(_scenario_problems(item))
    return problems
