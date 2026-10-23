# ADR-0032: The adaptive visual scale takes every visual update

- Status: accepted
- Date: 2026-10
- Related: [ADR-0006](0006-nis-window-monitor.md), [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [ADR-0031](0031-an-adaptive-visual-noise-scale.md), [PR #158](https://github.com/Telschow/contested-nav/pull/158), [issue #44](https://github.com/Telschow/contested-nav/issues/44), [issue #113](https://github.com/Telschow/contested-nav/issues/113)

## Context

[ADR-0031](0031-an-adaptive-visual-noise-scale.md) specifies the adaptive visual noise scale and lets only the updates that the chi-square gate accepted enter the exponentially weighted mean. The filter-level tests of [PR #158](https://github.com/Telschow/contested-nav/pull/158) measured what that rule does. The evidence is MEASUREMENT: scratch runs on the development seeds 0 to 4, one scenario, and the tests that pin it are in `tests/test_visual_scale.py`.

- From an injected visual sigma of about two and a half times the assumed one, the rotation gate starts rejecting updates. A rejected update never reaches the mean, so the rotation scale stays near one. The translation block, whose updates are not rejected, keeps adapting. A test pins this censoring.
- The existing preset `measured-front-end` multiplies the visual sigma by four, which is a factor of sixteen in variance, and the scale multiplies the covariance. Of the two values of `s_max` on the grid of ADR-0031, 8 cannot reach a factor of sixteen and only 16 can.

No tuning run and no candidate gate run had been made on any seed when this amendment was decided. The evidence is the five-seed filter-level tests of PR #158.

The precedent is [ADR-0006](0006-nis-window-monitor.md): the same filter has already shown that a gate which rejects is not evidence about the sensor when the covariance is what is wrong. Here the gate rejects because the scale has not grown, and the scale does not grow because the gate rejects.

## Options

**(a) Keep ADR-0031 and let the tuning run show the failure.** Rejected. The failure is already visible in the filter-level tests. If it first appeared in the tuning table, a later change would look like a repair made after seeing the result.

**(b) Take `d` from every visual update, capped at `s_max`. (Chosen.)** The scale can grow towards a noise that the gate rejects, the gate widens with it, and the rejections stop. The cost is that a visual fault also moves the scale. It is bounded, reported and tested against the fault matrix.

**(c) A separate, wider gate used only for the adaptation.** Rejected. A second gate is a second set of constants, and the constants would need their own justification.

**(d) Drop the cap.** Rejected. One outlier could move the scale a long way in one step.

## Decision

The adaptive visual noise scale of ADR-0031 changes in one rule. Its statistic d is taken from every visual update the filter receives, whether the chi-square gate accepts the update or not, and each d is capped at s_max before it enters the exponentially weighted mean. The sentence of ADR-0031 that lets only accepted updates enter the mean no longer applies. Everything else in ADR-0031 stays: the base covariances, the formula for d, the start at 1, the forgetting time tau, the bounds s_min and s_max, the hold while no update arrives, the grid of twelve points, the confirmation blocks and the single held-out evaluation. The gate keeps using the scaled covariance.

The reason is that with accepted updates only, a visual channel whose errors are larger than the gate admits produces rejections that never reach the mean, so the scale cannot grow towards the noise that causes them (measured in the filter-level tests of PR #158). With every update counted, the scale grows, the gate widens with it, and the rejections stop.

The cost is that a visual fault now also moves the scale, towards s_max at the rate the forgetting time allows, and widens the gate for the visual updates that follow. The scale is bounded and reported as in ADR-0031. The fault matrix re-run that ADR-0031 requires measures what this costs in detection, and the result goes into the record of the candidate. No candidate gate run on any seed had been made when this was decided; the evidence for it is the filter-level tests on seeds 0 to 4 in PR #158.

## Consequences

- A small code package changes the update rule. Tests come first:
  - rejected updates now move the scale;
  - a `d` above `s_max` enters as `s_max`;
  - the censoring test of PR #158 is replaced by a test that the scale follows a noise the old rule could not follow;
  - the byte-identity of the output with the setting off is checked again.
- The grid, the gate and the held-out rule are unchanged.
- `CONSTRAINTS.md` B1 stays as it is until a candidate has been evaluated.
