# Concepts

Why the headline result is not a tuning problem, what the filter is, and how calibration is measured.

## Why it is not a tuning problem

The filter runs, converges, and produces a bounded, well-behaved, wrong answer. No
crash, no NaN, no divergence. So the response was measurement and a shipping
decision, not a tuning pass:

- **It is a design property, not a bad seed.** Over **10 noise realisations** of
  the same trajectory, `outage_visual` is overconfident at **every** seed: mean
  NEES **844**, range **211.7 to 2103.4**, coverage **6.8% to 34.8%**. Over **8
  scenes** with trajectory geometry varied — path length **17.3 m to 80.6 m**, a
  **4.65×** range — **all seven case verdicts are identical in all eight scenes**,
  and `outage_visual` holds mean NEES **419.7 [414.4, 424.9]** at 20.0% coverage.
- **Sweeps cannot disagree with themselves.** Intervals are deterministic
  percentile bootstrap, 10 000 resamples, fixed RNG seed. CI runs the benchmark
  and the sweeps twice and fails if any two runs differ.
- **The fix is partly shipped, and is still not enough.** Adaptive covariance
  inflation ([ADR-0006](adr/0006-nis-window-monitor.md)) took this case from
  ATE **5.059 m to 2.541 m** and rejections **51 to 5** — and in doing so made
  the filter *more* accurate and therefore *harder* to catch by ranking on error.
- **So the mitigation is to refuse the feature.** Visual fusion ships
  `vision_enabled=False`, and the residual NEES gap is an open blocker recorded in
  [CONSTRAINTS.md](https://github.com/Telschow/contested-nav/blob/main/CONSTRAINTS.md), not a caveat in a footnote.
  [Why it cannot be fixed by more filtering](#the-one-thing-this-cannot-do).

The underlying cause is that the visual anchor is a pose the filter itself
produced, so its error is not independent evidence. The 21-state filter carries
the anchor error as two 3-D nuisance parameters (`c_p`, `c_t`) rather than
assuming it away — which fixes the *bulk* miscalibration and not the *tail*, and
the table above is the tail. Full mechanism in
[Reading the calibration numbers](calibration.md).

## The one thing this cannot do

**Visual fusion under GNSS denial is not trustworthy yet.** This is the central
open result.

With GNSS available the 21-state anchor model is well behaved. With GNSS denied
and vision enabled, the filter is badly overconfident. The cause is structural.

A visual front end supplies a *relative* transform between consecutive frames.
The absolute pose has to come from somewhere, so the filter declares an anchor
pose at the start of the run and carries its error as two estimated states
(`c_p`, `c_t`). That is the correct model, and while GNSS keeps the anchor
honest it works. When GNSS disappears, the only thing constraining the anchor is
the anchor itself, and the covariance stops describing reality.

The alternatives do not rescue it:

- **Anchor as measurement noise** — the obvious shortcut, and demonstrably
  worse. It looks identical in the source and drops coverage to 16%.
- **A single anchor for the whole run** — mean NEES 23 instead of 3. It makes
  the anchor error one unknown shared by every measurement.
- **A larger gate or a bigger anchor prior** — inflates the uncertainty to
  acknowledge the error instead of fixing it.

The anchor model is the wrong tool, and this is a known failure mode rather than
a discovery. A visual front end supplies only *relative* transforms, so the
absolute pose has to come from a single arbitrary reference; when that reference
is only weakly constrained, an error-state filter gains spurious information
along the unobservable directions and becomes overconfident. This has been
characterised in the vision-aided inertial navigation literature for over a
decade — Hesch et al. (IEEE T-RO, 2014) traced it to a mismatch between the
observability of the linearised estimator and that of the true system, and the
remedies are established: observability-constrained EKF, first-estimate
Jacobians, invariant and Schmidt filters, and pose-graph formulations. See
[docs/defense/DEFENSE_RELEVANCE.md](defense/DEFENSE_RELEVANCE.md) for the
citations.

**This repository implements none of those remedies.** What it contributes is a
reproducible harness that measures the failure in its own anchor formulation and
refuses to ship the configuration. Until one of the known fixes is implemented,
`vision_enabled` defaults to `False`: a caller who did not ask for a
confidently-wrong filter should not receive one.

The reasoning is recorded in
[ADR 0001](adr/0001-anchor-as-filter-state.md) and
[ADR 0003](adr/0003-ship-visual-disabled.md).

## What is in the filter

Twenty-one states in error-state form: attitude error, velocity error, position
error, gyro and accel bias error, plus six anchor-error states. Covariance is
propagated in 21×21 form and updated with the Joseph formulation, which preserves
covariance symmetry and positive-semidefinite structure under finite precision
rather than drifting until something breaks.

The measurement Jacobians are where the original defect lived, and the frame
matters as much as the sign. For a relative visual transform with
`T_prev_cur = T_prev⁻¹ T_cur`, writing `R_rel_pred = R_prevᵀ R_cur`:

| Block | Jacobian |
| --- | --- |
| attitude error | `H_theta = R_rel_pred` |
| anchor attitude | `H_ct = −R_rel_pred` |
| position | `H_p = R_prevᵀ` |
| anchor position | `H_cp = −R_prevᵀ` |

`H_ct = −R_rel_pred` rather than `+R_rel_pred` is what makes modelling the anchor
as filter state correct rather than merely different.

The rotation blocks are `R_rel_pred`, not the identity, because
`rot_log(Q · Exp(v) · Qᵀ) = Q · v`: the conjugation identity rotates the
increment into the previous body frame, which is the frame the residual lives
in. Writing `H_theta = +I` is a frame error that happens to be invisible
whenever the inter-frame rotation is small — at 20 Hz against a smooth
trajectory it changes the benchmark in the third decimal. All four blocks are
pinned against central differences of the filter's own residual in
`tests/test_estimators.py`, which is how this was found; a sign or frame error
here runs, fuses, and is wrong without ever raising.

## Calibration

`navkit.eval.calibration` implements the diagnostics from their published
definitions, with no SciPy:

- **NEES** — normalised error squared, from the filter's own covariance.
  Singularity is handled by symmetric regularisation, never by dropping an
  epoch; silently discarding the worst epochs is precisely how a miscalibrated
  filter comes to look well behaved.
- **Coverage** — the exact ellipsoid coverage for the stated degrees of
  freedom. The familiar "3σ means 99.7%" is the one-dimensional figure and does
  not hold for a 3-D position error; the real expectation at 2σ per axis in 3-D
  is 99.3%, and the code uses that.
- **Conformal radius** — a finite-sample, distribution-free bound, used to check
  whether a confidence claim still holds under shift.
- **Inflation factor** — the scalar covariance inflation that reaches a target
  coverage, reported as `inf` when the target is unreachable. Clipping it to a
  large finite number would disguise an unbounded calibration error as a merely
  large correction.

See [docs/calibration.md](calibration.md) for how to read these, and
[docs/architecture.md](architecture.md) for the state and update sequence.
