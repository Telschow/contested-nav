"""The seed policy refuses held-out seeds in every seed-taking CLI command. No seed of 100 or more is ever run."""

from __future__ import annotations

from pathlib import Path

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


@pytest.mark.parametrize("flag", ["--seed", "--scene-seed"])
@pytest.mark.parametrize("value", ["100", "101", "-1"])
def test_run_refuses_held_out_and_negative_seeds(flag: str, value: str, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["run", flag, value, "--list"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "held-out" in err or "negative" in err


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


# --- the inventory: a new seed flag cannot ship without a refusal case -------------------------

#: Modules with a seed argument that are not development-only: the candidate gate may use held-out blocks.
GATE_MODULES = {"candidate_gate.py"}
#: Every other module with a ``--...seed...`` argument, and where its refusal is tested.
#: ``sweep`` modules are in ``SEED_SWEEPS`` or the generic list above, ``run`` and ``euroc`` have their own tests.
GUARDED_MODULES = {
    "attribution.py",
    "b1_gate.py",  # tests/test_b1_gate.py: development seeds only, --held-out refused (ADR-0028 set spent)
    "runner.py",  # the shared study runner, for any study that declares Flags(seeds=True)
    "benchmark.py",
    "correlated_gnss_study.py",
    "euroc_compare.py",
    "euroc_eval.py",
    "fault_classification.py",
    "fault_matrix.py",
    "fdir_false_alarm.py",
    "mismatch_sweep.py",
    "outage_sweep.py",
    "scene_sweep.py",
    "seed_sweep.py",
    "separability.py",
    "shared_stream_effect.py",
    "slow_ramp.py",
    "start_draw_study.py",
    "vision_ramp.py",
}


def _modules_with_a_seed_flag() -> set[str]:
    import re
    from pathlib import Path

    import navkit

    # An ``add_argument`` call whose first string is a flag with "seed" in it, on the same or the next line.
    flag = re.compile(r"add_argument\(\s*[\"']--[a-z-]*seed[a-z-]*[\"']")
    root = Path(navkit.__file__).parent
    return {p.name for p in root.rglob("*.py") if flag.search(p.read_text())}


def test_every_module_with_a_seed_flag_is_listed() -> None:
    found = _modules_with_a_seed_flag()
    unlisted = found - GATE_MODULES - GUARDED_MODULES
    assert not unlisted, f"seed flag without a refusal case in tests/test_seed_policy.py: {sorted(unlisted)}"
    stale = (GATE_MODULES | GUARDED_MODULES) - found
    assert not stale, f"listed but no longer takes a seed flag: {sorted(stale)}"


@pytest.mark.parametrize(
    "kind, args",
    [
        ("attribution", ["--growth-seeds", "101"]),
        ("attribution", ["--fault-seeds", "101"]),
        ("mismatch", ["--ensemble-seeds", "101"]),
    ],
)
def test_the_secondary_seed_flags_refuse_held_out_counts(kind: str, args: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["sweep", kind, *args])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err


def test_the_shared_study_runner_refuses_held_out_seeds(tmp_path, capsys) -> None:
    from navkit.report.runner import Flags, Study
    from navkit.report.runner import run_study as run

    calls: list[object] = []

    def never(seeds):  # the refusal must come before any case runs
        calls.append(seeds)
        return []

    study = Study(
        prog="x",
        description="x",
        table=None,  # type: ignore[arg-type]
        run=never,
        flags=Flags(seeds=True),
    )
    with pytest.raises(SystemExit) as e:
        run(study, ["--seeds", "99,101"])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err
    assert calls == []


# --- seeds a config file sets itself ------------------------------------------------------------


def _config_with_gnss_seed(tmp_path, seed: int) -> tuple[Path, str, dict]:
    import yaml

    from navkit.benchmark import default_config_path

    doc = yaml.safe_load(default_config_path().read_text())
    name = next(n for n, c in doc["cases"].items() if (c.get("scenario") or {}).get("gnss"))
    doc["cases"][name]["scenario"]["gnss"]["seed"] = seed
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(doc))
    return path, name, doc


def test_run_refuses_a_config_whose_own_seed_is_held_out(tmp_path, monkeypatch, capsys) -> None:
    from navkit import benchmark

    calls: list[str] = []
    monkeypatch.setattr(benchmark, "run_case", lambda name, *a, **k: calls.append(name))
    path, name, _ = _config_with_gnss_seed(tmp_path, 150)
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--config", str(path), "--only", name])
    assert e.value.code == 2
    assert "held-out" in capsys.readouterr().err
    assert calls == []


def test_run_case_refuses_a_configured_held_out_seed_before_it_builds_anything(tmp_path, monkeypatch) -> None:
    from navkit import benchmark

    def never(*a, **k):  # if the guard is missing, stop before any seeded draw
        raise AssertionError("run_case reached the streams")

    monkeypatch.setattr(benchmark, "synthetic_trajectory", never)
    _, name, doc = _config_with_gnss_seed(tmp_path, 150)
    with pytest.raises(ValueError, match="held-out"):
        benchmark.run_case(name, doc["cases"][name], doc.get("defaults", {}))


def test_an_explicit_seed_replaces_the_configured_one(tmp_path, monkeypatch) -> None:
    """The sweeps and the gates pass ``seed=``. The config's own value is then not used, so it is not checked."""
    from navkit import benchmark

    class Reached(Exception):
        pass

    def stop(*a, **k):
        raise Reached

    monkeypatch.setattr(benchmark, "synthetic_trajectory", stop)
    _, name, doc = _config_with_gnss_seed(tmp_path, 150)
    with pytest.raises(Reached):
        benchmark.run_case(name, doc["cases"][name], doc.get("defaults", {}), seed=5)
