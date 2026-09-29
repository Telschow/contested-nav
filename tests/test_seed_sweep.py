"""Tests for the seed sweep and for the benchmark's ``--seed`` override.

A seed sweep is easy to write in a way that cannot detect anything, which makes
it worse than no sweep at all. These tests pin the properties the sweep depends
on to mean anything:

* the override actually reaches every stochastic stream, so two seeds are two
  independent draws and not one draw relabelled;
* the default run is unchanged, so the committed baseline stays reproducible and
  a sweep cannot quietly redefine the published numbers;
* each seed is hashed into the record, so provenance distinguishes a sweep from
  the single-draw benchmark;
* the disagreement statistics are honest about sample size.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench():
    return _load("run_benchmark", ROOT / "scripts" / "run_benchmark.py")


@pytest.fixture(scope="module")
def sweep():
    return _load("seed_sweep", ROOT / "scripts" / "seed_sweep.py")


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "configs" / "benchmark.yaml").read_text())


class TestSeedOverride:
    def test_override_reaches_every_stochastic_stream(self, bench, config):
        """All three RNG sources must move, or two seeds are the same draw.

        ``camera_drop`` is the easy one to forget: it has its own seed in the
        config, and leaving it behind would make the degraded-camera case
        sweep only its sensor noise while the drop pattern stayed fixed.
        """
        case = config["cases"]["outage_visual_degraded_camera"]
        defaults = config["defaults"]
        assert case["scenario"]["camera_drop"] is not None, "fixture lost its camera_drop block"

        a = bench.run_case("outage_visual_degraded_camera", case, defaults, seed=11)
        b = bench.run_case("outage_visual_degraded_camera", case, defaults, seed=12)

        assert a["scenario"]["gnss"]["seed"] == 11
        assert a["scenario"]["vision"]["seed"] == 11
        assert a["scenario"]["camera_drop"]["seed"] == 11
        assert b["scenario"]["gnss"]["seed"] == 12
        assert b["scenario"]["vision"]["seed"] == 12
        assert b["scenario"]["camera_drop"]["seed"] == 12

    def test_distinct_seeds_give_distinct_streams(self, bench, config):
        case = config["cases"]["gnss_only"]
        defaults = config["defaults"]
        a = bench.run_case("gnss_only", case, defaults, seed=1)
        b = bench.run_case("gnss_only", case, defaults, seed=2)
        assert a["headline"]["ate_rmse_m"] != b["headline"]["ate_rmse_m"]

    def test_same_seed_is_reproducible(self, bench, config):
        case = config["cases"]["gnss_only"]
        defaults = config["defaults"]
        a = bench.run_case("gnss_only", case, defaults, seed=7)
        b = bench.run_case("gnss_only", case, defaults, seed=7)
        assert a["headline"] == b["headline"]
        assert a["config_hash"] == b["config_hash"]

    def test_no_override_preserves_the_config_seed(self, bench, config):
        """The default must still use the config's own seeds.

        ``outage_visual_degraded_camera`` pins camera_drop to seed 3, so this
        is the case that would catch a default that overrode to 0.
        """
        case = config["cases"]["outage_visual_degraded_camera"]
        defaults = config["defaults"]
        rec = bench.run_case("outage_visual_degraded_camera", case, defaults)
        assert rec["scenario"]["camera_drop"]["seed"] == case["scenario"]["camera_drop"]["seed"] == 3
        assert rec["scenario"]["gnss"]["seed"] == case["scenario"]["gnss"]["seed"] == 0


class TestProvenance:
    def test_seed_is_hashed_into_the_record(self, bench, config):
        """A swept run must not be mistakable for the committed baseline."""
        case = config["cases"]["outage_visual"]
        defaults = config["defaults"]
        base = bench.run_case("outage_visual", case, defaults, seed=0)
        swept = bench.run_case("outage_visual", case, defaults, seed=5)
        assert base["config_hash"] != swept["config_hash"]
        assert swept["seed"] == 5

    def test_sweep_payload_is_labelled_synthetic(self, sweep):
        """More seeds must not upgrade a fixture to a field measurement.

        The disclaimer is the constraint here: ``claim_type`` alone is too easy
        to copy forward without reading, and quoting a 10-seed number as real
        performance is exactly the failure C5 exists to prevent.

        The needles below are checked against the two places the wording can
        actually live: the module docstring, which becomes ``--help`` output,
        and the emitted payload, which is what a reader of the JSON sees. An
        earlier version of this test used ``assert ... or True``, which made it
        permanently green and silently unverified the disclaimer it existed to
        protect.
        """
        assert "a known-answer fixture into\na field measurement" in sweep.__doc__
        text = (ROOT / "scripts" / "seed_sweep.py").read_text()
        assert '"data_class": "synthetic"' in text
        assert "Multiple seeds do not make" in text


class _Summary:
    """Minimal stand-in for the per-case summary the sweep builds."""

    @staticmethod
    def build(rows):
        verdict_counts: dict[str, int] = {}
        for verdict in rows:
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        return {
            "verdict_counts": verdict_counts,
            "verdict_stable": len(verdict_counts) == 1,
        }


class TestSummaryStatistics:
    def test_verdict_flip_is_detected(self):
        rows = ["calibrated"] * 9 + ["overconfident"]
        assert _Summary.build(rows)["verdict_stable"] is False

    def test_unanimous_verdict_is_stable(self):
        assert _Summary.build(["calibrated"] * 10)["verdict_stable"] is True

    def test_single_sample_omits_stdev(self):
        """A standard deviation from one draw is not a spread, and reporting it
        invites a reader to treat n=1 as if it carried distributional
        information."""
        assert "stdev" not in sweep_spread([1.0])

    def test_spread_reports_mean_min_max_median(self):
        stats = sweep_spread([1.0, 2.0, 3.0, 4.0])
        assert stats["mean"] == pytest.approx(2.5)
        assert stats["min"] == 1.0
        assert stats["max"] == 4.0
        assert stats["median"] == pytest.approx(2.5)
        assert stats["stdev"] > 0

    def test_ten_draws_recommend_reading_the_range(self):
        """A stdev over 10 draws is weak, which is why the range is reported
        alongside it; this guards that both survive refactors."""
        stats = sweep_spread([float(x) for x in range(10)])
        assert {"mean", "min", "max", "median", "stdev"} <= set(stats)

    def test_missing_metric_is_not_treated_as_zero(self, sweep):
        """``dead_reckoning`` reports no covariance. A NEES of zero would read as
        perfect calibration instead of not measured."""
        record = {
            "seed": 0,
            "config_hash": "x",
            "headline": {
                "ate_rmse_m": 1.0,
                "nees_mean": None,
                "coverage": None,
                "calibration_verdict": None,
            },
        }
        row = sweep._collect(record)
        assert row["nees_mean"] is None
        assert row["coverage_2sigma_pct"] is None
        assert row["verdict"] == "n/a"


def sweep_spread(values):
    module = sys.modules.get("seed_sweep")
    return module._spread(values)


class TestArgumentGuards:
    def test_single_seed_is_rejected(self, sweep):
        """A spread needs at least two draws; one draw is the original problem."""
        with pytest.raises(SystemExit, match="at least 2 seeds"):
            sweep.main(["--seeds", "1"])

    def test_unknown_case_is_rejected(self, sweep):
        with pytest.raises(SystemExit, match="unknown case"):
            sweep.main(["--seeds", "2", "--only", "not_a_case"])
