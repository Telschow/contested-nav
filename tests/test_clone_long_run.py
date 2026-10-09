"""A long run of the stochastic clone: does the claimed uncertainty keep growing, and does GNSS recover it?

A relative-pose measurement carries no information about global position or yaw, but a linearised filter can
gain some anyway. If it did, the claimed uncertainty would level off while the error kept growing and coverage
would collapse in the later blocks. These tests run 150 s, five times the benchmark, with the same motion
(the cycle counts scale with the duration), and check the shape of that behaviour. They are guards on the
fixture, not a proof of observability.
"""

from __future__ import annotations

import copy
from itertools import pairwise

import numpy as np
import pytest
import yaml

from navkit.benchmark import default_config_path, run_case

K = 5
BLOCK_S = 30.0


def _defaults_and_cases():
    cfg = yaml.safe_load(default_config_path().read_text())
    syn = dict(cfg["defaults"]["synthetic"])
    syn.update(
        duration_s=syn["duration_s"] * K,
        circles=syn["circles"] * K,
        sway_cycles=syn["sway_cycles"] * K,
        yaw_cycles=syn["yaw_cycles"] * K,
    )
    defaults = copy.deepcopy(cfg["defaults"])
    defaults["synthetic"] = syn
    return defaults, cfg["cases"]


def _blocks(record):
    ts = record["error_time_series"]
    t, e, s = np.array(ts["t"]), np.array(ts["position_error_m"]), np.array(ts["claimed_sigma_p_m"])
    q = (e / s) ** 2  # about 3 for a calibrated isotropic estimate
    out = []
    for a in np.arange(0.0, t[-1], BLOCK_S):
        m = (t >= a) & (t < a + BLOCK_S)
        if m.any():
            out.append(
                {
                    "t": a,
                    "sigma": float(np.median(s[m])),
                    "err": float(np.median(e[m])),
                    "inside": float(np.mean(q[m] <= 12.0)),
                }
            )
    return out


@pytest.fixture(scope="module")
def vision_only():
    defaults, cases = _defaults_and_cases()
    return run_case("vision_only_clone", copy.deepcopy(cases["vision_only_clone"]), defaults, seed=0)


@pytest.fixture(scope="module")
def restored():
    defaults, cases = _defaults_and_cases()
    case = copy.deepcopy(cases["outage_visual_clone"])
    case["scenario"]["gnss_outages"] = [{"start_s": 5.0, "duration_s": 100.0, "reason": "contested"}]
    return run_case("outage_visual_clone", case, defaults, seed=0)


def test_without_gnss_the_claimed_uncertainty_keeps_growing(vision_only):
    blocks = _blocks(vision_only)
    sigmas = [b["sigma"] for b in blocks]
    assert sigmas[-1] > 2.0 * sigmas[0]
    assert all(b > a for a, b in pairwise(sigmas))  # grows block after block


def test_without_gnss_the_error_stays_inside_the_claimed_region_in_every_block(vision_only):
    assert all(b["inside"] >= 0.95 for b in _blocks(vision_only))
    assert vision_only["headline"]["coverage"]["2sigma"] >= 0.99


def test_the_covariance_does_not_stop_growing_while_the_error_does_not_settle_either(vision_only):
    """The failure this guards against is a flat claimed sigma over a growing error."""
    blocks = _blocks(vision_only)
    late = blocks[len(blocks) // 2 :]
    assert late[-1]["sigma"] > late[0]["sigma"]


def test_when_gnss_returns_after_a_long_denial_it_is_accepted_and_the_error_collapses(restored):
    blocks = _blocks(restored)
    denied = [b for b in blocks if b["t"] + BLOCK_S <= 105.0 and b["t"] >= BLOCK_S]
    after = [b for b in blocks if b["t"] >= 105.0]
    assert denied and after
    assert max(b["err"] for b in after) < min(b["err"] for b in denied)
    assert restored["stats"]["gnss_updates_rejected"] == 0
    assert restored["stats"].get("fdir_gnss_faulted", 0.0) == 0.0
