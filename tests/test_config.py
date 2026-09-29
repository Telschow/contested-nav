"""Tests for experiment configuration loading and validation.

``config.py`` was at 0% coverage: no config file had ever been loaded by the
test suite. That is the module every published number flows through, so the
tests here are mostly about *rejection* — a config that silently accepts a
nonsensical value is how an outage of 45 s quietly becomes an outage of 10 s
and still reports a plausible-looking metric.
"""

import re
import textwrap

import pytest
import yaml

from navkit.config import (
    Config,
    DatasetConfig,
    EstimatorConfig,
    EvaluationConfig,
    default_noise_dict,
    load_config,
    validate_config_dict,
)
from navkit.degrade.config import ConfigError, Outage

VALID = {
    "name": "unit",
    "seed": 7,
    "scenarios": [
        {"name": "normal"},
        {"name": "denied", "gnss_outages": [{"start_s": 5.0, "duration_s": 15.0}]},
    ],
}


def write(tmp_path, data, name="cfg.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data))
    return str(path)


def write_text(tmp_path, text, name="cfg.yaml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_valid_config_loads_with_every_field(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.name == "unit"
    assert cfg.seed == 7
    assert [s.name for s in cfg.scenarios] == ["normal", "denied"]
    assert cfg.scenarios[1].gnss_outages[0].duration_s == 15.0
    assert cfg.source_path.endswith("cfg.yaml")


def test_defaults_are_applied_to_absent_sections(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.dataset.kind == "synthetic"
    assert cfg.dataset.imu_rate_hz == 200.0
    assert cfg.estimator.kind == "eskf"
    assert cfg.estimator.gate_sigma == 5.0
    assert cfg.evaluation.association == "interpolate"
    assert cfg.output_dir == "outputs"
    assert cfg.thresholds.position_rmse_m == 0.5


def test_scenarios_may_be_a_mapping_of_name_to_settings(tmp_path):
    data = {"scenarios": {"normal": None, "denied": {"gnss_outages": []}}}
    cfg = load_config(write(tmp_path, data))
    assert sorted(s.name for s in cfg.scenarios) == ["denied", "normal"]


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(str(tmp_path / "nope.yaml"))


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="file is empty"):
        load_config(write_text(tmp_path, ""))


def test_non_mapping_top_level_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_config(write_text(tmp_path, "- a\n- b\n"))


def test_unknown_top_level_key_is_rejected(tmp_path):
    data = dict(VALID, typo_scenario="oops")
    with pytest.raises(ConfigError, match="unknown top-level keys"):
        load_config(write(tmp_path, data))


def test_config_without_scenarios_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="at least one entry under 'scenarios'"):
        load_config(write(tmp_path, {"name": "x", "scenarios": []}))


def test_scenarios_must_be_a_list_or_mapping(tmp_path):
    with pytest.raises(ConfigError, match="must be a list or a mapping"):
        load_config(write(tmp_path, {"scenarios": "normal"}))


def test_scenario_without_normal_baseline_is_rejected(tmp_path):
    """A degraded run with no reference has nothing to be measured against."""
    data = {"scenarios": [{"name": "denied", "gnss_outages": []}]}
    with pytest.raises(ConfigError, match="must include a 'normal' baseline"):
        load_config(write(tmp_path, data))


def test_duplicate_scenario_names_are_rejected(tmp_path):
    data = {"scenarios": [{"name": "normal"}, {"name": "normal"}]}
    with pytest.raises(ConfigError, match="duplicate scenario names"):
        load_config(write(tmp_path, data))


# --- dataset -----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["synthetic", "file"])
def test_dataset_kind_accepts_documented_values(tmp_path, kind):
    data = dict(VALID, dataset={"kind": kind})
    if kind == "file":
        gt = tmp_path / "gt.txt"
        gt.write_text("0 0 0 0 1 0 0 0\n")
        data["dataset"]["groundtruth_path"] = str(gt)
    cfg = load_config(write(tmp_path, data))
    assert cfg.dataset.kind == kind


def test_unknown_dataset_kind_is_rejected(tmp_path):
    data = dict(VALID, dataset={"kind": "kafka"})
    with pytest.raises(ConfigError, match=re.escape("dataset.kind must be")):
        load_config(write(tmp_path, data))


def test_file_dataset_requires_a_groundtruth_path(tmp_path):
    data = dict(VALID, dataset={"kind": "file"})
    with pytest.raises(ConfigError, match=re.escape("requires dataset.groundtruth_path")):
        load_config(write(tmp_path, data))


def test_missing_groundtruth_file_is_rejected(tmp_path):
    data = dict(VALID, dataset={"kind": "file", "groundtruth_path": "/no/such/gt.txt"})
    with pytest.raises(ConfigError, match="groundtruth_path does not exist"):
        load_config(write(tmp_path, data))


def test_missing_imu_file_is_rejected(tmp_path):
    data = dict(VALID, dataset={"imu_path": "/no/such/imu.csv"})
    with pytest.raises(ConfigError, match="imu_path does not exist"):
        load_config(write(tmp_path, data))


def test_non_positive_imu_rate_is_rejected(tmp_path):
    data = dict(VALID, dataset={"imu_rate_hz": 0})
    with pytest.raises(ConfigError, match="imu_rate_hz must be > 0"):
        load_config(write(tmp_path, data))


def test_unknown_groundtruth_format_is_rejected(tmp_path):
    data = dict(VALID, dataset={"groundtruth_format": "rosbag"})
    with pytest.raises(ConfigError, match="groundtruth_format unknown"):
        load_config(write(tmp_path, data))


def test_dataset_must_be_a_mapping(tmp_path):
    with pytest.raises(ConfigError, match="dataset must be a mapping"):
        load_config(write(tmp_path, dict(VALID, dataset=["a"])))


def test_trim_values_are_coerced_to_float(tmp_path):
    data = dict(VALID, dataset={"trim": {"start_s": "1", "end_s": "9"}})
    cfg = load_config(write(tmp_path, data))
    assert cfg.dataset.trim == {"start_s": 1.0, "end_s": 9.0}


# --- estimator ---------------------------------------------------------------


def test_unknown_estimator_kind_is_rejected(tmp_path):
    data = dict(VALID, estimator={"kind": "particle_filter"})
    with pytest.raises(ConfigError, match=re.escape("estimator.kind must be")):
        load_config(write(tmp_path, data))


def test_dead_reckoning_estimator_is_selectable(tmp_path):
    cfg = load_config(write(tmp_path, dict(VALID, estimator={"kind": "dead_reckoning"})))
    assert cfg.estimator.kind == "dead_reckoning"


@pytest.mark.parametrize(
    "key",
    [
        "gnss_position_sigma_m",
        "vision_rot_sigma_deg",
        "vision_trans_sigma_m",
        "initial_pos_sigma_m",
        "initial_vel_sigma_m_s",
        "initial_rot_sigma_deg",
    ],
)
def test_non_positive_estimator_sigmas_are_rejected(tmp_path, key):
    """A zero sigma is an infinite-precision prior, which is never intended."""
    data = dict(VALID, estimator={key: 0.0})
    with pytest.raises(ConfigError, match=f"estimator.{key} must be > 0"):
        load_config(write(tmp_path, data))


def test_negative_gate_sigma_is_rejected(tmp_path):
    data = dict(VALID, estimator={"gate_sigma": -1.0})
    with pytest.raises(ConfigError, match="gate_sigma must be >= 0"):
        load_config(write(tmp_path, data))


def test_zero_gate_sigma_is_allowed_to_disable_gating(tmp_path):
    cfg = load_config(write(tmp_path, dict(VALID, estimator={"gate_sigma": 0.0})))
    assert cfg.estimator.gate_sigma == 0.0


def test_estimator_flags_are_coerced_to_bool(tmp_path):
    cfg = load_config(write(tmp_path, dict(VALID, estimator={"use_gnss": 0, "use_vision": 0})))
    assert cfg.estimator.use_gnss is False
    assert cfg.estimator.use_vision is False


# --- thresholds --------------------------------------------------------------


def test_unknown_threshold_key_is_rejected(tmp_path):
    data = dict(VALID, thresholds={"position_rmse": 1.0})
    with pytest.raises(ConfigError, match="unknown threshold keys"):
        load_config(write(tmp_path, data))


def test_threshold_violations_are_reported_with_a_prefix(tmp_path):
    data = dict(VALID, thresholds={"sustained_error_m": 2.0, "position_peak_m": 1.0})
    with pytest.raises(ConfigError, match=re.escape("thresholds.position_peak_m must be >= sustained_error_m")):
        load_config(write(tmp_path, data))


def test_all_threshold_violations_are_collected_not_just_the_first(tmp_path):
    """Validation returns every problem, so one round trip is enough to fix a file."""
    data = dict(VALID, thresholds={"sustained_error_m": 0.0, "min_duration_s": 0.0})
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, data))
    joined = " ".join(exc.value.problems)
    assert "sustained_error_m must be > 0" in joined
    assert "min_duration_s must be > 0" in joined


