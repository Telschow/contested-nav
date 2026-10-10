# ADR-0019: Slow-ramp GNSS spoofing is not detectable with IMU and GNSS alone

- Status: accepted
- Date: 2026-10
- Related: [ADR-0007](0007-spoof-permanence-hysteresis.md), [ADR-0018](0018-honest-return-separability.md), [slow ramp](../slow_ramp.md)

## Context

The slow-ramp experiment shows the filter follows a ramp of 0.05 to 2 m/s in every run, on two datasets and two
settings. The gate reacts only to the fastest ramps and only with the default noise, and a faulty declaration
does not stop the capture.

## Options

1. **Document the limit.** Track A's exit test states that spoof detection needs a second independent source.
2. **Add a rate-of-change check against the IMU.** It can only see ramps above what the IMU's own error growth
   allows, which the data suggests is a few m/s, not the slow ramps measured here.
3. **Make a second source a requirement.** Vision, a barometer or a map, to be tested in the same experiment.

## Decision

Option 1. The limit is documented: with an IMU and GNSS alone, a slow-ramp spoof is not detectable, and the
filter follows it. Track A's exit test is stated as not meetable for spoofing without a second independent source.
No rate check is added, because the data show the ramps that matter sit below what the IMU can distinguish from its
own error growth. Option 3, a second source as a requirement, is the follow-up experiment and is not started.

The limit is recorded in the limitations ([L6](../defense/LIMITATIONS.md)), the risk log (R10) and the roadmap.
The shipped configuration is unchanged.

## Consequences

Whatever is chosen, the claim stays limited to simulated GNSS, one direction and two datasets.
