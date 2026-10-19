"""The integrated autocorrelation time and the effective sample size, against series whose answer is known.

The estimator is Sokal's automatic windowing. For an AR(1) series ``x_t = a x_{t-1} + e_t`` the integrated
autocorrelation time is exactly ``(1 + a) / (1 - a)``, which is the known answer for the tolerances below. The
tolerances are chosen from the spread measured over several seeds (the PR shows it), with a margin, and are stated
next to each constant.

Nothing here is wired into a verdict. The estimator is a tool for a later package.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from navkit.eval import (
    AutocorrelationEstimate,
    autocorrelation_estimate,
    effective_sample_size,
    integrated_autocorrelation_time,
)


def ar1(a: float, n: int, seed: int) -> np.ndarray:
    """``x_t = a x_{t-1} + e_t`` with unit-variance Gaussian noise, started from its stationary distribution."""
    rng = np.random.default_rng(seed)
    e = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = e[0] / np.sqrt(1.0 - a * a)
    for t in range(1, n):
        x[t] = a * x[t - 1] + e[t]
    return x


def ar1_fast(a: float, n: int, seed: int) -> np.ndarray:
    """The same recursion for long runs: ``x`` is the white noise convolved with ``a^k``, cut where ``a^k < 1e-14``.

    A Python loop over millions of samples is slow, and NumPy has no linear filter. The cut leaves a relative error
    far below anything the tests can see, and the first ``K - 1`` noise samples are the burn-in, so the series is
    stationary from its first sample.
    """
    rng = np.random.default_rng(seed)
    k = int(np.ceil(np.log(1e-14) / np.log(a))) + 1
    e = rng.standard_normal(n + k - 1)
    h = a ** np.arange(k)
    size = 1 << int(np.ceil(np.log2(n + 2 * k)))
    full = np.fft.irfft(np.fft.rfft(e, size) * np.fft.rfft(h, size), size)
    return np.asarray(full[k - 1 : k - 1 + n])


def tau_ar1(a: float) -> float:
    return (1.0 + a) / (1.0 - a)


# ---------------------------------------------------------------- tolerances, from the measured spread
#: Relative tolerance on tau for AR(1) series, by coefficient: (n, tolerance). Each is a multiple of the spread
#: measured over eight seeds (the pull request shows the spread and the bias); a = 0.99 is harder and has its own n.
AR1_CASES = {
    0.5: (200_000, 0.08),
    0.9: (200_000, 0.12),
    0.99: (2_000_000, 0.15),
}
SEEDS = (11, 12, 13)


# ------------------------------------------------------------------------ known answers


def test_white_noise_has_tau_near_one_and_n_eff_near_n():
    x = np.random.default_rng(1).standard_normal(100_000)
    tau = integrated_autocorrelation_time(x)
    assert tau == pytest.approx(1.0, abs=0.05)
    assert effective_sample_size(x) == pytest.approx(x.size, rel=0.05)


@pytest.mark.parametrize("a", sorted(AR1_CASES))
def test_ar1_tau_matches_the_closed_form(a):
    n, tol = AR1_CASES[a]
    for seed in SEEDS:
        x = ar1_fast(a, n, seed)
        tau = integrated_autocorrelation_time(x)
        assert tau == pytest.approx(tau_ar1(a), rel=tol), (a, seed)
        assert effective_sample_size(x) == pytest.approx(n / tau_ar1(a), rel=tol * 1.5), (a, seed)


def test_the_fast_ar1_generator_is_an_ar1():
    """The generator used for the long series must have the stated recursion, or the closed form means nothing."""
    x = ar1_fast(0.9, 50_000, 3)
    assert np.corrcoef(x[:-1], x[1:])[0, 1] == pytest.approx(0.9, abs=0.01)
    assert np.var(x) == pytest.approx(1.0 / (1.0 - 0.81), rel=0.1)


def test_an_iid_chi_square_series_has_tau_near_one():
    """A consistent NEES (3 degrees of freedom, independent epochs) is what independent samples look like."""
    x = np.random.default_rng(5).chisquare(3, 100_000)
    assert integrated_autocorrelation_time(x) == pytest.approx(1.0, abs=0.06)


def test_a_slow_ar1_plus_white_noise_lies_between_the_two_pure_cases():
    n = 200_000
    slow = ar1_fast(0.9, n, 21)
    noise = np.random.default_rng(22).standard_normal(n)
    tau_slow = integrated_autocorrelation_time(slow)
    tau_noise = integrated_autocorrelation_time(noise)
    tau_sum = integrated_autocorrelation_time(slow + noise)
    assert tau_noise < tau_sum < tau_slow
    # The sum's autocovariance is the slow one's plus the noise variance at lag zero, so its tau is the slow
    # tau times the slow variance share, plus the white share. That is a known answer, not just an ordering.
    share = np.var(slow) / (np.var(slow) + np.var(noise))
    assert tau_sum == pytest.approx(1.0 + (tau_ar1(0.9) - 1.0) * share, rel=0.12)


def test_a_random_walk_does_not_return_n_over_one_or_a_negative_tau():
    """A non-stationary series has no finite integrated time. The windowing rule makes the answer large, not absurd.

    The plain sum of the autocorrelation of a random walk is of the order of n and can exceed it. With the rule, tau
    is large (thousands of lags here, a tenth of the length or more) and n_eff is small, tau is never below one, and
    n_eff is never n. Whether the rule is met at some lag before half the length depends on the draw (a random walk
    can look as if it decorrelates, late), so the test asserts the result for several draws and does not ask
    for a particular flag.
    """
    for seed in range(7, 13):
        x = np.cumsum(np.random.default_rng(seed).standard_normal(20_000))
        tau = integrated_autocorrelation_time(x)
        n_eff = effective_sample_size(x)
        assert tau > 100.0, seed
        assert 1.0 <= n_eff < x.size / 100.0, seed


def test_a_trend_never_meets_the_window_rule_and_says_so():
    """A series that never decorrelates is cut at half its length and marked truncated, with a small n_eff."""
    rng = np.random.default_rng(8)
    x = np.arange(20_000, dtype=float) + 100.0 * rng.standard_normal(20_000)
    detail = autocorrelation_estimate(x)
    assert detail.truncated is True
    assert detail.window == x.size // 2
    assert detail.tau > 1_000.0
    assert effective_sample_size(x) < 20.0


def test_a_stationary_series_is_not_marked_truncated():
    detail = autocorrelation_estimate(ar1_fast(0.5, 50_000, 2))
    assert detail.truncated is False
    assert detail.window < 50_000 // 2
    assert detail.window >= 5.0 * detail.tau
    assert detail.n == 50_000


def test_scale_and_offset_do_not_change_tau():
    x = ar1_fast(0.9, 50_000, 4)
    assert integrated_autocorrelation_time(3.0 * x + 7.0) == pytest.approx(integrated_autocorrelation_time(x), rel=1e-9)
    assert integrated_autocorrelation_time(-x) == pytest.approx(integrated_autocorrelation_time(x), rel=1e-9)


def test_tau_is_never_below_one_and_antithetic_series_are_not_rewarded():
    x = np.tile([1.0, -1.0], 5_000) + 0.01 * np.random.default_rng(9).standard_normal(10_000)
    assert integrated_autocorrelation_time(x) == 1.0
    assert effective_sample_size(x) == x.size


def test_the_estimate_is_deterministic():
    x = ar1_fast(0.9, 30_000, 5)
    assert integrated_autocorrelation_time(x) == integrated_autocorrelation_time(x.copy())


def test_the_window_constant_is_used():
    x = ar1_fast(0.9, 50_000, 6)
    loose = autocorrelation_estimate(x, c=3.0)
    strict = autocorrelation_estimate(x, c=8.0)
    assert loose.window < strict.window


# ------------------------------------------------------------------------------ edges


@pytest.mark.parametrize("call", [integrated_autocorrelation_time, effective_sample_size, autocorrelation_estimate])
class TestRefusals:
    def test_fewer_than_ten_samples(self, call):
        with pytest.raises(ValueError, match="at least 10"):
            call(np.arange(9.0))
        call(np.random.default_rng(0).standard_normal(10))  # ten is enough

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
    def test_non_finite_values(self, call, bad):
        x = np.random.default_rng(0).standard_normal(50)
        x[10] = bad
        with pytest.raises(ValueError, match="finite"):
            call(x)

    def test_a_constant_series(self, call):
        with pytest.raises(ValueError, match=r"constant|variance"):
            call(np.full(50, 3.0))

    def test_a_two_dimensional_input(self, call):
        with pytest.raises(ValueError, match=r"one-dimensional|1-D|1D"):
            call(np.random.default_rng(0).standard_normal((50, 2)))

    def test_a_non_positive_window_constant(self, call):
        with pytest.raises(ValueError, match="c must"):
            call(np.random.default_rng(0).standard_normal(50), c=0.0)


def test_the_detail_type_is_frozen():
    detail = autocorrelation_estimate(np.random.default_rng(0).standard_normal(100))
    assert isinstance(detail, AutocorrelationEstimate)
    with pytest.raises(AttributeError):
        detail.tau = 2.0  # type: ignore[misc]


# -------------------------------------------------------------------------- property


@given(
    st.integers(min_value=10, max_value=400),
    st.floats(min_value=-0.99, max_value=0.99),
    st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=60, deadline=None)
def test_n_eff_is_between_one_and_n_for_any_valid_series(n, a, seed):
    """A bounded effective sample size is the one thing a consumer can rely on, whatever the series is."""
    x = ar1(a, n, seed)
    n_eff = effective_sample_size(x)
    tau = integrated_autocorrelation_time(x)
    assert 1.0 <= n_eff <= n
    assert tau >= 1.0
    assert np.isfinite(n_eff) and np.isfinite(tau)
    assert n_eff == pytest.approx(min(max(n / tau, 1.0), float(n)))


def test_a_seeded_loop_of_odd_series_stays_bounded():
    """Series that are not AR(1): heavy tails, steps, a trend, a short period. The bounds still hold."""
    rng = np.random.default_rng(31)
    n = 500
    series = [
        rng.standard_t(2, n),
        np.concatenate([np.zeros(n // 2), np.ones(n // 2)]) + 0.1 * rng.standard_normal(n),
        np.arange(n, dtype=float) + rng.standard_normal(n),
        np.sin(np.arange(n) * 0.3) + 0.2 * rng.standard_normal(n),
        np.cumsum(rng.standard_normal(n)),
    ]
    for x in series:
        n_eff = effective_sample_size(x)
        assert 1.0 <= n_eff <= n
