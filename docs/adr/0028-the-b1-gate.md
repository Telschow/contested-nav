# ADR-0028: The B1 gate: when visual fusion may ship

- Status: accepted
- Date: 2026-10
- Related: [ADR-0003](0003-ship-visual-disabled.md), [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md), [issue #113](https://github.com/Telschow/contested-nav/issues/113), [issue #112](https://github.com/Telschow/contested-nav/issues/112)

## Context

The old gate for blocker B1 is: mean NEES below 10 and 2-sigma coverage above 90%, over the full run, in one run. It has four faults.

- It is one-sided. It rejects an overconfident filter. It does not reject an uninformative one, and an IMU-only filter passes it.
- It scores the epochs with GNSS as well as the outage, so the epochs that carry the question are diluted.
- It uses one run. Since [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md) each seed draws its own start error from the declared prior, and a single run where absolute position is unobservable is close to one sample.
- It never asks whether vision helps. A filter can be consistent and no better than not using the camera.

So the gate has to be an ensemble over seeds. The ensemble statistic and its band are in [the ensemble section of the calibration guide](../calibration.md). Epochs within a run are strongly autocorrelated, so the band must be built on the effective sample size and not on the raw epoch count. The estimator is `navkit.eval.statistics.effective_sample_size`.

The thresholds follow from four principles.

1. **Overconfidence is the failure this project exists to catch.** The upper side is therefore purely statistical: the grand mean must not exceed the upper edge of the chi-square band.
2. **Conservatism only costs usefulness.** The lower side is therefore an engineering tolerance and not a statistical test: the claimed standard deviation may be at most 1.5 times the actual error.
3. **Vision must be shown to be useful.** The gate pairs the candidate with the no-vision control, seed by seed, and looks at the worst seed as well as the typical one.
4. **The gate is evaluated once, on held-out seeds.** Neither the thresholds nor the candidate can then be tuned on the result.

Disclosure. The development-seed ensemble (seeds 0 to 24, [PR #140](https://github.com/Telschow/contested-nav/pull/140)) existed when the thresholds were set. The thresholds are meant to follow from the principles above and not from those results. A reader cannot verify that from this page, so the order of events is recorded here as a fact.

## The candidate

The configuration proposed as the default is the `outage_visual` scenario of `configs/benchmark.yaml` with `vision_model: clone` and `vision_noise_preset: measured-front-end` ([ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md)). Its paired control is `outage_control` with the same seed.

The names exist: both cases are in the configuration, `vision_model: clone` is an accepted estimator key, and `measured-front-end` is the one entry of `VISION_NOISE_PRESETS`. The preset multiplies the assumed visual noise by the factor ADR-0024 records, and it is accepted only together with `vision_model: clone`. The existing `outage_visual_clone` case sets `trans_sigma_m` and the vision `seed` explicitly, to their default values. The candidate leaves them at the defaults, which is the same sensor model.

## Definitions

These are the specification for the gate code, which is a separate package.

- **Seeds.** Seed `s` is run through the same code path as the seed sweep, for the candidate and for the control, so the start draw of ADR-0027 applies and the two runs of a seed share their start draw and their IMU and GNSS noise.
- **Window.** The GNSS-outage window as `window_mask` and `score_mask` define it: the half-open interval `[start, start + duration)`.
- **NEES.** The per-epoch position NEES that the calibration report scores, with `dof = 3`. Only the window epochs are used.
- **Grand mean.** The mean of the NEES over the 25 runs and all window epochs.
- **Effective sample size.** `n_eff_i` is `effective_sample_size` of the window NEES series of run `i`.
- **Degrees of freedom.** `D = floor(dof * sum_i n_eff_i)`.
- **Upper edge.** `chi2_ppf(0.975, D) * dof / D`.
- **Lower bound.** `0.44 * dof`.
- **Coverage.** The share of (run, window epoch, axis) triples with `|error| <= 2 sigma` on that axis, pooled over all of them. The error is the position error the NEES uses and sigma is the square root of the matching diagonal entry of the position covariance block.
- **ATE per seed.** The root mean square of the 3-D position error over the window epochs, with no alignment, for the candidate and for the control. The ratio is the candidate's divided by the control's.

## Decision

The B1 gate is evaluated once, on seeds 100 to 124 (N = 25), for the configuration proposed as the default, over the GNSS-outage window. It passes when all of these hold: (1) the ensemble grand mean NEES is at or below the upper edge of the 95% chi-square band with N × dof × n_eff degrees of freedom, n_eff being the per-run effective sample size; (2) that grand mean is at least 0.44 × dof (claimed standard deviation at most 1.5 times the actual error); (3) pooled 2-sigma per-axis coverage is at least 95%; (4) against the no-vision control, paired by seed, vision has the lower ATE in at least 20 of 25 seeds, the median ATE ratio is 0.8 or lower, and no seed's ratio exceeds 1.5. Seeds 0 to 24 are the development set. If the candidate fails, any change to it is tested on a new held-out set. The development-seed ensemble existed when these thresholds were set; they follow from the principles stated in the context, not from those results.

Passing the gate does not by itself change `vision_enabled`; that stays a separate maintainer decision.

## Consequences

- When the held-out result exists, `CONSTRAINTS.md` B1 is restated against this gate. Until then B1 is unchanged.
- The old gate stays visible as history. Its results are not deleted.
- The gate code is a separate package. It is reviewed before any run on seeds 100 to 124.
- The held-out run happens once, in its own pull request, after the gate code is reviewed and this record is merged.
- A failure is a result. It is recorded as one, and a changed candidate needs a new held-out set and a new record.
