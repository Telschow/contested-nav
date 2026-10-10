# ADR-0021: Fault classification from the GNSS innovations

- Status: proposed
- Date: 2026-10
- Related: [ADR-0005](0005-chi-square-fdir-gating.md), [ADR-0019](0019-slow-ramp-spoofing.md), [fault classification](../fault_classification.md)

## Context

The FDIR layer declares a channel faulty but does not say why (limitation L7). A feasibility study on real recorded
IMU data injected multipath, spoofing and sensor degradation and read five features from the GNSS innovations.
With the original five features multipath was called correctly in 97% of runs and spoofing in 38%, and a 10 m step
was called multipath. Five more features, chosen after that result (so the second round is not an independent
test), raised spoofing to 74% and multipath to 99%, and left the held-out control false-alarm rate at about one in
six. Weak faults are still missed. The Track A exit test is not met.

## Options

1. **Ship no classifier.** State what the innovations can and cannot separate, and restate the exit test to match.
2. **Ship a multipath detector only.** It is separable at every size tested. The label for the other two stays
   "faulty, cause unknown".
3. **Look for more features.** Done once, cheaply: innovation shape over time helped, and fault sizes below the noise
   did not. A second sensor (the simulated visual source) is the next candidate. More work, and the slow-ramp results
   suggest the limit is the sensor set.

## Decision

To be written by the maintainer.

## Consequences

Whatever is chosen, the claim stays limited to injected faults, simulated GNSS and two datasets.
