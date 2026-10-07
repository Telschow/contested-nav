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
