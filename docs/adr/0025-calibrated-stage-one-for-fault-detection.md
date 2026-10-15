# ADR-0025: A calibrated stage 1 for fault detection

- Status: proposed
- Date: 2026-10
- Related: [ADR-0021](0021-fault-classification-from-innovations.md), [ADR-0022](0022-multipath-signature.md), [fault classification](../fault_classification.md)

## Context

The confirmation run behind ADR-0021 found the any-fault stage of the classifier raising an alarm on about a third of
unseen control runs. That stage called a fault when any of ten features exceeded its largest value on the training
controls. A maximum over a few dozen samples is a poor tail estimate, and ten features give ten chances. Track A's exit test
needs a measured false-alarm rate of zero on the control.

## Options

1. **Keep the control maximum.** Known false-alarm rate on unseen controls: the first row of the table on the page.
2. **A fitted bound per feature at a stated level.** A one-sided normal bound (log scale for positive features), with
   0.5% per feature as a Bonferroni split of 5%. Fixed before the unseen controls were scored.
3. **More training controls, then a new confirmation.** Not possible in this session: the recordings and the
   hosts that serve them were out of reach, so no new run could be made.

## Decision

To be written by the maintainer.

## Evidence

On the 68 unseen controls the fitted bound raised fewer false alarms than the control maximum and did not reach zero.
Two of the ten features, `drift_m_s` and `axis_conc`, account for all the remaining alarms, because the training
controls (two seeds) were spread more tightly than the unseen ones. Detection of spoofing and degradation fell a little.
The multipath call is unchanged. The figures are in the table on the page, generated from the committed CSVs, and are
not repeated here.

## Consequences

The Track A exit test is not met under either rule, and a "zero false alarms" claim can only be a bound on the rate: with
none in a set of controls the rate is shown only to be below an upper limit, which the page tabulates. Option 3 is the way forward and needs fetched recordings, more
control seeds, and a confirmation on runs the new thresholds never saw. The shipped configuration is unchanged and no
detector is added to the filter.
