# ADR-0003: Ship with visual fusion disabled

- Status: accepted
- Date: 2026-09

## Context

The 21-state anchor model (ADR-0001) is close to calibrated when GNSS is
available: mean NEES 3.7 against 3 nominal, 2-sigma coverage 100%.

It is not well calibrated when GNSS is denied. From the generated benchmark,
15 s outage (`python scripts/run_benchmark.py`):

| Scenario | ATE RMSE | Claimed 1σ | Mean NEES | 2σ coverage |
|---|---:|---:|---:|---:|
| GNSS denied 5–20 s, vision off (control) | 3.782 m | 0.567 m | 4.1 | 100.0% |
| GNSS denied 5–20 s, vision on | 3.428 m | 0.154 m | 1051.3 | 16.0% |

Enabling the visual channel during a GNSS outage barely improves the trajectory
and makes the estimator dramatically overconfident: the claimed 1-sigma is
roughly a quarter of the control's, and the mean NEES is 1051 against a nominal
3, with one epoch in six inside the claimed 2-sigma ellipsoid. Note that the
ATE improves slightly, which is exactly the trap -- a marginally better path
with a covariance that is wrong by two orders of magnitude is worse for any
downstream consumer that trusts the covariance.

## Why this is structural

The visual anchor `c_t` is a constant offset in the body frame. In reality the
required offset drifts as inertial error grows, and a single constant model
cannot represent drift it does not have a parameter for. The filter therefore
maintains a constraint whose error it cannot track, and the induced
cross-covariance with the navigation block is wrong in a way no scalar
tuning corrects.

Three responses were considered:

1. **Constrain the anchor to the estimated position** (assume perfect
   correlation). Tested. Produces a degenerate, non-positive-semidefinite
   covariance. Rejected.
2. **Add process noise to the anchor**
   (`anchor_pos_drift_sigma_m_s`). Implemented and configurable, but it blurs
   the symptom rather than fixing the correlation structure. Defaulted to
   `0.0` because a knob that does not fix the problem should not look like it
   does.
3. **Pose graph over visual keyframes.** The actual fix. Deferred to
   ROADMAP stage 3.

## Decision

`vision_enabled` defaults to `False`.

Shipping a filter that is confidently wrong is worse than shipping no visual
fusion, because a downstream consumer has no way to detect the failure. The
limitation is documented in the README and pinned by
`test_gnss_denial_still_over_trusts_vision_and_that_is_pinned`, so it cannot
be quietly forgotten or accidentally "fixed" by a test tweak.

## Consequences

- The default configuration is honest: it is well calibrated, and its stated
  uncertainty can be trusted.
- Visual fusion is opt-in and clearly labelled as unvalidated during GNSS
  denial.
- A regression test now asserts the *bad* behaviour. That test is expected to
  fail when the pose graph lands, at which point ADR-0003 is superseded.