# --- evaluation --------------------------------------------------------------


def test_unknown_association_is_rejected(tmp_path):
    data = dict(VALID, evaluation={"association": "spline"})
    with pytest.raises(ConfigError, match="association must be"):
        load_config(write(tmp_path, data))


def test_unknown_alignment_variant_is_rejected(tmp_path):
    data = dict(VALID, evaluation={"alignment_variants": ["none", "umeyama7"]})
    with pytest.raises(ConfigError, match="alignment_variants contains unknown value"):
        load_config(write(tmp_path, data))


def test_rpe_delta_missing_fields_is_rejected(tmp_path):
    data = dict(VALID, evaluation={"rpe_deltas": [{"delta": 1.0}]})
    with pytest.raises(ConfigError, match="rpe_deltas entries need 'delta' and 'unit'"):
        load_config(write(tmp_path, data))


def test_rpe_delta_non_positive_is_rejected(tmp_path):
    data = dict(VALID, evaluation={"rpe_deltas": [{"delta": 0.0, "unit": "s"}]})
    with pytest.raises(ConfigError, match="rpe_deltas delta must be > 0"):
        load_config(write(tmp_path, data))


def test_rpe_delta_bad_unit_is_rejected(tmp_path):
    data = dict(VALID, evaluation={"rpe_deltas": [{"delta": 1.0, "unit": "furlong"}]})
    with pytest.raises(ConfigError, match="rpe_deltas unit must be"):
        load_config(write(tmp_path, data))


