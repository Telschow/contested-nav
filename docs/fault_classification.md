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

Features are read from the GNSS innovations of the 20 s after the onset. The first five are *nis* (the mean
normalised innovation squared, about 1 when healthy), *mean_shift* (the size of the whitened mean innovation, scaled
by the square root of the count), *drift_m_s* (the slope of the innovation over time), *bias_accel* and *bias_gyro*
(how far the filter's bias estimates moved).

A second round added five, to see whether richer innovations help: *ac1* (the lag-1 autocorrelation of the whitened
innovation, near 0 for white noise and near 1 for a persistent offset), *axis_conc* (the share of the innovation's
second moment along its dominant axis), *decay* (the innovation size in the last 5 s of the window over the first 5 s),
and *bias_accel_30* and *bias_gyro_30* (the bias movement over 30 s). **These five were chosen after the first round
showed a 10 m step being called multipath.** The cross-validation does not remove that: it protects against fitting a
model to its own sequence, not against designing features to fix a failure seen on the same data. A confirmation needs
runs the choice never saw, such as other fault sizes and more seeds.

Two stages. Stage 1 asks whether anything is wrong: a fault is called when any feature exceeds its largest value on
the training controls. Stage 2 names the cause with a small decision tree trained on faults only, with each class
weighted equally. A single tree over four classes was tried first and learned the class sizes: the control is a
twelfth of the runs, so it called the control a spoof. Everything is cross-validated leaving one sequence out, so a
run is never called by a model that saw its own sequence.

Simulated GNSS, injected faults, a decision tree on five features, two datasets. It is not the best possible
classifier. It tells what the innovations can carry, not what no classifier could.

## The two feature sets

The same cross-validation with the original five features and with all ten.

<!-- faultclass-compare:start -->

| Features | Control called a fault | Multipath called multipath | Spoofing called spoofing | Degradation called degradation | 10 m step called multipath | 0.5 m/s ramp detected |
|---|---:|---:|---:|---:|---:|---:|
| original five | 9% | 98% | 40% | 85% | 79% | 29% |
| all ten | 12% | 99% | 70% | 87% | 0% | 32% |

<!-- faultclass-compare:end -->

## The features

Median of each feature by fault and level.

<!-- faultclass-features:start -->

| Fault | Level | nis | mean_shift | drift_m_s | bias_accel | bias_gyro | ac1 | axis_conc | decay | bias_accel_30 | bias_gyro_30 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 0 | 1.06 | 0.775 | 0.0188 | 0.0737 | 0.00216 | 0.0485 | 0.411 | 0.945 | 0.0804 | 0.00254 |
| multipath | 3 | 8.46 | 18 | 0.619 | 0.108 | 0.00215 | 0.429 | 0.695 | 1.02 | 0.139 | 0.00317 |
| multipath | 10 | 37.2 | 31.9 | 2.59 | 0.0931 | 0.00209 | 0.186 | 0.756 | 0.451 | 0.093 | 0.00321 |
| multipath | 30 | 217 | 30.8 | 1.68 | 0.0369 | 0.00055 | 0.0463 | 0.419 | 0.0468 | 0.0887 | 0.00169 |
| ramp | 0.5 | 1.07 | 0.893 | 0.0267 | 0.0797 | 0.00207 | 0.0739 | 0.406 | 0.981 | 0.0849 | 0.00247 |
| ramp | 1 | 1.17 | 1.06 | 0.0412 | 0.105 | 0.00314 | 0.119 | 0.401 | 1.03 | 0.097 | 0.00316 |
| ramp | 2 | 1.37 | 1.71 | 0.0676 | 0.148 | 0.00493 | 0.236 | 0.437 | 0.858 | 0.12 | 0.00439 |
| ramp | 5 | 20.2 | 72.3 | 4.15 | 0.0978 | 0.00226 | 0.988 | 0.998 | 0.454 | 0.171 | 0.00316 |
| step | 10 | 7.54 | 24.5 | 0.73 | 0.165 | 0.00466 | 0.878 | 0.967 | 0.0501 | 0.129 | 0.00352 |
| step | 50 | 160 | 137 | 2.13 | 0.128 | 0.00311 | 0.963 | 0.997 | 0.0202 | 0.165 | 0.00422 |
| accel_bias | 0.2 | 1.08 | 1.33 | 0.0329 | 0.169 | 0.00281 | 0.101 | 0.411 | 0.906 | 0.177 | 0.00303 |
| accel_bias | 1 | 1.66 | 5.13 | 0.131 | 0.698 | 0.00365 | 0.381 | 0.542 | 0.732 | 0.78 | 0.00322 |
| gyro_bias | 0.01 | 1.2 | 5.4 | 0.0302 | 0.203 | 0.00663 | 0.162 | 0.409 | 1.19 | 0.184 | 0.00864 |
| gyro_bias | 0.05 | 108 | 145 | 11.5 | 0.208 | 0.00527 | 0.984 | 0.996 | 158 | 0.208 | 0.00585 |

<!-- faultclass-features:end -->

## Calls, by true class (all ten features)

<!-- faultclass-confusion:start -->

| True class | Runs | Called control | Called multipath | Called spoofing | Called degradation |
|---|---:|---:|---:|---:|---:|
| control | 34 | 88% | 0% | 9% | 3% |
| multipath | 102 | 0% | 99% | 0% | 1% |
| spoofing | 204 | 16% | 0% | 70% | 14% |
| degradation | 136 | 10% | 0% | 3% | 87% |

<!-- faultclass-confusion:end -->

## Calls, by fault and level (all ten features)

<!-- faultclass-levels:start -->

| Class | Fault | Level | Runs | Called correctly | Called control (missed) |
|---|---|---:|---:|---:|---:|
| control | none | 0 | 34 | 88% | 88% | 12% |
| multipath | multipath | 3 | 34 | 97% | 0% | 100% |
| multipath | multipath | 10 | 34 | 100% | 0% | 100% |
| multipath | multipath | 30 | 34 | 100% | 0% | 100% |
| spoofing | ramp | 0.5 | 34 | 24% | 68% | 32% |
| spoofing | ramp | 1 | 34 | 62% | 24% | 76% |
| spoofing | ramp | 2 | 34 | 56% | 3% | 97% |
| spoofing | ramp | 5 | 34 | 91% | 0% | 100% |
| spoofing | step | 10 | 34 | 88% | 0% | 100% |
| spoofing | step | 50 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.2 | 34 | 59% | 35% | 65% |
| degradation | accel_bias | 1 | 34 | 97% | 0% | 100% |
| degradation | gyro_bias | 0.01 | 34 | 91% | 6% | 94% |
| degradation | gyro_bias | 0.05 | 34 | 100% | 0% | 100% |

<!-- faultclass-levels:end -->

## Confirmation on unseen sizes and seeds

The second round of features was chosen after seeing the first round fail, so its figures are not an independent
test. This run is. The design was committed before it ran: fault sizes the model never saw (between and beyond the
training ones), seeds it never saw, and four seeds of control instead of two, so the false-alarm rate has 68 runs
behind it. The features, the thresholds and the tree are the ones fitted once on the whole training CSV. Nothing was
tuned afterwards.

<!-- faultclass-confirm-compare:start -->

| Figures | Runs | Control called a fault | Multipath called multipath | Spoofing called spoofing | Degradation called degradation |
|---|---:|---:|---:|---:|---:|
| cross-validated, training runs | 476 | 12% | 99% | 70% | 87% |
| frozen model, unseen runs | 544 | 34% | 100% | 68% | 85% |

<!-- faultclass-confirm-compare:end -->

By true class:

<!-- faultclass-confirm-calls:start -->

| True class | Runs | Called control | Called multipath | Called spoofing | Called degradation |
|---|---:|---:|---:|---:|---:|
| control | 68 | 66% | 0% | 29% | 4% |
| multipath | 68 | 0% | 100% | 0% | 0% |
| spoofing | 238 | 10% | 0% | 68% | 22% |
| degradation | 170 | 0% | 0% | 15% | 85% |

<!-- faultclass-confirm-calls:end -->

By fault and level:

<!-- faultclass-confirm-levels:start -->

| Class | Fault | Level | Runs | Called correctly | Called control (missed) | Detected (any fault called) |
|---|---|---:|---:|---:|---:|---:|
| control | none | 0 | 68 | 66% | 66% | 34% |
| multipath | multipath | 5 | 34 | 100% | 0% | 100% |
| multipath | multipath | 20 | 34 | 100% | 0% | 100% |
| spoofing | ramp | 0.75 | 34 | 50% | 38% | 62% |
| spoofing | ramp | 1.5 | 34 | 47% | 32% | 68% |
| spoofing | ramp | 3 | 34 | 65% | 0% | 100% |
| spoofing | ramp | 10 | 34 | 100% | 0% | 100% |
| spoofing | step | 5 | 34 | 15% | 0% | 100% |
| spoofing | step | 20 | 34 | 100% | 0% | 100% |
| spoofing | step | 100 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.4 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.7 | 34 | 88% | 0% | 100% |
| degradation | accel_bias | 2 | 34 | 38% | 0% | 100% |
| degradation | gyro_bias | 0.02 | 34 | 97% | 0% | 100% |
| degradation | gyro_bias | 0.1 | 34 | 100% | 0% | 100% |

<!-- faultclass-confirm-levels:end -->

1. **Multipath held.** All 68 multipath runs, at 5 and 20 m, are called multipath, and none of the 476 other runs is
   called multipath.
2. **Spoofing and degradation held.** Spoofing is called in 68% of runs (70% in cross-validation) and degradation in
   85% (87%). Steps of 20 m and above and a 10 m/s ramp are always called spoofing, and the 5 m step in 15% of runs.
3. **The false-alarm rate did not hold.** About a third of the control runs are called a fault (34%, against 12% in
   cross-validation). The calls are spread over almost every sequence, about one run in four on each, and are not
   one bad sequence. The stage 1 rule is "above the largest value seen on the training controls" for each of ten
   features. A threshold at the largest of 34 samples is exceeded by about 1 in 35 unseen runs, per feature, and
   ten features give ten chances, so adding features raises the false-alarm rate of a rule like this one.
4. **Weak ramps are still missed.** A 0.75 m/s ramp is detected in 62% of the runs.

## A calibrated stage 1

The confirmation showed that the stage 1 rule, "above the largest control value of each feature", is the weak part.
A bound fitted to the training controls was tried in its place: for each feature, a one-sided upper bound at 0.5% from a
normal fitted to the controls (on the log scale, except the autocorrelation), with the spread widened for the
uncertainty of the fitted mean. The 0.5% is a budget of 5% shared over ten features, fixed before the unseen controls
were scored. The first rule stays in the table as the control row. Stage 2 is unchanged.

<!-- faultclass-stage1:start -->

| Runs | Stage 1 rule | Controls | False alarms | Rate, upper 95% limit | Multipath detected | Spoofing detected | Degradation detected |
|---|---|---:|---:|---:|---:|---:|---:|
| training runs, cross-validated | control maximum | 34 | 4 | 12%, 25% | 100% | 84% | 90% |
| training runs, cross-validated | fitted bound, 0.5% per feature | 34 | 1 | 3%, 13% | 100% | 77% | 78% |
| unseen runs, frozen model | control maximum | 68 | 23 | 34%, 44% | 100% | 90% | 100% |
| unseen runs, frozen model | fitted bound, 0.5% per feature | 68 | 10 | 15%, 24% | 100% | 86% | 99% |

<!-- faultclass-stage1:end -->

1. **The false-alarm rate fell and is not zero.** On the unseen controls the fitted bound raises fewer alarms than the
   control maximum, but some remain. With no alarm at all in a set of controls, the rate is only shown to be below
   the upper limit in the table, so "zero false alarms" is a claim about a bound and never about a rate.
2. **Two features cause the remaining alarms.** Only `drift_m_s` and `axis_conc` fire on the unseen controls. Both were
   very tightly spread in the training controls (two seeds), and the unseen controls go past that spread.
   The other eight features stay inside their bounds. No rule was changed after seeing this, because the unseen controls
   would then be in-sample. A fix needs more training controls, on more seeds, and a new confirmation on runs it never saw.
3. **Detection fell with it.** Every fault class is detected a little less often, spoofing and degradation most. The
   weak ramps and weak accelerometer steps were already missed, and they are missed more.
4. **The samples are small.** The training controls and the unseen ones are few. The rate on
   a different set of sequences could differ by more than the table's limits suggest, since the limits assume
   independent runs and the runs share sequences and seeds.

## What it shows

1. **Multipath is separable.** Noise on the fixes raises the normalised innovation without a matching persistent
   offset, and 99% of multipath runs are called multipath, including at 3 m (97%).
2. **The added features fix the step.** With the original five features a 10 m step was called multipath in most
   runs, because the filter absorbs the offset within seconds. The autocorrelation separates a persistent offset
   from white noise, and with all ten features no 10 m step is called multipath and 94% of the step runs are called spoofing.
3. **Spoofing is better separated and not solved.** The share of spoofed runs called spoofing rises from 40% to
   70%. A 5 m/s ramp is called spoofing in 91% of runs, against 18% before. Ramps of 1 m/s and below are still often
   missed.
4. **The false-alarm rate did not improve.** About one in eight (12%) held-out control runs is called a fault, slightly
   more than before (9%). More features gave the stage 1 thresholds more ways to fire.
5. **Weak faults are still missed.** A 0.5 m/s ramp is detected in 32% of runs, against 29% with the original five features, and a 0.2 m/s²
   accelerometer step in about two thirds.
6. **Large degradation is called degradation.** Excluding the two weakest steps, 98% of degradation runs are called
   degradation.

## What follows

The Track A exit test, 95% detection per fault type at zero false alarms on the control, is still not met: the
false-alarm rate is not zero (about a third of unseen controls), weak spoofs are missed, and spoofing is called in
about 70% of runs. Only the multipath call survived the confirmation without a flaw: 100% recall and no
other run called multipath. Richer innovation
features helped where the signal was in the innovation's shape over time, and did not help where the fault is
smaller than the noise. That is the limit [ADR-0019](adr/0019-slow-ramp-spoofing.md) and
[ADR-0020](adr/0020-second-source-against-a-ramp.md) describe. See
[ADR-0021](adr/0021-fault-classification-from-innovations.md). The shipped configuration is unchanged.
