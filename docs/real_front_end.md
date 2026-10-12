# A real front end's errors, and the stochastic clone

[ADR-0017](adr/0017-stochastic-clone-for-the-visual-update.md) made the stochastic clone calibrated for independent
visual errors and found it fails when they are correlated over about 0.5 to 2 s. It left open which a real front end
has. [ADR-0020](adr/0020-second-source-against-a-ramp.md) made the answer the next step. This page measures the errors
of a small two-view front end on real camera frames, and runs the clone against them.

## Method

The front end is [`navkit.vo_frontend`](api/index.md), in NumPy only: Shi-Tomasi corners, pyramidal Lucas-Kanade
tracking with a forward-backward check, an eight-point essential matrix inside a RANSAC loop, and a cheirality test.
It is a plain feature tracker, not a visual odometry system, and it does not claim to match a production one. Frames
are tracked step by step, so a pair `g` frames apart is tracked through every frame between.

The data is 600 left-camera frames (30 s, 20 Hz) of EuRoC MH_01_easy, from 60 s to 90 s into the recording, where
the drone moves at about 0.5 m/s. Each pair is compared with the ground truth, through the camera-to-body extrinsic in
the dataset's calibration. A monocular pair has no scale, so the translation error is the error of the direction times
the true baseline. That is the error a front end with perfect scale would hand the filter. A real monocular front end
would be worse. Pairs where the camera did not move are skipped.

Then the clone is checked two ways, in a 30 s window with GNSS healthy for the first 10 s and lost for the last 20 s:

- **Surrogate**: the simulated front end of the earlier studies, given the measured error size and correlation time.
- **Replay**: the measured errors of the one-frame pairs, added to the true relative motion and fed to the filter as
  the visual stream. It carries the real errors, with their outliers, instead of a Gaussian stand-in.

## The errors

<!-- vo-errors:start -->

| Gap, frames | Pairs | Median baseline m | Rotation RMS deg | Lateral RMS m | Median direction error deg | Outlier share | Rotation lag-1 autocorrelation | Lateral lag-1 autocorrelation | Rotation correlation time s | Lateral correlation time s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 590 | 0.028 | 0.08 | 0.008 | 11.7 | 2% | 0.54 | 0.57 | 0.20 | 0.25 |
| 2 | 590 | 0.055 | 0.09 | 0.011 | 5.6 | 7% | 0.58 | 0.68 | 0.15 | 0.25 |
| 4 | 590 | 0.110 | 0.14 | 0.018 | 3.1 | 8% | 0.53 | 0.66 | 0.10 | 0.20 |
| 6 | 590 | 0.165 | 0.19 | 0.026 | 2.3 | 9% | 0.28 | 0.51 | 0.05 | 0.20 |
| 10 | 590 | 0.273 | 0.38 | 0.042 | 1.8 | 13% | 0.20 | 0.36 | 0.05 | 0.05 |

<!-- vo-errors:end -->

*Lag-1 autocorrelation* is the correlation between a pair and the next pair. Pairs that overlap share frames, so the
figure for longer gaps includes that overlap. *Correlation time* is the lag at which the autocorrelation first falls
below 1/e. *Outlier share* is the share of pairs whose rotation error exceeds the median by more than five robust
standard deviations.

## The clone against them

<!-- vo-clone:start -->

| Variant | Runs | Median mean NEES | Median 2-sigma coverage | Median final error m | Median claimed sigma m | Meets the gate (NEES < 10, coverage > 90%) |
|---|---:|---:|---:|---:|---:|---|
| IMU only | 5 | 1.5 | 100% | 64.33 | 56.15 | yes |
| anchor, measured errors | 5 | 8030.7 | 6% | 50.86 | 0.27 | no |
| clone, independent errors | 5 | 2.0 | 100% | 0.30 | 0.27 | yes |
| clone, measured correlation | 5 | 5.6 | 93% | 0.51 | 0.27 | yes |
| clone, measured correlation, noise assumed x4 | 5 | 1.4 | 100% | 0.49 | 0.67 | yes |
| replay, anchor | 5 | 16102.0 | 6% | 72.40 | 0.27 | no |
| replay, clone | 5 | 27.2 | 54% | 0.25 | 0.27 | no |
| replay, clone, noise assumed x4 | 5 | 4.1 | 92% | 0.64 | 0.66 | yes |

<!-- vo-clone:end -->

## A wider measurement: six windows, five sequences

The result above is one 30 s window of one sequence, and the replayed error series is one realisation. So the
measurement was widened, with a design fixed in code and committed before it ran
(`WIDE_SEQUENCES`, `WIDE_SCALES` and `pick_window` in `navkit.vo_error`):

- **Windows.** For each Machine Hall sequence, the 30 s window with the highest median ground-truth speed, on a 5 s
  grid, starting no earlier than 30 s. For MH_01 a second window that does not overlap the first. The rule picks windows
  where the camera moves, so that a translation direction exists.
- **Front end.** The same front end, at gaps of one and four frames.
- **Clone.** Replayed with the errors of that window, with the assumed noise set to the window's measured sigmas times
  1, 2, 4 and 8, three seeds each, and the single anchor at 1 for comparison.

The first window was run again with the run aligned to its frames. The first table of this page has five seeds and the
numbers below for that window have three, so they differ slightly.

<!-- vo-wide-errors:start -->