# --- output ------------------------------------------------------------------


def test_unknown_output_key_is_rejected(tmp_path):
    data = dict(VALID, output={"dir": "out", "nonsense": 1})
    with pytest.raises(ConfigError, match="unknown output keys"):
        load_config(write(tmp_path, data))


def test_output_dir_is_honoured(tmp_path):
    cfg = load_config(write(tmp_path, dict(VALID, output={"dir": "results"})))
    assert cfg.output_dir == "results"


# --- serialisation and hashing -----------------------------------------------


def test_config_hash_is_stable_across_loads(tmp_path):
    a = load_config(write(tmp_path, VALID, "a.yaml")).config_hash()
    b = load_config(write(tmp_path, VALID, "b.yaml")).config_hash()
    assert a == b, "hash must depend on content only, not on file path"


def test_config_hash_changes_when_a_number_changes(tmp_path):
    a = load_config(write(tmp_path, VALID, "a.yaml")).config_hash()
    b = load_config(write(tmp_path, dict(VALID, estimator={"gnss_position_sigma_m": 0.9}), "b.yaml")).config_hash()
    assert a != b


def test_canonical_dict_omits_source_path(tmp_path):
    d = load_config(write(tmp_path, VALID)).canonical_dict()
    assert "source_path" not in d
    assert "config_hash" not in d


