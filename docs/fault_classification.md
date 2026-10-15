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
| original five | 15% | 97% | 38% | 85% | 85% | 44% |
| all ten | 18% | 99% | 74% | 86% | 0% | 44% |

<!-- faultclass-compare:end -->

## The features

Median of each feature by fault and level.

<!-- faultclass-features:start -->

| Fault | Level | nis | mean_shift | drift_m_s | bias_accel | bias_gyro | ac1 | axis_conc | decay | bias_accel_30 | bias_gyro_30 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 0 | 1.03 | 0.967 | 0.0187 | 0.0945 | 0.00241 | 0.0487 | 0.41 | 1.01 | 0.0896 | 0.00244 |
| multipath | 3 | 8.7 | 19.2 | 0.655 | 0.138 | 0.00238 | 0.455 | 0.752 | 1.01 | 0.152 | 0.00273 |
| multipath | 10 | 37.2 | 31.3 | 2.47 | 0.08 | 0.00184 | 0.198 | 0.734 | 0.458 | 0.146 | 0.00236 |
| multipath | 30 | 210 | 32.8 | 1.45 | 0.0433 | 0.0006 | 0.0297 | 0.412 | 0.279 | 0.126 | 0.00167 |
| ramp | 0.5 | 1.05 | 0.944 | 0.0247 | 0.0935 | 0.00194 | 0.0743 | 0.406 | 1.03 | 0.0927 | 0.00231 |
| ramp | 1 | 1.17 | 1.26 | 0.0385 | 0.114 | 0.00194 | 0.117 | 0.401 | 0.951 | 0.104 | 0.00278 |
| ramp | 2 | 1.34 | 1.84 | 0.0607 | 0.154 | 0.004 | 0.234 | 0.418 | 0.878 | 0.126 | 0.00413 |
| ramp | 5 | 20.3 | 71.3 | 4.36 | 0.117 | 0.00304 | 0.988 | 0.998 | 0.46 | 0.187 | 0.00384 |
| step | 10 | 7.8 | 24.2 | 0.799 | 0.205 | 0.0038 | 0.88 | 0.963 | 0.0515 | 0.15 | 0.00442 |
| step | 50 | 154 | 137 | 1.95 | 0.13 | 0.00275 | 0.962 | 0.996 | 0.0235 | 0.187 | 0.00295 |
| accel_bias | 0.2 | 1.08 | 1.42 | 0.032 | 0.166 | 0.00274 | 0.0982 | 0.411 | 0.974 | 0.184 | 0.00307 |
| accel_bias | 1 | 1.66 | 4.9 | 0.132 | 0.663 | 0.00383 | 0.397 | 0.536 | 0.793 | 0.689 | 0.0034 |
| gyro_bias | 0.01 | 1.18 | 5.37 | 0.0306 | 0.218 | 0.00739 | 0.163 | 0.411 | 1.2 | 0.191 | 0.00828 |
| gyro_bias | 0.05 | 109 | 144 | 11.4 | 0.219 | 0.00541 | 0.984 | 0.996 | 166 | 0.219 | 0.00541 |

<!-- faultclass-features:end -->

## Calls, by true class (all ten features)

<!-- faultclass-confusion:start -->

| True class | Runs | Called control | Called multipath | Called spoofing | Called degradation |
|---|---:|---:|---:|---:|---:|
| control | 34 | 82% | 0% | 9% | 9% |
| multipath | 102 | 0% | 99% | 0% | 1% |
| spoofing | 204 | 13% | 0% | 74% | 14% |
| degradation | 136 | 10% | 0% | 4% | 86% |

<!-- faultclass-confusion:end -->

## Calls, by fault and level (all ten features)

<!-- faultclass-levels:start -->

| Class | Fault | Level | Runs | Called correctly | Called control (missed) |
|---|---|---:|---:|---:|---:|
| control | none | 0 | 34 | 82% | 82% | 18% |
| multipath | multipath | 3 | 34 | 97% | 0% | 100% |
| multipath | multipath | 10 | 34 | 100% | 0% | 100% |
| multipath | multipath | 30 | 34 | 100% | 0% | 100% |
| spoofing | ramp | 0.5 | 34 | 26% | 56% | 44% |
| spoofing | ramp | 1 | 34 | 56% | 21% | 79% |
| spoofing | ramp | 2 | 34 | 71% | 0% | 100% |
| spoofing | ramp | 5 | 34 | 88% | 0% | 100% |
| spoofing | step | 10 | 34 | 100% | 0% | 100% |
| spoofing | step | 50 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.2 | 34 | 56% | 32% | 68% |
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
| cross-validated, training runs | 476 | 18% | 99% | 74% | 86% |
| frozen model, unseen runs | 544 | 35% | 100% | 77% | 91% |

<!-- faultclass-confirm-compare:end -->

By true class:

<!-- faultclass-confirm-calls:start -->

| True class | Runs | Called control | Called multipath | Called spoofing | Called degradation |
|---|---:|---:|---:|---:|---:|
| control | 68 | 65% | 0% | 22% | 13% |
| multipath | 68 | 0% | 100% | 0% | 0% |
| spoofing | 238 | 11% | 0% | 77% | 12% |
| degradation | 170 | 0% | 0% | 9% | 91% |

