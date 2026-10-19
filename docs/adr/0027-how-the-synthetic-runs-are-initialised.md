# ADR-0027: How the synthetic runs are initialised

- Status: accepted
- Date: 2026-10
- Related: [ADR-0003](0003-ship-visual-disabled.md), [ADR-0012](0012-every-scenario-is-injected.md), [issue #137](https://github.com/Telschow/contested-nav/issues/137), and the T2-4 change to the dead-reckoning control

## Context

In the synthetic benchmark the truth starts at rest at the configured start position, with the identity attitude. The ESKF cases start at the origin. So every run carries the same fixed position offset at the start, a little larger than the declared position prior, and the prior does not describe it. The offset is the same in every run, so it is not a draw from anything.

Two scratch runs on synthetic data measured what this does. They are not committed, they are labelled MEASUREMENT, and the numbers stay in [the issue comment](https://github.com/Telschow/contested-nav/issues/137#issuecomment-6273627339) because an ADR records the reasons.

The first run compared the ESKF started at the origin with the same ESKF started exactly at the truth, one seed, five cases. The offset adds to the error of several cases and to the mean NEES of most of them. Starting exactly at the truth made the stochastic clone look underconfident on the vision-only case, because a filter with a one metre prior is then given a start error of zero.

The second run drew the start error from the declared prior, one part at a time (position, velocity, attitude), over five seeds. It showed two things. The anchor model does not recover from a start attitude error that lies inside its own declared prior, while the clone does, and the fixed start hides that. And where absolute position is unobservable (the vision-only clone), one whole run is close to a single chi-square sample, so the mean NEES of one run says little. Judging consistency there needs an ensemble over seeds, with the seed driving the start draw.

One seed for the first table and five for the second. Both are on synthetic data and say nothing about field performance.

## Options

1. **Start at the truth.** Removes the fixed offset. But a filter that declares a one metre position prior is then started with no error at all, so it looks underconfident, and the consistency test fails in the other direction.
2. **Start at the truth plus a draw from the declared prior.** This is what a consistency test assumes: the start error is a sample from the distribution the filter says it has. It needs an ensemble over seeds, because one draw is one sample. It also exposes that the anchor model does not recover from a start attitude error inside its prior.
3. **Keep the fixed start and document it.** Keeps every number as it is. But every NEES keeps an error that the prior does not describe, in the same direction, in every run.

## Decision

Option 2. Every ESKF case in the synthetic benchmark starts at the true initial state plus an error drawn from the filter's own declared prior: position, velocity and attitude, each axis independent and zero mean, with the attitude error applied in the filter's own error convention. The draw comes from its own random stream, seeded by the case seed and separate from the sensor-noise streams, so changing it does not change any sensor sample. The declared priors stay as they are, including the attitude prior; they are not changed after seeing these results. The dead-reckoning control keeps starting at the true state. Bias estimates start at zero as before, because the true biases are already drawn by the noise layer. Because a single run where absolute position is unobservable is close to one sample, headline consistency numbers move to ensembles over seeds, decided separately with the ensemble statistics; until then a single run is descriptive. The control rows stay.

## Consequences

- Every benchmark number, the golden file and the generated tables change once, in one package, when the rule is implemented. Nothing is regenerated before this record is merged, so the rule is fixed before the results are seen.
- The B1 conclusion is expected to hold. For the anchor model it is expected to become stronger, because a start attitude error inside the declared prior is part of what the anchor model fails on. That is an expectation from the scratch runs, not a result.
- The declared priors are not retuned after the regeneration. If a case then looks miscalibrated, that is a finding about the filter and not a reason to move the prior.
- The work order is: first the implementation of this rule, then the ensemble statistics on the new initialisation, then the thresholds of the B1 gate.
- Until the ensemble statistics are decided, a single run is descriptive, and no page may call one run calibrated or not on the strength of its mean NEES alone.
