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
| gnss_only | none (control) |  | 0.52 [0.47, 0.57] | 3.9 [3.0, 4.9] | 99.5 [98.4, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS spoof, sustained offset | 3 m | 2.89 [2.28, 3.65] | 79.7 [68.9, 94.6] | 38.9 [35.9, 43.2] | 5/5 | 2/5 | gnss | 11.2 | 0/5 | 15.9 [3.4, 28.3] |
| gnss_only | GNSS spoof, sustained offset | 10 m | 5.23 [0.73, 9.74] | 75.0 [2.6, 174.8] | 85.6 [70.7, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 47.9 [37.0, 59.5] |
| gnss_only | GNSS spoof, sustained offset | 40 m | 1.13 [0.73, 1.78] | 2.8 [2.3, 3.3] | 99.5 [98.4, 100.0] | 5/5 | 5/5 | gnss | 0.8 | 0/5 | 39.1 [39.1, 39.1] |
| gnss_only | GNSS single spike | 20 m | 0.52 [0.47, 0.57] | 3.9 [2.9, 5.0] | 99.6 [98.8, 100.0] | 5/5 | 0/5 | none | n/a | 0/5 | 0.7 [0.7, 0.7] |
| gnss_only | GNSS slow bias | 1 m (1 sigma) | 1.42 [1.07, 1.73] | 41.5 [17.9, 66.2] | 35.0 [19.0, 57.0] | 1/5 | 0/5 | none | n/a | 0/5 | 0.1 [0.0, 0.4] |
| gnss_only | GNSS slow bias | 3 m (1 sigma) | 4.07 [2.89, 5.45] | 198.1 [116.4, 325.5] | 10.0 [2.8, 17.2] | 5/5 | 2/5 | gnss | n/a | 0/5 | 18.7 [3.3, 35.2] |
| gnss_only | GNSS timestamp offset | 0.05 s | 0.54 [0.49, 0.59] | 4.1 [3.1, 5.1] | 98.9 [96.8, 100.0] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.2 s | 0.65 [0.61, 0.70] | 5.7 [4.5, 6.8] | 91.8 [85.7, 97.3] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| gnss_only | GNSS timestamp offset | 0.5 s | 1.02 [0.99, 1.05] | 13.2 [11.7, 14.7] | 56.0 [52.3, 60.3] | 2/5 | 0/5 | none | n/a | 0/5 | 0.4 [0.0, 0.9] |
| gnss_only | IMU sample loss | 0.5 s lost at 10 s | 0.87 [0.76, 0.98] | 13.4 [10.4, 16.8] | 56.7 [48.5, 64.6] | 2/5 | 0/5 | none | n/a | 0/5 | 0.3 [0.0, 0.5] |
| gnss_only | IMU sample loss | 2 s lost at 10 s | 70.93 [67.76, 73.41] | 1162.8 [1095.6, 1252.0] | 38.1 [36.8, 39.1] | 5/5 | 5/5 | gnss | 5.5 | 0/5 | 51.7 [50.9, 52.5] |
| outage_visual | none (control) |  | 3.26 [2.50, 4.38] | 626.9 [391.6, 1017.6] | 20.5 [15.2, 27.7] | 5/5 | 3/5 | gnss | n/a | 5/5 | 3.1 [1.4, 4.8] |
| outage_visual | GNSS spoof after an outage | 3 m | 3.66 [3.05, 4.38] | 748.8 [561.4, 958.8] | 17.0 [11.3, 26.1] | 5/5 | 3/5 | gnss | 6.3 | 5/5 | 2.9 [1.2, 4.6] |
| outage_visual | GNSS spoof after an outage | 10 m | 7.40 [6.29, 9.19] | 3246.1 [2204.7, 5047.3] | 16.9 [11.2, 26.1] | 5/5 | 3/5 | gnss | 4.9 | 4/5 | 3.3 [1.2, 5.6] |
| outage_visual | GNSS spoof after an outage | 22 m | 6.74 [5.08, 8.96] | 2976.9 [1819.2, 4901.4] | 16.9 [11.2, 26.1] | 5/5 | 5/5 | gnss | 0.8 | 1/5 | 7.3 [6.7, 7.6] |
| vision_only | none (control) |  | 3.60 [2.40, 5.20] | 888.6 [330.3, 1704.2] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.05 s | 3.54 [2.39, 5.10] | 853.0 [349.0, 1633.2] | 0.8 [0.8, 0.8] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision timestamp offset | 0.2 s | 3.46 [2.50, 4.84] | 786.3 [369.8, 1466.3] | 1.3 [1.3, 1.3] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision outage | 2 s lost at 10 s | 3.99 [2.54, 5.53] | 1053.6 [385.3, 1901.7] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |
| vision_only | Vision outage | 5 s lost at 10 s | 4.91 [3.51, 6.46] | 1392.1 [658.8, 2287.6] | 0.7 [0.7, 0.7] | 0/5 | 0/5 | none | n/a | 0/5 | 0.0 [0.0, 0.0] |

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
   grant in only one, and the error is still above the control's. This is the open problem recorded in
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
- Every cell, controls included, goes through the injection layer, so all of them have the default
  IMU noise. The `gnss_only` and `vision_only` controls therefore differ from the benchmark rows of
  the same name, which run with a noiseless IMU
  ([issue 56](https://github.com/Telschow/contested-nav/issues/56), model contract finding 7).
- "Detected" and "declared" describe what the filter's own gate did. Nothing here is a protection
  level or an integrity claim, and there is no detector for a slow bias or a timing error to
  measure.
