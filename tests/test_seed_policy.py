"""The seed policy refuses held-out seeds in every sweep entry point. No seed of 100 or more is ever run."""

from __future__ import annotations

import pytest

from navkit import mismatch_sweep, outage_sweep, scene_sweep, seed_policy, seed_sweep


def test_development_seeds_pass() -> None:
    seed_policy.require_development(range(100))


@pytest.mark.parametrize("seed", [100, 124, 125, 150])
def test_held_out_seed_is_refused(seed: int) -> None:
    with pytest.raises(ValueError, match="held-out"):
        seed_policy.require_development([seed])


def test_negative_seed_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        seed_policy.require_development([-1])


@pytest.mark.parametrize("module", [seed_sweep, outage_sweep, scene_sweep, mismatch_sweep])
def test_every_sweep_refuses_seed_100(module, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        module.main(["--seeds", "101"])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


def test_held_out_constants_are_defined_once() -> None:
    import re
    from pathlib import Path

    import navkit

    literal = re.compile(r"^[A-Z_]*(HELD_OUT|SEED_LIMIT|RESERVED_SEED)[A-Z_]* = (range\()?\d+", re.M)
    root = Path(navkit.__file__).parent
    hits = [p.name for p in root.glob("*.py") if literal.search(p.read_text())]
    assert hits == ["seed_policy.py"]
