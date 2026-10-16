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

<!-- urbannav-declared:end -->

**As declared**, one scalar GNSS sigma for every fix:

<!-- urbannav-run-declared:start -->

| Quantity | seed 0 | seed 1 | seed 2 | seed 3 | seed 4 | Unit |
|---|---:|---:|---:|---:|---:|---|
| Horizontal position RMSE over the recording | 4878 | 4776 | 4733 | 4806 | 4797 | m |
| Horizontal mean NEES (2 degrees of freedom, expected 2) | 26.9 | 25.87 | 25.55 | 26.16 | 26.06 |  |
| Share of epochs inside the horizontal 95% ellipse (expected 0.95) | 0.2334 | 0.2376 | 0.2353 | 0.2363 | 0.2377 |  |
| Vertical RMSE (the height is almost unused by design) | 33.68 | 30.57 | 29.67 | 30.74 | 30.89 | m |
| Horizontal error, median before the outage | 7.28 | 7.235 | 7.295 | 7.269 | 7.244 | m |
| Horizontal mean NEES before the outage | 10.18 | 9.972 | 10.17 | 10.01 | 9.947 |  |
| Horizontal error when the outage starts | 15.71 | 15.41 | 15.38 | 15.46 | 15.44 | m |
| Claimed horizontal sigma when the outage starts | 4.413 | 4.414 | 4.413 | 4.414 | 4.413 | m |
| Attitude error when the outage starts | 4.111 | 0.1512 | 1.6 | 1.144 | 0.7914 | deg |
| Peak horizontal error in the outage | 3675 | 3598 | 3566 | 3620 | 3613 | m |
| Horizontal error when the outage ends | 3675 | 3598 | 3566 | 3620 | 3614 | m |
| Claimed horizontal sigma when the outage ends | 530.8 | 531 | 531 | 531 | 530.9 | m |
| Attitude error when the outage ends | 4.09 | 4.431 | 5.46 | 3.932 | 4.062 | deg |
| For comparison: horizontal error from the accelerometer alone with the reference attitude | 426.7 | 426.7 | 426.7 | 426.7 | 426.7 | m |
| Vertical error when the outage ends | 20.41 | 10.59 | 15.82 | 11.51 | 13.09 | m |
| Horizontal mean NEES inside the outage | 19.05 | 18.27 | 17.96 | 18.49 | 18.42 |  |
| Horizontal error, median from 10 s after the outage | 8753 | 8582 | 8509 | 8631 | 8616 | m |
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
| Horizontal position RMSE over the recording | 4720 | 4651 | 4631 | 4671 | 4670 | m |
| Horizontal mean NEES (2 degrees of freedom, expected 2) | 29.95 | 29.06 | 28.89 | 29.3 | 29.26 |  |
| Share of epochs inside the horizontal 95% ellipse (expected 0.95) | 0.2266 | 0.2319 | 0.2298 | 0.2289 | 0.2315 |  |
| Vertical RMSE (the height is almost unused by design) | 32.55 | 32.14 | 31.16 | 31.79 | 31.93 | m |
| Horizontal error, median before the outage | 2.922 | 2.856 | 2.863 | 2.87 | 2.862 | m |
| Horizontal mean NEES before the outage | 20.13 | 19.47 | 19.5 | 19.62 | 19.52 |  |
| Horizontal error when the outage starts | 8.599 | 7.962 | 7.822 | 8.127 | 8.113 | m |
| Claimed horizontal sigma when the outage starts | 3.93 | 3.931 | 3.93 | 3.93 | 3.93 | m |
| Attitude error when the outage starts | 2.892 | 0.13 | 0.8434 | 0.8062 | 0.7478 | deg |
| Peak horizontal error in the outage | 3543 | 3492 | 3477 | 3507 | 3506 | m |
| Horizontal error when the outage ends | 3543 | 3492 | 3477 | 3507 | 3506 | m |
| Claimed horizontal sigma when the outage ends | 514.7 | 514.7 | 514.6 | 514.7 | 514.7 | m |
| Attitude error when the outage ends | 3.675 | 4.392 | 4.878 | 3.985 | 4.01 | deg |
| For comparison: horizontal error from the accelerometer alone with the reference attitude | 426.7 | 426.7 | 426.7 | 426.7 | 426.7 | m |
| Vertical error when the outage ends | 7.314 | 2.102 | 1.254 | 0.7907 | 0.2571 | m |
| Horizontal mean NEES inside the outage | 18.72 | 18.14 | 17.98 | 18.3 | 18.29 |  |
| Horizontal error, median from 10 s after the outage | 8469 | 8354 | 8321 | 8388 | 8386 | m |
| The start-bias stretch was judged at rest (1 yes, 0 no) | 0 | 0 | 0 | 0 | 0 | flag |
| Valid fixes offered to the filter | 248 | 248 | 248 | 248 | 248 | count |
| Fixes the filter rejected | 111 | 111 | 111 | 111 | 111 | count |
| GNSS channel declared faulty by the end | 1 | 1 | 1 | 1 | 1 | count |
| Times a faulty channel was taken back | 0 | 0 | 0 | 0 | 0 | count |
| Fixes whose NIS is over the 0.1% chi-square level | 111 | 111 | 111 | 111 | 111 | count |
| Valid fixes over 10 m from the reference | 13 | 13 | 13 | 13 | 13 | count |
| Of those, over the 0.1% chi-square level | 3 | 3 | 3 | 3 | 3 | count |

