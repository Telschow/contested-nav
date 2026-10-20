"""The B1 gate of ADR-0028 as a pure function, and the guard on the held-out seeds.

Nothing here runs a case, and nothing here runs a seed from the held-out set. The cases are in
``test_b1_gate_run.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from navkit import b1_gate
from navkit.eval import gate
from navkit.eval.gate import B1GateResult, Condition, evaluate_b1_gate
from navkit.eval.statistics import AutocorrelationEstimate, chi2_ppf, effective_sample_size

N, K, DOF = 25, 600, 3


def _inputs(seed: int = 4, n: int = N, k: int = K):
    """Runs that are consistent by construction: errors are drawn from the sigma the filter claims."""
    rng = np.random.default_rng(seed)
    sigma = rng.uniform(0.5, 2.0, (n, k, DOF))
    z = rng.standard_normal((n, k, DOF))
    err = z * sigma
    nees = (z**2).sum(axis=2)
    return nees, err, sigma


def _ates(ratios):
    ratios = np.asarray(ratios, float)
    return ratios * 1.0, np.ones_like(ratios)


def _call(nees=None, err=None, sigma=None, ratios=None, **kw):
    base_nees, base_err, base_sigma = _inputs()
    cand, ctrl = _ates([0.5] * N if ratios is None else ratios)
    return evaluate_b1_gate(
        base_nees if nees is None else nees,
        base_err if err is None else err,
        base_sigma if sigma is None else sigma,
        cand,
        ctrl,
        **kw,
    )


def _ratios(better: int, n: int = N, bad: float = 1.2, good: float = 0.5):
    return [good] * better + [bad] * (n - better)


# ------------------------------------------------------------------------------------------ known answers


def test_a_consistent_ensemble_with_a_useful_vision_passes_every_condition():
    result = _call()
    assert isinstance(result, B1GateResult)
    assert [c.passed for c in result.conditions] == [True] * 6
    assert result.passed
    assert result.n_runs == N and result.dof == DOF
    assert result.nees_upper.value == pytest.approx(3.0, abs=0.1)
    assert result.coverage.value == pytest.approx(0.9545, abs=0.005)


def test_nees_four_times_too_large_fails_the_upper_edge_only():
    nees, _, _ = _inputs()
    result = _call(nees=4.0 * nees)
    assert not result.nees_upper.passed and not result.passed
    assert result.nees_lower.passed and result.coverage.passed and result.ate_better.passed


def test_nees_five_times_too_small_fails_the_lower_bound_only():
    nees, _, _ = _inputs()
    result = _call(nees=0.2 * nees)
    assert not result.nees_lower.passed and not result.passed
    assert result.nees_upper.passed and result.coverage.passed


def test_claimed_sigma_too_small_fails_the_coverage_only():
    _, _, sigma = _inputs()
    result = _call(sigma=0.5 * sigma)
    assert not result.coverage.passed and not result.passed
    assert result.coverage.value == pytest.approx(0.6827, abs=0.01)
    assert result.nees_upper.passed and result.nees_lower.passed


def test_coverage_counts_triples_and_the_boundary_is_inclusive():
    nees, err, sigma = _inputs()
    sigma = np.ones_like(sigma)
    err = np.full_like(err, 2.0)  # exactly 2 sigma on every axis
    assert _call(nees=nees, err=err, sigma=sigma).coverage.value == 1.0
    err[:, : K // 2, 0] = 2.0 + 1e-9  # a quarter of the triples fall just outside... one axis in six
    assert _call(nees=nees, err=err, sigma=sigma).coverage.value == pytest.approx(1.0 - 1.0 / 6.0)
    assert _call(nees=nees, err=-err, sigma=sigma).coverage.value == pytest.approx(1.0 - 1.0 / 6.0)  # sign is free


# ----------------------------------------------------------------------------------------- the ATE rules


@pytest.mark.parametrize(("better", "passes"), [(20, True), (19, False), (25, True), (0, False)])
def test_the_better_count_is_at_least_eighty_percent_of_n(better, passes):
    result = _call(ratios=_ratios(better))
    assert result.ate_better.value == better
    assert result.ate_better.threshold == 20
    assert result.ate_better.passed is passes


def test_the_better_rule_scales_with_n_and_is_strictly_lower_ate():
    nees, err, sigma = _inputs(n=10)
    cand, ctrl = _ates([0.5] * 8 + [1.2, 1.2])
    r = evaluate_b1_gate(nees, err, sigma, cand, ctrl)
    assert r.ate_better.threshold == 8 and r.ate_better.passed
    cand, ctrl = _ates([0.5] * 7 + [1.0, 1.2, 1.2])  # a tie is not better
    r = evaluate_b1_gate(nees, err, sigma, cand, ctrl)
    assert r.ate_better.value == 7 and not r.ate_better.passed


def test_the_median_ratio_boundary():
    at = [0.5] * 7 + [0.8] * 13 + [1.2] * 5
    over = [0.5] * 7 + [0.81] * 13 + [1.2] * 5
    assert _call(ratios=at).ate_better.passed and _call(ratios=over).ate_better.passed  # same count in both
    assert _call(ratios=at).ate_median.value == 0.8 and _call(ratios=at).ate_median.passed
    assert _call(ratios=over).ate_median.value == 0.81 and not _call(ratios=over).ate_median.passed


def test_the_worst_ratio_boundary():
    at = _ratios(20, bad=1.5)
    over = _ratios(20, bad=1.51)
    assert _call(ratios=at).ate_worst.value == 1.5 and _call(ratios=at).ate_worst.passed
    assert _call(ratios=over).ate_worst.value == 1.51 and not _call(ratios=over).ate_worst.passed
    assert _call(ratios=at).passed and not _call(ratios=over).passed


def test_the_ratio_is_candidate_over_control():
    nees, err, sigma = _inputs()
    cand = np.full(N, 3.0)
    ctrl = np.full(N, 4.0)
    r = evaluate_b1_gate(nees, err, sigma, cand, ctrl)
    assert r.ate_median.value == pytest.approx(0.75) and r.ate_worst.value == pytest.approx(0.75)


# ----------------------------------------------------------------------------------- D and the upper edge


def test_the_degrees_of_freedom_and_the_edge_follow_the_adr_formula():
    nees, _, _ = _inputs()
    result = _call(nees=nees)
    n_eff = [effective_sample_size(row) for row in nees]
    assert result.sum_n_eff == pytest.approx(sum(n_eff))
    d = math.floor(DOF * sum(n_eff))
    assert result.degrees_of_freedom == d
    assert result.nees_upper.threshold == chi2_ppf(0.975, d) * DOF / d
    assert result.nees_upper.value == nees.mean()
    assert result.nees_lower.threshold == 0.44 * DOF
    assert result.nees_lower.value == nees.mean()


def test_white_noise_is_worth_about_its_length():
    nees, _, _ = _inputs()
    result = _call(nees=nees)
    assert 0.8 * N * K < result.sum_n_eff <= N * K


def test_a_known_effective_sample_size_gives_a_known_d_and_the_floor_is_applied(monkeypatch):
    def fake(x, c=5.0):
        return AutocorrelationEstimate(tau=len(x) / 40.5, window=3, truncated=False, n=len(x), c=c)

    monkeypatch.setattr(gate, "autocorrelation_estimate", fake)
    result = _call()
    assert result.sum_n_eff == pytest.approx(N * 40.5)  # 1012.5
    assert result.degrees_of_freedom == 3037  # floor(3 * 1012.5), not 3038 and not 3037.5
    assert result.nees_upper.threshold == chi2_ppf(0.975, 3037) * DOF / 3037


def test_a_shorter_effective_sample_widens_the_edge(monkeypatch):
    base = _call()

    def fake(x, c=5.0):
        return AutocorrelationEstimate(tau=len(x) / 10.0, window=3, truncated=False, n=len(x), c=c)

    monkeypatch.setattr(gate, "autocorrelation_estimate", fake)
    assert _call().nees_upper.threshold > base.nees_upper.threshold


def test_a_truncated_autocorrelation_estimate_is_reported(monkeypatch):
    assert _call().n_truncated == 0 and _call().any_truncated is False

    def fake(x, c=5.0):
        return AutocorrelationEstimate(tau=5.0, window=len(x) // 2, truncated=True, n=len(x), c=c)

    monkeypatch.setattr(gate, "autocorrelation_estimate", fake)
    result = _call()
    assert result.n_truncated == N and result.any_truncated is True


# ------------------------------------------------------------------------------------ result and inputs


def test_the_thresholds_are_the_adr_constants():
    assert gate.B1_BAND_UPPER_QUANTILE == 0.975
    assert gate.B1_LOWER_BOUND_PER_DOF == 0.44
    assert gate.B1_COVERAGE_SIGMA == 2.0 and gate.B1_COVERAGE_MIN == 0.95
    assert gate.B1_BETTER_FRACTION_MIN == 0.8
    assert gate.B1_MEDIAN_RATIO_MAX == 0.8 and gate.B1_WORST_RATIO_MAX == 1.5


def test_the_result_is_frozen_and_lists_its_six_conditions_in_order():
    result = _call()
    assert [c.name for c in result.conditions] == [
        "nees_upper",
        "nees_lower",
        "coverage",
        "ate_better",
        "ate_median",
        "ate_worst",
    ]
    assert all(isinstance(c, Condition) and c.relation in {"<=", ">="} for c in result.conditions)
    with pytest.raises(AttributeError):
        result.passed = False  # type: ignore[misc]
    assert result.passed == all(c.passed for c in result.conditions)


def test_any_n_of_two_or_more_is_accepted_and_fewer_is_not():
    nees, err, sigma = _inputs(n=2)
    cand, ctrl = _ates([0.5, 0.5])
    assert evaluate_b1_gate(nees, err, sigma, cand, ctrl).n_runs == 2
    with pytest.raises(ValueError, match="two runs"):
        evaluate_b1_gate(nees[:1], err[:1], sigma[:1], cand[:1], ctrl[:1])


def test_bad_input_is_refused():
    nees, err, sigma = _inputs(n=3)
    cand, ctrl = _ates([0.5] * 3)
    with pytest.raises(ValueError, match="shape"):
        evaluate_b1_gate(nees, err[:, :-1], sigma, cand, ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_b1_gate(nees, err, sigma[:2], cand, ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_b1_gate(nees, err, sigma, cand[:2], ctrl)
    with pytest.raises(ValueError, match="shape"):
        evaluate_b1_gate(nees[0], err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="finite"):
        bad = nees.copy()
        bad[0, 0] = np.nan
        evaluate_b1_gate(bad, err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="finite"):
        bad = err.copy()
        bad[0, 0, 0] = np.inf
        evaluate_b1_gate(nees, bad, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="negative"):
        evaluate_b1_gate(-nees, err, sigma, cand, ctrl)
    with pytest.raises(ValueError, match="negative"):
        evaluate_b1_gate(nees, err, -sigma, cand, ctrl)
    with pytest.raises(ValueError, match="positive"):
        evaluate_b1_gate(nees, err, sigma, cand, np.zeros(3))
    with pytest.raises(ValueError, match="epochs"):
        evaluate_b1_gate(nees[:, :5], err[:, :5], sigma[:, :5], cand, ctrl)


# ------------------------------------------------------------------------------ the held-out seeds guard


@pytest.mark.parametrize("text", ["100-124", "0-124", "124-124", "100,101", "99-100", "24-100"])
def test_the_command_refuses_the_held_out_seeds_without_the_flag(text, capsys):
    with pytest.raises(SystemExit) as stop:
        b1_gate.build_parser().parse_args(["--seeds", text, "--csv", "x.csv"])
    assert stop.value.code == 2
    assert "held-out" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["0-24", "0-99", "125-149", "24-24", "5,6,7"])
def test_the_command_accepts_other_seeds_without_the_flag(text):
    args = b1_gate.build_parser().parse_args(["--seeds", text, "--csv", "x.csv"])
    assert args.held_out is False and len(args.seeds) >= 1


def test_the_flag_allows_the_held_out_seeds_and_says_it_is_single_use(capsys):
    args = b1_gate.build_parser().parse_args(["--seeds", "100-124", "--csv", "x.csv", "--held-out"])
    assert list(args.seeds) == list(range(100, 125))
    assert "single use" in capsys.readouterr().err


def test_the_run_function_refuses_the_held_out_seeds_itself():
    with pytest.raises(ValueError, match="held-out"):
        b1_gate.run_gate(list(range(100, 125)))
    with pytest.raises(ValueError, match="held-out"):
        b1_gate.run_gate([3, 110])


def test_the_command_fixes_the_gate_at_twenty_five_seeds(capsys):
    with pytest.raises(SystemExit) as stop:
        b1_gate.main(["--seeds", "0-9", "--csv", "x.csv"])
    assert stop.value.code == 2
    assert "25" in capsys.readouterr().err


def test_seed_lists_parse_ranges_and_commas():
    assert b1_gate.parse_seeds("3-5") == [3, 4, 5]
    assert b1_gate.parse_seeds("1,4,2") == [1, 4, 2]
    for bad in ("", "a-b", "5-3", "1,,2", "-1-3"):
        with pytest.raises(ValueError):
            b1_gate.parse_seeds(bad)
