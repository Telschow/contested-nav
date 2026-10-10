"""The ``navkit`` command line: routing, defaults and agreement with the golden snapshot."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from navkit import __version__, benchmark, cli

GOLDEN = Path(__file__).resolve().parent / "golden" / "benchmark.json"
CASES = [
    "gnss_only",
    "dead_reckoning",
    "vision_anchor_in_measurement_noise",
    "vision_only",
    "outage_control",
    "outage_visual",
    "outage_visual_degraded_camera",
    "outage_visual_clone",
    "outage_visual_degraded_camera_rereferenced",
    "outage_visual_degraded_camera_clone",
    "vision_only_clone",
    "outage_visual_clone_outliers",
    "outage_visual_clone_scale_drift",
    "outage_visual_clone_correlated",
    "outage_visual_clone_correlated_inflated",
]


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"navkit {__version__}"


def test_no_command_prints_help_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    out = capsys.readouterr().out
    assert "run" in out
    assert "navkit <command> --help" in out


def test_an_unknown_command_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["frobnicate"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_run_list_prints_every_case_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--list"]) == 0
    assert capsys.readouterr().out.split() == CASES


def test_run_rejects_an_unknown_case() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--only", "no_such_case"])
    assert "unknown case" in str(exc.value)


def test_the_default_config_is_found_and_is_the_canonical_file() -> None:
    path = benchmark.default_config_path()
    assert path.name == "benchmark.yaml"
    assert path.is_file()


def test_the_config_label_is_canonical_by_default_and_the_given_path_otherwise(tmp_path: Path) -> None:
    assert benchmark._config_label(benchmark.default_config_path(), given=False) == "configs/benchmark.yaml"
    outside = tmp_path / "mine.yaml"
    assert benchmark._config_label(outside, given=True) == str(outside)


def test_run_reproduces_the_golden_headline_for_one_case(tmp_path: Path) -> None:
    out = tmp_path / "one.json"
    assert cli.main(["run", "--only", "gnss_only", "--out", str(out)]) == 0
    got = json.loads(out.read_text())
    want = json.loads(GOLDEN.read_text())["cases"]["gnss_only"]["headline"]
    assert len(got["cases"]) == 1
    headline = got["cases"][0]["headline"]
    for key in ("ate_rmse_m", "claimed_sigma_p_m", "nees_mean"):
        assert headline[key] == pytest.approx(want[key], rel=1e-9, abs=1e-9)
    assert got["config_file"] == "configs/benchmark.yaml"


def test_python_dash_m_navkit_is_an_alias() -> None:
    proc = subprocess.run([sys.executable, "-m", "navkit", "--version"], capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == f"navkit {__version__}"


def test_sweep_without_a_kind_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sweep"]) == 2
    assert (
        "navkit sweep {seeds, scenes, outages, mismatch, faults, attribution, separability, ramp}"
        in capsys.readouterr().err
    )


def test_sweep_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sweep", "--help"]) == 0
    assert "seeds" in capsys.readouterr().err


def test_sweep_refuses_an_unknown_kind() -> None:
    assert cli.main(["sweep", "bogus"]) == 2


@pytest.mark.parametrize(("kind", "message"), [("seeds", "at least 2 seeds"), ("scenes", "at least 2 scenes")])
def test_sweep_routes_to_the_matching_sweep(kind: str, message: str) -> None:
    """Each kind reaches its own argument guard, so the router did not cross them."""
    with pytest.raises(SystemExit, match=message):
        cli.main(["sweep", kind, "--seeds", "1"])


def test_sweep_seeds_runs_and_labels_the_default_config(tmp_path: Path) -> None:
    out = tmp_path / "seed_sweep.json"
    assert cli.main(["sweep", "seeds", "--seeds", "2", "--only", "gnss_only", "--out", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["n_seeds"] == 2
    assert payload["config_file"] == "configs/benchmark.yaml"


def test_figures_needs_a_results_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not found"):
        cli.main(["figures", "--results", str(tmp_path / "missing.json")])


def test_figures_writes_under_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The figures land in ``docs/figures`` of the current directory, not of the package."""
    results = tmp_path / "benchmark.json"
    assert cli.main(["run", "--only", "gnss_only", "--out", str(results)]) == 0
    monkeypatch.chdir(tmp_path)
    assert cli.main(["figures", "--results", str(results)]) == 0
    assert (tmp_path / "docs" / "figures" / "error-vs-claim.png").stat().st_size > 0
    assert (tmp_path / "docs" / "figures" / "coverage.png").stat().st_size > 0


def test_sweep_scenes_runs_and_prints_a_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "scene_sweep.json"
    argv = ["sweep", "scenes", "--seeds", "2", "--only", "gnss_only", "--markdown", "--out", str(out)]
    assert cli.main(argv) == 0
    assert json.loads(out.read_text())["n_scenes"] == 2
    assert "gnss_only" in capsys.readouterr().out
