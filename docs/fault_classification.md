# Telling multipath, spoofing and degradation apart

Track A asks for more than "this channel is faulty". This page measures whether the GNSS innovations alone can say
which of three causes is behind a fault, on real recorded IMU data with simulated GNSS. It is a feasibility study. It
does not ship a detector.

## Method

A fault is injected 35 s into each recording (EuRoC, TUM VI), in the calibrated bias-walk setting, two seeds:

- **Multipath**: extra white noise of 3, 10 or 30 m per axis on every fix for 20 s. No mean shift.
- **Spoofing**: a ramp of 0.5, 1, 2 or 5 m/s, or a step offset of 10 or 50 m, on the GNSS positions.
- **Degradation**: a constant added to the accelerometer (0.2 or 1 m/s²) or the gyroscope (0.01 or 0.05 rad/s),
  spread over three axes. The GNSS is healthy; the IMU is wrong.
- **Control**: nothing.

Five features are read from the GNSS innovations of the 20 s after the onset: *nis* (the mean normalised innovation
squared, about 1 when healthy), *mean_shift* (the size of the whitened mean innovation, scaled by the square root of
the count), *drift_m_s* (the slope of the innovation over time), *bias_accel* and *bias_gyro* (how far the filter's
bias estimates moved).

Two stages. Stage 1 asks whether anything is wrong: a fault is called when any feature exceeds its largest value on
the training controls. Stage 2 names the cause with a small decision tree trained on faults only, with each class
weighted equally. A single tree over four classes was tried first and learned the class sizes: the control is a
twelfth of the runs, so it called the control a spoof. Everything is cross-validated leaving one sequence out, so a
run is never called by a model that saw its own sequence.

Simulated GNSS, injected faults, a decision tree on five features, two datasets. It is not the best possible
classifier. It tells what the innovations can carry, not what no classifier could.

## The features

Median of each feature by fault and level.

<!-- faultclass-features:start -->

| Fault | Level | nis | mean_shift | drift_m_s | bias_accel | bias_gyro |
|---|---:|---:|---:|---:|---:|---:|
| none | 0 | 1.03 | 0.967 | 0.0187 | 0.0945 | 0.00241 |
| multipath | 3 | 8.7 | 19.2 | 0.655 | 0.138 | 0.00238 |
| multipath | 10 | 37.2 | 31.3 | 2.47 | 0.08 | 0.00184 |
| multipath | 30 | 210 | 32.8 | 1.45 | 0.0433 | 0.0006 |
| ramp | 0.5 | 1.05 | 0.944 | 0.0247 | 0.0935 | 0.00194 |
| ramp | 1 | 1.17 | 1.26 | 0.0385 | 0.114 | 0.00194 |
| ramp | 2 | 1.34 | 1.84 | 0.0607 | 0.154 | 0.004 |
| ramp | 5 | 20.3 | 71.3 | 4.36 | 0.117 | 0.00304 |
| step | 10 | 7.8 | 24.2 | 0.799 | 0.205 | 0.0038 |
| step | 50 | 154 | 137 | 1.95 | 0.13 | 0.00275 |
| accel_bias | 0.2 | 1.08 | 1.42 | 0.032 | 0.166 | 0.00274 |
| accel_bias | 1 | 1.66 | 4.9 | 0.132 | 0.663 | 0.00383 |
| gyro_bias | 0.01 | 1.18 | 5.37 | 0.0306 | 0.218 | 0.00739 |
| gyro_bias | 0.05 | 109 | 144 | 11.4 | 0.219 | 0.00541 |

<!-- faultclass-features:end -->

## Calls, by true class

<!-- faultclass-confusion:start -->

| True class | Runs | Called control | Called multipath | Called spoofing | Called degradation |
|---|---:|---:|---:|---:|---:|
| control | 34 | 85% | 0% | 9% | 6% |
| multipath | 102 | 0% | 97% | 2% | 1% |
| spoofing | 204 | 15% | 25% | 38% | 22% |
| degradation | 136 | 10% | 1% | 4% | 85% |

<!-- faultclass-confusion:end -->

## Calls, by fault and level

<!-- faultclass-levels:start -->

| Class | Fault | Level | Runs | Called correctly | Called control (missed) |
|---|---|---:|---:|---:|---:|
| control | none | 0 | 34 | 85% | 85% | 15% |
| multipath | multipath | 3 | 34 | 97% | 0% | 100% |
| multipath | multipath | 10 | 34 | 97% | 0% | 100% |
| multipath | multipath | 30 | 34 | 97% | 0% | 100% |
| spoofing | ramp | 0.5 | 34 | 24% | 56% | 44% |
| spoofing | ramp | 1 | 34 | 50% | 24% | 76% |
| spoofing | ramp | 2 | 34 | 50% | 12% | 88% |
| spoofing | ramp | 5 | 34 | 9% | 0% | 100% |
| spoofing | step | 10 | 34 | 15% | 0% | 100% |
| spoofing | step | 50 | 34 | 82% | 0% | 100% |
| degradation | accel_bias | 0.2 | 34 | 56% | 35% | 65% |
| degradation | accel_bias | 1 | 34 | 94% | 0% | 100% |
| degradation | gyro_bias | 0.01 | 34 | 94% | 6% | 94% |
| degradation | gyro_bias | 0.05 | 34 | 94% | 0% | 100% |

<!-- faultclass-levels:end -->

## What it shows

1. **Multipath is separable.** Noise on the fixes raises the normalised innovation without a matching shift, and
   97% of multipath runs are called multipath at every size, including 3 m.
2. **Strong faults are detected, weak ones are not.** Every multipath run, every step, and the larger bias steps are
   detected. A 0.5 m/s ramp is detected in under half the runs, and a 0.2 m/s² accelerometer bias in about two
   thirds.
3. **The false-alarm rate is not zero.** About one in seven held-out control runs is called a fault. The stage 1
   thresholds make the training controls clean and the held-out ones are not.
4. **Spoofing is the class that is confused.** Fewer than half the spoofed runs are called spoofing. A 10 m step is
   mostly called multipath, because the filter absorbs the offset within seconds and what is left in the window
   looks like a burst. A 5 m/s ramp is mostly called multipath or degradation.
5. **Degradation is mostly separable when it is large.** The larger bias steps and the gyroscope steps are called
   degradation in at least 94% of runs. The small accelerometer step is not.

## What follows

The Track A exit test, 95% detection per fault type at zero false alarms on the control, is not met on any of its
three terms: detection of weak spoofs, the false-alarm rate, and the separation of spoofing from the other two. The
innovations carry enough to call multipath and large faults, and not enough to name a spoof. A second feature source
would be needed: the structure of the innovation over time, a second sensor, or the bias estimates over a longer
window. None of that is tested. See [ADR-0021](adr/0021-fault-classification-from-innovations.md). The shipped
configuration is unchanged.