<!-- urbannav-run-per-fix:end -->

### What the run shows

1. **Through the real outage the filter is wrong and far more confident than it should be.** The horizontal error at
   the end of the outage is several times the sigma the filter claims, in both variants and every seed.
2. **The drift is much more than the accelerometer alone would give.** Integrating the accelerometer with the reference
   attitude and no gyroscope gives an error that is a small fraction of the filter's. The filter's attitude error
   grows to several degrees across the outage. That fits the attitude as the driver. No run here removes the attitude
   error, so it is not shown to be the cause.
3. **The GNSS channel is lost for good.** After the outage the gate rejects every fix, the channel is declared faulty
   and it is never taken back, so the error keeps growing to the end of the recording. This is the lockout behaviour of
   the existing gate, reached here on real data. The filter has no way to recover from an error this large.
4. **Before the tunnel, weighting each fix by the receiver's own sigma follows the fixes more closely**, and the
   filter is still not calibrated: the normalised error is above its expected value in both variants. The receiver's own
   sigma is optimistic against the reference.
5. **The receiver's sigma already marks the worst fixes.** The fixes just before the receiver gives up are far from the
   reference and carry a large reported sigma. The scalar variant rejects most of the wrong ones. The per-fix variant
   accepts most of them, because it believes the sigma that came with them.
6. **The start biases were a guess.** The stretch used to estimate them is judged not at rest, because the vehicle moves
   off within seconds of the start. The accelerometer-only comparison does not depend on it.
7. **The seeds agree**, because the start perturbation is small against the effect.

### What this does not show

- It does not say how another IMU, another tunnel or a better start alignment would do. The Xsens MTi-10 is an
  industrial MEMS unit, and its noise figures were declared from two datasheets that disagree.
- The reference in the tunnel is carried by its own inertial sensors, so the scores inside the outage are against an
  estimate. Its error there is unknown. The gap between it and the filter is far larger than the accelerometer-only
  drift, so it is not plausibly all reference error.
- The antenna offset from the IMU is not corrected, and the height is almost unused by design.
- Deep-Urban-1, the planned unseen check, has not been fetched or run.

## What it shows about the data

1. **One real outage.** The F9P reports no fix for one continuous stretch, and the rule finds a single outage there.
2. **The two clocks agree.** The offset between the reference and the IMU is within one search step of zero. The
   method was checked by shifting a synthetic reference by known amounts, and it recovered each. The 1 Hz reference
   limits how sharply it can say so, and the estimate uses only the yaw axis.
3. **The edges of the outage are the hard part.** The fixes just before the receiver gives up are the worst of the
   valid ones, and the first fixes after it recovers are wrong too.

## What follows

The attitude is the next thing to understand: a run that starts from a better alignment, or that holds the gyroscope
bias, would show how much of this is the start and how much is the sensor. The planned unseen check on Deep-Urban-1
needs its NMEA file. See [ADR-0026](adr/0026-urbannav-as-a-real-gnss-dataset.md).
