# ADR-0018: Honest returns after an outage and the GNSS gate

- Status: accepted
- Date: 2026-10
- Related: [ADR-0007](0007-spoof-permanence-hysteresis.md), [ADR-0014](0014-textbook-imu-process-noise-by-default.md), [separability](../separability.md)

## Context

On real recorded IMU data the shipped gate rejects many honest GNSS returns after an outage, and the channel is
then declared faulty. The measurement on the separability page shows that with the default noise the honest
returns and spoofs of tens of metres overlap, and that with a calibrated bias walk they separate, but only for
spoofs larger than the claimed uncertainty (tens of metres after 20 s).

## Options

1. **Change nothing.** Document the limit.
2. **Make the calibrated bias walk the default for recorded IMUs.** Honest returns pass; small spoofs stay
   undetectable by the first fix.
3. **A bounded re-acquisition after an outage, with a tuned gate.** A gate fitted on EuRoC did not transfer to
   TUM VI (16% honest rejection at a 5% target), so this needs more data than two datasets.

## Decision

Option 2, with option 1's honesty about the limit. For recorded IMUs the filter is run with the calibrated bias
walk (`--preset adis16448-walk` on EuRoC, the walk-scaled setting on TUM VI). The shipped defaults and the FDIR gate
are unchanged. No re-acquisition gate is tuned, because a gate fitted on one dataset did not transfer to the other.

The limit is stated, not tuned away: a spoof smaller than the claimed uncertainty at return (tens of metres after
a 20 s outage) cannot be told from an honest return by the first fix. A slow-ramp spoof is not covered by this
measurement and stays open.

## Consequences

Whatever is chosen, the claim stays limited to simulated GNSS and the first gate. Spoof detectability depends on
the honest population, which here is two datasets.
