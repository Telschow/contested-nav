# Fault matrix

What the filter does when a sensor fails, measured against the same case with no fault.

The fault-mode table in the [model contract](MODEL.md) used to mark most fault modes "unit-tested
only": the code path ran, the effect on accuracy and calibration was not measured. This page
measures them. Each fault is injected into a benchmark case at one level at a time, over five noise
seeds, and compared with a control: the same case, same seeds, no fault.

```bash
navkit sweep faults --csv docs/data/fault_matrix.csv --page docs/faults.md
```

**What is counted.** *Gate rejected*: in how many seeds the chi-square gate rejected at least one
measurement. *Fault declared*: in how many seeds the FDIR layer declared a channel faulty at some
point (read from its event log, not the end-of-run flag, so a channel that was declared and later
recovered still counts). *Latency*: mean time from the fault's onset to the first declaration, over
the seeds that declared after the onset. *Inflation grant*: seeds in which the NIS monitor gave a
channel one bounded covariance inflation ([ADR-0006](adr/0006-nis-window-monitor.md)). On a control,
the same counts are the **false alarms**: a healthy sensor that is rejected or declared faulty.

The table is generated from [`data/fault_matrix.csv`](data/fault_matrix.csv); a test fails if they
disagree, and CI reruns the sweep and fails if the committed CSV no longer matches it.

<!-- faults:start -->

