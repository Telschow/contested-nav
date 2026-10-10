"""The outage-attribution experiments, run small enough to be quick.

These check the machinery: that a change reaches the run, that the fitted exponent is the exponent, and that the
tables come from the rows. What the experiments found is checked against the committed CSV in
``tests/test_attribution_page.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit import attribution as at
from navkit.cli import main as cli_main
from navkit.types import ImuSample


def test_a_run_reports_the_peak_inside_the_outage_and_the_gnss_outcome():
    out = at.run_arm(0)
    assert set(out) == {"peak_error_m", "gnss_rejected", "gnss_faulted", "error_after_return_m"}
    assert out["peak_error_m"] > out["error_after_return_m"] > 0.0  # the fix after the outage collapses the error
    assert out["gnss_rejected"] == 0.0


def test_the_peak_is_inside_the_outage_and_not_the_recovery_at_its_last_instant():
    """The metric this experiment was first run with, by mistake: the error at the outage's last instant is the
    error after the first fix returns, which measures the recovery. Pin that the peak is larger."""
    out = at.run_arm(0)
    assert out["peak_error_m"] > 3.0 * out["error_after_return_m"]


def test_the_gnss_noise_reaches_the_run_and_a_better_receiver_gives_a_smaller_error():
    assert at.run_arm(0, gnss_sigma_m=0.08)["peak_error_m"] < 0.5 * at.run_arm(0)["peak_error_m"]


def test_a_known_start_reaches_the_run_through_the_estimator_keys():
    assert at.run_arm(0, estimator=at.START_KNOWN)["peak_error_m"] < 0.5 * at.run_arm(0)["peak_error_m"]


def test_a_source_scaled_far_up_reaches_the_run():
    big = at.run_arm(0, noise_scale=dict.fromkeys(at.SOURCES["gyroscope white noise"], 100.0))
    assert big["peak_error_m"] > 2.0 * at.run_arm(0)["peak_error_m"]


def test_the_bias_step_adds_to_the_x_axis_from_the_outage_start_only():
    t = np.arange(0.0, 10.0, 0.01)
    imu = ImuSample(t=t, accel=np.zeros((len(t), 3)), gyro=np.zeros((len(t), 3)))
    out = at.bias_step_hook(0.3)(imu)
    assert np.all(out.accel[t < at.OUTAGE_START_S] == 0.0)
    assert np.allclose(out.accel[t >= at.OUTAGE_START_S, 0], 0.3)
    assert np.all(out.accel[:, 1:] == 0.0) and np.all(imu.accel == 0.0)  # the input is not changed


def test_a_large_bias_fault_makes_the_filter_reject_the_returning_gnss():
    out = at.run_arm(0, imu_hook=at.bias_step_hook(1.0))
    assert out["gnss_rejected"] > 0.0 and out["gnss_faulted"] > 0.0
    assert out["error_after_return_m"] > out["peak_error_m"]


def test_the_ablation_has_every_arm_for_every_seed():
    rows = at.ablation_rows(1)
    arms = [r["arm"] for r in rows]
    assert arms[0] == "baseline" and "no inertial errors" in arms and "start known exactly" in arms
    assert len(arms) == len(set(arms)) == 10
    assert all(r["experiment"] == "ablation" for r in rows)


def test_the_growth_rows_cover_the_requested_arms_and_durations_on_a_shorter_fixture():
    rows = at.growth_rows(1, durations=(5.0, 15.0), arms=("baseline", "no inertial errors"), scale=2)
    assert {(r["arm"], r["param"]) for r in rows} == {
        (a, d) for a in ("baseline", "no inertial errors") for d in (5.0, 15.0)
    }
    peaks = {(r["arm"], r["param"]): r["peak_error_m"] for r in rows}
    assert peaks[("baseline", 15.0)] > peaks[("baseline", 5.0)]


def _synthetic_growth(power: float) -> list[dict]:
    return [
        {
            "experiment": "growth",
            "arm": "a",
            "param": d,
            "seed": s,
            "peak_error_m": 2.0 * d**power,
            "gnss_rejected": 0.0,
            "gnss_faulted": 0.0,
            "error_after_return_m": 0.0,
        }
        for d in (5.0, 15.0, 45.0, 90.0)
        for s in (0, 1)
    ]


@pytest.mark.parametrize("power", [1.0, 1.5, 2.0, 3.0])
def test_the_fitted_exponent_is_the_exponent(power):
    assert at.exponent(_synthetic_growth(power), "a") == pytest.approx(power, abs=1e-9)


def test_the_tables_are_made_from_the_rows_and_a_missing_arm_is_an_error():
    full = at.ablation_rows(1)
    with pytest.raises(KeyError):
        at._mean(full, "ablation", "no such arm")
    text = at.ablation_markdown(full)
    assert text.splitlines()[2].startswith("| baseline |") and "+0%" in text.splitlines()[2]


def test_the_csv_round_trips_and_a_page_without_markers_is_refused(tmp_path):
    rows = _synthetic_growth(2.0)
    path = tmp_path / "a.csv"
    at.write_csv(path, rows)
    back = at.rows_from_csv(path)
    assert tuple(back[0]) == at.CSV_COLUMNS and at.exponent(back, "a") == pytest.approx(2.0)
    page = tmp_path / "p.md"
    page.write_text("x\n<!-- attribution-growth:start -->\nold\n<!-- attribution-growth:end -->\ny\n")
    at.write_block(page, "attribution-growth", "NEW")
    assert page.read_text() == "x\n<!-- attribution-growth:start -->\n\nNEW\n\n<!-- attribution-growth:end -->\ny\n"
    page.write_text("nothing")
    with pytest.raises(ValueError, match="attribution-growth:start"):
        at.write_block(page, "attribution-growth", "x")


def test_the_command_rebuilds_tables_and_a_page_from_a_saved_csv(tmp_path, capsys):
    rows = at.ablation_rows(1) + at.fault_rows(1, sizes=(0.0, 0.2))
    csv_path, page = tmp_path / "a.csv", tmp_path / "p.md"
    at.write_csv(csv_path, rows)
    page.write_text(
        "<!-- attribution-ablation:start -->\n<!-- attribution-ablation:end -->\n"
        "<!-- attribution-fault:start -->\n<!-- attribution-fault:end -->\n"
    )
    assert cli_main(["sweep", "attribution", "--from-csv", str(csv_path), "--page", str(page)]) == 0
    text = page.read_text()
    assert "| baseline |" in text and "| Bias step" in text
    assert cli_main(["sweep", "attribution", "--from-csv", str(csv_path), "--markdown"]) == 0
    assert "Peak error inside the outage" in capsys.readouterr().out
