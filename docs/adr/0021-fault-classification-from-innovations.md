# ADR-0021: Fault classification from the GNSS innovations

- Status: proposed
- Date: 2026-10
- Related: [ADR-0005](0005-chi-square-fdir-gating.md), [ADR-0019](0019-slow-ramp-spoofing.md), [fault classification](../fault_classification.md)

## Context

The FDIR layer declares a channel faulty but does not say why (limitation L7). A feasibility study on real recorded
IMU data injected multipath, spoofing and sensor degradation and read five features from the GNSS innovations.
Multipath is called correctly in 97% of runs. Spoofing is called correctly in fewer than half. About one in seven
held-out control runs is called a fault. The Track A exit test is not met.

## Options

1. **Ship no classifier.** State what the innovations can and cannot separate, and restate the exit test to match.
2. **Ship a multipath detector only.** It is separable at every size tested. The label for the other two stays
   "faulty, cause unknown".
3. **Look for more features.** The structure of the innovation over time, a longer bias window, or a second sensor.
   More work, and the slow-ramp results suggest the limit is the sensor set.

## Decision

To be written by the maintainer.

## Consequences

Whatever is chosen, the claim stays limited to injected faults, simulated GNSS and two datasets.
