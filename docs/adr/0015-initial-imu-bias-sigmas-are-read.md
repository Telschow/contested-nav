# ADR-0015: The initial IMU bias sigmas are read

- Status: proposed
- Date: 2026-10
- Related: [ADR-0012](0012-every-scenario-is-injected.md), [ADR-0014](0014-textbook-imu-process-noise-by-default.md)

## Context

`ImuNoiseModel` has `gyro_bias_sigma` and `accel_bias_sigma`. They were accepted, scaled and hashed,
and read by nothing: the injected bias was a random walk that started at zero, and the benchmark
filter's initial bias covariance was zero too ([model contract](../MODEL.md), finding 1). The filter
had a single `initial_bias_sigma` for two quantities with different units (finding 3). A real IMU does
not start with zero bias, and on the EuRoC recordings a declared bias prior changed whether runs
recovered after an outage (ADR-0014).

## Options

1. **Leave them inert and document it.** Nothing moves. The fields keep suggesting an effect they do
   not have.
2. **Remove the fields.** Honest, and breaks any config that sets them.
3. **Read them.** The generator draws an initial bias per axis from each sigma, and the benchmark
   filter is told the same sigmas. The synthetic numbers move.

## Decision

_To be written by the maintainer._

## What the code does in the meantime

It implements option 3. The initial bias is drawn from its own random stream, so the white noise and
the random walk of every scenario are drawn exactly as before and a scenario with zero sigmas is
unchanged. `EskfConfig` gains `initial_gyro_bias_sigma` and `initial_accel_bias_sigma`, each falling back
to `initial_bias_sigma` when unset, so existing configs behave as before. The benchmark sets them from
the scenario's noise model, scaled by `imu_noise_scale`, so the filter is told what the generator used.

Every benchmark case, sweep, figure and table was regenerated, and the golden snapshot in its own
commit. The headline cases move by amounts that depend on one noise draw, and no calibration verdict
changes. One count moved: the 22 m GNSS spoof after an outage earned an inflation grant in one seed of five before and in none after. The fault-matrix claim now says "at most one". Numbers in older ADRs, the roadmap's completed items and the dated baselines were measured
before this change and are not recomputed.

## What this does not settle

- The default bias sigmas are the project's order-of-magnitude figures for a consumer IMU, not
  measurements of any sensor.
- The drift keys named per second that are per square-root second (finding 2) are untouched.
- The EuRoC path does not use these fields: it takes its noise from the sensor's own `sensor.yaml`
  and declares a bias prior with `--bias-sigma`.
