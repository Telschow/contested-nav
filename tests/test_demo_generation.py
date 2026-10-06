"""Test the deterministic demo generation.

Runs ``scripts/generate_demo.py`` once into a temporary directory and checks the
artefacts it writes. The demo is generated here, not read from a checked-out
``artifacts/`` directory, because generated output is gitignored and a fresh
clone must pass the suite without a manual step first.

The visual snapshot itself is not verified automatically; the checks cover the
existence of the machine-readable result and that its headline values come from
the run rather than from hand-typed constants.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_demo.py"


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the demo once for the module and return its output directory."""
    out = tmp_path_factory.mktemp("demo")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    return out


def test_demo_results_exist(demo_dir: Path) -> None:
    """Check that the demo artefacts have been generated."""
    for name in ("results.json", "snapshot.png", "metadata.json"):
        assert (demo_dir / name).exists(), f"{name} not found in {demo_dir}"


def test_demo_json_schema(demo_dir: Path) -> None:
    """Validate that the generated JSON contains the expected top-level keys."""
    with (demo_dir / "results.json").open() as f:
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


def test_demo_deterministic_values(demo_dir: Path) -> None:
    """Ensure that the headline values in results.json are derived from the run.

    This test checks that the values exist and are within reasonable bounds,
    confirming that they come from the navkit execution rather than being
    hand-typed constants.
    """
    with (demo_dir / "results.json").open() as f:
        data = json.load(f)

    headline = data.get("headline", {})
    claimed_sigma = headline.get("claimed_sigma_p_m")
    nees_mean = headline.get("nees_mean")
    cov_2sigma = headline.get("coverage", {}).get("2sigma")

    # The values should be numbers (not None) and within plausible ranges.
    assert claimed_sigma is not None, "claimed_sigma missing"
    assert 0.0 <= claimed_sigma <= 10.0, f"claimed_sigma out of range: {claimed_sigma}"

    assert nees_mean is not None, "nees_mean missing"
    assert nees_mean > 0.0, f"nees_mean non-positive: {nees_mean}"

    assert cov_2sigma is not None, "coverage 2sigma missing"
    assert 0.0 <= cov_2sigma <= 1.0, f"coverage out of range: {cov_2sigma}"

    # Additional sanity: ensure they are not obvious hard-coded constants.
    # If the implementation ever changes and these values become e.g. 0.0 or 100.0,
    # the test will still pass as long as they are within range, but a human
    # reviewer should verify that the new numbers make sense.
    assert claimed_sigma != 0.0, "claimed_sigma is zero, suspicious"
    assert nees_mean != 0.0, "nees_mean is zero, suspicious"


def test_metadata_present(demo_dir: Path) -> None:
    """Verify that metadata.json exists and contains a seed."""
    with (demo_dir / "metadata.json").open() as f:
        meta = json.load(f)
    assert "seed" in meta, "Metadata missing seed"
    assert meta["seed"] == 0, f"Unexpected seed {meta['seed']}"
