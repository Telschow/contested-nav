# ADR-0017: A stochastic clone for the visual update

- Status: accepted
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

Option 2, as an opt-in. The stochastic clone stays behind `vision_model: clone`. The default stays `anchor`,
`vision_enabled` stays `False`, and visual fusion still ships off.

The clone meets the gate on the synthetic fixture and holds over a long run, but it does so for a front end whose
errors are independent. When the errors are correlated over a second or more it is overconfident again, and it is
calibrated only with a noise inflation found by trial. A real front end's error correlation is not known from any
data in this repository, so there is nothing to base a change of the shipped setting on. The single-anchor rows stay
as the control.

Blocker B1 stays open for the shipped configuration. It can be reconsidered when a front end's error correlation is
measured on real data, or when a visual front end exists in this project; the options not taken (a sliding window,
first-estimate Jacobians) wait for the same evidence. A claim in the README or the docs that visual fusion is
calibrated must name the independence assumption beside it.

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

## Follow-up: stress tests

The first result used a surrogate front end that is independent, Gaussian and unbiased, which the audit's own
caveat warned about. The surrogate now has opt-in departures (`vision.noise_corr_s`, `outlier_fraction`,
`scale_sigma`), all off by default and drawn from a stream of their own, so no existing number moved. What
they showed, with the rows in [Results](../results.md) and `tests/test_clone_long_run.py`:

- **Observability held over a long run.** With no GNSS for five times the benchmark's length, the claimed
  uncertainty kept growing and the error stayed inside it in every 30 s block. If the filter had been gaining
  spurious information about global position, the claimed uncertainty would have flattened while the error grew.
  After a long denial, GNSS was accepted on return with no rejection and no fault declared, and the error
  collapsed. In a 300 s run (not committed, as it takes minutes) the claimed uncertainty was conservative late
  in the run, not overconfident.
- **Gross outliers are survivable.** A twentieth of the frames carrying a twenty-fold error are rejected by the
  chi-square gate and the filter stays calibrated.
- **Scale drift is benign here.** The inertial unit holds the metric scale. On a faster platform, where the
  per-frame baseline is large against the noise, this could differ.
- **Correlated errors are not survivable as configured.** When the visual errors are correlated over a second or
  more, as they are when consecutive frames share features, the clone assumes independence and is overconfident
  again. The shortfall grows with the correlation time. Telling the filter the visual noise is four times larger
  restores calibration, with the position error still well inside the no-vision control's. That factor was
  found by trying a few; it is not derived, and a front end with a different correlation needs a different one.

So the clone closes B1 for a front end whose errors are independent, and for a correlated one only with a noise
inflation chosen to fit. That is a narrower claim than the first result suggested, and it is the claim to make.

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
