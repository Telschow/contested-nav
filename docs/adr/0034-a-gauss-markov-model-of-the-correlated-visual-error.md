# ADR-0034: A Gauss-Markov model of the correlated visual error

- Status: accepted
- Date: 2026-10
- Related: [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [ADR-0031](0031-an-adaptive-visual-noise-scale.md), [ADR-0032](0032-the-adaptive-visual-scale-takes-every-visual-update.md), [ADR-0033](0033-one-convention-for-the-synthetic-visual-translation-noise.md), [PR #161](https://github.com/Telschow/contested-nav/pull/161), [issue #44](https://github.com/Telschow/contested-nav/issues/44), [issue #113](https://github.com/Telschow/contested-nav/issues/113)

## Context

[ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md) fixed a gate in two scenarios. S1 has independent visual errors. S2 has visual errors correlated over time. The same configuration must pass both. The first candidate of that ADR, the adaptive visual noise scale ([ADR-0031](0031-an-adaptive-visual-noise-scale.md) and [ADR-0032](0032-the-adaptive-visual-scale-takes-every-visual-update.md)), failed on the development seeds in [PR #161](https://github.com/Telschow/contested-nav/pull/161). That run was made on the fixture before [ADR-0033](0033-one-convention-for-the-synthetic-visual-translation-noise.md).

**What is measured, on the corrected fixture.** MEASUREMENT, development seeds only, no seed from 100 up. The tables of the candidate gate on seeds 25 to 49 are in `docs/calibration.md` (the section on the candidate gate) and in [PR #163](https://github.com/Telschow/contested-nav/pull/163). The plain clone passes S1 and fails S2 by a wide margin. The third comment on [issue #44](https://github.com/Telschow/contested-nav/issues/44) records the measurements that led here. A scratch sweep of the plain clone over the correlation time of the visual error, on seeds 25 to 49 and not committed, gives the result in one sentence: the median per-run NEES grows from about 2 for independent errors to about 19 at 0.25 s and about 110 at 2 s.

**Why the adaptive scale could not see them.** HYPOTHESIS, from the third comment on issue #44. Correlated visual errors are absorbed into the state, so the innovations stay small while the position error grows, and an estimate made from the innovations cannot see them. A fixed inflation works because it encodes the correlation as prior knowledge. The scale in S2 rose only to a small value, and the upper bound had no effect. The failure is on the earlier fixture, and the re-run on the corrected fixture is not made.

**Correlated visual error is the measured case.** `docs/real_front_end.md` measures the errors of a real two-view front end: they are correlated for a fraction of a second, with a correlation time of 0.2 s for rotation and 0.25 s for translation at one frame. So a correlated visual error is what a front end produces, and not only a stress test.

**What the generator does, FACT checked before this ADR.** The correlated error of the simulator is a first-order autoregressive process per axis. In `src/navkit/sensors/models.py` the function `_stress` applies `_ar1` to the rotation and translation noise arrays with the coefficient `a = exp(-dt / noise_corr_s)`, where `dt` is the interval of the vision rate. The recursion is `out[k] = a out[k-1] + sqrt(1 - a^2) x[k]`, so the marginal standard deviation is kept. A direct check on a long synthetic run (scratch, 30 000 frames) gives, for correlation times 0.25, 0.5 and 2 s, a lag-1 correlation within 0.005 of `a` on every axis, a lag-2 correlation near `a` squared, and a standard deviation within 2% of the declared one.

**What a discrete Gauss-Markov state does, FACT checked before this ADR.** With correlation time `tau` and stationary standard deviation `sigma_e`, the discrete process has coefficient `exp(-dt / tau)` and process variance `sigma_e^2 (1 - exp(-2 dt / tau))`. At the vision rate this is the same coefficient and the same marginal variance as the generator's autoregressive process when `tau` equals `noise_corr_s`. When the state is propagated in several inertial steps between two vision updates, the coefficients multiply and the process variances accumulate to the same two values; a numerical check of five steps agrees to the printed digits. The generator's recursion runs over the frames of the grid, so after a dropped frame the correlation between two delivered frames is `a` squared, which is what the state gives by propagating over the longer interval.

The clone filter has 21 error states, and the clone update treats each block of the visual error as white with the declared standard deviation. Nothing in it represents a correlation of the measurement error.

## Options

(a) A fixed multiplier on the visual noise. Rejected. A multiplier large enough for S2 makes S1 conservative, and one small enough for S1 fails S2. No single value passes both.

(b) The adaptive scale of ADR-0031 and ADR-0032. It failed on the development seeds, and the likely reason is that the error it should see is not in the innovations.

(c) Thinning the visual updates, that is, using every k-th frame. Rejected. Consecutive relative poses share their errors, so composing them sums the correlation and does not remove it.

(d) A Gauss-Markov model of the correlated part of the visual error. Chosen. It puts the correlation into the filter as prior knowledge, the way a fixed inflation does, without a multiplier that is wrong in one of the two scenarios.

(e) Covariance intersection. A baseline only, tracked in [issue #116](https://github.com/Telschow/contested-nav/issues/116). It makes no assumption about the correlation and is conservative by construction.

## Decision

What it is. An optional Gauss-Markov model of the temporally correlated part of the visual measurement error in the stochastic-clone update. Six error states are added to the clone filter: e_rot (3) and e_trans (3), one per axis of the rotation and translation measurement. The measurement models become the existing ones plus the matching e term, so that z_rot has e_rot added and z_trans has e_trans added, and the white part n of each block remains. Each e is a first-order Gauss-Markov process with correlation time tau and stationary standard deviation sigma_e = sqrt(rho) times sigma, where sigma is the declared base sigma of the block (vision_rot_sigma_deg or vision_trans_sigma_m) and rho, between 0 and 1, is the declared share of the error variance that is correlated. The white part has variance (1 - rho) times sigma squared, so the total declared variance of each block stays sigma squared. The states are propagated with the inertial propagation (coefficient exp(-dt / tau), process variance sigma_e squared times 1 minus the coefficient squared), start at zero with variance sigma_e squared, and are not reset when the clone is re-committed. The model is opt-in through vision_gm_error (off by default), applies only to vision_model clone, is refused together with vision_noise_preset and with vision_adaptive_scale, and with it off every output is byte-identical to the previous behaviour.

What it is not. The states model a correlation that is declared in advance. They are not an estimate of the correlation from the data, and the documentation says so. The parameters tau and rho are properties of the visual front end, one pair for every scenario; the configuration is not told which scenario it faces.

How the parameters are chosen. The parameters are tau and rho, chosen only on development seeds by a procedure fixed here before it is run. The grid is tau in {0.25, 0.5, 1, 2} seconds and rho in {0.5, 0.75, 0.9}: twelve points, and no others. The value 0.25 seconds is the correlation time measured on the real front end. Each point is evaluated with the candidate gate of ADR-0030 in both scenarios on seeds 0 to 24. A point qualifies if the gate passes in both scenarios. The score of a point is its smallest margin, where the margin of a condition is its distance from its threshold in units of the threshold, over all conditions in both scenarios, and the qualifying point with the largest score is chosen; ties go to the smaller tau, then the smaller rho. The chosen point must also pass the gate in both scenarios on seeds 25 to 49, 50 to 74 and 75 to 99. If no point qualifies, or the chosen point fails a confirmation block, the candidate is recorded as failed on development seeds and is not taken to a held-out block; it is not repaired by adding grid points. Otherwise the parameters are frozen with the code commit and the candidate is evaluated once on the next unused held-out block, seeds 125 to 149, in both scenarios, as ADR-0030 requires.

What stays open. Whether the held-out evaluation passes, what the model costs in detection when the fault matrix is re-run for the candidate before that evaluation, and whether vision_enabled ever changes are not decided here. The adaptive visual noise scale of ADR-0031 and ADR-0032 stays recorded as failed on development seeds on the earlier fixture; its re-run on the corrected fixture is not made.

## Consequences

- A code package adds the states and the flag `vision_gm_error`, with `tau` and `rho` as settings. Tests come first. They include: with the flag off, every output is byte-identical to the previous behaviour; a filter with `rho` equal to 1 and a matching `tau`, fed a synthetic first-order autoregressive error, has a consistent covariance; the new states stay out of the clone re-commit; and the three refusals (not the clone model, together with a noise preset, together with the adaptive scale).
- A tuning package runs the stated grid once, on seeds 0 to 24, with the confirmation blocks, as the Decision says. It uses the selection and margin functions of the earlier tuning run.
- The fault matrix is re-run for the candidate before the held-out evaluation, and the change in detection is reported.
- The held-out run is a separate, single-use package on seeds 125 to 149.
- `CONSTRAINTS.md` B1 stays as it is until a candidate has been evaluated.
- The fixed preset of ADR-0024 remains as it is. This candidate does not use it.
