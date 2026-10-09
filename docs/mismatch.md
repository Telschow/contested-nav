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
| gnss_only | 0.25 | 45.28 [26.86, 63.02] | 68.4 [46.1, 94.2] | 10.8 [3.7, 18.0] | 7.207 | 94.4 [92.1, 96.8] | overconfident x5 |
| gnss_only | 0.5 | 9.37 [0.67, 18.49] | 19.0 [15.0, 24.1] | 31.1 [14.6, 46.1] | 2.236 | 46.5 [21.7, 74.2] | overconfident x5 |
| gnss_only | 0.7 | 0.57 [0.53, 0.61] | 7.6 [6.0, 9.0] | 80.4 [71.5, 89.5] | 0.189 | 4.5 [4.0, 5.3] | overconfident x5 |
| gnss_only | 0.8 | 0.53 [0.50, 0.58] | 5.6 [4.5, 6.7] | 92.4 [87.1, 96.9] | 0.208 | 0.9 [0.7, 1.2] | mixed(bulk xoverconfident, tail xunderconfident) x1, overconfident x4 |
| gnss_only | 0.9 | 0.52 [0.48, 0.56] | 4.3 [3.4, 5.3] | 99.1 [97.9, 100.0] | 0.230 | 0.1 [0.0, 0.4] | mixed(bulk xoverconfident, tail xunderconfident) x3, overconfident x2 |
| gnss_only | 1 | 0.51 [0.48, 0.56] | 3.6 [2.8, 4.3] | 100.0 [100.0, 100.0] | 0.254 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x3, underconfident x2 |
| gnss_only | 1.25 | 0.51 [0.47, 0.55] | 2.4 [1.8, 2.9] | 100.0 [100.0, 100.0] | 0.313 | 0.0 [0.0, 0.0] | mixed(bulk xcalibrated, tail xunderconfident) x1, mixed(bulk xoverconfident, tail xunderconfident) x1, underconfident x3 |
| gnss_only | 2 | 0.50 [0.45, 0.55] | 1.0 [0.8, 1.2] | 100.0 [100.0, 100.0] | 0.490 | 0.0 [0.0, 0.0] | underconfident x5 |
| gnss_only | 4 | 0.55 [0.49, 0.61] | 0.4 [0.3, 0.5] | 100.0 [100.0, 100.0] | 0.921 | 0.0 [0.0, 0.0] | underconfident x5 |
| outage_control | 0.25 | 35.06 [15.33, 57.65] | 45.0 [28.2, 65.4] | 38.5 [14.4, 62.4] | 6.880 | 87.4 [81.1, 93.7] | overconfident x5 |
| outage_control | 0.5 | 21.18 [12.69, 32.04] | 17.2 [11.7, 25.1] | 33.0 [14.5, 53.8] | 2.669 | 42.9 [20.0, 67.9] | overconfident x5 |
| outage_control | 0.7 | 11.55 [6.80, 16.30] | 7.0 [4.8, 8.8] | 78.2 [61.0, 94.2] | 0.420 | 3.7 [2.4, 5.3] | overconfident x5 |
| outage_control | 0.8 | 11.34 [6.71, 15.96] | 5.7 [3.8, 7.3] | 96.5 [90.9, 99.6] | 0.464 | 0.8 [0.0, 1.8] | mixed(bulk xoverconfident, tail xunderconfident) x1, mixed(bulk xunderconfident, tail xcalibrated) x1, overconfident x3 |
| outage_control | 0.9 | 10.56 [6.22, 14.89] | 4.4 [2.9, 5.6] | 98.8 [96.4, 100.0] | 0.512 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x3, overconfident x1, underconfident x1 |
| outage_control | 1 | 9.74 [5.67, 13.81] | 3.5 [2.4, 4.5] | 99.7 [99.1, 100.0] | 0.567 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x3, overconfident x1, underconfident x1 |
| outage_control | 1.25 | 8.04 [4.55, 11.54] | 2.1 [1.5, 2.9] | 100.0 [100.0, 100.0] | 0.703 | 0.0 [0.0, 0.0] | mixed(bulk xoverconfident, tail xunderconfident) x1, underconfident x4 |
| outage_control | 2 | 5.06 [2.71, 8.09] | 0.9 [0.6, 1.3] | 100.0 [100.0, 100.0] | 0.944 | 0.0 [0.0, 0.0] | underconfident x5 |
| outage_control | 4 | 3.38 [2.42, 4.79] | 0.5 [0.3, 0.6] | 100.0 [100.0, 100.0] | 1.713 | 0.0 [0.0, 0.0] | underconfident x5 |

<!-- mismatch:end -->

![Mismatch sweep](figures/mismatch-sweep.png)

## What it shows

Each statement below is checked against the CSV by `tests/test_mismatch_sweep.py`.

1. **An optimistic noise model is not a graceful failure.** With the assumed noise below the
   true noise, the chi-square gate starts rejecting healthy GNSS fixes (see the rejection
   column), the filter dead-reckons through the gap, and error grows. In `gnss_only` it grows by
   more than an order of magnitude at the strongest mismatch; in `outage_control`, which starts
   from a large error, it still more than doubles. The gate meant to protect the filter from bad data turns an
   optimistic noise model into data loss. I checked this mechanism on one run (seed 0, factor
   0.5, `gnss_only`): 116 of 151 fixes were rejected and one fault was declared. That one run is
   an observation, not part of the table.
2. **Calibration is lost well before the gate does much damage.** Mean 2σ coverage leaves a
   90% band between factors 0.7 and 0.8 in both cases, while the rejection share is still in
   single digits. An underestimate of the sensor noise of between 20% and 30% is enough. The
   90% band is my choice, not a derived threshold.
3. **A pessimistic noise model is benign for accuracy and honest about it.** With the assumed
   noise above the true noise, the position error in `gnss_only` barely moves, the claimed
   uncertainty scales up with the assumption, coverage stays at 100% and the filter reads as
   underconfident. Looser, not wrong.
4. **With the true noise, the bulk test already reads slightly overconfident.** At factor 1
   the mean NEES is above 3 in both cases, although its interval includes 3, which matches the
   benchmark's `mixed` verdicts. By factor 1.25 the mean NEES is below 3.
5. **One result I did not expect and have not explained.** In `outage_control`, position error
   falls as the assumed noise grows, and the intervals at factors 1 and 4 do not overlap. A
   plausible reason is that a larger assumed noise keeps the bias states from fitting GNSS
   noise before the outage, which would make dead reckoning through it better. That is a
   hypothesis; I did not test it.

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
