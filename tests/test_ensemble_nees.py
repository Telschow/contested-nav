"""The ensemble NEES over seeds, its chi-square band, and the CSV built from it.

After ADR-0027 each seed draws its own start error, and one run where absolute position is unobservable is close to
one sample. The test of consistency is an ensemble: at each epoch the mean NEES over N independent runs times N is
chi-square with N times the degrees of freedom if the filter is consistent, so the ensemble mean has a two-sided band
``chi2_ppf(0.025, N dof) / N`` to ``chi2_ppf(0.975, N dof) / N``. Nothing here decides a verdict or a gate.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from navkit import benchmark as bm
from navkit import ensemble
from navkit.eval.calibration import EnsembleNees, ensemble_nees, ensemble_nees_band
from navkit.eval.statistics import chi2_ppf

# ------------------------------------------------------------------------------------------------- the band


@pytest.mark.parametrize(("n", "dof"), [(2, 3), (5, 3), (10, 3), (25, 3), (10, 1), (7, 6)])
def test_the_band_is_the_chi_square_quantiles_over_n(n, dof):
    low, high = ensemble_nees_band(n, dof)
    assert low == chi2_ppf(0.025, n * dof) / n
    assert high == chi2_ppf(0.975, n * dof) / n


def test_the_band_brackets_the_expected_value_and_narrows_as_the_ensemble_grows():
    widths = []
    for n in (2, 5, 10, 25, 100):
        low, high = ensemble_nees_band(n, 3)
        assert low < 3.0 < high
        widths.append(high - low)
    assert widths == sorted(widths, reverse=True)


def test_another_level_gives_another_band():
    low90, high90 = ensemble_nees_band(10, 3, level=0.90)
    low95, high95 = ensemble_nees_band(10, 3, level=0.95)
    assert low95 < low90 < high90 < high95
    assert (low90, high90) == (chi2_ppf(0.05, 30) / 10, chi2_ppf(0.95, 30) / 10)


@pytest.mark.parametrize(("n", "dof", "level"), [(1, 3, 0.95), (0, 3, 0.95), (10, 0, 0.95), (10, 3, 1.0), (10, 3, 0.0)])
def test_the_band_refuses_an_ensemble_of_one_no_dof_or_a_level_outside_the_open_interval(n, dof, level):
    with pytest.raises(ValueError):
        ensemble_nees_band(n, dof, level)


# ------------------------------------------------------------------------------------------ known answers


def _consistent(n_runs: int, n_epochs: int, dof: int = 3, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).chisquare(dof, (n_runs, n_epochs))


def test_a_consistent_ensemble_has_about_ninety_five_percent_of_epochs_inside_the_band():
    """For independent runs and independent epochs each epoch is inside with probability 0.95, so the fraction is
    binomial(K, 0.95) / K, with a standard deviation of about 0.005 at K = 2000. Four of them is 0.02."""
    k = 2000
    result = ensemble_nees(_consistent(10, k))
    sd = np.sqrt(0.95 * 0.05 / k)
    assert result.fraction_inside == pytest.approx(0.95, abs=4.0 * sd)
    assert result.fraction_inside + result.fraction_below + result.fraction_above == pytest.approx(1.0)
    assert result.grand_mean == pytest.approx(3.0, abs=0.05)
    assert (result.n_runs, result.n_epochs, result.dof) == (10, k, 3)
    assert result.mean.shape == (k,)
    assert (result.low, result.high) == ensemble_nees_band(10, 3)


def test_an_overconfident_ensemble_is_above_the_band_and_an_underconfident_one_below():
    base = _consistent(10, 2000)
    over = ensemble_nees(4.0 * base)
    under = ensemble_nees(0.25 * base)
    assert over.fraction_inside < 0.01 and over.fraction_above > 0.99
    assert under.fraction_inside < 0.01 and under.fraction_below > 0.99
    assert over.grand_mean == pytest.approx(4.0 * 3.0, rel=0.02)


def test_the_statistic_is_the_mean_over_runs_at_each_epoch_and_its_extremes_are_reported():
    series = np.array([[1.0, 5.0, 9.0], [3.0, 5.0, 11.0]])
    result = ensemble_nees(series)
    np.testing.assert_array_equal(result.mean, [2.0, 5.0, 10.0])
    assert result.grand_mean == pytest.approx(np.mean([2.0, 5.0, 10.0]))
    assert (float(result.mean.min()), float(result.mean.max())) == (2.0, 10.0)


def test_identical_runs_are_not_detected_because_independence_is_the_callers_job():
    """The function cannot know that the runs repeat one another. It scores them as given."""
    one = _consistent(1, 500)[0]
    result = ensemble_nees(np.tile(one, (10, 1)))
    # a degenerate ensemble has the spread of a single run, so it falls outside the narrow band far too often
    assert result.fraction_inside < 0.5


def test_the_result_is_frozen():
    result = ensemble_nees(_consistent(4, 10))
    assert isinstance(result, EnsembleNees)
    with pytest.raises(AttributeError):
        result.grand_mean = 0.0  # type: ignore[misc]


def test_bad_input_is_refused():
    good = _consistent(3, 10)
    with pytest.raises(ValueError, match="two runs"):
        ensemble_nees(good[:1])
    with pytest.raises(ValueError, match="two-dimensional"):
        ensemble_nees(good[0])
    with pytest.raises(ValueError, match="epoch"):
        ensemble_nees(np.empty((3, 0)))
    for bad in (np.nan, np.inf, -np.inf):
        broken = good.copy()
        broken[1, 4] = bad
        with pytest.raises(ValueError, match="finite"):
            ensemble_nees(broken)
    negative = good.copy()
    negative[0, 0] = -1.0
    with pytest.raises(ValueError, match="negative"):
        ensemble_nees(negative)


# ------------------------------------------------------------------------------------------- the CSV


def _doc():
    return yaml.safe_load(bm.default_config_path().read_text(encoding="utf-8"))


def test_seeded_runs_differ_so_the_ensemble_is_not_degenerate():
    doc = _doc()
    series = []
    for seed in range(3):
        box: dict = {}
        bm.run_case("gnss_only", doc["cases"]["gnss_only"], doc["defaults"], seed=seed, nees_out=box)
        series.append(box["squared"])
    assert not np.array_equal(series[0], series[1]) and not np.array_equal(series[1], series[2])
    assert len({tuple(s[:5]) for s in series}) == 3  # they differ from the first epochs, where the start draw acts


def _without_timing(value):
    if isinstance(value, dict):
        return {k: _without_timing(v) for k, v in value.items() if k not in {"runtime_s", "wall_s", "realtime_factor"}}
    if isinstance(value, list):
        return [_without_timing(v) for v in value]
    return value


def test_collecting_a_run_does_not_change_the_record():
    doc = _doc()
    case = doc["cases"]["gnss_only"]
    plain = bm.run_case("gnss_only", case, doc["defaults"], seed=1)
    box: dict = {}
    kept = bm.run_case("gnss_only", case, doc["defaults"], seed=1, nees_out=box)
    assert _without_timing(plain) == _without_timing(kept)
    assert box["dof"] == 3 and box["squared"].shape == box["t"].shape


@pytest.fixture(scope="module")
def tiny() -> tuple[list[dict], str]:
    doc = _doc()
    names = ["dead_reckoning", "gnss_only", "outage_control"]
    rows = ensemble.run_ensemble(names, doc["cases"], doc["defaults"], n_runs=3)
    return rows, ensemble.csv_text(rows)


def test_the_csv_rows_are_documented_and_scoped(tiny):
    rows, text = tiny
    assert text.splitlines()[0] == ",".join(ensemble.CSV_FIELDS)
    assert ensemble.CSV_FIELDS == (
        "case",
        "scope",
        "n_runs",
        "dof",
        "n_epochs",
        "grand_mean",
        "band_low",
        "band_high",
        "fraction_inside",
        "fraction_below",
        "fraction_above",
        "ensemble_mean_min",
        "ensemble_mean_max",
    )
    assert [(r["case"], r["scope"]) for r in rows] == [
        ("gnss_only", "full"),
        ("outage_control", "full"),
        ("outage_control", "outage"),
    ]  # dead reckoning has no covariance; only the case with an outage has an outage scope
    assert {r["n_runs"] for r in rows} == {3} and {r["dof"] for r in rows} == {3}
    low, high = ensemble_nees_band(3, 3)
    for r in rows:
        assert (r["band_low"], r["band_high"]) == (low, high)
        assert r["fraction_inside"] + r["fraction_below"] + r["fraction_above"] == pytest.approx(1.0)
        assert r["ensemble_mean_min"] <= r["grand_mean"] <= r["ensemble_mean_max"]
    full, outage = rows[1], rows[2]
    assert outage["n_epochs"] < full["n_epochs"]  # the half-open outage window is a subset of the run


def test_the_csv_is_deterministic_and_reads_back(tiny):
    rows, text = tiny
    doc = _doc()
    again = ensemble.run_ensemble(
        ["dead_reckoning", "gnss_only", "outage_control"], doc["cases"], doc["defaults"], n_runs=3
    )
    assert ensemble.csv_text(again) == text
    assert ensemble.parse_csv(text) == [
        {k: (float(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rows
    ]


def test_the_outage_scope_scores_only_the_epochs_inside_the_window():
    doc = _doc()
    case = doc["cases"]["outage_control"]
    box: dict = {}
    record = bm.run_case("outage_control", case, doc["defaults"], seed=0, nees_out=box)
    windows = [(w["start_s"], w["end_s"]) for w in record["outage_calibration"]["windows"]]
    inside = (box["t"] >= windows[0][0]) & (box["t"] < windows[0][1])
    assert 0 < int(inside.sum()) < box["t"].size
    assert ensemble.window_epochs(box) == int(inside.sum())


def test_compare_rows_tolerates_last_bit_differences_and_nothing_else(tiny):
    rows, _ = tiny
    assert ensemble.compare_rows(rows, rows) == []
    near = [{**r, "grand_mean": r["grand_mean"] * (1.0 + 1e-9)} for r in rows]
    assert ensemble.compare_rows(near, rows) == []
    far = [{**r, "grand_mean": r["grand_mean"] * 1.001} for r in rows]
    assert ensemble.compare_rows(far, rows) != []
    assert ensemble.compare_rows([{**rows[0], "n_epochs": rows[0]["n_epochs"] + 1}, *rows[1:]], rows) != []
    assert ensemble.compare_rows(rows[:-1], rows) != []


def test_the_command_writes_the_csv_and_the_page_table_and_compares(tmp_path):
    from navkit import cli

    page = tmp_path / "page.md"
    page.write_text("a\n<!-- ensemble:start -->\nold\n<!-- ensemble:end -->\nb\n", encoding="utf-8")
    csv_path = tmp_path / "e.csv"
    base = ["sweep", "seeds", "--seeds", "2", "--only", "gnss_only", "--out", str(tmp_path / "s.json")]
    assert cli.main([*base, "--ensemble-csv", str(csv_path), "--ensemble-page", str(page)]) == 0
    rows = ensemble.parse_csv(csv_path.read_text(encoding="utf-8"))
    assert [(r["case"], r["scope"], r["n_runs"]) for r in rows] == [("gnss_only", "full", 2)]
    text = page.read_text(encoding="utf-8")
    assert "old" not in text and ensemble.markdown_table(rows) in text and text.startswith("a\n")
    assert cli.main([*base, "--ensemble-compare", str(csv_path)]) == 0
    csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(",2,3,", ",2,4,"), encoding="utf-8")
    assert cli.main([*base, "--ensemble-compare", str(csv_path)]) == 1


def test_a_page_without_the_markers_is_refused():
    with pytest.raises(ValueError, match="needs the lines"):
        ensemble.splice_table("no markers here", "x")
