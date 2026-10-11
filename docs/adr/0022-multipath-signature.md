# ADR-0022: A multipath signature on the GNSS innovations

- Status: accepted
- Date: 2026-10
- Related: [ADR-0021](0021-fault-classification-from-innovations.md), [ADR-0005](0005-chi-square-fdir-gating.md), [multipath](../multipath.md)

## Context

ADR-0021 chose to ship at most a multipath detector. A rule of two numbers on a window of GNSS innovations (NIS and
lag-1 autocorrelation) was tested in two versions, with the shipping criteria written before the fresh runs.

## Options

1. **The sensitive rule** (NIS at least 2). It sees multipath from 1 m and calls small steps multipath too.
2. **The specific rule** (NIS at least 6). It sees multipath from about 3 m and called nothing else on the fresh runs.
3. **Wire a detector into the filter.** The filter would report multipath as a cause on the FDIR event.

## Decision

Option 2, as a function and not as filter behaviour. `navkit.fdir.multipath.signature` and `is_multipath` use the
specific rule by default. The sensitive rule stays available as an argument, so the trade-off can be seen. Nothing in
the estimator or the FDIR layer calls it, and no FDIR event changes. Wiring it in (option 3) is a separate step with
its own ADR, because it changes what a user of the filter is told.

The criteria were met on fresh runs by the specific rule only: 100% of the multipath runs of 3 m and above, and none
of the other runs. The floor is about 3 m.

## Consequences

The claim is limited to injected white noise on simulated GNSS, two datasets and 20 s windows. Real multipath is
correlated and may exceed the autocorrelation limit. A real-receiver check is not done. The Track A exit test is
still not met: the multipath call alone does not give 95% detection per type at zero false alarms for spoofing and
degradation.