| Sequence | Window start s | Gap, frames | Pairs | Rotation RMS deg | Lateral RMS m | Outlier share | Rotation correlation time s | Lateral correlation time s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MH_01_easy | 60 | 1 | 590 | 0.08 | 0.008 | 2% | 0.20 | 0.25 |
| MH_01_easy | 60 | 4 | 590 | 0.14 | 0.018 | 8% | 0.10 | 0.20 |
| MH_01_easy | 90 | 1 | 595 | 0.09 | 0.006 | 5% | 0.20 | 0.40 |
| MH_01_easy | 90 | 4 | 596 | 0.13 | 0.010 | 6% | 0.10 | 0.20 |
| MH_02_easy | 105 | 1 | 596 | 0.07 | 0.005 | 8% | 0.25 | 0.20 |
| MH_02_easy | 105 | 4 | 596 | 0.09 | 0.007 | 7% | 0.25 | 0.15 |
| MH_03_medium | 80 | 1 | 596 | 0.12 | 0.013 | 6% | 0.05 | 0.05 |
| MH_03_medium | 80 | 4 | 590 | 0.38 | 0.036 | 10% | 0.05 | 0.20 |
| MH_04_difficult | 60 | 1 | 596 | 0.16 | 0.020 | 6% | 0.15 | 0.50 |
| MH_04_difficult | 60 | 4 | 596 | 0.44 | 0.061 | 8% | 0.05 | 0.30 |
| MH_05_difficult | 30 | 1 | 596 | 0.10 | 0.012 | 7% | 0.15 | 0.25 |
| MH_05_difficult | 30 | 4 | 596 | 0.29 | 0.039 | 11% | 0.20 | 0.10 |

<!-- vo-wide-errors:end -->

<!-- vo-wide-clone:start -->

| Sequence | Window start s | clone x1: NEES / coverage | clone x2: NEES / coverage | clone x4: NEES / coverage | clone x8: NEES / coverage | anchor x1: NEES / coverage |
|---|---:|---|---|---|---|---|
| MH_01_easy | 60 | 31.5 / 52% | 12.6 / 67% | 4.49 / 91% ok | 1.88 / 100% ok | 1.13e+05 / 6% |
| MH_01_easy | 90 | 13.5 / 58% | 6.07 / 90% | 2.62 / 100% ok | 1.32 / 100% ok | 1.19e+05 / 5% |
| MH_02_easy | 105 | 4.28 / 100% ok | 3.7 / 100% ok | 1.94 / 100% ok | 1.27 / 100% ok | 1.56e+05 / 5% |
| MH_03_medium | 80 | 3.5 / 100% ok | 2.03 / 100% ok | 1.2 / 100% ok | 1.05 / 100% ok | 9.73e+04 / 7% |
| MH_04_difficult | 60 | 74.3 / 18% | 14.8 / 42% | 2.73 / 99% ok | 1.16 / 100% ok | 9.04e+04 / 9% |
| MH_05_difficult | 30 | 33.4 / 36% | 12.5 / 59% | 3.99 / 100% ok | 1.6 / 100% ok | 1.6e+05 / 6% |
| **Windows meeting the gate** | | 2 of 6 | 2 of 6 | 6 of 6 | 6 of 6 | 0 of 6 |

<!-- vo-wide-clone:end -->

## What it shows

1. **The front end's errors are smaller than the surrogate's.** At one frame the rotation error is 0.08° RMS and the
   lateral error 8 mm, against the surrogate's defaults of 0.35° and 5 cm. The translation has the true scale.
2. **They are correlated for a fraction of a second.** The correlation time is 0.2 s for rotation and 0.25 s for
   translation at one frame, and 0.05 s at ten frames. That is below the 0.5 to 2 s where ADR-0017 found the clone
   failing.
3. **A longer baseline gives a better direction and a larger error in metres.** The direction error falls from 12° at
   a 3 cm baseline to 2° at 27 cm, and the lateral error grows from 8 mm to 42 mm because it is the direction error
   times the baseline.
4. **Outliers grow with the gap.** 2% of one-frame pairs, 13% of ten-frame pairs.
5. **A Gaussian surrogate with the measured size and correlation time passes the gate.** NEES 5.6 and 93% coverage.
6. **The real errors do not.** Replayed at the measured size, the clone has NEES 27 and 54% coverage and fails the
   gate. The surrogate misses what the real error series has beyond a size and a correlation time.
7. **Assuming four times the measured noise brings it back.** NEES 4.1 and 92% coverage in this window. That is the
   factor ADR-0017 found by trial.
8. **The single anchor fails badly on the same errors.** NEES in the tens of thousands and 6% coverage, as in the
   earlier studies.
9. **Vision is worth having.** Dead reckoning on the IMU alone ends the window 64 m off. The clone ends it within
   a metre.
10. **In every window the errors are small and short-lived.** One-frame rotation error is 0.07° to 0.16° RMS and
    lateral error 5 mm to 20 mm. Correlation times run from 0.05 s to 0.5 s; the longest, 0.5 s on the lateral error in
    the MH_04 window, sits at the edge of the range where ADR-0017 found the clone failing.
11. **At the measured noise the clone meets the gate in two of six windows.** In the other four the replayed errors make
    it overconfident. Doubling the assumed noise does not change that count.
12. **At four times the measured noise it meets the gate in all six windows,** across five sequences including the two
    marked difficult. The tightest window has a coverage of 91%, so the margin is thin there. Eight times is also
    inside the gate everywhere, and costs a larger claimed uncertainty.
13. **The single anchor meets the gate in none of the six windows.**

## Limits

Six windows of five sequences, all from one dataset (the EuRoC Machine Hall) and one front end. In each window the
replayed errors are one realisation: the seeds change the simulated GNSS and not the visual errors, so a window's result
has no spread of its own. The front end is mine and plain. The translation has the true scale, which no monocular front
end has. The ground truth is itself an estimate. The conclusion that the clone needs about four times the measured noise
holds for this front end on these windows, and it is not shown for another front end or dataset. `vision_enabled`
stays False.
See [ADR-0023](adr/0023-clone-against-a-measured-front-end.md).
