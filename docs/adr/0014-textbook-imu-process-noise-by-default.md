# ADR-0014: IMU white noise enters the process covariance in the textbook form

- Status: proposed
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

Two measurements on the EuRoC Machine Hall sequences (recorded IMU, GNSS simulated from the ground
truth, a 20 s outage at several start times, two seeds), reproducible with `navkit euroc run`:

- The textbook form alone lowers mean NEES and the number of GNSS lockouts after an outage a little. It
  does not remove the lockouts. The cause of those is that the datasheet IMU noise understates the real
  error growth: the filter claims several times less uncertainty than the error it has at the end of an
  outage, so it rejects GNSS when it returns and never recovers. Starting exactly on the ground truth
  changes nothing. Scaling the assumed IMU noise by 3 removes the lockouts on the sequences it was
  chosen on and on the others, and is offered as `--preset adis16448`, not as a filter default.
- A declared bias prior on its own helped on the easy sequences and hurt on the difficult ones.

These are not in the repository as committed results. The commands below regenerate them.

## Options

1. **Keep the old form as the default.** Nothing in the benchmark moves. The covariance stays wrong
   in a way a reader of the code cannot see.
2. **Make the textbook form the default and keep the old one selectable.** The synthetic numbers
   move a little. `process_noise_form="legacy"` reproduces the old ones.
3. **Replace the old form.** Loses the ability to reproduce any number quoted before this change.

## Decision

_To be written by the maintainer._

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
  sequence and checked on four others, all of them Machine Hall. The Vicon room sequences have not
  been run.
- GNSS is simulated from the ground truth. Nothing here is GNSS-denied performance in the field.
- The filter does not model scale-factor error, axis misalignment, or a time-varying bias, which are
  the likely sources of the gap between the datasheet noise and the real error growth. That is a
  hypothesis, not a result.
