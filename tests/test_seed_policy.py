"""The seed policy refuses held-out seeds in every seed-taking CLI command. No seed of 100 or more is ever run."""

from __future__ import annotations

import pytest

from navkit import cli, euroc_compare, euroc_eval, mismatch_sweep, outage_sweep, scene_sweep, seed_policy, seed_sweep

#: One refusal command per seed-taking ``navkit sweep`` entry point. ``multipath`` takes no seed.
SEED_SWEEPS = {
    "seeds": ["--seeds", "101"],
    "scenes": ["--seeds", "101"],
    "outages": ["--seeds", "101"],
    "mismatch": ["--seeds", "101"],
    "faults": ["--seeds", "101"],
    "fdir": ["rate", "--seeds", "101"],
    "attribution": ["--seeds", "101"],
    "separability": ["--seeds", "101"],
    "ramp": ["--seeds", "101"],
    "faultclass": ["--seeds", "101"],
    "vision-ramp": ["--seeds", "101"],
    "start-draw": ["--csv", "unused.csv", "--seeds", "101"],
    "correlated-gnss": ["--csv", "unused.csv", "--seeds", "101"],
    "shared-stream": ["--csv", "unused.csv", "--seeds", "101"],
}


def test_development_seeds_pass() -> None:
    seed_policy.require_development(range(100))


@pytest.mark.parametrize("seed", [100, 124, 125, 150])
def test_held_out_seed_is_refused(seed: int) -> None:
    with pytest.raises(ValueError, match="held-out"):
        seed_policy.require_development([seed])


def test_negative_seed_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        seed_policy.require_development([-1])


@pytest.mark.parametrize("kind", sorted(SEED_SWEEPS))
def test_every_seed_taking_sweep_refuses_seed_101(kind: str, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["sweep", kind, *SEED_SWEEPS[kind]])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


@pytest.mark.parametrize("module", [seed_sweep, outage_sweep, scene_sweep, mismatch_sweep])
def test_every_generic_sweep_refuses_seed_101(module, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        module.main(["--seeds", "101"])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


# --- the two seed-taking EuRoC commands --------------------------------------------------------


def test_euroc_run_refuses_held_out_seed(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["euroc", "run", "--seed", "100"])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


def test_euroc_run_refuses_negative_seed(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["euroc", "run", "--seed", "-1"])
    assert e.value.code == 2
    assert "negative" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--seeds", "101"],
        ["--first-seed", "99", "--seeds", "2"],
    ],
)
def test_euroc_compare_refuses_held_out_seeds(args: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["euroc", "compare", *args])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


def test_euroc_compare_refuses_negative_first_seed(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["euroc", "compare", "--first-seed", "-1", "--seeds", "1"])
    assert e.value.code == 2
    assert "negative" in capsys.readouterr().err


def _stop_at_the_dataset(dataset: str) -> None:
    raise RuntimeError("reached the dataset loader")


def test_euroc_run_allows_seed_99(monkeypatch) -> None:
    monkeypatch.setattr(euroc_eval, "dataset_loader", _stop_at_the_dataset)
    with pytest.raises(RuntimeError, match="reached the dataset loader"):
        cli.main(["euroc", "run", "--sequence", "MH_01_easy", "--seed", "99"])


def test_euroc_compare_allows_first_seed_99(monkeypatch) -> None:
    monkeypatch.setattr(euroc_compare, "dataset_loader", _stop_at_the_dataset)
    with pytest.raises(RuntimeError, match="reached the dataset loader"):
        cli.main(["euroc", "compare", "--first-seed", "99", "--seeds", "1"])


def test_held_out_constants_are_defined_once() -> None:
    import re
    from pathlib import Path

    import navkit

    literal = re.compile(r"^[A-Z_]*(HELD_OUT|SEED_LIMIT|RESERVED_SEED)[A-Z_]* = (range\()?\d+", re.M)
    root = Path(navkit.__file__).parent
    hits = [p.name for p in root.glob("*.py") if literal.search(p.read_text())]
    assert hits == ["seed_policy.py"]
