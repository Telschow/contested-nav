# ADR-0045: A dead-reckoning horizon

- Status: accepted
- Date: 2026-11
- Related: [ADR-0035](0035-the-integrity-status-record.md), [ADR-0040](0040-staleness-of-the-nis-windows.md), [ADR-0044](0044-a-protection-level-from-the-calibrated-covariance.md), [issue #166](https://github.com/Telschow/contested-nav/issues/166)

## Context

**The question.** When GNSS is out, how long can the vehicle keep going before the claimed position bound exceeds an alert limit? The answer comes from propagating the claimed covariance forward with no updates. It is worth something only if that covariance is calibrated.

**What exists today. FACT, checked in the code.** The filter propagates `P` with its state-transition and process-noise models. An accelerometer-only dead-reckoning run over 60 s exists as a sanity row on the UrbanNav page. The integrity record has no horizon field. The issue was paused after the nav-trust-c2 project chose to derive its monitor inputs from PX4's figures, so no integrity record crosses between the projects and the field has no consumer today. This repository's own use remains.

**Why it needs a decision.**

- The alert limit is a threshold, and it differs per mission type. Nothing in the repository supports a value, and the issue proposes configuration instead of a hard-coded one.
- The requirement is conservative: the predicted horizon should not be later than the observed exceedance. That needs a target fraction.
- The covariance is not calibrated through long outages in every case. On Deep-Urban-1 the imposed middle and long outages end with an error above the claimed bound (one sequence, one receiver, reference error unknown). A horizon derived from that covariance would be late in those cases.
- A field in the integrity record is a schema change (ADR-0035), as for ADR-0040 and ADR-0044.

## Options

(a) Do not build it. Cost: none. The question is answered by reading `sigma_h` over time.

(b) Covariance propagation only. Propagate `P` forward with the filter's own model and report the first time the horizontal 2-sigma bound crosses the limit. Exact for the linear model, closed-form for a constant accelerometer bias, so it is testable against a known answer. Inherits the covariance's errors.

(c) Option (b) with a declared margin factor on the claimed bound, chosen on development seeds so the fraction of not-late predictions meets the target. The margin is a threshold and needs its own evidence.

(d) A sampled horizon. Propagate perturbed states and report a quantile. More machinery, and it needs a stated sample count and seed.

For each of (b) to (d), the placement is a second choice: a study output only, or a field in the integrity record as schema version 2.

## Decision

Adopt option (a), decided by the maintainer on 2026-11-07. The horizon is not built. The question is answered by reading `sigma_h` over time. Options (b), (c) and (d) are not adopted. Revisit if a consumer appears and the covariance is shown to be calibrated through long outages.

## Consequences

- No code, no record field and no schema change.
- [Issue #166](https://github.com/Telschow/contested-nav/issues/166) stays open as deferred, not as work to do.
- The reason is recorded: no consumer exists, and on the long imposed outage on Deep-Urban-1 the error ends above the claimed bound, so a horizon taken from that covariance would be late (one sequence, one receiver, reference error unknown).