def test_as_dict_adds_hash_and_source(tmp_path):
    d = load_config(write(tmp_path, VALID)).as_dict()
    assert len(d["config_hash"]) == 16
    assert d["source_path"].endswith("cfg.yaml")


def test_to_yaml_round_trips_through_load_config(tmp_path):
    original = load_config(write(tmp_path, VALID))
    out = tmp_path / "again.yaml"
    out.write_text(original.to_yaml())
    again = load_config(str(out))
    assert again.config_hash() == original.config_hash()


def test_to_yaml_emits_block_style_for_non_empty_collections(tmp_path):
    text = load_config(write(tmp_path, VALID)).to_yaml()
    assert "scenarios:" in text
    assert "\n- " in text, "scenario list should be block style, not inline flow"


def test_raw_payload_is_retained_but_hidden_from_repr(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.raw["seed"] == 7
    assert "raw=" not in repr(cfg)


# --- lookup helpers ----------------------------------------------------------


def test_scenario_lookup_by_name(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.scenario("denied").name == "denied"


def test_scenario_lookup_failure_lists_available_names(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    with pytest.raises(KeyError, match="no scenario named"):
        cfg.scenario("ghost")


def test_default_noise_dict_is_populated():
    d = default_noise_dict()
    assert d
    assert all(isinstance(v, float) for v in d.values())


def test_validate_config_dict_flags_unknown_keys():
    assert validate_config_dict({"bogus": 1}) == ["unknown top-level keys: ['bogus']"]


def test_validate_config_dict_flags_bad_scenarios():
    problems = validate_config_dict(
        {"scenarios": [{"name": "normal", "gnss_outages": [{"start_s": -1, "duration_s": 5}]}]}
    )
    assert any("gnss_outages" in p for p in problems)


def test_validate_config_dict_passes_a_clean_mapping():
    assert validate_config_dict(VALID) == []


def test_validate_config_dict_flags_a_misspelled_camera_drop_key():
    """The audit's finding #2, as a regression test.

    `configs/benchmark.yaml` asked for `fraction: 0.3`, the field is
    `drop_fraction`, and the unknown key was discarded silently -- so the
    degraded-camera case ran at the 0.2 default while five documents described
    a 30% burst and tagged it measured. A config parser that cannot tell a typo
    from an absent key selects a different experiment without complaint, which
    is why this asserts the *plain* spelling is flagged below.
    """
    problems = validate_config_dict({"scenarios": [{"name": "degraded", "camera_drop": {"fraction": 0.3}}]})
    assert any("camera_drop" in p and "fraction" in p for p in problems), problems


def test_validate_config_dict_accepts_the_correct_camera_drop_spelling():
    problems = validate_config_dict({"scenarios": [{"name": "degraded", "camera_drop": {"drop_fraction": 0.3}}]})
    assert not any("camera_drop" in p for p in problems), problems


def test_validate_config_dict_tolerates_absent_scenarios():
    assert validate_config_dict({"name": "x"}) == []


# --- sub-config dataclasses ---------------------------------------------------


def test_subconfig_as_dict_round_trips_through_construction():
    for obj, cls in (
        (DatasetConfig(kind="file", imu_rate_hz=100.0), DatasetConfig),
        (EstimatorConfig(gate_sigma=3.0), EstimatorConfig),
        (EvaluationConfig(association="nearest"), EvaluationConfig),
    ):
        rebuilt = cls(**dict(obj.as_dict()))
        assert rebuilt.as_dict() == obj.as_dict()


def test_default_config_has_no_scenarios():
    assert Config().scenarios == []


def test_outage_covers_is_half_open():
    o = Outage(start_s=5.0, duration_s=15.0)
    assert o.covers(5.0)
    assert o.covers(19.999)
    assert not o.covers(20.0), "endpoint must be excluded, or outage windows double-count"
    assert not o.covers(4.999)
    assert o.end_s == 20.0
