# Noise mismatch

What happens when the filter is told the wrong sensor noise.

Every calibrated result elsewhere in this site has the filter told the true noise of the
sensors that made the data. That is the easiest case a Kalman filter can have, and a real
filter never gets it. This page generates the data once with the true noise and filters it
with the assumed GNSS and vision sigmas multiplied by a factor. A factor below 1 makes the
filter trust the sensor more than it should; above 1, less. ([Model contract](MODEL.md),
as-implemented finding 5.)

```bash
navkit sweep mismatch --csv docs/data/mismatch_sweep.csv \
    --figure docs/figures/mismatch-sweep.png --page docs/mismatch.md
```

Two cases, nine factors, five noise seeds each. `gnss_only` has GNSS and no outage;
`outage_control` has the 15 s GNSS outage with vision off. The table below is generated from
[`data/mismatch_sweep.csv`](data/mismatch_sweep.csv) and a test fails if they disagree. CI
reruns the sweep and fails if the committed CSV no longer matches it.

<!-- mismatch:start -->

| Case | Assumed noise x | ATE rmse m [95% CI] | NEES mean [95% CI] | Coverage @2σ % [95% CI] | Claimed 1σ m | GNSS fixes rejected % [95% CI] | Verdicts |
|---|---:|---|---|---|---:|---|---|
| gnss_only | 0.25 | 48.81 [22.30, 75.32] | 53.6 [35.7, 71.4] | 7.7 [3.6, 14.0] | 8.369 | 94.6 [92.2, 96.4] | overconfident x5 |
| gnss_only | 0.5 | 17.05 [0.68, 33.59] | 29.1 [15.1, 50.3] | 31.8 [14.7, 48.8] | 2.470 | 47.7 [21.2, 75.6] | overconfident x5 |
| gnss_only | 0.7 | 0.59 [0.55, 0.62] | 7.6 [6.2, 8.9] | 80.4 [72.8, 88.5] | 0.189 | 4.8 [3.8, 5.6] | overconfident x5 |
| gnss_only | 0.8 | 0.55 [0.50, 0.59] | 5.5 [4.8, 6.2] | 94.2 [92.6, 95.7] | 0.207 | 0.9 [0.4, 1.3] | overconfident x5 |
| gnss_only | 0.9 | 0.53 [0.49, 0.58] | 4.4 [3.7, 5.1] | 98.7 [97.7, 99.7] | 0.229 | 0.1 [0.0, 0.4] | mixed(bulk xoverconfident, tail xunderconfident) x2, overconfident x3 |
| gnss_only | 1 | 0.53 [0.49, 0.58] | 3.7 [3.1, 4.2] | 99.9 [99.6, 100.0] | 0.253 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x3, mixed(bulk xunderconfident, tail xcalibrated) x1, underconfident x1 |
| gnss_only | 1.25 | 0.54 [0.49, 0.58] | 2.5 [2.1, 2.9] | 100.0 [100.0, 100.0] | 0.313 | 0.0 [0.0, 0.0] | mixed(bulk xcalibrated, tail xunderconfident) x1, underconfident x4 |
| gnss_only | 2 | 0.56 [0.52, 0.61] | 1.2 [1.0, 1.4] | 100.0 [100.0, 100.0] | 0.489 | 0.0 [0.0, 0.0] | underconfident x5 |
| gnss_only | 4 | 0.72 [0.65, 0.79] | 0.6 [0.5, 0.6] | 100.0 [100.0, 100.0] | 0.921 | 0.0 [0.0, 0.0] | underconfident x5 |
| outage_control | 0.25 | 67.15 [39.13, 92.84] | 38.2 [22.8, 61.8] | 10.5 [3.5, 22.7] | 11.682 | 90.8 [86.8, 94.5] | overconfident x5 |
| outage_control | 0.5 | 18.36 [10.65, 29.97] | 17.8 [13.0, 25.4] | 35.2 [17.8, 51.9] | 2.369 | 35.0 [18.7, 59.2] | overconfident x5 |
| outage_control | 0.7 | 12.74 [9.08, 16.02] | 7.1 [5.4, 8.6] | 84.5 [67.6, 95.7] | 0.432 | 3.9 [3.2, 4.7] | overconfident x5 |
| outage_control | 0.8 | 11.76 [8.66, 14.85] | 5.6 [4.2, 7.0] | 95.4 [88.6, 99.6] | 0.464 | 0.8 [0.0, 1.8] | calibrated x1, mixed(bulk xoverconfident, tail xcalibrated) x1, mixed(bulk xoverconfident, tail xunderconfident) x1, overconfident x2 |
| outage_control | 0.9 | 11.55 [8.72, 14.23] | 4.5 [3.3, 5.6] | 98.9 [97.6, 100.0] | 0.512 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x2, overconfident x2, underconfident x1 |
| outage_control | 1 | 10.88 [8.47, 13.34] | 3.6 [2.8, 4.5] | 99.7 [99.5, 100.0] | 0.567 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xcalibrated) x2, mixed(bulk xoverconfident, tail xunderconfident) x2, underconfident x1 |
| outage_control | 1.25 | 9.51 [7.11, 11.90] | 2.4 [1.9, 3.0] | 100.0 [100.0, 100.0] | 0.703 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x1, underconfident x4 |
| outage_control | 2 | 8.15 [5.56, 10.70] | 1.2 [0.9, 1.5] | 100.0 [100.0, 100.0] | 0.944 | 0.0 [0.0, 0.0] | underconfident x5 |
| outage_control | 4 | 10.21 [7.21, 13.65] | 0.9 [0.5, 1.3] | 100.0 [100.0, 100.0] | 1.713 | 0.0 [0.0, 0.0] | underconfident x5 |

