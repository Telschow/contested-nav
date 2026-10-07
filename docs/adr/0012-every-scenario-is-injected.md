# ADR-0012: Every scenario goes through the injection layer

- Status: accepted
- Date: 2026-10
- Fixes: [issue 56](https://github.com/Telschow/contested-nav/issues/56)

## Context

`run_case` in `src/navkit/benchmark.py` applied a scenario to the clean sensor streams with
`inject()` only if the scenario had a camera drop or an outage. Otherwise the filter was given the
clean streams. The synthetic IMU has no noise of its own (`synthetic.py`: "no noise floor"); the IMU
noise and bias are added by `apply_imu_noise`, inside `inject()`.

So four of the seven benchmark cases (`gnss_only`, `dead_reckoning`,
`vision_anchor_in_measurement_noise`, `vision_only`) ran with a noiseless IMU, and the three outage
cases ran with the default IMU noise. `configs/benchmark.yaml` says cases "differ only in what is
degraded, which is what makes them comparable". They also differed in IMU noise. A scenario that
set only a timestamp offset, or only a vision noise multiplier, had no effect.

It was found while building the fault matrix: a GNSS timestamp offset of 0.5 s produced a result
identical to the control to every digit.

## Decision

Every scenario goes through `inject()`. The `force_inject` argument added to `run_case` for the fault
matrix is removed, because nothing is skipped any more.

A noiseless IMU is still available to anyone who wants it: set `imu_noise_scale: 0` on the scenario.
`tests/test_injection_path.py` checks that this reproduces the old dead-reckoning number.

## Consequences

The three outage cases are bit-identical: the golden snapshot has no changed path for them. The four
cases that were not injected move, and none changes its calibration verdict:

| Case | ATE m | Mean NEES | 2σ coverage |
|---|---|---|---|
| `gnss_only` | 0.503 to 0.509 | 3.7 to 4.0 | 100.0% to 100.0% |
| `dead_reckoning` | 1.877 to 2.248 | n/a | n/a |
| `vision_anchor_in_measurement_noise` | 1.307 to 1.310 | 387.3 to 405.0 | 16.0% to 16.2% |
| `vision_only` | 2.309 to 2.357 | 331.0 to 358.5 | 0.7% to 0.7% |

Claimed 1σ is unchanged to three decimals (0.252, 0.091, 0.156 m). The headline result, GNSS denied
with vision on (ATE 2.541 m, claimed 0.161 m, mean NEES 419.4, coverage 20.0%), does not move.

The golden snapshot was regenerated in its own commit. The README, results, getting-started and
calibration pages, and three figures, were updated. The 10-seed and 8-scene sweeps were rerun:
`outage_visual` is unchanged, the `vision_only` seed range is now 231 to 2917 mean NEES, and all
seven verdicts are still identical in all eight scenes. The noise-mismatch sweep was rerun with the
layer applied to `gnss_only`; the statements on its page still hold. The fault matrix was already
forced through the layer and is unchanged.

`dead_reckoning` is now dead reckoning on a noisy IMU, which is the more honest control. Its error
is 20% higher than before.

## Alternatives rejected

- **Keep skipping, and state per case that the IMU is clean.** It keeps the old numbers, and keeps
  four cases that cannot be compared with the other three or with any fault study. The numbers move
  by little, so the cost of fixing is small.
- **Add IMU noise to the generator.** The IMU noise model, its seed derivation and its manifest
  already live in the injection layer. A second source would double the noise or need a switch.
- **A config key to opt out of injection.** `imu_noise_scale: 0` already says what is meant.

## What this does not settle

The IMU noise injected into every case is the default model
(`ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)`), whose bias sigma fields are inert
([model contract](../MODEL.md), finding 1). The decision is about which cases get the noise, not
about whether the noise model is right.
