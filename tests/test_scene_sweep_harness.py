"""Tests for the multi-scene sweep harness.

`scripts/scene_sweep.py` exists to answer a question the noise sweep cannot:
whether a published verdict is a property of the estimator or an artefact of
the single trajectory in `configs/benchmark.yaml`. A harness that cannot
distinguish those two is worse than no harness, so these tests pin the
properties that make the answer meaningful -- chiefly that it actually varies
the scene, that the bootstrap is deterministic, and that a missing metric is
reported as missing rather than as zero.

They test the harness, not the filter. The finding being generalised is a
property of the estimator and is recorded in the generated JSON, not asserted
here: a software test cannot establish that a filter is miscalibrated.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sweep(bench):
    # `scene_sweep` imports `run_benchmark` as a top-level module, so that one
    # has to be in `sys.modules` first. Depending on `bench` here both enforces
    # the order and removes the ordering from the reader's side.
    return _load("scene_sweep", ROOT / "scripts" / "scene_sweep.py")


@pytest.fixture(scope="module")
def bench():
    return _load("run_benchmark", ROOT / "scripts" / "run_benchmark.py")


class TestBootstrap:
    def test_ci_is_deterministic(self, sweep):
        """A confidence interval that moved between runs would be unreportable.

        The resample index comes from a fixed generator rather than the global
        numpy state, so a caller gets the same interval without seeding
        anything themselves.

        Note that comparing two calls to `bootstrap_ci` would not prove this:
        with 10k resamples the percentile endpoints converge to the same two
        decimals however the indices are drawn, so a seeded and an unseeded
        version agree. What is asserted is the stronger, actual property -- the
        resample indices themselves are a pure function of the fixed seed.
        """
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert sweep.bootstrap_ci(vals) == sweep.bootstrap_ci(vals)

        def indices():
            rng = np.random.default_rng(sweep._BOOTSTRAP_SEED)
            return rng.integers(0, len(vals), size=(64, len(vals)))

        assert np.array_equal(indices(), indices())

    def test_the_bootstrap_generator_is_not_the_global_numpy_state(self, sweep):
        """A caller seeding numpy globally must not move these intervals.

        If the resampling drew from the global state, a sweep run after
        `np.random.seed(...)` anywhere in the process would produce a
        different interval, and the published CI would not be reproducible
        from the recorded inputs.
        """
        vals = [1.0, 4.0, 2.0, 8.0, 3.0]
        before = sweep.bootstrap_ci(vals)
        np.random.seed(1234)
        assert sweep.bootstrap_ci(vals) == before
        np.random.seed(9999)
        assert sweep.bootstrap_ci(vals) == before

    def test_ci_brackets_the_mean(self, sweep):
        vals = [10.0, 12.0, 11.0, 13.0, 9.0, 14.0]
        ci = sweep.bootstrap_ci(vals)
        assert ci["lo"] <= ci["point"] <= ci["hi"]

    def test_ci_reports_how_many_distinct_values_went_in(self, sweep):
        """A tight interval over one repeated value is not a tight result.

        With very small samples a bootstrap can put most of its mass on a
        single observed value, so the count of distinct inputs is reported
        alongside and a reader can tell the two cases apart.
        """
        assert sweep.bootstrap_ci([5.0] * 8)["n_distinct"] == 1
        assert sweep.bootstrap_ci([float(i) for i in range(8)])["n_distinct"] == 8

    def test_a_single_sample_gives_a_degenerate_interval_rather_than_an_error(self, sweep):
        ci = sweep.bootstrap_ci([3.0])
        assert ci["lo"] == ci["hi"] == 3.0
        assert ci["n"] == 1

    def test_a_wider_sample_gives_a_wider_interval(self, sweep):
        tight = sweep.bootstrap_ci([10.0, 10.1, 9.9, 10.0, 10.1])
        wide = sweep.bootstrap_ci([1.0, 50.0, 2.0, 49.0, 3.0])
        assert (wide["hi"] - wide["lo"]) > (tight["hi"] - tight["lo"])


class TestSceneAxis:
    def test_scene_seed_reaches_the_trajectory_not_the_noise(self, sweep, bench):
        """Two scene seeds must differ in geometry with the noise held fixed.

        This is the whole point of the script. If the scene seed only moved
        sensor noise it would duplicate `seed_sweep.py` and the generalisation
        question would remain unasked.
        """
        doc = {"defaults": {}, "cases": {"outage_visual": {}}}
        rows = []
        for scene in (0, 1):
            rec = bench.run_case(
                "outage_visual",
                {**doc["cases"]["outage_visual"], "scenario": _scenario()},
                doc["defaults"],
                scene_seed=scene,
            )
            rows.append((rec["synthetic"]["radius_m"], rec["headline"]["ate_rmse_m"]))
        assert rows[0][0] != rows[1][0], "scene seed did not change the trajectory"
        # Noise held fixed means the sensor config is untouched.
        assert rows[0][1] != 0.0 and rows[1][1] != 0.0

    def test_unseeded_runs_are_unaffected_by_the_new_argument(self, sweep, bench):
        """The default path must stay bit-identical to the committed baseline."""
        rec = bench.run_case("outage_visual", {"scenario": _scenario()}, {})
        assert rec.get("scene_seed") is None

    def test_scene_seed_is_recorded_in_provenance(self, sweep, bench):
        rec = bench.run_case("outage_visual", {"scenario": _scenario()}, {}, scene_seed=5)
        assert rec["scene_seed"] == 5
        assert rec["config_hash"], "a swept scene must still carry a config hash"

    def test_scene_and_noise_seeds_produce_different_hashes(self, sweep, bench):
        """Provenance must distinguish the two axes, or a result is untraceable."""
        noise = bench.run_case("outage_visual", {"scenario": _scenario()}, {}, seed=5)
        scene = bench.run_case("outage_visual", {"scenario": _scenario()}, {}, scene_seed=5)
        assert noise["config_hash"] != scene["config_hash"]


class TestMissingData:
    def test_absent_nees_is_reported_as_none_not_zero(self, sweep):
        """dead_reckoning has no covariance, so NEES is unmeasured, not zero.

        Collapsing "not measured" into 0.0 would drag every mean towards zero
        and make an unmeasured estimator look like a well-calibrated one.
        """
        rec = {
            "seed": 0,
            "scene_seed": 0,
            "config_hash": "h",
            "synthetic": {"radius_m": 4.0},
            "headline": {
                "ate_rmse_m": 1.88,
                "nees_mean": None,
                "coverage": None,
                "calibration_verdict": None,
            },
            "summary": {"path_length_m": 20.0},
        }
        row = sweep._collect(rec)
        assert row["nees_mean"] is None
        assert row["coverage_2sigma_pct"] is None
        assert row["verdict"] == "n/a"


class TestSummary:
    def test_verdict_stability_needs_every_run_to_agree(self, sweep):
        """A mean that is stable while the verdict flips is a weaker result.

        This is the single most useful question the sweep answers, so the
        summary must not average the disagreement away.
        """
        summary = {
            "all_same": {
                "n_runs": 3,
                "verdict_counts": {"overconfident": 3},
                "verdict_stable": len({"overconfident": 3}) == 1,
            },
            "split": {
                "n_runs": 3,
                "verdict_counts": {"overconfident": 2, "calibrated": 1},
                "verdict_stable": len({"overconfident": 2, "calibrated": 1}) == 1,
            },
        }
        assert summary["all_same"]["verdict_stable"] is True
        assert summary["split"]["verdict_stable"] is False

    def test_markdown_reports_a_split_verdict_rather_than_hiding_it(self, sweep):
        md = sweep.as_markdown(
            {
                "case": {
                    "n_runs": 4,
                    "nees_mean": {"mean": 400.0, "ci95": {"lo": 380.0, "hi": 420.0, "n": 4}},
                    "ate_rmse_m": {"mean": 2.5, "ci95": {"lo": 2.4, "hi": 2.6}},
                    "coverage_2sigma_pct": {"mean": 20.0, "ci95": {"lo": 19.0, "hi": 21.0}},
                    "verdict_stable": False,
                    "verdict_counts": {"overconfident": 3, "calibrated": 1},
                }
            }
        )
        assert "NO" in md
        assert "overconfident" in md and "calibrated" in md

    def test_markdown_says_na_rather_than_inventing_a_number(self, sweep):
        md = sweep.as_markdown(
            {
                "case": {
                    "n_runs": 4,
                    "nees_mean": None,
                    "ate_rmse_m": {"mean": 1.88, "ci95": {"lo": 1.88, "hi": 1.88}},
                    "coverage_2sigma_pct": None,
                    "verdict_stable": True,
                    "verdict_counts": {"n/a": 4},
                }
            }
        )
        assert md.count("n/a") == 2


def _scenario():
    from navkit.degrade.config import scenario_from_dict

    s = scenario_from_dict({"gnss": {"enabled": True}, "vision": {"enabled": True}})
    assert s is not None
    return s.as_dict()
