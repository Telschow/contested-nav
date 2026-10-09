"""Characterisation test: the seeded benchmark must reproduce its committed output.

``tests/golden/benchmark.json`` is a snapshot of ``scripts/run_benchmark.py`` at the
default seed. It exists so that a refactor, which is meant to change no behaviour,
fails here when it changes a number, instead of surviving until a documented table
happens to disagree. It is a lock on current behaviour, not a statement that the
numbers are right: the headline result is a known overconfidence, and the snapshot
records it as it is.

What is compared. Every section of every case except wall-clock values (which
measure the machine, not the filter) and the ``environment`` block. The 6001-sample
position-error series is decimated to every 200th sample plus the last, which keeps
the file small and still moves if the trajectory error moves. Floats are compared with
a relative tolerance of 1e-9 plus an absolute floor of 1e-9. The floor was first added after
the first CI run found the snapshot differing from a laptop run by up to 4e-11 absolute,
and the macOS and Windows legs then showed the cause: the synthetic IMU used to be a finite
difference whose rounding error was amplified by about 1e10, so it moved with the math
library (see ADR-0009). The IMU is now derived analytically and all three operating systems
pass at this tolerance, which is kept because it was set with margin and has not been
measured below. The headline covariance metrics (NEES, claimed sigma, coverage) agree at the
relative tolerance. The claimed-sigma series alone has a looser tolerance, see
``SERIES_REL_TOL``. A NaN matches a NaN: dead reckoning reports no covariance, and that is
part of the record.

Regenerate after an intended behaviour change, and say why in the commit:

    python tests/test_golden_benchmark.py --update
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_benchmark.py"
GOLDEN = Path(__file__).resolve().parent / "golden" / "benchmark.json"

#: Keys that measure the machine, not the filter. Stripped wherever they appear.
TIMING_KEYS = frozenset({"runtime_s", "wall_s", "realtime_factor"})
#: Top-level keys that describe the environment of the run, not its result.
ENVIRONMENT_KEYS = frozenset({"environment"})
DECIMATE_EVERY = 200
REL_TOL = 1e-9
ABS_TOL = 1e-9
#: The claimed-sigma series is read straight out of the covariance, which is sensitive to which
#: CPU kernel the linear algebra dispatches to. The same commit differed between GitHub runners
#: by up to 1.1e-8 relative in it, while every other quantity agreed at 1e-9. 1e-6 is about
#: 100 times the largest gap seen; see ADR-0009.
SERIES_REL_TOL = 1e-6
SERIES_MARKER = ".error_time_series.claimed_sigma_p_m["


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in TIMING_KEYS}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _decimate(series: list[Any]) -> list[Any]:
    kept = series[::DECIMATE_EVERY]
    if series and (len(series) - 1) % DECIMATE_EVERY != 0:
        kept.append(series[-1])
    return kept


def make_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    """Reduce a ``run_benchmark.py`` result to the part that is locked."""
    snapshot = {k: _strip(v) for k, v in result.items() if k not in ENVIRONMENT_KEYS and k != "cases"}
    cases: dict[str, Any] = {}
    for case in result["cases"]:
        reduced = _strip(case)
        series = reduced.get("error_time_series")
        if isinstance(series, dict):
            reduced["error_time_series"] = {k: _decimate(v) for k, v in series.items()}
        cases[case["name"]] = reduced
    snapshot["cases"] = cases
    return snapshot


def _differences(path: str, got: Any, want: Any) -> list[str]:
    """Return a human-readable list of differences between two JSON-like trees."""
    if isinstance(want, dict) and isinstance(got, dict):
        out: list[str] = []
        for key in sorted(set(want) | set(got)):
            if key not in got:
                out.append(f"{path}.{key}: missing (golden has it)")
            elif key not in want:
                out.append(f"{path}.{key}: unexpected (golden lacks it)")
            else:
                out.extend(_differences(f"{path}.{key}", got[key], want[key]))
        return out
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            return [f"{path}: length {len(got)} != golden {len(want)}"]
        out = []
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            out.extend(_differences(f"{path}[{i}]", g, w))
        return out
    if isinstance(want, float) or isinstance(got, float):
        if isinstance(want, bool) or isinstance(got, bool) or want is None or got is None:
            return [] if got == want else [f"{path}: {got!r} != golden {want!r}"]
        if math.isnan(want) and math.isnan(got):
            return []
        rel_tol = SERIES_REL_TOL if SERIES_MARKER in path else REL_TOL
        if math.isclose(got, want, rel_tol=rel_tol, abs_tol=ABS_TOL):
            return []
        return [f"{path}: {got!r} != golden {want!r}"]
    return [] if got == want else [f"{path}: {got!r} != golden {want!r}"]


def _run_benchmark(out: Path) -> dict[str, Any]:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    with out.open() as f:
        loaded: dict[str, Any] = json.load(f)
    return loaded


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Run the benchmark once for the module and reduce it to the locked snapshot."""
    out = tmp_path_factory.mktemp("golden") / "benchmark.json"
    return make_snapshot(_run_benchmark(out))


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    with GOLDEN.open() as f:
        loaded: dict[str, Any] = json.load(f)
    return loaded


