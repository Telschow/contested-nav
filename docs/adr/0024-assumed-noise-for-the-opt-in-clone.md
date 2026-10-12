# ADR-0024: The assumed visual noise of the opt-in clone

- Status: accepted
- Date: 2026-10
- Related: [ADR-0017](0017-stochastic-clone-for-the-visual-update.md), [ADR-0023](0023-clone-against-a-measured-front-end.md), [real front end](../real_front_end.md)

## Context

ADR-0023 kept the stochastic clone opt-in and asked for more windows and sequences before anything changed. The wider
measurement ran: six windows of five Machine Hall sequences, a plain two-view front end, the measured errors of each
window replayed into the filter. With the assumed visual noise at the measured size, the clone meets the gate (NEES below
10, 2-sigma coverage above 90%) in two of six windows. At twice the measured size, in two of six. At four times, in all
six. At eight times, in all six. The single anchor meets it in none. The tightest window at four times has a coverage of
91%.

All of it is one dataset, one front end that is not a production one, and a translation with the true scale.

## Options

1. **Keep the clone opt-in and record four times as the supported assumption.** `vision_enabled` stays False. The docs
   say that an opt-in user of a feature-tracking front end should assume four times the measured visual noise, and that
   this holds on the windows measured so far.
2. **Add the factor to the configuration as a named setting.** A documented preset so that the opt-in path does not
   depend on a number found in a page. Code and docs change; the default does not.
3. **Make the clone the default with four times the noise.** It needs a monocular scale, a second dataset and a front end
   that is not mine first.

## Decision

Options 1 and 2.

The clone stays opt-in and `vision_enabled` stays False. For a feature-tracking two-view front end like the one
measured, the supported assumption for the opt-in clone is four times the measured visual noise. The docs say so, with
the evidence and its limits.

The assumption is a named setting, so that the opt-in path does not depend on a number found in a page:
`navkit.estimators.eskf.VISION_NOISE_PRESETS["measured-front-end"]`, four times. In a scenario file it is
`estimator.vision_noise_preset: measured-front-end`, valid only with `vision_model: clone`, and it excludes
`vision_sigma_scale`. For recorded data it is `RunOptions.vision_noise_preset`, which excludes `vision_noise_scale`. A
test ties the constant to the four-times run of the wider measurement, so the two cannot drift apart. No shipped case
or default uses it.

Option 3 is not taken. It needs a monocular scale, a second dataset and a front end that is not mine first.

## Consequences

Whatever is chosen, the claim stays limited to the Machine Hall windows measured, this front end and a known scale. The
factor of four is an empirical value, not a derived constant.
