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
    assert set(out) == {
        "peak_error_m",
        "gnss_rejected",
        "gnss_faulted",
        "error_after_return_m",
        "recovery_median_m",
        "recovery_max_m",
    }
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
            "recovery_median_m": 0.0,
            "recovery_max_m": 0.0,
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


# ------------------------------------------------------- the recovery window (T2-8)
#
# A regular grid of 0.25 s is exact in binary floating point, so the half-open bounds are exact too. The outage ends
# at END; the window is [END + 2, END + 6) = [22, 26) and holds 16 epochs; the legacy instant is END + 4 = 24.
END = 20.0
GRID = np.arange(0.0, 40.0, 0.25)


def _step(t_s: float, high: float = 3.0, low: float = 1.0) -> np.ndarray:
    """An error series that is ``high`` before ``t_s`` and ``low`` from ``t_s`` on."""
    return np.where(t_s > GRID, high, low)


def _legacy(t: np.ndarray, e: np.ndarray, end: float) -> float:
    """What ``run_arm`` reports as ``error_after_return_m``: the value at the first epoch at or after end + 4."""
    return float(e[min(int(np.searchsorted(t, end + 4.0)), len(e) - 1)])


def test_the_window_is_two_to_six_seconds_after_the_end_and_needs_ten_epochs():
    assert at.RECOVERY_WINDOW_S == (2.0, 6.0) and at.RECOVERY_MIN_EPOCHS == 10


def test_the_window_is_half_open_and_holds_the_exact_epochs_of_a_regular_grid():
    mask = at.recovery_window(GRID, END)
    assert GRID[mask][0] == 22.0 and GRID[mask][-1] == 25.75  # 22 is in, 26 is out
    assert int(mask.sum()) == 16
    fine = np.arange(6001) / 200.0  # the 200 Hz series of the benchmark; 22.0 and 26.0 are exact on it
    assert int(at.recovery_window(fine, END).sum()) == 800


def test_the_statistics_use_exactly_the_epochs_of_the_window():
    """The error is the time itself, so the median and the maximum say which epochs were used."""
    median, peak = at.recovery_stats(GRID, GRID.copy(), END)
    assert peak == 25.75  # the epoch at 26 is outside; a closed window would give 26
    assert median == pytest.approx((23.75 + 24.0) / 2)  # 16 epochs 22 .. 25.75; a window shifted by one epoch differs


def test_the_legacy_value_jumps_when_the_step_crosses_its_instant_and_the_median_moves_in_two_steps():
    """Error 3 m, then 1 m from t_s. Move t_s one grid step at a time across the window [22, 26).

    The legacy instant is 24: it reads 3 for every t_s above 24 and 1 for every t_s at or below it, one jump of 2 m.
    With k epochs of the window before t_s, the window holds k threes and 16 - k ones. The median of 16 values is the
    mean of the 8th and 9th: 1 for k <= 7, 2 for k = 8, 3 for k >= 9. So it changes only when more than half of the
    window is on the other side, and by 1 m per grid step where it does. The maximum is 3 whenever any epoch is 3.
    """
    legacy, median, peak = [], [], []
    ks = range(0, 17)
    for k in ks:
        e = _step(22.0 + 0.25 * k)
        legacy.append(_legacy(GRID, e, END))
        m, p = at.recovery_stats(GRID, e, END)
        median.append(m)
        peak.append(p)
    assert legacy == [1.0] * 9 + [3.0] * 8  # t_s = 24 reads 1 (the epoch at 24 is already low); 24.25 reads 3
    assert median == [1.0] * 8 + [2.0] + [3.0] * 8
    assert peak == [1.0] + [3.0] * 16  # t_s = 22 leaves the whole window low
    assert max(abs(np.diff(legacy))) == 2.0 and max(abs(np.diff(median))) == 1.0
    assert int(np.count_nonzero(np.diff(legacy))) == 1 and int(np.count_nonzero(np.diff(median))) == 2


def test_a_step_outside_the_window_changes_the_median_and_the_maximum_by_nothing():
    before, after = _step(10.0), _step(30.0)  # all low in the window; all high in the window
    assert at.recovery_stats(GRID, before, END) == (1.0, 1.0)
    assert at.recovery_stats(GRID, after, END) == (3.0, 3.0)


def test_one_late_spike_moves_the_maximum_and_not_the_median():
    e = np.full_like(GRID, 1.0)
    e[GRID == 25.75] = 9.0
    assert at.recovery_stats(GRID, e, END) == (1.0, 9.0)
    e[GRID == 25.75] = 1.0
    e[GRID == 26.0] = 9.0  # one epoch after the window: not seen
    assert at.recovery_stats(GRID, e, END) == (1.0, 1.0)


def test_a_window_with_too_few_epochs_is_an_error_at_the_stated_minimum():
    coarse = np.arange(0.0, 40.0, 0.5)  # 8 epochs in [22, 26): below the default minimum of 10
    with pytest.raises(ValueError, match="8 epochs"):
        at.recovery_stats(coarse, np.ones_like(coarse), END)
    assert at.recovery_stats(GRID, np.ones_like(GRID), END, min_epochs=16) == (1.0, 1.0)  # exactly 16: allowed
    with pytest.raises(ValueError, match="16 epochs"):
        at.recovery_stats(GRID, np.ones_like(GRID), END, min_epochs=17)


def test_a_series_that_stops_inside_the_window_is_an_error_and_not_a_clamped_last_value():
    t = GRID[GRID < 24.0]  # the run ends 4 s after the outage: the legacy instant clamps to the last epoch
    with pytest.raises(ValueError, match="epochs"):
        at.recovery_stats(t, np.ones_like(t), END)
    with pytest.raises(ValueError, match="0 epochs"):
        at.recovery_stats(GRID[GRID < 20.0], np.ones(int((GRID < 20.0).sum())), END)


def test_a_run_reports_the_window_next_to_the_legacy_instant():
    out = at.run_arm(0)
    assert 0.0 < out["recovery_median_m"] <= out["recovery_max_m"]
    assert out["peak_error_m"] > out["recovery_max_m"]  # the fix after the outage collapses the error


def test_the_csv_has_the_old_columns_first_and_unchanged_then_the_two_new_ones():
    assert at.CSV_COLUMNS[:8] == (
        "experiment",
        "arm",
        "param",
        "seed",
        "peak_error_m",
        "gnss_rejected",
        "gnss_faulted",
        "error_after_return_m",
    )
    assert at.CSV_COLUMNS[8:] == ("recovery_median_m", "recovery_max_m")
