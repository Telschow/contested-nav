# ADR-0017: A stochastic clone for the visual update

- Status: proposed
- Date: 2026-10
- Related: [ADR-0001](0001-anchor-as-filter-state.md), [ADR-0003](0003-ship-visual-disabled.md), blocker B1

## Context

With GNSS denied and visual aiding on, the filter is accurate and confidently wrong (blocker B1). The audit
traced it to one place: at each visual update the previous pose is a raw copy of the filter state, treated as
error-free to first order, and its covariance with the live state is set to zero at every commit. The
information a relative measurement carries about absolute position is then the Schur complement
`P_pp - P_pc P_cc^-1 P_cp`, which with `P_pc = 0` collapses to `P_pp`: each relative measurement acts as if it
carried absolute information, and the position covariance shrinks by the full nominal amount every frame.
The roadmap named a pose graph or a multi-anchor filter. The audit suggested that stochastic cloning is the
cheaper first step with the same key property, and said to treat that as a hypothesis, with a gate fixed in
advance: mean NEES below 10 and 2-sigma coverage above 90% with GNSS denied, and a go/no-go that either
outcome would be evidence.

## Options

1. **Leave the anchor model.** The limitation stays documented and measured. Visual fusion ships off.
2. **A stochastic clone of the previous pose.** Six error states that start perfectly correlated with the live
   pose, propagate with it, and enter the relative-pose measurement through their own Jacobians. After an
   update the live pose and the clone are corrected together, and the clone is replaced by a copy of the
   updated pose. No new dependency; the six states reuse the slots of the anchor.
3. **A sliding window or a pose graph.** The full remedy, and a larger piece of engineering. Not needed
   if option 2 meets the gate.
4. **Observability-constrained or first-estimate Jacobians.** The remedy for the spurious information that a
   relative-only linearisation can gain about global position and yaw. More scope, and only worth it if option
   2 leaves a residual.

## Decision

_To be written by the maintainer._

## What the code does in the meantime

It implements option 2 behind `EskfConfig.vision_model = "clone"`. The default is `"anchor"`, so nothing that
shipped moves, `vision_enabled` stays `False`, and the single-anchor cases stay in the benchmark as the
control rows. The clone cases are `outage_visual_clone`, `outage_visual_degraded_camera_clone` and
`vision_only_clone`; `outage_visual_degraded_camera_rereferenced` is the single-anchor control for the
degraded-camera pair (see below).

What the spike found, in words; the figures are in [Results](../results.md) and the sweeps named there.

- **The gate is met on the synthetic fixture.** On `outage_visual` the clone is calibrated where the anchor is
  overconfident by two orders of magnitude, and its position error is below the no-vision control's. The 10-seed
  sweep, the 8-trajectory sweep and the 8-window outage sweep all agree, including the early-start windows where
  the anchor model's vision was worse than the control. `vision_only` is honest: the claimed uncertainty grows
  with the error instead of staying small.
- **The degraded-camera case needed a fix to the generator, not to the filter.** When frames are dropped, the
  generator still measures each delivered frame against the immediately preceding grid frame, which may be the
  dropped one. A filter that compares with its last received frame is then handed a measurement of a different
  transform. The exact clone cannot absorb that, and the single anchor's loose declared uncertainty hid it. With
  `vision.rereference: true` each delivered measurement is taken against the last delivered frame, with a fresh
  draw of the same per-measurement noise. The clone is then calibrated on that case, and the single anchor stays
  overconfident, so the generator was not what made the anchor fail.
- **The Jacobians are verified** against numerical derivatives of the filter's own residual, and the structural
  properties are tested: a new clone is perfectly correlated with the live pose, a measurement taken straight
  after the commit carries no information, and the covariance stays symmetric and positive semidefinite.

## What this does not settle

- **It is synthetic.** The visual front end is a surrogate: relative poses with independent Gaussian noise. A real
  front end has correlated errors, scale ambiguity and outliers. Nothing here is field performance.
- **Whether to ship it.** Meeting the numeric gate is not the roadmap's exit test, which also has
  `vision_enabled = True` as the shipped default. That change touches ADR-0003 and constraint S3 and is yours.
- **Observability.** A relative-only update can still gain spurious information about global position and yaw
  through linearisation. Over the horizons here the covariance did not collapse, but a long vision-only run is
  the place to look, and the first-estimate Jacobian remedy (option 4) has not been tried.
- **The FDIR layer** was not reworked for the clone. Its frozen-anchor cross-check reads the clone's pose as
  it would the anchor's, and is unreachable in both models (ADR-0008).
- **The re-reference setting is not the default.** Existing degraded-camera numbers keep the generator as it
  was. Whether it should become the default is a separate question.