def test_the_golden_file_covers_the_documented_cases(golden: dict[str, Any]) -> None:
    assert len(golden["cases"]) == 11


def test_the_same_cases_are_produced(snapshot: dict[str, Any], golden: dict[str, Any]) -> None:
    # Sorted: the golden file is written with sorted keys, and case order is not behaviour.
    assert sorted(snapshot["cases"]) == sorted(golden["cases"])


def test_top_level_metadata_matches(snapshot: dict[str, Any], golden: dict[str, Any]) -> None:
    got = {k: v for k, v in snapshot.items() if k != "cases"}
    want = {k: v for k, v in golden.items() if k != "cases"}
    diffs = _differences("$", got, want)
    assert not diffs, "\n".join(diffs[:10])


@pytest.mark.parametrize(
    "case",
    [
        "gnss_only",
        "dead_reckoning",
        "vision_anchor_in_measurement_noise",
        "vision_only",
        "outage_control",
        "outage_visual",
        "outage_visual_degraded_camera",
    ],
)
def test_case_matches_golden(case: str, snapshot: dict[str, Any], golden: dict[str, Any]) -> None:
    diffs = _differences(f"$.cases.{case}", snapshot["cases"][case], golden["cases"][case])
    assert not diffs, f"{len(diffs)} difference(s), first {min(len(diffs), 10)}:\n" + "\n".join(diffs[:10])


def test_the_comparison_notices_a_small_change(golden: dict[str, Any]) -> None:
    """A relative change of 1e-6 in a headline number must be reported."""
    changed = json.loads(json.dumps(golden))
    headline = changed["cases"]["outage_visual"]["headline"]
    headline["ate_rmse_m"] *= 1.000001
    diffs = _differences("$", changed, golden)
    assert len(diffs) == 1
    assert diffs[0].startswith("$.cases.outage_visual.headline.ate_rmse_m")


def test_the_claimed_sigma_series_tolerates_runner_to_runner_noise_but_not_a_real_change(
    golden: dict[str, Any],
) -> None:
    """The series gets 1e-6, the rest of the snapshot keeps 1e-9."""
    series = golden["cases"]["outage_control"]["error_time_series"]["claimed_sigma_p_m"]
    noisy = json.loads(json.dumps(golden))
    noisy["cases"]["outage_control"]["error_time_series"]["claimed_sigma_p_m"][14] = series[14] * (1.0 + 2e-8)
    assert _differences("$", noisy, golden) == []
    changed = json.loads(json.dumps(golden))
    changed["cases"]["outage_control"]["error_time_series"]["claimed_sigma_p_m"][14] = series[14] * (1.0 + 1e-4)
    assert len(_differences("$", changed, golden)) == 1
    # The same 2e-8 on a headline number is still a difference.
    headline = json.loads(json.dumps(golden))
    headline["cases"]["outage_control"]["headline"]["claimed_sigma_p_m"] *= 1.0 + 2e-8
    assert len(_differences("$", headline, golden)) == 1


def test_the_comparison_ignores_last_bit_noise(golden: dict[str, Any]) -> None:
    changed = json.loads(json.dumps(golden))
    changed["cases"]["outage_visual"]["headline"]["ate_rmse_m"] *= 1.0 + 1e-12
    assert _differences("$", changed, golden) == []


def _update() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        snap = make_snapshot(_run_benchmark(Path(tmp) / "benchmark.json"))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN.open("w") as f:
        json.dump(snap, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {GOLDEN.relative_to(ROOT)} ({GOLDEN.stat().st_size} bytes)")


if __name__ == "__main__":
    if "--update" not in sys.argv[1:]:
        raise SystemExit("usage: python tests/test_golden_benchmark.py --update")
    _update()
