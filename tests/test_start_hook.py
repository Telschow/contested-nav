"""``run_case(start_hook=...)`` sees the drawn start error and returns the one to use (issue #168)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from navkit import benchmark
from navkit.benchmark import StartError, run_case

ROOT = Path(__file__).resolve().parent.parent
TIMING_KEYS = {"runtime_s", "wall_s", "realtime_factor"}


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "configs" / "benchmark.yaml").read_text(encoding="utf-8"))


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in TIMING_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _run(doc: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return run_case("outage_visual", doc["cases"]["outage_visual"], doc["defaults"], seed=3, **kw)


def test_a_hook_that_returns_its_argument_changes_nothing(doc):
    plain = _strip(_run(doc))
    hooked = _strip(_run(doc, start_hook=lambda err: err))
    assert hooked == plain


def test_the_hook_sees_the_drawn_error_and_is_not_in_the_hash(doc):
    seen: list[StartError] = []

    def hook(err: StartError) -> StartError:
        seen.append(err)
        return err

    record = _run(doc, start_hook=hook)
    assert len(seen) == 1
    assert np.any(seen[0].dtheta != 0.0)
    assert record["config_hash"] == _run(doc)["config_hash"]


def test_a_hook_that_zeroes_the_attitude_gives_an_exactly_zero_initial_attitude_error(doc, monkeypatch):
    captured: dict[str, Any] = {}
    real = benchmark.start_state

    def spy(true_R, true_p, true_v, err):
        out = real(true_R, true_p, true_v, err)
        captured["true_R"], captured["R"] = np.asarray(true_R), out.R
        return out

    monkeypatch.setattr(benchmark, "start_state", spy)
    _run(doc, start_hook=lambda e: StartError(dp=e.dp, dv=e.dv, dtheta=np.zeros(3)))
    assert np.array_equal(captured["R"], captured["true_R"])


def test_every_variant_of_a_seed_sees_the_same_draw(doc, monkeypatch):
    drawn: list[StartError] = []
    real = benchmark.draw_start_error

    def spy(cfg, base_seed):
        out = real(cfg, base_seed)
        drawn.append(out)
        return out

    monkeypatch.setattr(benchmark, "draw_start_error", spy)
    _run(doc)
    _run(doc, start_hook=lambda e: StartError(e.dp, e.dv, np.zeros(3)))
    _run(doc, start_hook=lambda e: StartError(np.zeros(3), np.zeros(3), e.dtheta))
    assert len(drawn) == 3
    for other in drawn[1:]:
        assert np.array_equal(other.dp, drawn[0].dp)
        assert np.array_equal(other.dv, drawn[0].dv)
        assert np.array_equal(other.dtheta, drawn[0].dtheta)