<!-- mismatch:end -->

![Mismatch sweep](figures/mismatch-sweep.png)

## What it shows

Each statement below is checked against the CSV by `tests/test_mismatch_sweep.py`.

1. **An optimistic noise model is not a graceful failure.** With the assumed noise below the
   true noise, the chi-square gate starts rejecting healthy GNSS fixes (see the rejection
   column), the filter dead-reckons through the gap, and error grows. In `gnss_only` it grows by
   more than an order of magnitude at the strongest mismatch; in `outage_control`, which starts
   from a large error, it still more than doubles. The gate meant to protect the filter from bad data turns an
   optimistic noise model into data loss. The rejection column shows it directly.
2. **Calibration is lost well before the gate does much damage.** Mean 2σ coverage leaves a
   90% band between factors 0.7 and 0.8 in both cases, while the rejection share is still in
   single digits. An underestimate of the sensor noise of between 20% and 30% is enough. The
   90% band is my choice, not a derived threshold.
3. **A pessimistic noise model costs little accuracy and is honest about it.** With the assumed
   noise above the true noise, the position error in `gnss_only` barely moves at a factor of two and rises
   modestly at four, the claimed uncertainty scales up with the assumption, coverage stays at 100% and the
   filter reads as underconfident. Looser, not wrong.
4. **With the true noise, the bulk test already reads slightly overconfident.** At factor 1
   the mean NEES is above 3 in both cases. Its interval includes 3 in `outage_control` and only just excludes it in
   `gnss_only`, which matches the benchmark's `mixed` verdicts. By factor 1.25 the mean NEES is below 3.
5. **One result I did not expect and have not explained.** In `outage_control`, position error
   falls as the assumed noise grows from the strongest mismatch up to a factor of two, and the intervals at those
   two ends do not overlap. At four it is no better than at two. Between the true noise and a factor of two the
   intervals overlap, so five seeds do not establish a trend near the true noise. An earlier version of this page
   saw the error fall all the way to four, with non-overlapping intervals at one and four; that did not survive the
   start being drawn from the declared prior. A plausible reason for the fall is that a larger assumed noise keeps
   the bias states from fitting GNSS noise before the outage, which would make dead reckoning through it better.
   That is a hypothesis; I did not test it.

## What this does not show

- One synthetic path, one noise model (white and Gaussian), and one factor applied to every
  axis and, with `--channel both`, to both sensors. Nothing here says how a real receiver's
  noise is mismatched.
- Only the assumed GNSS and vision sigmas change. IMU noise, the outage window and the
  trajectory do not.
- Both cases have the default IMU noise ([ADR-0012](adr/0012-every-scenario-is-injected.md)). An
  earlier version of this sweep ran `gnss_only` with a noiseless IMU; it was rerun after that was fixed
  and the statements above still hold.
- Five seeds per cell, so the intervals are rough. At factor 1 the per-seed verdicts are split
  between `mixed`, `underconfident` and `overconfident`; the verdict column shows the split
  rather than a single label.
- It does not say what the right noise is, or how to estimate it. Adaptive noise estimation is
  not implemented.