| Case | Fault | Level | ATE rmse m [95% CI] | NEES mean [95% CI] | Coverage @2σ % [95% CI] | Gate rejected | Fault declared | Declared channel | Latency s | Inflation grant | Measurements rejected % [95% CI] |
|---|---|---:|---|---|---|---:|---:|---|---:|---:|---|
| gnss_only | none (control) |  | 0.53 [0.49, 0.58] | 3.7 [3.1, 4.2] | 99.9 [99.6, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS spoof, sustained offset | 3 m | 2.97 [2.27, 3.79] | 77.9 [67.0, 90.5] | 38.5 [34.7, 42.6] | 5/5 | 2/5 | gnss | 11.2 | 0/5 | 15.5 [3.0, 27.9] |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5.44 [0.74, 10.25] | 99.9 [2.5, 251.1] | 84.9 [68.7, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 46.6 [35.4, 58.5] |
| gnss_only | GNSS spoof, sustained offset | 40 m | 1.24 [0.77, 1.98] | 2.9 [2.2, 3.7] | 99.9 [99.6, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 39.1 [39.1, 39.1] |
| gnss_only | GNSS single spike | 20 m | 0.54 [0.49, 0.58] | 3.7 [3.0, 4.3] | 99.9 [99.6, 100.0] | 5/5 | 0/5 | none | n/a | 0/5 | 0.7 [0.7, 0.7] |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 1.45 [1.11, 1.78] | 39.1 [17.8, 61.0] | 34.1 [18.8, 54.4] | 2/5 | 0/5 | none | n/a | 0/5 | 0.3 [0.0, 0.5] |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 4.12 [2.96, 5.46] | 204.3 [126.2, 302.0] | 7.8 [0.8, 15.9] | 5/5 | 2/5 | gnss | n/a | 0/5 | 15.4 [2.6, 28.2] |
| gnss_only | GNSS timestamp offset | 0.05 s | 0.55 [0.51, 0.60] | 3.8 [3.2, 4.5] | 99.6 [99.1, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.2 s | 0.67 [0.61, 0.71] | 5.3 [4.5, 6.2] | 95.5 [93.3, 97.8] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.5 s | 1.03 [0.98, 1.07] | 12.6 [11.4, 13.8] | 56.3 [50.7, 61.4] | 1/5 | 0/5 | none | n/a | 0/5 | 0.1 [0.0, 0.4] |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 0.82 [0.73, 0.92] | 10.7 [8.4, 12.6] | 62.7 [52.9, 76.9] | 1/5 | 0/5 | none | n/a | 0/5 | 0.1 [0.0, 0.4] |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 71.18 [68.88, 73.41] | 1094.2 [1042.5, 1170.0] | 37.9 [36.4, 39.1] | 5/5 | 5/5 | gnss | 5.5 | 0/5 | 51.8 [51.3, 52.5] |
| outage_visual | none (control) |  | 25.34 [12.91, 40.04] | 39641.7 [8976.7, 78949.2] | 9.2 [5.7, 14.1] | 5/5 | 5/5 | gnss | n/a | 1/5 | 7.3 [6.6, 7.8] |
| outage_visual | GNSS spoof after an outage | 3 m | 25.25 [12.73, 39.99] | 39595.4 [8884.0, 78949.2] | 8.9 [5.5, 14.1] | 5/5 | 5/5 | gnss | 1.4 | 1/5 | 7.3 [6.6, 7.8] |
| outage_visual | GNSS spoof after an outage | 10 m | 26.41 [15.06, 40.04] | 40553.1 [10799.5, 78949.2] | 8.8 [5.5, 14.1] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 7.6 [7.6, 7.8] |
| outage_visual | GNSS spoof after an outage | 22 m | 26.41 [15.06, 40.04] | 40553.1 [10799.5, 78949.2] | 8.8 [5.5, 14.1] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 7.6 [7.6, 7.8] |
| vision_only | none (control) |  | 47.65 [31.69, 63.60] | 117213.6 [46753.8, 191954.6] | 2.1 [0.5, 4.9] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.05 s | 47.48 [31.63, 63.33] | 116250.2 [46513.6, 190346.7] | 2.2 [0.6, 4.9] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.2 s | 47.02 [31.41, 62.64] | 113668.5 [45704.4, 186167.9] | 2.6 [1.1, 5.1] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision outage | 2 s lost at 10 s | 48.39 [32.23, 64.55] | 118524.9 [47340.8, 194158.7] | 2.1 [0.5, 4.9] | 5/5 | 0/5 | none | n/a | 0/5 | 0.2 [0.2, 0.2] |
| vision_only | Vision outage | 5 s lost at 10 s | 49.52 [32.99, 66.05] | 117435.6 [46793.3, 192168.4] | 2.1 [0.5, 4.9] | 5/5 | 0/5 | none | n/a | 0/5 | 0.2 [0.2, 0.2] |

<!-- faults:end -->

## What it shows

Each statement below is checked against the CSV by `tests/test_fault_matrix.py`.

1. **False alarms are zero on two controls and not on the third, and the third is not a false-alarm rate.** On
   `gnss_only` and `vision_only` the gate rejects nothing and no fault is declared. On `outage_visual`, the case
   with the outage, the gate rejects measurements in every seed and a fault is declared in every seed: the healthy
   GNSS receiver is declared faulty after it returns. That comes from the single-anchor filter failing under the
   start attitude error drawn from its own prior ([ADR-0027](adr/0027-how-the-synthetic-runs-are-initialised.md)), so
   it rejects fixes the receiver gets right. It is not a stand-alone false-alarm rate for the FDIR layer, and a
   cell whose own no-fault control also fires says nothing about detection. The per-update false-alarm measurement
   is in [FDIR false alarms and constant sensitivity](#fdir-false-alarms-and-constant-sensitivity), further down this
   page.
2. **A large sustained spoof is declared fast.** At 10 m and 40 m the GNSS channel is declared
   faulty in every seed, 0.8 s after the offset starts, which is five consecutive rejected fixes at
   5 Hz.
3. **Declaring a fault is not protecting the estimate.** The 10 m spoof is declared just as fast as
   the 40 m one and costs far more error, in some seeds (the interval is wide). Damage does not grow
   with the size of the offset.
4. **A modest sustained spoof is rejected by the gate and mostly not declared.** At 3 m the gate
   rejects fixes in every seed, but a fault is declared in only two, and on average 11.2 s after the
   offset started, which is after the 10 s spoof window had ended. The error is several times the
   control's, the mean NEES is far above 3 and coverage is under half. I did not check what
   triggered those two declarations; the timing suggests the genuine fixes returning to a filter the
   spoof had moved, not the spoof.
5. **A single 20 m spike is handled.** The gate rejects it in every seed, no fault is declared, and
   the error does not move.
6. **A slow GNSS bias is mostly invisible and makes the filter overconfident.** At 1 σ the gate
   rejects fixes in at most two seeds and nothing is declared, yet the mean NEES is more than ten
   times the control's and coverage is under half. At 3 σ the gate reacts in every seed.
7. **A GNSS timestamp offset degrades calibration without detection.** No fault is declared at any
   level. Error, NEES and the loss of coverage all grow with the offset; at 0.5 s coverage is under
   60% and the gate rejected in only one seed. A 0.05 s offset is not visible. A vision timestamp
   offset shows no measurable effect, but its control is already badly uncalibrated, so this case
   cannot show one.
8. **Losing 2 s of IMU samples is catastrophic, and the wrong sensor is blamed.** The error rises by
   two orders of magnitude over the control, and in every seed the FDIR layer declares the GNSS
   channel faulty, which is the healthy sensor. A 0.5 s loss is not declared, but it raises error
   and costs coverage.
9. **The spoof-after-outage cells are not informative.** The control on this case declares a fault in every seed
   (point 1), so the 3 m, 10 m and 22 m cells declare in every seed too, with the same detection count, and cannot
   be told apart from the control. Their error is within a few percent of the control's. The 22 m cell, which was a
   clear case before the start was drawn from the prior, no longer separates from the control. The open problem
   recorded in [ADR-0007](adr/0007-spoof-permanence-hysteresis.md) stays open, and this sweep does not measure it
   until the control stops firing.
10. **Vision outages of 2 s and 5 s** raise the error slowly on a case that is already
    uncalibrated. The gate now rejects measurements in every seed of these cells, where the no-outage control
    rejects none. That is not a detection result: it is the single-anchor filter, already inconsistent after the
    start attitude error, rejecting its own visual measurements when they resume after the gap. No fault is
    declared, and the cells do not show that fault detection got better.

## The Track A exit test, restated

[`ROADMAP.md`](roadmap.md) Track A asks for detection above 95% per fault type at zero false alarms
on the control. **It is not met.**

- Zero false alarms holds for two of the three controls (point 1).
- By the strict test, a fault declared in every seed, six of the eighteen fault cells qualify. Three of them
  are the spoof-after-outage cells, whose control also declares in every seed, so they show nothing about
  detection (point 9). The other three are the 10 m and 40 m sustained spoofs and the 2 s IMU loss, where the
  channel declared is the wrong one.
- Five seeds cannot establish a 95% rate in any case. Zero misses in *n* runs supports a rate above
  95% at 95% confidence only when *n* is at least 59 (ln 0.05 / ln 0.95 is 58.4).

## What this does not show

- One fault window per fault, on one synthetic path, five seeds. Intervals are wide: the 10 m spoof
  runs from under 1 m to nearly 10 m.
- The spoof is a constant offset east. A spoof that ramps, or that is consistent with the IMU, is
  not tried.
- Every cell, controls included, has the default IMU noise, as does every benchmark case
  ([ADR-0012](adr/0012-every-scenario-is-injected.md)). Before that decision four benchmark cases ran
  with a noiseless IMU; this sweep did not, because it forced the injection.
- "Detected" and "declared" describe what the filter's own gate did. Nothing here is a protection
  level or an integrity claim, and there is no detector for a slow bias or a timing error to
  measure.

## FDIR false alarms and constant sensitivity

This section reports two measurements of the FDIR layer. It tunes nothing: no `FdirConfig` default changes here, and
no sentence below recommends a value. Point 1 above counted control false alarms over five seeds on three cases. This
section counts them per update, against the false-alarm probability the gate states, and then moves three constants one
at a time. Every number in the generated blocks is read from a committed CSV, and `tests/test_fdir_false_alarm_page.py`
fails if a block, a sentence or a CSV drifts. The data is synthetic.

### Per-update false-alarm rate

```bash
navkit sweep fdir rate --csv docs/data/fdir_false_alarm.csv --page docs/faults.md
```

**What is counted.** A rejection is the per-update chi-square test of [`navkit.fdir.gating`](api/fdir.md): the squared
Mahalanobis distance of a GNSS position innovation, recomputed from the residual and the innovation covariance the filter
recorded before it decided, above the threshold for the stated α. It is not a fault declaration, which needs several
rejections in a row. The gating module says the stated rate holds only if the innovation covariance is the right size,
and the predicted-rate table below tests that statement.

**The cases.** `gnss_only` has healthy GNSS throughout. `outage_control` has a GNSS outage, and the fixes inside the
outage do not exist. The fixes in the settling period after the return are reported on their own row and are not in the
false-alarm count, because rejecting the first fixes after an outage is the gate doing its job on a filter that has
drifted. The settling period was chosen before the first run and has not been varied. The seeds are the development set
of the [ensemble](calibration.md). The seeds reserved for the B1 gate ([ADR-0028](adr/0028-the-b1-gate.md)) are not used,
and the code refuses them.

**Autocorrelation.** Successive updates in one run are not independent, because the filter state carries over from one
update to the next, so the raw Wilson interval, which treats them as independent, is too narrow. The second interval
replaces the update count by the sum over runs of the effective sample size of the rejection indicator
(`navkit.eval.statistics`, Sokal windowing) and scales each run's rejection count by the same ratio. A run with no
rejection is a constant series, for which the estimator returns no value, and it is counted as that many independent
updates. A run with a lone rejection gets a value equal to its length, because one event has no measurable
autocorrelation. With few rejections the two intervals can therefore be equal, and equality there does not show that the
updates are independent. For that reason the effective size of the NIS series, which is where the dependence
would sit, is listed too. It enters neither interval.

**The predicted rate.** The scale factor c is the mean NIS of the counted healthy updates over the three degrees of
freedom. If the innovation covariance were too small by the factor c, the rejection rate would be the chi-square tail
above the threshold divided by c. That assumes one factor for all directions and treats c as exact, though the mean NIS
carries its own sampling error. The block reports where the predicted rate falls relative to the observed rate and its
intervals, and says nothing more about it.

**What this does not cover.** The innovations are the filter's own, in closed loop: a rejected fix leaves the state as
it was, so the updates after a rejection are not drawn from the same distribution as the ones before. The filter is told
the noise the generator used. A receiver whose real error differs from the noise the filter assumes is a different
measurement (see [the mismatch sweep](mismatch.md)). The path is one synthetic trajectory.

<!-- fdir-false-alarm:start -->

Seeds 0 to 24 (25 runs per case). The stated α is 0.100%, which is a threshold of 16.266 for 3 degrees of freedom. The settling period after an outage is 5 s, the half-open interval from the return to 5 s after it.

Per-update gate rejections of healthy GNSS fixes:

| Case | Updates counted | Updates | Rejections | Observed rate | 95% Wilson interval, raw count | Summed effective updates | Effective rejections | 95% Wilson interval, effective count | Stated α |
|---|---|---:|---:|---:|---|---:|---:|---|---:|
| gnss_only | all updates | 3775 | 5 | 0.132% | [0.057%, 0.310%] | 3775.0 | 5.00 | [0.057%, 0.310%] | 0.100% |
| outage_control | outside the outage and its settling period | 1275 | 0 | 0.000% | [0.000%, 0.300%] | 1275.0 | 0.00 | [0.000%, 0.300%] | 0.100% |
| outage_control | first 5 s after the return (reported apart) | 625 | 1 | 0.160% | [0.028%, 0.901%] | 625.0 | 1.00 | [0.028%, 0.901%] | 0.100% |

Predicted rate from the scale factor c, next to the observed rate:

| Case | Updates counted | Mean NIS (expected 3) | c = mean NIS / 3 | Threshold | Predicted rate P(χ²₃ > threshold / c) | Observed rate | Stated α |
|---|---|---:|---:|---:|---:|---:|---:|
| gnss_only | all updates | 2.982 | 0.994 | 16.266 | 0.096% | 0.132% | 0.100% |
| outage_control | outside the outage and its settling period | 2.951 | 0.984 | 16.266 | 0.088% | 0.000% | 0.100% |
| outage_control | first 5 s after the return (reported apart) | 3.170 | 1.057 | 16.266 | 0.151% | 0.160% | 0.100% |

Effective sample size of the rejection indicator, per run:

| Case | Updates counted | Runs | Runs where the estimator returned a value for the indicator | Indicator, per-run effective size, min / median / max | NIS series, per-run effective size, min / median / max (diagnostic, in neither interval) | Per-run updates, median |
|---|---|---:|---:|---|---|---:|
| gnss_only | all updates | 25 | 5 | 151.0 / 151.0 / 151.0 | 111.5 / 151.0 / 151.0 | 151 |
| outage_control | outside the outage and its settling period | 25 | 0 | 51.0 / 51.0 / 51.0 | 29.7 / 51.0 / 51.0 | 51 |
| outage_control | first 5 s after the return (reported apart) | 25 | 1 | 25.0 / 25.0 / 25.0 | 22.2 / 25.0 / 25.0 | 25 |

- **gnss_only, all updates.** The gate rejected 5 of 3775 updates, 0.132%. The stated α is 0.100%, which is inside the raw-count interval [0.057%, 0.310%] and inside the effective-count interval [0.057%, 0.310%]. The mean NIS is 2.982, so c is 0.994 and the predicted rate is 0.096%. The predicted rate is inside the raw-count interval and inside the effective-count interval, and it is farther from the observed rate than α is.
- **outage_control, outside the outage and its settling period.** The gate rejected 0 of 1275 updates, 0.000%. The stated α is 0.100%, which is inside the raw-count interval [0.000%, 0.300%] and inside the effective-count interval [0.000%, 0.300%]. The mean NIS is 2.951, so c is 0.984 and the predicted rate is 0.088%. The predicted rate is inside the raw-count interval and inside the effective-count interval, and it is closer to the observed rate than α is.
- **outage_control, first 5 s after the return (reported apart).** The gate rejected 1 of 625 updates, 0.160%. The stated α is 0.100%, which is inside the raw-count interval [0.028%, 0.901%] and inside the effective-count interval [0.028%, 0.901%]. The mean NIS is 3.170, so c is 1.057 and the predicted rate is 0.151%. The predicted rate is inside the raw-count interval and inside the effective-count interval, and it is closer to the observed rate than α is.

<!-- fdir-false-alarm:end -->

### One constant at a time

```bash
navkit sweep fdir sensitivity --csv docs/data/fdir_sensitivity.csv --page docs/faults.md
```

**What is changed.** One of `max_consecutive_rejections`, `reacq_consecutive_rejections` and `reacq_sigma_m` is set to
half and to double its default while the other two and every other field keep their defaults. An integer is rounded
half up. The cells are the cells of the fault matrix above, with the same faults, levels and seeds. *Detected* and
*declared* mean what they mean in the matrix: the seeds in which the gate rejected at least one measurement, and the
seeds in which the FDIR layer declared a channel faulty. The control rows are the no-fault runs of each base case, so
their declared count is the false-alarm count for that setting. The counts at the defaults are those of the matrix, and
a test checks that they agree.

<!-- fdir-sensitivity:start -->

Seeds 0 to 4, as the fault matrix above uses. The defaults are the ones in `FdirConfig`, and the table is read from them:

| Constant | Default | Half | Double | Type |
|---|---:|---:|---:|---|
| `max_consecutive_rejections` | 5 | 3 | 10 | integer, rounded half up |
| `reacq_consecutive_rejections` | 3 | 2 | 6 | integer, rounded half up |
| `reacq_sigma_m` | 3 | 1.5 | 6 | float |

False alarms: seeds in which the no-fault control declared a channel faulty, out of 5:

| Setting | gnss_only control declared | outage_visual control declared | vision_only control declared | Cells whose detected count differs from the defaults | Cells whose declared count differs from the defaults |
|---|---:|---:|---:|---:|---:|
| defaults | 0/5 | 5/5 | 0/5 | 0 | 0 |
| max_consecutive_rejections = 3 (half; default 5) | 0/5 | 5/5 | 0/5 | 0 | 1 |
| max_consecutive_rejections = 10 (double; default 5) | 0/5 | 5/5 | 0/5 | 0 | 2 |
| reacq_consecutive_rejections = 2 (half; default 3) | 0/5 | 5/5 | 0/5 | 0 | 0 |
| reacq_consecutive_rejections = 6 (double; default 3) | 0/5 | 5/5 | 0/5 | 0 | 0 |
| reacq_sigma_m = 1.5 (half; default 3) | 0/5 | 5/5 | 0/5 | 0 | 0 |
| reacq_sigma_m = 6 (double; default 3) | 0/5 | 5/5 | 0/5 | 0 | 0 |

`max_consecutive_rejections`, detected / declared, out of 5 seeds:

| Case | Fault | Level | max_consecutive_rejections = 5 (default) | max_consecutive_rejections = 3 (half) | max_consecutive_rejections = 10 (double) |
|---|---|---:|---|---|---|
| gnss_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS spoof, sustained offset | 3 m | 5/2 | 5/3 | 5/0 |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS spoof, sustained offset | 40 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS single spike | 20 m | 5/0 | 5/0 | 5/0 |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 2/0 | 2/0 | 2/0 |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 5/2 | 5/2 | 5/1 |
| gnss_only | GNSS timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.5 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 5/5 | 5/5 | 5/5 |
| outage_visual | none (control) |  | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 3 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 10 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 22 m | 5/5 | 5/5 | 5/5 |
| vision_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision outage | 2 s lost at 10 s | 5/0 | 5/0 | 5/0 |
| vision_only | Vision outage | 5 s lost at 10 s | 5/0 | 5/0 | 5/0 |

`reacq_consecutive_rejections`, detected / declared, out of 5 seeds:

| Case | Fault | Level | reacq_consecutive_rejections = 3 (default) | reacq_consecutive_rejections = 2 (half) | reacq_consecutive_rejections = 6 (double) |
|---|---|---:|---|---|---|
| gnss_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS spoof, sustained offset | 3 m | 5/2 | 5/2 | 5/2 |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS spoof, sustained offset | 40 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS single spike | 20 m | 5/0 | 5/0 | 5/0 |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 2/0 | 2/0 | 2/0 |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 5/2 | 5/2 | 5/2 |
| gnss_only | GNSS timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.5 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 5/5 | 5/5 | 5/5 |
| outage_visual | none (control) |  | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 3 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 10 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 22 m | 5/5 | 5/5 | 5/5 |
| vision_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision outage | 2 s lost at 10 s | 5/0 | 5/0 | 5/0 |
| vision_only | Vision outage | 5 s lost at 10 s | 5/0 | 5/0 | 5/0 |

`reacq_sigma_m`, detected / declared, out of 5 seeds:

| Case | Fault | Level | reacq_sigma_m = 3 (default) | reacq_sigma_m = 1.5 (half) | reacq_sigma_m = 6 (double) |
|---|---|---:|---|---|---|
| gnss_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS spoof, sustained offset | 3 m | 5/2 | 5/2 | 5/2 |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS spoof, sustained offset | 40 m | 5/5 | 5/5 | 5/5 |
| gnss_only | GNSS single spike | 20 m | 5/0 | 5/0 | 5/0 |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 2/0 | 2/0 | 2/0 |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 5/2 | 5/2 | 5/2 |
| gnss_only | GNSS timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| gnss_only | GNSS timestamp offset | 0.5 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 1/0 | 1/0 | 1/0 |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 5/5 | 5/5 | 5/5 |
| outage_visual | none (control) |  | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 3 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 10 m | 5/5 | 5/5 | 5/5 |
| outage_visual | GNSS spoof after an outage | 22 m | 5/5 | 5/5 | 5/5 |
| vision_only | none (control) |  | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.05 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision timestamp offset | 0.2 s | 0/0 | 0/0 | 0/0 |
| vision_only | Vision outage | 2 s lost at 10 s | 5/0 | 5/0 | 5/0 |
| vision_only | Vision outage | 5 s lost at 10 s | 5/0 | 5/0 | 5/0 |

What the counts show:

- The `gnss_only` control declared a channel faulty in 0 of 5 seeds at every setting.
- The `outage_visual` control declared a channel faulty in 5 of 5 seeds at every setting.
- The `vision_only` control declared a channel faulty in 0 of 5 seeds at every setting.
- max_consecutive_rejections = 3 (half): 1 cell(s) differ from the defaults (gnss_only, GNSS spoof, sustained offset 3 m: detected 5 to 5, declared 2 to 3; of 5 seeds).
- max_consecutive_rejections = 10 (double): 2 cell(s) differ from the defaults (gnss_only, GNSS spoof, sustained offset 3 m: detected 5 to 5, declared 2 to 0; gnss_only, GNSS slow bias 3 m (1 sigma): detected 5 to 5, declared 2 to 1; of 5 seeds).
- reacq_consecutive_rejections = 2 (half): no cell differs from the defaults in its detected or declared count.
- reacq_consecutive_rejections = 6 (double): no cell differs from the defaults in its detected or declared count.
- reacq_sigma_m = 1.5 (half): no cell differs from the defaults in its detected or declared count.
- reacq_sigma_m = 6 (double): no cell differs from the defaults in its detected or declared count.

<!-- fdir-sensitivity:end -->

**What this does not show.** Five seeds and one fault window per fault. A changed count is a count of seeds, not a rate.
One constant at a time says nothing about two moved together. The counts are all the table reports, so it would not show
a change in error or coverage that leaves every count as it was. A control that declares in every seed at a setting
cannot separate detection from false alarm at that setting (point 1). Nothing here ranks the settings or says which one
to use.
