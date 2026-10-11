# ADR-0021: Fault classification from the GNSS innovations

- Status: accepted
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

Option 2. A multipath detector is the only classifier worth shipping from this evidence: multipath is separable at
every size tested, in 99% of runs. The label for every other detected fault stays "faulty, cause unknown". The
ten-feature classifier that names spoofing and degradation is a study result, not a detector. It calls spoofing in
about three quarters of runs, has a control false-alarm rate near one in six, and its second round of features was
chosen after seeing the first round fail on the same data.

No detector is added to the filter by this decision. Building one needs its own work package, the multipath
signature held to a false-alarm rate measured on runs the thresholds never saw (the confirmation run on the page),
and its own ADR. Track A's exit test is restated, not met: detection per type at zero false alarms holds for none of
the three causes. Option 3, more features, was done once, cheaply, and a second sensor remains the next candidate.

## Consequences

A confirmation run on unseen fault sizes and seeds supports the decision. Multipath was called in 100% of 68 runs
and in none of the other 476. The false-alarm rate of the any-fault stage rose from 18% to 35% on 68 unseen controls,
so the stage 1 thresholds are not usable as they are. The claim stays limited to injected faults, simulated GNSS and
two datasets.
