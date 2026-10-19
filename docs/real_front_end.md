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
| IMU only | 5 | 1.4 | 100% | 66.48 | 49.68 | yes |
| anchor, measured errors | 5 | 8032.3 | 6% | 50.86 | 0.27 | no |
| clone, independent errors | 5 | 2.1 | 100% | 0.31 | 0.27 | yes |
| clone, measured correlation | 5 | 4.7 | 97% | 0.51 | 0.27 | yes |
| clone, measured correlation, noise assumed x4 | 5 | 1.3 | 100% | 0.49 | 0.67 | yes |
| replay, anchor | 5 | 16089.8 | 6% | 72.37 | 0.27 | no |
| replay, clone | 5 | 27.9 | 55% | 0.24 | 0.27 | no |
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
| MH_01_easy | 60 | 32.2 / 53% | 12.8 / 67% | 4.53 / 91% ok | 1.88 / 100% ok | 1.13e+05 / 6% |
| MH_01_easy | 90 | 14.1 / 58% | 6.16 / 87% | 2.6 / 100% ok | 1.35 / 100% ok | 1.19e+05 / 5% |
| MH_02_easy | 105 | 5.32 / 100% ok | 3.98 / 100% ok | 1.99 / 100% ok | 1.3 / 100% ok | 1.56e+05 / 5% |
| MH_03_medium | 80 | 3.46 / 100% ok | 2.04 / 100% ok | 1.21 / 100% ok | 1.07 / 100% ok | 9.74e+04 / 7% |
| MH_04_difficult | 60 | 69.9 / 19% | 14.6 / 42% | 2.74 / 99% ok | 1.15 / 100% ok | 9.06e+04 / 9% |
| MH_05_difficult | 30 | 33.6 / 37% | 12.8 / 59% | 4.09 / 100% ok | 1.62 / 100% ok | 1.6e+05 / 6% |
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

## The supported setting

For a feature-tracking two-view front end like this one, the supported assumption for the opt-in clone is four times
the measured visual noise ([ADR-0024](adr/0024-assumed-noise-for-the-opt-in-clone.md)). It is a named setting:
`vision_noise_preset: measured-front-end` in a scenario file (with `vision_model: clone`), or
`RunOptions.vision_noise_preset` for recorded data. It is off unless asked for, and `vision_enabled` stays False. It is
an empirical value for this front end on these windows, not a derived constant.

## Reproducing these rows

Three files in `docs/data/` hold what this page reports.

- `vo_errors.csv` holds the front-end rows, one per tracked pair.
- `vo_clone_check.csv` holds the clone runs of the first window.
- `vo_wide.csv` holds the clone runs of the six windows.

The tables above are generated from them and checked against them by `tests/test_vo_page.py`. The two clone files are
replayed from the front-end rows, so they need the EuRoC ground truth and IMU files and no camera frames. Write every
output to a scratch path first and compare, because `--csv` and `--wide-csv` overwrite the file they are given.

```bash
navkit euroc vo --root data/raw/euroc --from-csv docs/data/vo_errors.csv --clone --clone-csv scratch/clone.csv
navkit euroc vo --root data/raw/euroc --from-csv docs/data/vo_errors.csv --wide-replay --wide-csv scratch/wide.csv
navkit euroc vo --sequence MH_01_easy --root data/raw/euroc --csv scratch/first_window.csv
cp docs/data/vo_errors.csv scratch/vo_errors.csv
navkit euroc vo --wide --root data/raw/euroc --csv scratch/vo_errors.csv --wide-csv scratch/wide_full.csv
```

The first command regenerates `vo_clone_check.csv` and the second regenerates `vo_wide.csv`. The third measures the
first window and the fourth measures the wider windows, which needs their frames and takes an hour or more. The fourth
needs the first window's rows already in its `--csv` file, so that it picks the same windows, and it appends the new rows
to that file.

Reproduced, on main at commit a79b935 on 2026-10-19:

- `vo_clone_check.csv` and `vo_wide.csv` came out byte for byte the same from the first two commands.
- The front-end rows of `vo_errors.csv` matched exactly, in every column, for the first window and for each of the five
  wider windows. They were regenerated with the measurement call that the third and fourth commands make, one window at
  a time. For one window it was run twice, once with only that window's frames on disk and once with all of that
  sequence's frames. The two runs gave the same rows. The third and fourth commands themselves were not run end to end.

This was measured once on one machine, not checked by CI. CI cannot run it, because the EuRoC frames are not vendored.
A different machine, NumPy build or library version could change the last digits, and the tests above read the
committed files instead.

## Limits

Six windows of five sequences, all from one dataset (the EuRoC Machine Hall) and one front end. In each window the
replayed errors are one realisation: the seeds change the simulated GNSS and not the visual errors, so a window's result
has no spread of its own. The front end is mine and plain. The translation has the true scale, which no monocular front
end has. The ground truth is itself an estimate. The conclusion that the clone needs about four times the measured noise
holds for this front end on these windows, and it is not shown for another front end or dataset. `vision_enabled`
stays False.
See [ADR-0023](adr/0023-clone-against-a-measured-front-end.md).
