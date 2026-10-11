# ADR-0023: The clone against a measured front end

- Status: accepted
- Date: 2026-10
- Related: [ADR-0017](0017-stochastic-clone-for-the-visual-update.md), [ADR-0020](0020-second-source-against-a-ramp.md), [real front end](../real_front_end.md)

## Context

ADR-0017 left the clone opt-in because it is calibrated for independent visual errors, and no data said which a real
front end has. A plain NumPy two-view front end was run on 30 s of real EuRoC frames and its errors were measured. They
are small and correlated over a fraction of a second. A Gaussian surrogate with that size and correlation time keeps
the clone inside its gate. Replaying the measured errors themselves does not: NEES 27 and 55% coverage. Assuming four
times the measured noise brings the clone back inside, with NEES 4.3 and 91% coverage.

## Options

1. **Leave the clone opt-in and record the finding.** `vision_enabled` stays False. The opt-in clone is used with the
   assumed visual noise inflated by four.
2. **Make the clone the default with the inflation.** One sequence and one error series do not support that.
3. **Measure more first.** More sequences, other windows, and a keyframe-based front end.

## Decision

Options 1 and 3. `vision_enabled` stays False and the clone stays opt-in. For a feature-tracking front end like the
one measured, the opt-in clone should assume four times the measured visual noise. B1 stays open for the shipped
configuration. The next step is more sequences and windows, so that the replay result has a spread.

## Consequences

The finding is limited to this front end, this window and a known translation scale. The factor of four is a trial
value that held in one replay, not a derived constant. A front end with another error structure may need another
factor.
