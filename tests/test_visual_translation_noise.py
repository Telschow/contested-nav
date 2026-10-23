"""The synthetic visual translation noise is drawn per axis, as declared (ADR-0033).

Each axis of the relative translation error is an independent zero-mean normal with the standard deviation
``trans_sigma_m * noise_multiplier``. That is the covariance the stream declares and the filter assumes. The earlier
draw, a random unit direction times one scalar, had a per-axis variance of one third of that.

The rotation noise must not move. ``tests/data/visual_rotation_reference.npz`` holds the rotation block of the stream
as origin/main produced it before this change, recorded by a script run on a clean origin/main, and the tests compare
against it. The draws are the same on every platform, so on the machine that recorded the file the match is bit for bit;
elsewhere the trigonometric functions inside the rotation exponential can differ in the last digit (ADR-0009), so the
comparison is exact to 1e-12, nine orders of magnitude below the rotation noise, which any other draw would change.

Tolerances. With ``n`` independent zero-mean normal draws, the sample second moment has a relative standard error of
``sqrt(2 / n)`` and a sample correlation coefficient has a standard error of ``1 / sqrt(n)``. The tests allow four
standard errors. For a correlated stream (AR(1)) ``n`` is the effective sample size ``n (1 - a) / (1 + a)``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from navkit.sensors import models
from navkit.sensors.models import VisionConfig, rereference_visual_updates, visual_updates
from navkit.synthetic import SyntheticConfig, synthetic_trajectory

DATA = Path(__file__).resolve().parent / "data" / "visual_rotation_reference.npz"
SIGMA = 0.05
SEED = 3
FOUR_SE = 4.0
RECORDED_ATOL = 1e-12  # absolute, on rotation matrices; the rotation noise itself is about 6e-3 rad

#: A long trajectory for the statistics: 30 000 frames at the default 20 Hz.
LONG = synthetic_trajectory(SyntheticConfig(duration_s=1500.0, rate_hz=100.0))
#: The trajectory of the reference file.
SHORT = synthetic_trajectory(SyntheticConfig(duration_s=15.0, rate_hz=100.0))


def _translation_noise(**kw) -> tuple[np.ndarray, object]:
    """The translation noise of ``visual_updates`` alone: the stream minus the same stream without noise."""
    noisy = visual_updates(LONG, VisionConfig(trans_sigma_m=SIGMA, seed=SEED, **kw))
    clean = visual_updates(LONG, VisionConfig(trans_sigma_m=0.0, seed=SEED, **kw))
    return (noisy.t_rel - clean.t_rel)[1:], noisy


@pytest.fixture(scope="module")
def noise_and_stream():
    return _translation_noise()


# ----------------------------------------------------------------------------------------- the statistics


def test_each_axis_has_the_declared_variance(noise_and_stream):
    noise, _ = noise_and_stream
    n = len(noise)
    tol = FOUR_SE * np.sqrt(2.0 / n)
    ratio = np.mean(noise**2, axis=0) / SIGMA**2
    assert np.all(np.abs(ratio - 1.0) < tol), (ratio, tol)


def test_the_axes_are_uncorrelated_and_the_mean_is_zero(noise_and_stream):
    noise, _ = noise_and_stream
    n = len(noise)
    corr = np.corrcoef(noise.T)
    off = np.array([corr[0, 1], corr[0, 2], corr[1, 2]])
    assert np.all(np.abs(off) < FOUR_SE / np.sqrt(n)), off
    assert np.all(np.abs(noise.mean(axis=0)) < FOUR_SE * SIGMA / np.sqrt(n))


def test_the_squared_norm_of_a_frame_is_three_axes_of_variance_and_not_one(noise_and_stream):
    # The earlier draw was one scalar along one direction, so its mean squared norm was sigma^2. Three independent
    # axes of variance sigma^2 each give 3 sigma^2.
    noise, _ = noise_and_stream
    n = len(noise)
    assert abs(np.mean(np.sum(noise**2, axis=1)) / (3.0 * SIGMA**2) - 1.0) < FOUR_SE * np.sqrt(2.0 / (3.0 * n))


def test_the_declared_covariance_is_what_is_produced(noise_and_stream):
    noise, stream = noise_and_stream
    declared = np.asarray(stream.trans_cov)[1:]
    assert np.all(declared == SIGMA**2)
    n = len(noise)
    tol = FOUR_SE * np.sqrt(2.0 / n)
    assert np.all(np.abs(np.mean(noise**2, axis=0) / declared[0] - 1.0) < tol)


def test_the_rereference_generator_draws_per_axis_too():
    noisy_base = visual_updates(LONG, VisionConfig(seed=SEED))
    dropped = np.zeros(len(noisy_base), dtype=bool)
    dropped[0] = True
    dropped[1::3] = True  # every third frame is lost, so the frame after each loss is measured against an older one
    noisy_base.dropped = dropped
    cfg = VisionConfig(trans_sigma_m=SIGMA, seed=SEED)
    clean_cfg = VisionConfig(trans_sigma_m=0.0, seed=SEED)
    noisy = rereference_visual_updates(noisy_base, LONG, cfg)
    clean = rereference_visual_updates(noisy_base, LONG, clean_cfg)
    previous, rows = None, []
    for i in range(len(dropped)):
        if dropped[i]:
            continue
        if previous is not None and previous != i - 1:
            rows.append(i)
        previous = i
    noise = (noisy.t_rel - clean.t_rel)[rows]
    n = len(noise)
    assert n > 5000
    assert np.all(np.abs(np.mean(noise**2, axis=0) / SIGMA**2 - 1.0) < FOUR_SE * np.sqrt(2.0 / n))
    corr = np.corrcoef(noise.T)
    assert np.all(np.abs([corr[0, 1], corr[0, 2], corr[1, 2]]) < FOUR_SE / np.sqrt(n))


def test_the_marginal_variance_is_kept_when_the_errors_are_correlated_over_time():
    corr_s = 0.5
    noise, _ = _translation_noise(noise_corr_s=corr_s)
    a = float(np.exp(-0.05 / corr_s))
    n_eff = len(noise) * (1.0 - a) / (1.0 + a)
    tol = FOUR_SE * np.sqrt(2.0 / n_eff)
    ratio = np.mean(noise**2, axis=0) / SIGMA**2
    assert np.all(np.abs(ratio - 1.0) < tol), (ratio, tol)


def test_noise_multiplier_scales_the_translation_standard_deviation_linearly():
    base, _ = _translation_noise()
    tripled, _ = _translation_noise(noise_multiplier=3.0)
    assert np.allclose(tripled, 3.0 * base, rtol=1e-9, atol=1e-12)
    n = len(tripled)
    assert np.all(np.abs(np.mean(tripled**2, axis=0) / (3.0 * SIGMA) ** 2 - 1.0) < FOUR_SE * np.sqrt(2.0 / n))


# ---------------------------------------------------------------------------------------- the streams


def test_the_translation_noise_comes_from_the_named_stream(noise_and_stream):
    noise, _ = noise_and_stream
    rng = np.random.default_rng(np.random.SeedSequence([SEED, models.TRANSLATION_NOISE_STREAM]))
    expected = rng.standard_normal((len(noise), 3)) * SIGMA
    assert np.allclose(noise, expected, rtol=1e-9, atol=1e-12)


def test_the_two_generators_use_different_translation_streams():
    assert models.TRANSLATION_NOISE_STREAM != models.REREFERENCE_TRANSLATION_NOISE_STREAM


def test_a_different_scenario_seed_gives_different_translation_noise():
    a = visual_updates(LONG, VisionConfig(seed=1)).t_rel
    b = visual_updates(LONG, VisionConfig(seed=2)).t_rel
    assert not np.allclose(a[1:200], b[1:200])


def test_changing_the_translation_sigma_does_not_move_the_rotation_noise():
    a = visual_updates(SHORT, VisionConfig(seed=SEED, trans_sigma_m=0.05))
    b = visual_updates(SHORT, VisionConfig(seed=SEED, trans_sigma_m=0.5))
    assert np.array_equal(a.R_rel, b.R_rel)
    assert not np.array_equal(a.t_rel, b.t_rel)


def test_changing_the_rotation_sigma_does_not_move_the_translation_noise():
    a = visual_updates(SHORT, VisionConfig(seed=SEED, rot_sigma_deg=0.35))
    b = visual_updates(SHORT, VisionConfig(seed=SEED, rot_sigma_deg=1.0))
    assert np.array_equal(a.t_rel, b.t_rel)
    assert not np.array_equal(a.R_rel, b.R_rel)


def test_the_same_holds_for_the_rereference_generator():
    base = visual_updates(SHORT, VisionConfig(seed=SEED))
    dropped = np.zeros(len(base), dtype=bool)
    dropped[0] = True
    dropped[[10, 30, 31, 60]] = True
    base.dropped = dropped
    a = rereference_visual_updates(base, SHORT, VisionConfig(seed=SEED, trans_sigma_m=0.05))
    b = rereference_visual_updates(base, SHORT, VisionConfig(seed=SEED, trans_sigma_m=0.5))
    assert np.array_equal(a.R_rel, b.R_rel)
    c = rereference_visual_updates(base, SHORT, VisionConfig(seed=SEED, rot_sigma_deg=1.0))
    d = rereference_visual_updates(base, SHORT, VisionConfig(seed=SEED, rot_sigma_deg=0.35))
    assert np.array_equal(c.t_rel, d.t_rel)


# ----------------------------------------------------------------------------- the rotation is unchanged


def _matches_recorded(got: np.ndarray, want: np.ndarray) -> None:
    assert got.shape == want.shape
    worst = float(np.max(np.abs(got - want)))
    assert worst <= RECORDED_ATOL, worst


@pytest.fixture(scope="module")
def reference():
    return np.load(DATA)


def test_the_reference_file_is_small_and_has_the_four_arrays(reference):
    assert sorted(reference.files) == ["multiplier", "plain", "rereference", "stress"]
    assert all(reference[k].shape == (301, 3, 3) for k in reference.files)


def test_the_rotation_noise_is_bit_for_bit_what_origin_main_produced(reference):
    got = visual_updates(SHORT, VisionConfig(seed=7))
    _matches_recorded(got.R_rel, reference["plain"])


def test_the_rotation_noise_is_unchanged_with_the_stress_options_on(reference):
    cfg = VisionConfig(seed=11, noise_corr_s=0.5, outlier_fraction=0.1, outlier_scale=20.0, scale_sigma=0.02)
    _matches_recorded(visual_updates(SHORT, cfg).R_rel, reference["stress"])


def test_the_rotation_noise_is_unchanged_with_a_noise_multiplier(reference):
    got = visual_updates(SHORT, VisionConfig(seed=3, noise_multiplier=3.0))
    _matches_recorded(got.R_rel, reference["multiplier"])


def test_the_rereference_rotation_noise_is_unchanged(reference):
    base = visual_updates(SHORT, VisionConfig(seed=5))
    dropped = np.zeros(len(base), dtype=bool)
    dropped[0] = True
    dropped[[7, 19, 20, 21, 40, 80, len(base) - 1]] = True
    base.dropped = dropped
    got = rereference_visual_updates(base, SHORT, VisionConfig(seed=5))
    _matches_recorded(got.R_rel, reference["rereference"])
    # the reference does cover re-referenced frames
    assert int(np.sum(np.any(got.R_rel != base.R_rel, axis=(1, 2)))) == 4
