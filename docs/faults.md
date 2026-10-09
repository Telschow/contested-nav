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
| gnss_only | none (control) |  | 0.51 [0.48, 0.56] | 3.6 [2.8, 4.3] | 100.0 [100.0, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS spoof, sustained offset | 3 m | 2.86 [2.27, 3.59] | 75.9 [66.7, 88.5] | 39.4 [36.1, 43.4] | 5/5 | 2/5 | gnss | 11.2 | 0/5 | 15.6 [3.0, 28.2] |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5.42 [0.73, 10.21] | 99.1 [2.5, 249.1] | 85.1 [69.1, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 47.4 [37.0, 58.9] |
| gnss_only | GNSS spoof, sustained offset | 40 m | 1.11 [0.72, 1.77] | 2.7 [2.3, 3.1] | 99.7 [99.2, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 39.1 [39.1, 39.1] |
| gnss_only | GNSS single spike | 20 m | 0.52 [0.47, 0.56] | 3.6 [2.8, 4.4] | 100.0 [100.0, 100.0] | 5/5 | 0/5 | none | n/a | 0/5 | 0.7 [0.7, 0.7] |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 1.43 [1.08, 1.76] | 38.0 [17.2, 59.1] | 37.2 [22.2, 58.8] | 1/5 | 0/5 | none | n/a | 0/5 | 0.1 [0.0, 0.4] |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 4.07 [2.93, 5.36] | 189.6 [118.3, 299.0] | 9.9 [2.8, 17.1] | 5/5 | 2/5 | gnss | n/a | 0/5 | 17.9 [2.6, 34.7] |
| gnss_only | GNSS timestamp offset | 0.05 s | 0.53 [0.49, 0.58] | 3.8 [3.0, 4.6] | 99.9 [99.6, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.2 s | 0.65 [0.61, 0.69] | 5.3 [4.3, 6.2] | 95.2 [90.9, 98.4] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.5 s | 1.02 [0.99, 1.05] | 12.6 [11.3, 13.8] | 57.3 [53.8, 61.0] | 2/5 | 0/5 | none | n/a | 0/5 | 0.3 [0.0, 0.5] |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 0.80 [0.72, 0.90] | 10.4 [8.1, 12.5] | 61.9 [50.2, 76.8] | 1/5 | 0/5 | none | n/a | 0/5 | 0.1 [0.0, 0.4] |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 71.15 [68.70, 73.33] | 1100.0 [1032.4, 1185.2] | 38.1 [36.8, 39.1] | 5/5 | 5/5 | gnss | 5.5 | 0/5 | 51.8 [51.3, 52.5] |
| outage_visual | none (control) |  | 3.15 [2.37, 4.32] | 502.3 [290.6, 836.6] | 21.0 [15.5, 28.2] | 5/5 | 3/5 | gnss | n/a | 5/5 | 2.9 [1.2, 4.7] |
| outage_visual | GNSS spoof after an outage | 3 m | 3.54 [2.91, 4.30] | 595.7 [432.6, 786.7] | 17.1 [11.3, 26.3] | 5/5 | 3/5 | gnss | 6.9 | 5/5 | 2.7 [0.9, 4.5] |
| outage_visual | GNSS spoof after an outage | 10 m | 7.30 [6.17, 9.10] | 2619.8 [1802.6, 4035.5] | 17.0 [11.2, 26.3] | 5/5 | 3/5 | gnss | 5.5 | 4/5 | 3.1 [0.9, 5.6] |
| outage_visual | GNSS spoof after an outage | 22 m | 6.28 [4.67, 8.66] | 2214.3 [1229.4, 3852.1] | 17.0 [11.2, 26.3] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 7.6 [7.6, 7.6] |
| vision_only | none (control) |  | 3.57 [2.52, 4.97] | 691.6 [323.8, 1242.5] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.05 s | 3.51 [2.55, 4.88] | 664.8 [328.9, 1189.3] | 0.8 [0.8, 0.8] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.2 s | 3.42 [2.51, 4.68] | 616.2 [319.8, 1073.7] | 1.3 [1.3, 1.3] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision outage | 2 s lost at 10 s | 3.99 [2.75, 5.39] | 835.6 [374.7, 1425.5] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision outage | 5 s lost at 10 s | 4.96 [3.79, 6.31] | 1158.3 [650.6, 1795.9] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |

<!-- faults:end -->

## What it shows

Each statement below is checked against the CSV by `tests/test_fault_matrix.py`.

1. **False alarms are zero on two controls and not on the third.** On `gnss_only` and
   `vision_only` the gate rejects nothing and no fault is declared. On `outage_visual`, the case
   with the outage, the gate rejects measurements in every seed and a fault is declared in three of
   five: the healthy GNSS receiver is declared faulty after it returns.
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
   rejects fixes in at most one seed and nothing is declared, yet the mean NEES is more than ten
   times the control's and coverage is under half. At 3 σ the gate reacts in every seed.
7. **A GNSS timestamp offset degrades calibration without detection.** No fault is declared at any
   level. Error, NEES and the loss of coverage all grow with the offset; at 0.5 s coverage is under
   60% and the gate rejected in only two seeds. A 0.05 s offset is not visible. A vision timestamp
   offset shows no measurable effect, but its control is already badly uncalibrated, so this case
   cannot show one.
8. **Losing 2 s of IMU samples is catastrophic, and the wrong sensor is blamed.** The error rises by
   two orders of magnitude over the control, and in every seed the FDIR layer declares the GNSS
   channel faulty, which is the healthy sensor. A 0.5 s loss is not declared, but it raises error
   and costs coverage.
9. **A modest spoof after an outage is not detected beyond the control's false alarms.** At 3 m and
   10 m the declarations match the control's (three of five seeds), so they cannot be told apart
   from the false alarms in point 1. At 22 m the spoof is declared in every seed, with an inflation
   grant in at most one, and the error is still above the control's. (The count was one in five
   seeds before the initial IMU bias was drawn, [ADR-0015](adr/0015-initial-imu-bias-sigmas-are-read.md),
   and is none in five after; it moves with the noise realisation.) This is the open problem recorded in
   [ADR-0007](adr/0007-spoof-permanence-hysteresis.md). It stays open.
10. **Vision outages of 2 s and 5 s** raise the error slowly on a case that is already
    uncalibrated, and nothing is detected, because a missing measurement is not an outlier.

## The Track A exit test, restated

[`ROADMAP.md`](roadmap.md) Track A asks for detection above 95% per fault type at zero false alarms
on the control. **It is not met.**

- Zero false alarms holds for two of the three controls (point 1).
- By the strict test, a fault declared in every seed, four of the eighteen fault cells qualify:
  the 10 m and 40 m sustained spoofs, the 22 m post-outage spoof, and the 2 s IMU loss, where the
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
