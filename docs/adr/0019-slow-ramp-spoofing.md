# ADR-0019: Slow-ramp GNSS spoofing is not detectable with IMU and GNSS alone

- Status: proposed
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

To be written by the maintainer.

## Consequences

Whatever is chosen, the claim stays limited to simulated GNSS, one direction and two datasets.
