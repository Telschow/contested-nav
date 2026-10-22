# UrbanNav: recorded IMU and real GNSS outages

The first dataset here with a real GNSS receiver and a real GNSS outage. The reader is `navkit.urbannav_data`, the
measurements below come from `navkit urbannav check`, and the decision behind the dataset is
[ADR-0026](adr/0026-urbannav-as-a-real-gnss-dataset.md). This page says what the files contain, then what the filter
did on the Tunnel-1 recording with the receiver's own fixes and its real outage.

## Read this before quoting anything

- **One sequence, one receiver, one recording.** The five seeds perturb only the start state, so they are not five
  independent tests. This is not field performance.
- **The settings were declared before the first run, with one exception.** The first table below was fixed before the
  filter ran on this data. The second variant (the receiver's sigma per fix) was added after the first result, so it is
  not blind, and it is labelled as such. Neither was tuned on the result.
- **The data is not in the repository (S2).** It is fetched with `navkit urbannav fetch`. The table below comes from a
  committed CSV of aggregate quantities, so CI can check the page and cannot reread the data. The data is MIT licensed
  by its authors, who ask for a citation of Hsu et al. (2023), NAVIGATION.
- **The receiver is the u-blox F9P**, through its own NMEA position fixes. The NovAtel and F9P RINEX files hold raw
  observations only, and positions from them would need navigation files that the download does not contain.
- **The outage rule reads the receiver's fix flag and nothing else.** An epoch is denied when the fix quality is 0 or
  it has no position, and time with no epoch is denied. It was written before any filter ran on this data, and it
  does not look at the reference, the satellite count or how wrong a fix turns out to be.
- **A fix marked valid can be badly wrong.** In the seconds before the receiver gives up, and in the first seconds
  after it recovers, the fixes carry a valid flag and differ from the reference by tens of metres (rows below).
  The rule does not cover them. The filter's gate has to catch them, and how well it does is a result.
- **The reference is an estimate.** It is a post-processed NovAtel SPAN-CPT solution at 1 Hz. Through the tunnel it is
  carried by that unit's inertial sensors alone, and its error there is unknown. Scores against it inside the outage
  are scores against an estimate. Its quality column has six codes, and what each means has not been confirmed.
- **The fixes are not the simulated ones.** They differ from the reference by metres, with a long tail, where the
  simulated GNSS of the other pages differs by a fraction of a metre. The vertical difference is a bias that changes
  between the two sides of the outage, so the height is not usable as given.
- **The two units share one frame.** The dataset's `extrinsic.yaml` gives an identity rotation between the IMU and the
  reference unit, with the body axes x right, y forward, z up. The start attitude is taken from the reference. The
  convention was checked on the data: the reference velocity rotated with it matches the velocity from the positions,
  and the static accelerometer reading rotated with it points up. The antenna offset from the IMU (measured by hand)
  is not corrected.

## What the files contain

<!-- urbannav-data:start -->

| Sequence | Quantity | Value | Unit |
|---|---|---:|---|
| tunnel1 | IMU samples | 159459 | count |
| tunnel1 | IMU time span | 398.6 | s |
| tunnel1 | IMU rate, median | 400.6 | Hz |
| tunnel1 | IMU longest gap | 9.227 | ms |
| tunnel1 | Reference epochs | 401 | count |
| tunnel1 | Reference spacing, median | 1 | s |
| tunnel1 | Distinct reference quality codes | 6 | count |
| tunnel1 | Reference-to-IMU clock offset | 0 | s |
| tunnel1 | Offset search step | 0.01 | s |
| tunnel1 | F9P fixes (GGA sentences) | 401 | count |
| tunnel1 | Epochs with no fix | 151 | count |
| tunnel1 | Outages by the rule | 1 | count |
| tunnel1 | First outage, start (IMU clock) | 137.5 | s |
| tunnel1 | First outage, end (IMU clock) | 288.5 | s |
| tunnel1 | First outage, length | 151 | s |
| tunnel1 | Fix horizontal difference from the reference, median | 1.999 | m |
| tunnel1 | Fix horizontal difference, 95th percentile | 11.33 | m |
| tunnel1 | Fix horizontal difference, largest | 83.25 | m |
| tunnel1 | Last valid fix before the outage, difference | 83.25 | m |
| tunnel1 | Largest difference in the last valid fixes before the outage | 83.25 | m |
| tunnel1 | First valid fix after the outage, difference | 52.76 | m |
| tunnel1 | Largest difference in the first valid fixes after the outage | 52.76 | m |
| tunnel1 | Mean fix height minus reference height, before the outage | -7.63 | m |
| tunnel1 | Mean fix height minus reference height, after the outage | 1.164 | m |

<!-- urbannav-data:end -->

## The run

The filter is the repository's own, with no change to its gating. The settings, generated from the code that runs:

<!-- urbannav-declared:start -->

| Setting | Value | Meaning |
|---|---|---|
| gyro_noise_density | 0.0005236 | rad/s/sqrt(Hz): the larger of 0.03 and 0.01 deg/s/sqrt(Hz) |
| accel_noise_density | 0.0007845 | m/s^2/sqrt(Hz): the larger of 60 and 80 ug/sqrt(Hz) |
| gyro_bias_rw | 2e-06 | rad/s/sqrt(Hz): the repository default |
| accel_bias_rw | 0.0001 | m/s^2/sqrt(Hz): the repository default |
| gnss_horizontal_sigma | receiver | per axis: the root mean square of the receiver's own latitude and longitude sigma over valid fixes |
| gnss_vertical_sigma | 100 | m: declared large because the height is biased |
| start_pose | reference | pose and velocity from the reference at the first IMU sample, perturbed by the filter's start sigmas |
| start_bias | static | estimated from the quietest stretch of the first seconds |
| clock_offset_applied | 0 | s |
| antenna_offset | not corrected | about 0.9 m |
| seeds | 0 1 2 3 4 | perturb the start state only; the data is one recording |
| variant: declared | scalar sigma | the settings above, fixed before the first run |
| variant: per_fix | receiver sigma per fix | added AFTER the first run, because one scalar over-weights the fixes at the tunnel mouth. Not blind |
| variant: oracle_tilt | reference roll and pitch in the outage | ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the roll and pitch are set to the reference's at every IMU step and the yaw is the filter's own. Otherwise the declared settings |
| variant: oracle_yaw | reference yaw in the outage | ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the yaw is set to the reference's at every IMU step and the roll and pitch are the filter's own. Otherwise the declared settings |
| variant: oracle_attitude | reference attitude in the outage | ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the whole attitude is set to the reference's at every IMU step. Otherwise the declared settings |

<!-- urbannav-declared:end -->

**As declared**, one scalar GNSS sigma for every fix:

<!-- urbannav-run-declared:start -->

| Quantity | seed 0 | seed 1 | seed 2 | seed 3 | seed 4 | Unit |
|---|---:|---:|---:|---:|---:|---|
| Horizontal position RMSE over the recording | 4944 | 4786 | 4762 | 4817 | 4836 | m |
| Horizontal mean NEES (2 degrees of freedom, expected 2) | 27.33 | 25.77 | 25.62 | 26.07 | 26.21 |  |
| Share of epochs inside the horizontal 95% ellipse (expected 0.95) | 0.2313 | 0.2373 | 0.2348 | 0.2361 | 0.237 |  |
| Vertical RMSE (the height is almost unused by design) | 35.2 | 30.82 | 30.36 | 31 | 31.97 | m |
| Horizontal error, median before the outage | 7.265 | 7.225 | 7.286 | 7.26 | 7.233 | m |
| Horizontal mean NEES before the outage | 10.2 | 9.956 | 10.15 | 9.993 | 9.934 |  |
| Horizontal error when the outage starts | 15.99 | 15.47 | 15.46 | 15.52 | 15.55 | m |
| Claimed horizontal sigma when the outage starts | 4.378 | 4.378 | 4.378 | 4.378 | 4.378 | m |
| Attitude error when the outage starts | 6.369 | 0.2777 | 0.7097 | 1.399 | 2.041 | deg |
| Peak horizontal error in the outage | 3726 | 3607 | 3588 | 3630 | 3644 | m |
| Horizontal error when the outage ends | 3726 | 3607 | 3589 | 3630 | 3644 | m |
| Claimed horizontal sigma when the outage ends | 529.7 | 529.5 | 529.5 | 529.4 | 529.6 | m |
| Attitude error when the outage ends | 5.439 | 4.309 | 4.841 | 3.858 | 3.743 | deg |
| For comparison: horizontal error from the accelerometer alone with the reference attitude | 426.7 | 426.7 | 426.7 | 426.7 | 426.7 | m |
| Vertical error when the outage ends | 18.09 | 10.4 | 14.81 | 11.44 | 11.81 | m |
| Horizontal mean NEES inside the outage | 19.47 | 18.22 | 18.05 | 18.45 | 18.59 |  |
| Horizontal error, median from 10 s after the outage | 8864 | 8600 | 8559 | 8651 | 8683 | m |
| Roll error when the outage starts (estimate minus reference) | -0.1578 | -0.06654 | -0.05381 | -0.08395 | -0.09397 | deg |
| Pitch error when the outage starts (estimate minus reference) | -0.1452 | -0.1377 | -0.1348 | -0.1396 | -0.1407 | deg |
| Yaw error when the outage starts (estimate minus reference) | 6.369 | 0.2332 | -0.6937 | 1.391 | 2.036 | deg |
| Roll error when the outage ends (estimate minus reference) | -3.789 | -3.697 | -3.682 | -3.715 | -3.726 | deg |
| Pitch error when the outage ends (estimate minus reference) | 0.217 | 0.1596 | 0.1568 | 0.172 | 0.1774 | deg |
| Yaw error when the outage ends (estimate minus reference) | 3.607 | -2.518 | -3.444 | -1.362 | -0.7188 | deg |
| NIS of the first fix after the outage (3 degrees of freedom) | 51 | 47.37 | 46.95 | 48.06 | 48.46 |  |
| Fixes offered after the outage | 111 | 111 | 111 | 111 | 111 | count |
| Of those, over the 0.1% chi-square level | 111 | 111 | 111 | 111 | 111 | count |
| Receiver epochs the reader did not pass on (no fix or no position) | 151 | 151 | 151 | 151 | 151 | count |
| Fixes dropped because a reported variance was negative, NaN or infinite | 0 | 0 | 0 | 0 | 0 | count |
| Fixes with a reported sigma below the filter's floor | 0 | 0 | 0 | 0 | 0 | count |
| The start-bias stretch was judged at rest (1 yes, 0 no) | 0 | 0 | 0 | 0 | 0 | flag |
| Valid fixes offered to the filter | 248 | 248 | 248 | 248 | 248 | count |
| Fixes the filter rejected | 118 | 118 | 118 | 118 | 118 | count |
| GNSS channel declared faulty by the end | 1 | 1 | 1 | 1 | 1 | count |
| Times a faulty channel was taken back | 0 | 0 | 0 | 0 | 0 | count |
| Fixes whose NIS is over the 0.1% chi-square level | 118 | 118 | 118 | 118 | 118 | count |
| Valid fixes over 10 m from the reference | 13 | 13 | 13 | 13 | 13 | count |
| Of those, over the 0.1% chi-square level | 10 | 10 | 10 | 10 | 10 | count |

<!-- urbannav-run-declared:end -->

**Per-fix sigma**, added after the first result. Each fix is weighted with the error estimate the receiver reported
for it:

<!-- urbannav-run-per-fix:start -->

| Quantity | seed 0 | seed 1 | seed 2 | seed 3 | seed 4 | Unit |
|---|---:|---:|---:|---:|---:|---|
| Horizontal position RMSE over the recording | 4760 | 4664 | 4649 | 4688 | 4699 | m |
| Horizontal mean NEES (2 degrees of freedom, expected 2) | 30.33 | 29.12 | 28.99 | 29.4 | 29.49 |  |
| Share of epochs inside the horizontal 95% ellipse (expected 0.95) | 0.2236 | 0.2311 | 0.229 | 0.229 | 0.2301 |  |
| Vertical RMSE (the height is almost unused by design) | 33.76 | 32.59 | 31.74 | 32.33 | 32.93 | m |
| Horizontal error, median before the outage | 2.935 | 2.849 | 2.858 | 2.867 | 2.864 | m |
| Horizontal mean NEES before the outage | 20.32 | 19.46 | 19.51 | 19.63 | 19.59 |  |
| Horizontal error when the outage starts | 8.994 | 8.024 | 7.91 | 8.236 | 8.328 | m |
| Claimed horizontal sigma when the outage starts | 3.919 | 3.919 | 3.92 | 3.919 | 3.92 | m |
| Attitude error when the outage starts | 4.489 | 0.4263 | 0.2367 | 1.409 | 1.827 | deg |
| Peak horizontal error in the outage | 3574 | 3503 | 3491 | 3520 | 3529 | m |
| Horizontal error when the outage ends | 3574 | 3503 | 3491 | 3521 | 3529 | m |
| Claimed horizontal sigma when the outage ends | 514.3 | 514.3 | 514.3 | 514.3 | 514.3 | m |
| Attitude error when the outage ends | 4.196 | 4.158 | 4.482 | 3.781 | 3.693 | deg |
| For comparison: horizontal error from the accelerometer alone with the reference attitude | 426.7 | 426.7 | 426.7 | 426.7 | 426.7 | m |
| Vertical error when the outage ends | 6.03 | 2.527 | 0.6393 | 1.26 | 0.6926 | m |
| Horizontal mean NEES inside the outage | 19.04 | 18.22 | 18.08 | 18.41 | 18.5 |  |
| Horizontal error, median from 10 s after the outage | 8536 | 8378 | 8352 | 8417 | 8435 | m |
| Roll error when the outage starts (estimate minus reference) | -0.06422 | -0.008905 | -0.0008733 | -0.02251 | -0.02826 | deg |
| Pitch error when the outage starts (estimate minus reference) | -0.1307 | -0.1243 | -0.1226 | -0.126 | -0.1269 | deg |
| Yaw error when the outage starts (estimate minus reference) | 4.488 | 0.4078 | -0.2024 | 1.403 | 1.823 | deg |
| Roll error when the outage ends (estimate minus reference) | -3.682 | -3.625 | -3.616 | -3.639 | -3.646 | deg |
| Pitch error when the outage ends (estimate minus reference) | 0.1661 | 0.1342 | 0.1328 | 0.1432 | 0.1459 | deg |
| Yaw error when the outage ends (estimate minus reference) | 1.736 | -2.337 | -2.946 | -1.343 | -0.9246 | deg |
| NIS of the first fix after the outage (3 degrees of freedom) | 49.74 | 47.52 | 47.25 | 48.04 | 48.28 |  |
| Fixes offered after the outage | 111 | 111 | 111 | 111 | 111 | count |
| Of those, over the 0.1% chi-square level | 111 | 111 | 111 | 111 | 111 | count |
| Receiver epochs the reader did not pass on (no fix or no position) | 151 | 151 | 151 | 151 | 151 | count |
| Fixes dropped because a reported variance was negative, NaN or infinite | 0 | 0 | 0 | 0 | 0 | count |
| Fixes with a reported sigma below the filter's floor | 0 | 0 | 0 | 0 | 0 | count |
| The start-bias stretch was judged at rest (1 yes, 0 no) | 0 | 0 | 0 | 0 | 0 | flag |
| Valid fixes offered to the filter | 248 | 248 | 248 | 248 | 248 | count |
| Fixes the filter rejected | 111 | 111 | 111 | 111 | 111 | count |
| GNSS channel declared faulty by the end | 1 | 1 | 1 | 1 | 1 | count |
| Times a faulty channel was taken back | 0 | 0 | 0 | 0 | 0 | count |
| Fixes whose NIS is over the 0.1% chi-square level | 111 | 111 | 111 | 111 | 111 | count |
| Valid fixes over 10 m from the reference | 13 | 13 | 13 | 13 | 13 | count |
| Of those, over the 0.1% chi-square level | 3 | 3 | 3 | 3 | 3 | count |

<!-- urbannav-run-per-fix:end -->

**Oracle diagnostics.** These are not filters. They use the reference, to find out where the outage error comes
from. Inside the outage, at every IMU step, part of the filter's attitude is replaced by the reference's, and
everything else is the declared filter. Outside the outage they are the declared filter, so they start from the same
place. One sequence, one receiver; the seeds perturb only the start state.

<!-- urbannav-run-oracle:start -->

| Variant | Quantity | seed 0 | seed 1 | seed 2 | seed 3 | seed 4 | Unit |
|---|---|---:|---:|---:|---:|---:|---|
| declared filter | Horizontal error when the outage ends | 3726 | 3607 | 3589 | 3630 | 3644 | m |
|  | Fixes the filter rejected | 118 | 118 | 118 | 118 | 118 | count |
| ORACLE DIAGNOSTIC: reference roll and pitch in the outage | Horizontal error when the outage ends | 159.8 | 115 | 108.7 | 122.9 | 127.3 | m |
|  | Fixes the filter rejected | 16 | 16 | 16 | 16 | 16 | count |
| ORACLE DIAGNOSTIC: reference yaw in the outage | Horizontal error when the outage ends | 3738 | 3607 | 3586 | 3632 | 3648 | m |
|  | Fixes the filter rejected | 118 | 118 | 118 | 118 | 118 | count |
| ORACLE DIAGNOSTIC: reference attitude in the outage | Horizontal error when the outage ends | 148.9 | 117.6 | 113.7 | 122.6 | 125.5 | m |
|  | Fixes the filter rejected | 16 | 16 | 16 | 16 | 16 | count |

<!-- urbannav-run-oracle:end -->

The last rows of the two run tables above are counts from the data: the receiver epochs the reader did not pass on
(no fix or no position), the fixes dropped for a negative, NaN or infinite reported variance, and the fixes whose
reported sigma is below the filter's floor, which the filter raises to the floor. The filter raises an error on an
unusable variance, so the run drops such a fix before the filter sees it and reports how many.

### What the run shows

Every statement is about one sequence and one receiver, and points at rows of the generated tables above.

1. **With GNSS available the filter is already inconsistent on this sequence.** The horizontal mean NEES before the
   outage is above its expected value in both variants and every seed. The yaw error when the outage starts reaches
   several degrees on one of the five seeds. Neither is caused by the outage. This does not say how much comes from the start attitude
   and how much from the IMU model.
2. **The outage error is driven by tilt error (roll and pitch) inside the outage.** The roll error when the outage
   ends is far larger than when it starts. The pitch error is small at both moments, so the rows do not show pitch
   growing, and the oracle row for roll and pitch together does not separate the two. The horizontal error at the
   end is several times the sigma the filter claims. Integrating the accelerometer with the reference attitude and no gyroscope gives an error that is a
   small fraction of the filter's. The oracle rows separate the cause: with the reference roll and pitch inside the
   outage the end error falls by an order of magnitude, and with the reference yaw alone it does not change. A tilt
   error leaks gravity into horizontal acceleration, so the position error grows with the square of time. The oracle
   rows say where the error comes from. They are not a better filter.
3. **A link between statement 1, the inconsistency before the outage, and statement 2, the tilt growth in the
   outage, is not shown.** At the start of the outage the tilt error is small and the yaw error does not drive the outage error.
4. **The lost channel is a consequence of the position error, not a separate finding.** The gate rejects every fix after
   the outage, including the first, whose NIS is several times the 0.1% chi-square level, and the channel is declared
   faulty and never taken back (rows "NIS of the first fix after the outage" and "Fixes offered after the outage").
   That follows from an error many times the claimed sigma. With the reference roll and pitch inside the outage,
   far fewer fixes are rejected. This is the lockout behaviour of the existing gate, reached on real data.
5. **Before the tunnel, weighting each fix by the receiver's own sigma follows the fixes more closely**, and the filter
   is still not calibrated: the normalised error is above its expected value in both variants. The receiver's own sigma
   is optimistic against the reference. Note (2026-10-22): the sentence holds under the rule of
   [ADR-0029](adr/0029-how-a-single-runs-verdict-is-formed.md), which forms a single run's verdict with the effective
   sample size. The bulk verdict of the horizontal normalised error before the outage is overconfident for both
   variants on all five seeds. For the scalar variant the effective sample size is a handful of samples and
   truncated, so an upper bound; for the per-fix variant it is a little larger and not truncated. The result was
   recomputed once, to a scratch path, measured once on one machine, not checked by CI. The committed tables are
   unchanged.
6. **The receiver's sigma already marks the worst fixes.** The fixes just before the receiver gives up are far from the
   reference and carry a large reported sigma. The scalar variant rejects most of the wrong ones. The per-fix variant
   accepts most of them, because it believes the sigma that came with them.
7. **The start biases were a guess.** The stretch used to estimate them is judged not at rest, because the vehicle moves
   off within seconds of the start. The accelerometer-only comparison does not depend on it.
8. **The seeds agree**, because the start perturbation is small against the effect.

### What the run does not show

- It does not say how another IMU, another tunnel or a better start alignment would do. The Xsens MTi-10 is an
  industrial MEMS unit, and its noise figures were declared from two datasheets that disagree.
- The reference in the tunnel is carried by its own inertial sensors, so the scores inside the outage are against an
  estimate. Its error there is unknown. The gap between it and the filter is far larger than the accelerometer-only
  drift, so it is not plausibly all reference error.
- The antenna offset from the IMU is not corrected, and the height is almost unused by design.
- **The cause of the tilt growth is not shown.** HYPOTHESIS, not tested here: the gyroscope bias, and so the tilt, is
  weakly observable during driving at roughly constant velocity. The tilt growth is of the same size as a gyroscope
  bias inferred from the data over the stretch before the outage, but starting the filter from the inferred biases in
  a scratch run (no code in the repository reproduces it) still ended with a kilometre-scale error, so the growth is
  not explained.
- Deep-Urban-1, the planned unseen check, has not been fetched or run.

## What it shows about the data

1. **One real outage.** The F9P reports no fix for one continuous stretch, and the rule finds a single outage there.
2. **No clock offset was applied.** The offset search above returned zero within its step. The reference is 1 Hz and
   the search uses only the yaw axis, so it cannot rule out a shift of a fraction of a second. The method was checked
   by shifting a synthetic reference by known amounts, and it recovered each.
3. **The edges of the outage are the hard part.** The fixes just before the receiver gives up are the worst of the
   valid ones, and the first fixes after it recovers are wrong too.

## What follows

The attitude is the next thing to understand: a run that starts from a better alignment, or that holds the gyroscope
bias, would show how much of this is the start and how much is the sensor. The planned unseen check on Deep-Urban-1
needs its NMEA file. See [ADR-0026](adr/0026-urbannav-as-a-real-gnss-dataset.md).
