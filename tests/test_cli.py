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
