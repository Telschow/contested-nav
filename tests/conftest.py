"""Shared pytest configuration.

Hypothesis profiles. Property tests must be reproducible, because a CI failure that
cannot be replayed is noise. ``derandomize=True`` makes Hypothesis derive its examples
from the test source rather than from the clock, so the same commit runs the same
examples everywhere, and a failure found by a developer's wider search can be pasted
into the test as an explicit ``@example``. ``deadline=None`` because the filter runs
take tens of milliseconds and a wall-clock deadline would measure the machine.

    HYPOTHESIS_PROFILE=explore pytest tests/test_properties.py   # 20x the examples, random seed
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=100,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "explore",
    max_examples=2000,
    derandomize=False,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


def _coverage_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "coverage_report.py"
    spec = importlib.util.spec_from_file_location("_navkit_coverage_report", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_configure(config):
    """Under ``scripts/coverage_report.py``, each xdist worker traces and writes its hit lines at the end."""
    if os.environ.get("NAVKIT_COV_DIR") and os.environ.get("PYTEST_XDIST_WORKER"):
        config._navkit_cov = _coverage_module()
        config._navkit_cov.worker_start()


def pytest_unconfigure(config):
    cov = getattr(config, "_navkit_cov", None)
    if cov is not None:
        cov.worker_finish()
