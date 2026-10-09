# ADR-0014: IMU white noise enters the process covariance in the textbook form

- Status: accepted
- Date: 2026-10
- Related: [ADR-0013](0013-recorded-imu-with-simulated-gnss.md)

## Context

The filter's process covariance took IMU white noise as `sigma_a^2 dt^3 / 3` on position, nothing on
velocity, and `sigma_g^2 dt^3 / 3` on attitude. Continuous white noise on the error-state model gives
`sigma_a^2 dt` on velocity (with `dt^3 / 3` and `dt^2 / 2` on position and the cross term) and
`sigma_g^2 dt` on attitude. With no prior and no bias, the old form grew the position, velocity and
attitude 1-sigma by orders of magnitude less than the theory over a few seconds.
`tests/test_known_gaps.py` states the theory, one noise source at a time (gyro noise also reaches
velocity through gravity, which is physics and not process noise), and shows the old form failing it.

It was found while running the filter on a recorded EuRoC IMU (ADR-0013). On the synthetic benchmark
the difference is small, because the synthetic IMU noise is small and the aiding is frequent.

Measurements on all eleven EuRoC sequences (Machine Hall and Vicon rooms; recorded IMU, GNSS simulated
from the ground truth, a 20 s outage at up to four start times, two seeds), reproducible with
`navkit euroc run`. A run counts as lost when the filter rejects more than a fifth of its GNSS fixes:

- With the new default, about half of the runs are lost, and the Vicon rooms are worse than Machine Hall.
  The textbook form alone lowers mean NEES and the number of losses a little. It does not remove them.
  The cause is that the datasheet IMU noise understates the real error growth: the filter claims several
  times less uncertainty than the error it has at the end of an outage, so it rejects GNSS when it returns
  and does not recover. Starting exactly on the ground truth changes nothing.
- With `--preset adis16448` (assumed IMU noise x3, 0.05 bias prior) a handful of runs are lost, on MH_04,
  MH_05 and V1_01, and the median NEES and the 2-sigma coverage are close to nominal. The scale was chosen
  on MH_01_easy and then checked on the other ten sequences. It is a tuning for this sensor, not a filter
  default.
- A declared bias prior on its own helped on the easy sequences and hurt on the difficult ones.
- The FDIR layer's "channel faulted" flag undercounts these losses. Some runs reject hundreds of GNSS fixes
  and are never declared faulty, so a measure based on the flag alone looked better than it was. An earlier
  version of this analysis used the flag and was corrected.

These are not in the repository as committed results. The commands below regenerate them.

## Options

1. **Keep the old form as the default.** Nothing in the benchmark moves. The covariance stays wrong
   in a way a reader of the code cannot see.
2. **Make the textbook form the default and keep the old one selectable.** The synthetic numbers
   move a little. `process_noise_form="legacy"` reproduces the old ones.
3. **Replace the old form.** Loses the ability to reproduce any number quoted before this change.

## Decision

Option 2. The `textbook` form is the default and `legacy` stays selectable.

The old form fails a test that states plain white-noise theory, and a known-wrong covariance is hard
to defend as a default. Keeping `legacy` costs nothing and keeps the earlier numbers reproducible.

This fix is not what rescued the EuRoC runs. The IMU noise scale did that, and it is a tuning for one
sensor, not a filter property. The `textbook` form is the correct model, not a cure.

Reopen this if a real-GNSS dataset shows that inflation like the `adis16448` preset is still needed
with the `textbook` form, or shows that it is not.

## What the code does in the meantime

It implements option 2: `EskfConfig.process_noise_form` defaults to `"textbook"`. Every benchmark
case, sweep, figure and table was regenerated, and the golden snapshot was regenerated in its own
commit. No calibration verdict changes: the controls that were overconfident still are, and the
single-anchor defect case is kept as a control row.

Numbers quoted in older ADRs, in the completed items of the roadmap, and in the dated baselines and
audit snapshots were measured with the old form and are not recomputed. Where a live page quotes a
before-and-after of an earlier change (for example the effect of ADR-0006), the pair is left as it was
measured.

```bash
navkit euroc run --sequence MH_01_easy --outage 60:20 --process-noise legacy --out results/legacy.json
navkit euroc run --sequence MH_01_easy --outage 60:20 --out results/textbook.json
navkit euroc run --sequence MH_01_easy --outage 60:20 --preset adis16448 --out results/preset.json
```

## What this does not settle

- The IMU noise inflation is a property of one sensor and these recordings. It was chosen on one
  sequence and checked on ten others from the same dataset, so it has not been tested on another
  IMU or another vehicle. It still fails on a few runs, and V1_01_easy is the weakest.
- That the FDIR layer misses a long run of rejections is a separate finding and is not addressed here.
- GNSS is simulated from the ground truth. Nothing here is GNSS-denied performance in the field.
- The filter does not model scale-factor error, axis misalignment, or a time-varying bias, which are
  the likely sources of the gap between the datasheet noise and the real error growth. That is a
  hypothesis, not a result.
