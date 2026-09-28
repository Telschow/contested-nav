# ADR-0005: Chi-square innovation gating with per-channel fault isolation

- Status: accepted
- Date: 2026-09

## Context

The filter already gated updates. `EskfConfig.gate_sigma` rejects an update
whose innovation exceeds `gate_sigma` standard deviations, per component.

That gate has two defects, and neither is a threshold value.

**It has no false-alarm rate.** The threshold is 3 by hand, chosen before
anyone asked how often a healthy receiver would trip it. There is no answer,
so there is nothing to tune against and no way to trade detection against
nuisance alarms deliberately. It is a number, not a decision rule.

**It is stateless.** A rejection is a counter increment. A receiver that has
been lost for ten seconds and one that dropped a single frame produce the
same record: one more rejected update. The system that is supposed to notice
a contested sensor cannot tell a momentary spike from a dead channel, and so
cannot respond differently to them.

ADR-0001 and ADR-0003 established that this project's failures are not
smooth — a collapsed covariance, a correlated error the model cannot
represent. Smoothing is what the filter already does well. What it lacks is
a way to say *this channel is lying* rather than *this number looks odd*.

## Decision

- Add `fdir/`, with no SciPy. A tabulated chi-square threshold for the dof a
  navigation filter actually produces (1, 2, 3, 6), exact quantiles from
  `eval/statistics.py` for the small untabulated values where
  Wilson-Hilferty is not trustworthy, and Wilson-Hilferty in closed form
  beyond that.
- Test every update before the Kalman gain is formed. A rejected update
  returns immediately: `P^+ = P^-`, state untouched.
- Track fault state per channel, with `max_consecutive_rejections` to exclude
  a channel and `auto_recovery_count` consecutive accepted updates to bring
  it back. Log transitions, not transients.
- Gate the two blocks of a relative-pose fix as `vision_rot` and
  `vision_trans`. They come from one transform, so a single `vision` channel
  would let the healthy half vouch for the broken half.
- Keep `gate_sigma`. It is a second, independent bound, and the existing
  rejection counters — which is how the ADR-0001 defect was found — keep
  meaning what they meant.

### Why `alpha = 0.001` and not 0.01

The brief asked for 0.99 confidence and zero false rejections at that
operating point. Those two are the same number, and it is not achievable: a
gate at 99% confidence rejects 1% of healthy updates by definition, because
that is what the 1% means.

Measured on this project's own fixture — 20 s runs, 12 visual seeds, 1212
healthy GNSS fixes:

| `alpha` | Healthy fixes rejected | Broken configuration |
|---:|---:|---|
| 0.01 | 13 of 1212 (1.07%) | 68 of 101 rejected, fault declared |
| 0.001 | 0 of 1212 | broken detection unchanged |

Nuisance rate matches the nominal rate almost exactly, which is the expected
result and a good sign that the test is sound. But a healthy receiver
tripping the fault detector once per hundred epochs is a receiver nobody
can fly with, and it would drown the covariance-collapse alarm this
subsystem exists to extend.

`FdirConfig` still accepts 0.99. It is a real operating point for a channel
whose every rejection is logged and acted on. It is not the default for a
channel sharing a filter with a health monitor.

## Consequences

- `src/navkit/fdir/gating.py` 87.0% covered, `fdir_manager.py` 90.2%.
- GNSS: a 15 m spoof step and a 50 m multipath spike are both rejected;
  baseline peak position error on the fixture is 0.29 m, so following the
  fix would show up as 15 m. A 30-fix spoof escalates to `SENSOR_FAULT` at
  the fifth consecutive rejection, not the thirtieth.
- Vision: a 10 m translation step faults `vision_trans` with zero rejections
  recorded on `vision_rot`. A 90 deg rotation step is the mirror image. The
  modelled anchor absorbs a 20 deg step, which is what the anchor is for.
- **The flagship benchmark case got worse, and this is the honest cost.**
  `outage_visual` ATE 3.428 m -> 5.059 m; `outage_visual_degraded_camera`
  2.545 m -> 3.339 m. In both, FDIR rejects the GNSS fixes that return at
  `t = 20 s` after the denial — 51 of 75 in `outage_visual` — because the
  filter ends the outage displaced and holding a collapsed covariance, and a
  gate that trusts that covariance reads a healthy 3 m fix as an outlier. The
  filter then dead-reckons the last 9 s instead of snapping back.

  The gate is doing exactly what it was specified to do. The specification
  assumes a calibrated `S`, and this filter does not have one in precisely
  the configurations this project exists to study. The mitigation is a
  consistency monitor — an innovation-consistency statistic that detects the
  miscalibration and widens the gate when the chi-square premise is void —
  not a different threshold. Tracked as blocker B4 and pinned by
  `test_fdir_throws_away_the_absolute_fixes_that_would_rescue_a_displaced_filter`,
  so the cost cannot be quietly forgotten or quietly re-measured as a
  regression in the gate.
- A 20 deg rotation step is absorbed by the modelled anchor rather than
  rejected. This is the anchor working, not the gate failing, and it is
  stated here so a future test does not pick that magnitude and conclude
  the gate is blind.
- SENSOR_CHANNELS lists four channel names, not three. There is no `vision`
  channel, and there is no altimeter update in the filter; the constant
  documents the vocabulary the tracker is called with, and
  `tests/test_estimators.py` is where the actual call sites live.