<!-- faultclass-confirm-calls:end -->

By fault and level:

<!-- faultclass-confirm-levels:start -->

| Class | Fault | Level | Runs | Called correctly | Called control (missed) | Detected (any fault called) |
|---|---|---:|---:|---:|---:|---:|
| control | none | 0 | 68 | 65% | 65% | 35% |
| multipath | multipath | 5 | 34 | 100% | 0% | 100% |
| multipath | multipath | 20 | 34 | 100% | 0% | 100% |
| spoofing | ramp | 0.75 | 34 | 32% | 50% | 50% |
| spoofing | ramp | 1.5 | 34 | 44% | 24% | 76% |
| spoofing | ramp | 3 | 34 | 65% | 0% | 100% |
| spoofing | ramp | 10 | 34 | 100% | 0% | 100% |
| spoofing | step | 5 | 34 | 100% | 0% | 100% |
| spoofing | step | 20 | 34 | 100% | 0% | 100% |
| spoofing | step | 100 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.4 | 34 | 100% | 0% | 100% |
| degradation | accel_bias | 0.7 | 34 | 88% | 0% | 100% |
| degradation | accel_bias | 2 | 34 | 91% | 0% | 100% |
| degradation | gyro_bias | 0.02 | 34 | 74% | 0% | 100% |
| degradation | gyro_bias | 0.1 | 34 | 100% | 0% | 100% |

<!-- faultclass-confirm-levels:end -->

1. **Multipath held.** All 68 multipath runs, at 5 and 20 m, are called multipath, and none of the 476 other runs is
   called multipath.
2. **Spoofing and degradation held.** Spoofing is called in 77% of runs (74% in cross-validation) and degradation in
   91% (86%). Steps are called spoofing at every size, and a 10 m/s ramp always.
3. **The false-alarm rate did not hold.** About a third of the control runs are called a fault (35%, against 18% in
   cross-validation). The calls are spread over almost every sequence, about one run in four on each, and are not
   one bad sequence. The stage 1 rule is "above the largest value seen on the training controls" for each of ten
   features. A threshold at the largest of 34 samples is exceeded by about 1 in 35 unseen runs, per feature, and
   ten features give ten chances, so adding features raises the false-alarm rate of a rule like this one.
4. **Weak ramps are still missed.** A 0.75 m/s ramp is detected in half the runs.

## A calibrated stage 1

The confirmation showed that the stage 1 rule, "above the largest control value of each feature", is the weak part.
A bound fitted to the training controls was tried in its place: for each feature, a one-sided upper bound at 0.5% from a
normal fitted to the controls (on the log scale, except the autocorrelation), with the spread widened for the
uncertainty of the fitted mean. The 0.5% is a budget of 5% shared over ten features, fixed before the unseen controls
were scored. The first rule stays in the table as the control row. Stage 2 is unchanged.

<!-- faultclass-stage1:start -->

| Runs | Stage 1 rule | Controls | False alarms | Rate, upper 95% limit | Multipath detected | Spoofing detected | Degradation detected |
|---|---|---:|---:|---:|---:|---:|---:|
| training runs, cross-validated | control maximum | 34 | 6 | 18%, 32% | 100% | 87% | 90% |
| training runs, cross-validated | fitted bound, 0.5% per feature | 34 | 0 | 0%, 8% | 100% | 76% | 78% |
| unseen runs, frozen model | control maximum | 68 | 24 | 35%, 46% | 100% | 89% | 100% |
| unseen runs, frozen model | fitted bound, 0.5% per feature | 68 | 7 | 10%, 18% | 100% | 83% | 96% |

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
   from white noise, and with all ten features no 10 m step is called multipath and every step is called spoofing.
3. **Spoofing is better separated and not solved.** The share of spoofed runs called spoofing rises from 38% to
   74%. A 5 m/s ramp is called spoofing in 88% of runs, against 9% before. Ramps of 1 m/s and below are still often
   missed.
4. **The false-alarm rate did not improve.** About one in six held-out control runs is called a fault, slightly
   more than before. More features gave the stage 1 thresholds more ways to fire.
5. **Weak faults are still missed.** A 0.5 m/s ramp is detected in 44% of runs, as before, and a 0.2 m/s²
   accelerometer step in about two thirds.
6. **Large degradation is called degradation.** Excluding the two weakest steps, 98% of degradation runs are called
   degradation.

## What follows

The Track A exit test, 95% detection per fault type at zero false alarms on the control, is still not met: the
false-alarm rate is not zero (about a third of unseen controls), weak spoofs are missed, and spoofing is called in
about three quarters of runs. Only the multipath call survived the confirmation without a flaw: 100% recall and no
other run called multipath. Richer innovation
features helped where the signal was in the innovation's shape over time, and did not help where the fault is
smaller than the noise. That is the limit [ADR-0019](adr/0019-slow-ramp-spoofing.md) and
[ADR-0020](adr/0020-second-source-against-a-ramp.md) describe. See
[ADR-0021](adr/0021-fault-classification-from-innovations.md). The shipped configuration is unchanged.
