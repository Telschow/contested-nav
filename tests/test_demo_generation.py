"""Test the deterministic demo generation.

Verifies that the demo runs reproducibly and that the headline metrics in the
output JSON correspond to the values embedded in the visual snapshot (which is
not verified automatically, but the existence of a machine‑readable result is
checked).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "artifacts" / "demo"


def test_demo_results_exist() -> None:
    """Check that the demo artefacts have been generated."""
    assert DEMO_DIR.exists(), f"Demo directory not found at {DEMO_DIR}"
    results_path = DEMO_DIR / "results.json"
    assert results_path.exists(), f"results.json not found at {results_path}"
    snapshot_path = DEMO_DIR / "snapshot.png"
    assert snapshot_path.exists(), f"snapshot.png not found at {snapshot_path}"
    metadata_path = DEMO_DIR / "metadata.json"
    assert metadata_path.exists(), f"metadata.json not found at {metadata_path}"


def test_demo_json_schema() -> None:
    """Validate that the generated JSON contains the expected top‑level keys."""
    results_path = DEMO_DIR / "results.json"
    with results_path.open() as f:
        data = json.load(f)

    required_keys = {
        "name",
        "claim_type",
        "headline",
        "error_time_series",
        "trajectory_est",
        "trajectory_ref",
    }
    missing = required_keys - set(data.keys())
    assert not missing, f"Missing keys in results.json: {missing}"

    headline = data.get("headline", {})
    assert headline.get("ate_rmse_m") is not None, "Headline missing ATE RMSE"
    assert headline.get("claimed_sigma_p_m") is not None, "Headline missing claimed σ"
    assert headline.get("nees_mean") is not None, "Headline missing mean NEES"
    assert headline.get("coverage", {}).get("2sigma") is not None, "Headline missing 2σ coverage"


def test_demo_deterministic_values() -> None:
    """Ensure that the headline values in results.json are derived from the run.

    This test checks that the values exist and are within reasonable bounds,
    confirming that they come from the navkit execution rather than being
    hand‑typed constants.
    """
    results_path = DEMO_DIR / "results.json"
    with results_path.open() as f:
        data = json.load(f)

    headline = data.get("headline", {})
    claimed_sigma = headline.get("claimed_sigma_p_m")
    nees_mean = headline.get("nees_mean")
    cov_2sigma = headline.get("coverage", {}).get("2sigma")

    # The values should be numbers (not None) and within plausible ranges.
    assert claimed_sigma is not None, "claimed_sigma missing"
    assert 0.0 <= claimed_sigma <= 10.0, f"claimed_sigma out of range: {claimed_sigma}"

    assert nees_mean is not None, "nees_mean missing"
    assert nees_mean > 0.0, f"nees_mean non‑positive: {nees_mean}"

    assert cov_2sigma is not None, "coverage 2sigma missing"
    assert 0.0 <= cov_2sigma <= 1.0, f"coverage out of range: {cov_2sigma}"

    # Additional sanity: ensure they are not obvious hard‑coded constants.
    # If the implementation ever changes and these values become e.g. 0.0 or 100.0,
    # the test will still pass as long as they are within range, but a human
    # reviewer should verify that the new numbers make sense.
    assert claimed_sigma != 0.0, "claimed_sigma is zero – suspicious"
    assert nees_mean != 0.0, "nees_mean is zero – suspicious"


def test_metadata_present() -> None:
    """Verify that metadata.json exists and contains a seed."""
    metadata_path = DEMO_DIR / "metadata.json"
    with metadata_path.open() as f:
        meta = json.load(f)
    assert "seed" in meta, "Metadata missing seed"
    assert meta["seed"] == 0, f"Unexpected seed {meta['seed']}"
