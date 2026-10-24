# Reading the calibration numbers

This is the guide to interpreting what `navkit` reports, and, more usefully,
to noticing when a result is not what it appears to be.

## The core idea

A trajectory is not a result. A trajectory with a covariance attached is a
claim about how much to trust it. If the covariance is wrong, everything
downstream is wrong, and the failure is silent because the output still looks
smooth.

Three numbers expose it.

## NEES: normalised estimation error squared

```
NEES = e^T P^-1 e
```

where `e` is the error between the estimate and truth, and `P` is the filter's
claimed covariance. If both are right, NEES is chi-square distributed with
`n` degrees of freedom, where `n` is the dimension of the state being scored.

`navkit` scores the 3-D position block, so the nominal mean is **3**, not 21.
The filter state has 21 entries, but the reported NEES is a position-only
statistic: `e^T P_pp^-1 e` with `P_pp` the 3x3 position covariance, and that
reference does not grow with the size of the state vector.

**Read it like this:**

| NEES vs nominal | Meaning |
|---|---|
| near nominal | consistent with calibration |
| far above | **overconfident**: claims more certainty than it has |
| far below | underconfident: claims less certainty than it has |

The number to be suspicious of is the gap, not the value. The generated
`outage_visual` and `vision_only` cases report a mean NEES that is thousands of times the nominal 3 in the seed-0
run, which is one run with one start draw
([ADR-0027](adr/0027-how-the-synthetic-runs-are-initialised.md)). That is not a filter that is slightly
miscalibrated.

The gap once fell when ADR-0006 stopped the filter discarding the GNSS fixes that B5 caused it to reject (R2 in
`CONSTRAINTS.md`, measured on the old fixed start). The remaining gap is the unmodelled visual anchor error, which
is a separate defect: the filter was more honest then because it stopped throwing away evidence, not because the
model behind `P` was repaired. Read NEES and the coverage column together with ATE. On the old fixed start ATE alone
stopped flagging this case; with the start drawn from the declared prior it flags it again, but that is no reason to
rank by error.

A 10-seed sweep changes the reading of the digits, not the verdict. Over 10 seeds, each with its own start draw,
`outage_visual` and `vision_only` were overconfident at every one, and their mean NEES spanned about two orders of
magnitude and about one (measured once on one machine, not checked by CI, at 946d661). So the order of magnitude is the right thing to write down, not a single digit.
A control's verdict string is also one draw: `outage_control` read consistent in 5 of the 10 seeds and mixed in the
others.

**Why it is decisive:** NEES only blows up when the error is large *and*
`P` is small. A filter that merely tracks badly has a large error but an
honestly large `P`, and its NEES stays near nominal. A NEES in the hundreds
requires both.

## 2-sigma coverage

The fraction of steps where the true error lies inside the claimed 2-sigma
ellipsoid.

```
coverage = mean(e^T P^-1 e <= 2^2 * 3)
```

evaluated over the scored window, where `e^T P^-1 e` is the squared Mahalanobis
distance and 3 is the number of position axes. For a 3-D position error at 2 sigma
per axis, a calibrated filter covers `P(chi2_3 <= 12) = 0.9926`, about **99.3%** of
the time. The 95% figure belongs to a single axis (`erf(2/sqrt(2)) = 0.9545`), and
using it here would make a well-calibrated filter look like it is missing a
quarter of its epochs. The same number comes from
`navkit.eval.statistics.ellipsoid_coverage(2.0, 3)`.

This is the most direct read for a downstream consumer: it is the probability
that a safety check written against this covariance would have been satisfied
by the truth. A filter at 0.7% coverage would fail roughly 99 checks in 100
that it believed it was passing.

**Coverage is also how you catch a filter that is accidentally too
conservative**, which is why it is reported alongside NEES rather than
instead of it. A filter that never updates has perfect coverage and useless
output.

## Calibration verdict

`navkit/eval/calibration.py` classifies each run as overconfident, underconfident
or consistent. `consistent` means that the run did not reject calibration; one run cannot establish it. The bulk
test compares the mean NEES with its chi-square band, and the tail test puts a **Wilson interval** on the coverage
fraction. Both are formed with the effective sample size of the run's scored NEES series, not with its epoch count,
because the epochs of a run are strongly autocorrelated
([ADR-0029](adr/0029-how-a-single-runs-verdict-is-formed.md)). A series of fewer than ten epochs, or a constant one,
has no estimate and reads `insufficient_data`.

The Wilson interval matters. A naive coverage estimate from 10 steps that
hits 9/10 looks perfect; a Wilson interval says the 95% interval on that
proportion still includes 0.5, so no verdict should be declared. Without the
interval, short runs produce confident nonsense, which is the same failure
mode as the original bug, one level up.

## The ensemble over seeds

Each seed starts from its own draw of the declared prior
([ADR-0027](adr/0027-how-the-synthetic-runs-are-initialised.md)), so one run, where absolute position cannot be
observed, is close to one sample. The test that fits is an ensemble. Run a case for many seeds and, at each epoch,
average the NEES over the runs. If the filter is consistent, that average times the number of runs is chi-square with
the number of runs times the degrees of freedom, so the average has a two-sided band: the 2.5% and 97.5% quantiles of
that chi-square, divided by the number of runs. The band narrows as the number of runs grows. The table uses 25
runs, because with 10 the band is too wide to separate a slightly conservative filter from a consistent one.

The table is generated from [`data/ensemble_nees.csv`](data/ensemble_nees.csv) and checked against it by a test. It
gives, for each case, the share of scored epochs at which the ensemble mean is inside, below or above the band. The
`outage` scope scores only the epochs inside the GNSS outage. Dead reckoning has no covariance and is not in the
table. Regenerate it with:

```bash
navkit sweep seeds --seeds 25 --ensemble-csv docs/data/ensemble_nees.csv --ensemble-page docs/calibration.md
```

<!-- ensemble:start -->

Band for the ensemble mean over N = 25 runs with 3 degrees of freedom: 2.118 to 4.034. Shares are of the scored epochs.

| Case | Scope | Scored epochs | Grand mean NEES | Inside the band | Below | Above |
|---|---|---:|---:|---:|---:|---:|
| gnss_only | full | 6001 | 3.353 | 92.3% | 0.0% | 7.7% |
| vision_anchor_in_measurement_noise | full | 6001 | 4.092e+05 | 0.0% | 0.0% | 100.0% |
| vision_only | full | 6001 | 1.925e+05 | 0.3% | 0.0% | 99.7% |
| outage_control | full | 6001 | 3.303 | 96.0% | 0.0% | 4.0% |
| outage_control | outage | 3000 | 3.474 | 100.0% | 0.0% | 0.0% |
| outage_visual | full | 6001 | 8.132e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual | outage | 3000 | 1.803e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera | full | 6001 | 3.736e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera | outage | 3000 | 8011 | 0.0% | 0.0% | 100.0% |
| outage_visual_clone | full | 6001 | 3.424 | 85.4% | 0.0% | 14.6% |
| outage_visual_clone | outage | 3000 | 3.592 | 79.4% | 0.0% | 20.6% |
| outage_visual_degraded_camera_rereferenced | full | 6001 | 3.726e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera_rereferenced | outage | 3000 | 8028 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera_clone | full | 6001 | 3.131 | 99.3% | 0.0% | 0.7% |
| outage_visual_degraded_camera_clone | outage | 3000 | 3.12 | 100.0% | 0.0% | 0.0% |
| vision_only_clone | full | 6001 | 3.174 | 100.0% | 0.0% | 0.0% |
| outage_visual_clone_outliers | full | 6001 | 3.376 | 92.9% | 0.0% | 7.1% |
| outage_visual_clone_outliers | outage | 3000 | 3.53 | 92.6% | 0.0% | 7.4% |
| outage_visual_clone_scale_drift | full | 6001 | 3.976 | 57.4% | 0.0% | 42.6% |
| outage_visual_clone_scale_drift | outage | 3000 | 4.416 | 34.3% | 0.0% | 65.7% |
| outage_visual_clone_correlated | full | 6001 | 112 | 3.1% | 0.0% | 96.9% |
| outage_visual_clone_correlated | outage | 3000 | 151.3 | 0.0% | 0.0% | 100.0% |
| outage_visual_clone_correlated_inflated | full | 6001 | 6.087 | 24.6% | 0.0% | 75.4% |
| outage_visual_clone_correlated_inflated | outage | 3000 | 8.14 | 0.0% | 0.0% | 100.0% |

<!-- ensemble:end -->

How to read it:

- The 25 runs of every case use seeds 0 to 24, so the cases are not independent of one another: they see the same
  noise draws and the same start draws.
- Because every case shares the start draws, the ensemble mean at the first epoch is the same sample in every row. It
  can sit outside the band for that reason alone. The first epoch is not excluded.
- The shares are descriptive, not a p-value. Epochs within a run are strongly autocorrelated, so the scored epochs
  are far from independent. `effective_sample_size` in `navkit.eval.statistics` measures that, and the next table
  gives its value for each case.

What the table shows. Each sentence is checked against the CSV by `tests/test_ensemble_page.py`.

- The no-vision controls (`gnss_only` and `outage_control`) are inside the band for most scored epochs.
- The single-anchor rows (`vision_anchor_in_measurement_noise`, `vision_only`, `outage_visual`,
  `outage_visual_degraded_camera` and `outage_visual_degraded_camera_rereferenced`) are above the band for nearly
  all scored epochs.
- The clone rows with independent visual errors are never below the band. Except for the row with a drifting
  translation scale, each is inside the band for more than three quarters of its scored epochs.
- The clone row with a drifting translation scale has a large share of its scored epochs above the band: more than
  a third in the full scope and more than half in the outage scope.
- The clone with visual errors correlated over time is above the band for nearly all scored epochs. The same case
  with the assumed visual noise inflated is no longer mostly inside the band: most of its scored epochs are above it
  in the full scope, and nearly all of them in the outage scope.

The table was regenerated on the fixture of [ADR-0033](adr/0033-one-convention-for-the-synthetic-visual-translation-noise.md), where each axis of the synthetic visual
translation noise is drawn with the standard deviation that the stream declares. Before that change the clone rows
with independent visual errors had a share below the band, and the case with the inflated assumed
noise was mostly inside it. That conservatism of the clone was largely the generator and the filter using different
noise conventions.

This table does not replace the single-run verdicts, which stay descriptive. How a gate would use the ensemble is
decided separately, with an ADR.

### How many independent samples a run is worth

A run of thousands of epochs is worth far fewer independent samples, because its epochs are strongly autocorrelated.
The table gives, for each case and scope, the smallest, median and largest effective sample size over the 25 runs,
and how many of those runs have a truncated estimate. It is generated from
[`data/effective_sample_size.csv`](data/effective_sample_size.csv) and checked against it by a test. The runs are the
same as in the ensemble table above, so the two describe one set of runs. Regenerate both with:

```bash
navkit sweep seeds --seeds 25 --ensemble-csv docs/data/ensemble_nees.csv --ensemble-page docs/calibration.md \
    --ess-csv docs/data/effective_sample_size.csv --ess-page docs/calibration.md
```

<!-- ess:start -->

| Case | Scope | Runs | Scored epochs | n_eff, smallest | n_eff, median | n_eff, largest | Truncated runs |
|---|---|---:|---:|---:|---:|---:|---:|
| gnss_only | full | 25 | 6001 | 10.4 | 19.8 | 48.1 | 0 |
| vision_anchor_in_measurement_noise | full | 25 | 6001 | 3.8 | 4.3 | 5.1 | 25 |
| vision_only | full | 25 | 6001 | 3.5 | 4.3 | 4.6 | 25 |
| outage_control | full | 25 | 6001 | 5.8 | 15.9 | 55.8 | 2 |
| outage_control | outage | 25 | 3000 | 3.3 | 4.0 | 14.4 | 23 |
| outage_visual | full | 25 | 6001 | 4.2 | 4.6 | 14.1 | 22 |
| outage_visual | outage | 25 | 3000 | 3.6 | 4.0 | 4.4 | 25 |
| outage_visual_degraded_camera | full | 25 | 6001 | 4.0 | 4.7 | 14.2 | 23 |
| outage_visual_degraded_camera | outage | 25 | 3000 | 3.5 | 4.1 | 4.5 | 25 |
| outage_visual_clone | full | 25 | 6001 | 7.2 | 14.8 | 34.0 | 2 |
| outage_visual_clone | outage | 25 | 3000 | 3.6 | 11.9 | 30.1 | 7 |
| outage_visual_degraded_camera_rereferenced | full | 25 | 6001 | 4.3 | 4.7 | 14.4 | 21 |
| outage_visual_degraded_camera_rereferenced | outage | 25 | 3000 | 3.4 | 4.1 | 4.4 | 25 |
| outage_visual_degraded_camera_clone | full | 25 | 6001 | 4.5 | 15.8 | 35.5 | 4 |
| outage_visual_degraded_camera_clone | outage | 25 | 3000 | 5.0 | 11.9 | 16.6 | 7 |
| vision_only_clone | full | 25 | 6001 | 3.5 | 7.0 | 24.6 | 14 |
| outage_visual_clone_outliers | full | 25 | 6001 | 6.6 | 14.9 | 38.6 | 2 |
| outage_visual_clone_outliers | outage | 25 | 3000 | 3.8 | 11.2 | 27.7 | 6 |
| outage_visual_clone_scale_drift | full | 25 | 6001 | 7.2 | 14.5 | 38.6 | 3 |
| outage_visual_clone_scale_drift | outage | 25 | 3000 | 3.8 | 11.0 | 28.7 | 8 |
| outage_visual_clone_correlated | full | 25 | 6001 | 3.3 | 12.9 | 29.1 | 4 |
| outage_visual_clone_correlated | outage | 25 | 3000 | 3.4 | 11.8 | 23.7 | 11 |
| outage_visual_clone_correlated_inflated | full | 25 | 6001 | 7.0 | 14.5 | 49.1 | 3 |
| outage_visual_clone_correlated_inflated | outage | 25 | 3000 | 3.4 | 6.6 | 23.1 | 14 |

<!-- ess:end -->

A truncated estimate means that the autocorrelation did not die away within the largest window the estimator allows,
which is half the series. The effective sample size is then an upper bound, because the estimated autocorrelation time
is a lower bound. A band built on it is narrower than it should be. A dagger after a verdict in a table means that the
effective sample size behind that verdict is truncated ([ADR-0029](adr/0029-how-a-single-runs-verdict-is-formed.md)).

## The B1 gate on the development seeds

[ADR-0028](adr/0028-the-b1-gate.md) sets the gate for blocker B1. This section is the development set, seeds 0 to 24.
The decision run is separate. It uses seeds 100 to 124, it is evaluated once, and its result is in the next section.
The table below was regenerated on the fixture of [ADR-0033](adr/0033-one-convention-for-the-synthetic-visual-translation-noise.md). The decision run was made on the
fixture before that change.

The candidate is the `outage_visual` scenario with the stochastic clone and the `measured-front-end` noise preset. Its
control is `outage_control` on the same seed, with vision off. Everything is scored over the GNSS-outage window only,
the half-open interval the calibration report uses. The table is generated from
[`data/b1_gate_dev.csv`](data/b1_gate_dev.csv) and checked against it by a test. Regenerate it with:

```bash
navkit gate b1 --seeds 0-24 --csv docs/data/b1_gate_dev.csv --page docs/calibration.md
```

What each condition means. The value and the threshold of every one are in the second table.

- **Upper edge.** The grand mean NEES is the mean over all runs and all window epochs. It must not exceed the upper
  edge of the 95% chi-square band. The band's degrees of freedom come from the effective sample size of each run
  (`effective_sample_size` in `navkit.eval.statistics`), not from the epoch count, because epochs within a run are
  strongly autocorrelated. This is the test for overconfidence. A truncated run is one whose autocorrelation estimate
  reached its largest window; its effective sample size is then an upper bound, so the band for it may be narrower
  than it should be.
- **Lower bound.** The same grand mean must not fall below a floor, which says that the claimed standard deviation is
  at most 1.5 times the actual error. This is an engineering tolerance for conservatism, not a statistical test.
- **Coverage.** The share of (run, epoch, axis) triples whose error is within 2 sigma on that axis, pooled. It is per
  axis, so it is not the ellipsoid coverage reported elsewhere.
- **Lower ATE.** The number of seeds in which the candidate has the lower ATE than its control over the window.
- **Median ratio.** The median over seeds of the candidate's ATE divided by the control's.
- **Largest ratio.** The worst seed's ratio.

The DIAGNOSTIC rows apply the same function to the same seeds. They are not gate decisions. The single-anchor
`outage_visual` is there to show that the gate can say no, and the plain clone `outage_visual_clone` is there to show
what the preset changes.

<!-- b1-gate-dev:start -->

| Role | Subject | Seeds | Runs | Window epochs | Sum of n_eff | Band degrees of freedom | Truncated runs | All conditions hold |
|---|---|---|---:|---:|---:|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | 0-24 | 25 | 3000 | 147.2 | 441 | 21 | yes |
| DIAGNOSTIC | outage_visual | 0-24 | 25 | 3000 | 100.9 | 302 | 25 | no |
| DIAGNOSTIC | outage_visual_clone | 0-24 | 25 | 3000 | 299.4 | 898 | 7 | no |

| Role | Subject | Condition | Value | Threshold | Holds |
|---|---|---|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at most the upper edge of the band | 1.976 | <= 3.409 | yes |
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at least the lower bound | 1.976 | >= 1.32 | yes |
| candidate | outage_visual+clone+measured-front-end | Pooled 2-sigma per-axis coverage | 96.41% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | Median ATE ratio, candidate over control | 0.1366 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | Largest ATE ratio | 0.4699 | <= 1.5 | yes |
| DIAGNOSTIC | outage_visual | Grand mean NEES, at most the upper edge of the band | 1.803e+04 | <= 3.497 | no |
| DIAGNOSTIC | outage_visual | Grand mean NEES, at least the lower bound | 1.803e+04 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | Pooled 2-sigma per-axis coverage | 12.99% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | Runs where the candidate has the lower ATE | 8 | >= 20 | no |
| DIAGNOSTIC | outage_visual | Median ATE ratio, candidate over control | 1.14 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | Largest ATE ratio | 11.2 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual_clone | Grand mean NEES, at most the upper edge of the band | 3.592 | <= 3.284 | no |
| DIAGNOSTIC | outage_visual_clone | Grand mean NEES, at least the lower bound | 3.592 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual_clone | Pooled 2-sigma per-axis coverage | 93.23% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual_clone | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| DIAGNOSTIC | outage_visual_clone | Median ATE ratio, candidate over control | 0.09655 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | Largest ATE ratio | 0.5428 | <= 1.5 | yes |

<!-- b1-gate-dev:end -->

This is the development set. It does not decide B1 and it does not change `vision_enabled`.

## The B1 gate: the decision run on the held-out seeds

This is the decision run of [ADR-0028](adr/0028-the-b1-gate.md): seeds 100 to 124, the candidate above, over the
GNSS-outage window. It was run once, with the code at commit 4c88341 on 2026-10-20. The held-out set is single use, so
it is not run again. A second run to a scratch path reproduced the committed file to the tolerance used for the
ensemble; it was a check and not a second decision.

Produced under the earlier draw of the synthetic visual translation noise (ADR-0033); not regenerated.

The table is generated from [`data/b1_gate_heldout.csv`](data/b1_gate_heldout.csv) and checked against it by a test.
The conditions are the same as in the section above. The DIAGNOSTIC rows are not computed on the held-out seeds, and
the command does not do so. The status of B1 is in `CONSTRAINTS.md`. It does not change `vision_enabled`.

<!-- b1-gate-heldout:start -->

| Role | Subject | Seeds | Runs | Window epochs | Sum of n_eff | Band degrees of freedom | Truncated runs | All conditions hold |
|---|---|---|---:|---:|---:|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | 100-124 | 25 | 3000 | 154.2 | 462 | 22 | no |

| Role | Subject | Condition | Value | Threshold | Holds |
|---|---|---|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at most the upper edge of the band | 1.176 | <= 3.399 | yes |
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at least the lower bound | 1.176 | >= 1.32 | no |
| candidate | outage_visual+clone+measured-front-end | Pooled 2-sigma per-axis coverage | 99.49% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | Median ATE ratio, candidate over control | 0.1551 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | Largest ATE ratio | 0.2726 | <= 1.5 | yes |

<!-- b1-gate-heldout:end -->

## The candidate gate of ADR-0030 on the development seeds

Work under this ADR has stopped. [ADR-0036](adr/0036-b1-is-closed-as-characterised-not-solved.md) records why and what stays.

[ADR-0030](adr/0030-the-gate-for-the-next-visual-update-candidate.md) sets the gate for the next visual-update
candidate. This section is the development run: seeds 25 to 49, which are development seeds. It shows that the
machinery works and that the gate can say no in each direction. No new candidate is evaluated here. The held-out blocks
start at seed 125 and are used one at a time; [the ledger](data/heldout_ledger.csv) lists the blocks used so far.

A candidate is a set of estimator settings, and the same settings run in two scenarios. S1 is the scenario of
`outage_visual`, with independent visual errors. S2 is the scenario of `outage_visual_clone_correlated`, which differs
only in that the visual errors are correlated over time. The configuration is not told which scenario it faces. In each
scenario the candidate and the no-vision control `outage_control` run on the same seeds, over the GNSS-outage window.
Each run gives the time mean of its NEES and the effective sample size of that series.

What each condition means. The value and the threshold of every one are in the second table.

- **(U) upper.** The 90th percentile of the per-run mean NEES must not exceed the upper edge of a chi-square band built
  on the median effective sample size. This is the test for overconfidence. It is a percentile and not a mean, so a few
  heavy-tailed runs cannot decide it.
- **(L) lower.** The median of the per-run mean NEES must not fall below a floor. This is the engineering tolerance for
  conservatism of the first gate, and not a statistical test.
- **(C) coverage.** The pooled share of (run, epoch, axis) triples whose error is within 2 sigma on that axis.
- **(P) paired against the control.** The number of seeds on which the candidate has the lower ATE, the median ratio of
  the candidate's ATE to the control's, and the largest ratio.

A scenario passes when all six hold, and a candidate passes only when it passes in both scenarios. The confidence level
of (U) is not chosen. It is the first level of a fixed list at which simulated runs behave as intended for (U) and (L),
and a test fails if the value differs from what that rule returns for
[the pool of effective sample sizes](data/gate_n_eff_pool.csv). The table is generated from
[`data/candidate_gate_dev.csv`](data/candidate_gate_dev.csv) and checked against it by a test. Regenerate it with:

```bash
navkit gate candidate --seeds 25-49 --csv docs/data/candidate_gate_dev.csv --page docs/calibration.md
```

<!-- candidate-gate-dev:start -->

| Role | Subject | Scenario | Seeds | Runs | Median n_eff (m) | Level of (U) | Holds in this scenario | Holds in both |
|---|---|---|---|---:|---:|---:|---|---|
| candidate | outage_visual+clone+measured-front-end | S1 | 25-49 | 25 | 5.8 | 0.975 | no | no |
| candidate | outage_visual+clone+measured-front-end | S2 | 25-49 | 25 | 10.9 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual_clone | S1 | 25-49 | 25 | 10.5 | 0.975 | yes | no |
| DIAGNOSTIC | outage_visual_clone | S2 | 25-49 | 25 | 9.3 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual | S1 | 25-49 | 25 | 4.0 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual | S2 | 25-49 | 25 | 4.1 | 0.975 | no | no |

| Role | Subject | Scenario | Condition | Value | Threshold | Holds |
|---|---|---|---|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 1.299 | <= 5.295 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Median of the per-run mean NEES, at least the lower bound | 0.5895 | >= 1.32 | no |
| candidate | outage_visual+clone+measured-front-end | S1 | Pooled 2-sigma per-axis coverage | 100.00% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Median ATE ratio, candidate over control | 0.1364 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Largest ATE ratio | 0.6278 | <= 1.5 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 12.22 | <= 4.619 | no |
| candidate | outage_visual+clone+measured-front-end | S2 | Median of the per-run mean NEES, at least the lower bound | 6.632 | >= 1.32 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Pooled 2-sigma per-axis coverage | 84.38% | >= 95.00% | no |
| candidate | outage_visual+clone+measured-front-end | S2 | Runs where the candidate has the lower ATE | 19 | >= 20 | no |
| candidate | outage_visual+clone+measured-front-end | S2 | Median ATE ratio, candidate over control | 0.5786 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Largest ATE ratio | 3.582 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual_clone | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 4.241 | <= 4.65 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Median of the per-run mean NEES, at least the lower bound | 2.37 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Pooled 2-sigma per-axis coverage | 96.60% | >= 95.00% | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Median ATE ratio, candidate over control | 0.1115 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Largest ATE ratio | 0.5568 | <= 1.5 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 196.6 | <= 4.771 | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Median of the per-run mean NEES, at least the lower bound | 110.6 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | Pooled 2-sigma per-axis coverage | 25.19% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Runs where the candidate has the lower ATE | 15 | >= 20 | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Median ATE ratio, candidate over control | 0.7089 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | Largest ATE ratio | 5.895 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 1.879e+04 | <= 5.816 | no |
| DIAGNOSTIC | outage_visual | S1 | Median of the per-run mean NEES, at least the lower bound | 8172 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | S1 | Pooled 2-sigma per-axis coverage | 13.76% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | S1 | Runs where the candidate has the lower ATE | 4 | >= 20 | no |
| DIAGNOSTIC | outage_visual | S1 | Median ATE ratio, candidate over control | 1.492 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | S1 | Largest ATE ratio | 7.249 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 2.104e+04 | <= 5.813 | no |
| DIAGNOSTIC | outage_visual | S2 | Median of the per-run mean NEES, at least the lower bound | 1.043e+04 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | S2 | Pooled 2-sigma per-axis coverage | 18.13% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | S2 | Runs where the candidate has the lower ATE | 4 | >= 20 | no |
| DIAGNOSTIC | outage_visual | S2 | Median ATE ratio, candidate over control | 1.585 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | S2 | Largest ATE ratio | 6.528 | <= 1.5 | no |

<!-- candidate-gate-dev:end -->

The candidate row is the candidate of ADR-0028, so that the machinery can be exercised. It is not a new candidate. The
DIAGNOSTIC rows apply the same function to the same seeds: the plain clone and the single anchor. They are not
candidates. They are there to show that the gate can say no. Passing the gate does not change `vision_enabled`; that is
a separate maintainer decision.

What the table shows, on the development seeds 25 to 49 and on the fixture of [ADR-0033](adr/0033-one-convention-for-the-synthetic-visual-translation-noise.md). Each
sentence is checked against the CSV by `tests/test_candidate_gate_page.py`.

- The plain clone `outage_visual_clone` passes all six conditions in S1. In S2 it fails the upper edge, the coverage,
  the paired count and the largest ratio.
- The candidate of ADR-0028, the clone with the `measured-front-end` preset, fails one condition in S1, the lower
  bound on the median NEES, and fails the same four conditions in S2 as the plain clone.
- The single anchor `outage_visual` fails both scenarios.

So the measured-front-end preset, which assumes four times the visual noise, no longer meets S2 on the synthetic
fixture. The evidence for it on recorded-data windows ([ADR-0024](adr/0024-assumed-noise-for-the-opt-in-clone.md))
was produced on a different fixture and is not affected. Before ADR-0033 the plain clone failed S1 on the lower
bound, and the candidate passed S2; the earlier table is in the history of this file. That conservatism was largely
the generator and the filter using different noise conventions. Nothing here changes `vision_enabled`.

## The tuning run of the adaptive visual scale (ADR-0031)

Work under this ADR has stopped. [ADR-0036](adr/0036-b1-is-closed-as-characterised-not-solved.md) records why and what stays.

[ADR-0031](adr/0031-an-adaptive-visual-noise-scale.md), amended by
[ADR-0032](adr/0032-the-adaptive-visual-scale-takes-every-visual-update.md), fixes how the three parameters of the
adaptive visual scale are chosen. The grid, the margin and the tie rule were written down before the run, and the grid
was run once. Each grid point is the stochastic clone with the scale on and no noise preset. It goes through the
candidate gate of ADR-0030 in both scenarios on the development seeds, and it qualifies if it passes that gate in both.

The margin of a condition is its distance from its threshold in units of the threshold, and it is negative when the
condition fails. The score of a point is its smallest margin over all conditions in both scenarios. The qualifying point
with the largest score is chosen. Ties go to the smaller tau, then the larger s_min, then the smaller s_max. The chosen
point must then pass the gate in both scenarios on further blocks of development seeds. If no point qualifies, or the
chosen point fails a block, the candidate is recorded as failed on development seeds. It is not repaired, no grid point
is added, and it is not taken to a held-out block.

Produced under the earlier draw of the synthetic visual translation noise (ADR-0033); not regenerated.

The rows are in [`data/adaptive_scale_tuning.csv`](data/adaptive_scale_tuning.csv). The tables below are generated from
them and checked against them by a test, which also recomputes the margins, the scores and the choice. Regenerate them
with:

```bash
navkit gate tune-scale --csv docs/data/adaptive_scale_tuning.csv --page docs/calibration.md
```

<!-- scale-tuning:start -->

Grid, development seeds 0 to 24. The score is the smallest margin of a point, and the last column names the condition that gives it.

| tau (s) | s_min | s_max | S1 holds | S2 holds | Score | Smallest margin is | Qualifies | Chosen |
|---:|---:|---:|---|---|---:|---|---|---|
| 2 | 0.25 | 8 | no | no | -40.34 | S2 upper | no |  |
| 2 | 0.25 | 16 | no | no | -40.34 | S2 upper | no |  |
| 2 | 0.5 | 8 | yes | no | -25.69 | S2 upper | no |  |
| 2 | 0.5 | 16 | yes | no | -25.69 | S2 upper | no |  |
| 5 | 0.25 | 8 | yes | no | -32.58 | S2 upper | no |  |
| 5 | 0.25 | 16 | yes | no | -32.58 | S2 upper | no |  |
| 5 | 0.5 | 8 | yes | no | -24.09 | S2 upper | no |  |
| 5 | 0.5 | 16 | yes | no | -24.09 | S2 upper | no |  |
| 10 | 0.25 | 8 | yes | no | -22.28 | S2 upper | no |  |
| 10 | 0.25 | 16 | yes | no | -22.28 | S2 upper | no |  |
| 10 | 0.5 | 8 | yes | no | -21.33 | S2 upper | no |  |
| 10 | 0.5 | 16 | yes | no | -21.33 | S2 upper | no |  |

Outcome: failed on development seeds. No point of the grid passed the gate in both scenarios on seeds 0 to 24, so none was chosen and none was confirmed.

<!-- scale-tuning:end -->

What the outcome does not show. The data are synthetic. There are two scenarios, and the visual errors in them are
generated by the simulator, not measured. Only development seeds were used, so the candidate has not been evaluated on
a held-out block, and nothing here stands in for that. The fault matrix has not been re-run for the scale. The scale stays off
by default, and `vision_enabled` is unchanged.

## The tuning run of the Gauss-Markov visual error model (ADR-0034)

Work under this ADR has stopped. [ADR-0036](adr/0036-b1-is-closed-as-characterised-not-solved.md) records why and what stays.

[ADR-0034](adr/0034-a-gauss-markov-model-of-the-correlated-visual-error.md) fixes how the two parameters of the
Gauss-Markov model of the correlated visual error are chosen. The grid, the margin and the tie rule were written down
before the run, and the grid was run once. Each grid point is the stochastic clone with the model on, no noise preset
and no adaptive scale. It goes through the candidate gate of ADR-0030 in both scenarios on the development seeds, and it
qualifies if it passes that gate in both.

The margin of a condition is its distance from its threshold in units of the threshold, and it is negative when the
condition fails. The score of a point is its smallest margin over all conditions in both scenarios. The qualifying point
with the largest score is chosen. Ties go to the smaller tau, then the smaller rho. The chosen point must then pass the
gate in both scenarios on further blocks of development seeds. If no point qualifies, or the chosen point fails a block,
the candidate is recorded as failed on development seeds. It is not repaired, no grid point is added, and it is not
taken to a held-out block. The margin functions are those of the run for the adaptive scale, imported and not copied.

The rows are in [`data/gm_tuning.csv`](data/gm_tuning.csv). The tables below are generated from them and checked
against them by a test, which also recomputes the margins, the scores and the choice. Regenerate them with:

```bash
navkit gate tune-gm --csv docs/data/gm_tuning.csv --page docs/calibration.md
```

<!-- gm-tuning:start -->

Grid, development seeds 0 to 24. The score is the smallest margin of a point, and the column 'Smallest margin is' names the condition that gives it.

| tau (s) | rho | S1 holds | S2 holds | Score | Smallest margin is | Qualifies | Chosen |
|---:|---:|---|---|---:|---|---|---|
| 0.25 | 0.5 | yes | no | -7.353 | S2 upper | no |  |
| 0.25 | 0.75 | yes | no | -4.915 | S2 upper | no |  |
| 0.25 | 0.9 | yes | no | -4.17 | S2 upper | no |  |
| 0.5 | 0.5 | no | no | -3.448 | S2 upper | no |  |
| 0.5 | 0.75 | no | no | -2.197 | S2 upper | no |  |
| 0.5 | 0.9 | yes | no | -1.904 | S2 upper | no |  |
| 1 | 0.5 | no | no | -1.814 | S2 upper | no |  |
| 1 | 0.75 | yes | no | -0.9187 | S2 upper | no |  |
| 1 | 0.9 | yes | no | -0.5013 | S2 upper | no |  |
| 2 | 0.5 | no | no | -0.6418 | S2 upper | no |  |
| 2 | 0.75 | yes | no | -0.491 | S2 worst_ratio | no |  |
| 2 | 0.9 | yes | no | -0.4701 | S2 worst_ratio | no |  |

Outcome: failed on development seeds. No point of the grid passed the gate in both scenarios on seeds 0 to 24, so none was chosen and none was confirmed.

<!-- gm-tuning:end -->

DIAGNOSTIC, outside the decision. After the decision, the same gate is evaluated for the chosen point (or, if no point
qualified, the point with the highest score) in the S2-like scenario at other visual-error correlation times, on
development seeds that the grid did not use. It shows whether the point is robust to a correlation time it was not tuned
for. It is not a selection input and not a pass or fail, and nothing in the decision reads it. The rows are in
[`data/gm_tuning_robustness.csv`](data/gm_tuning_robustness.csv).

<!-- gm-tuning-robustness:start -->

DIAGNOSTIC, outside the decision. The subject is the point with the highest score, because no point qualified (tau = 2 s, rho = 0.9). The S2-like scenario is run with the visual-error correlation time set to each value below, on development seeds 25 to 49, and the gate of ADR-0030 is evaluated for that scenario alone. This is not a pass or fail and not a selection input: it shows whether the point is robust to a correlation time it was not tuned for.

| Correlation time (s) | Condition | Value | Threshold | Margin | Holds | All six hold |
|---:|---|---:|---:|---:|---|---|
| 0 | upper | 1.768 | 4.517 | 0.6086 | yes | no |
| 0 | lower | 0.9374 | 1.32 | -0.2899 | no | no |
| 0 | coverage | 0.9997 | 0.95 | 0.05235 | yes | no |
| 0 | better | 25 | 20 | 0.25 | yes | no |
| 0 | median_ratio | 0.3165 | 0.8 | 0.6044 | yes | no |
| 0 | worst_ratio | 0.6714 | 1.5 | 0.5524 | yes | no |
| 0.25 | upper | 2.429 | 4.313 | 0.4369 | yes | no |
| 0.25 | lower | 0.9899 | 1.32 | -0.2501 | no | no |
| 0.25 | coverage | 0.9977 | 0.95 | 0.05021 | yes | no |
| 0.25 | better | 22 | 20 | 0.1 | yes | no |
| 0.25 | median_ratio | 0.382 | 0.8 | 0.5226 | yes | no |
| 0.25 | worst_ratio | 1.293 | 1.5 | 0.1378 | yes | no |
| 0.5 | upper | 2.839 | 4.317 | 0.3425 | yes | no |
| 0.5 | lower | 1.135 | 1.32 | -0.1401 | no | no |
| 0.5 | coverage | 0.9949 | 0.95 | 0.0473 | yes | no |
| 0.5 | better | 22 | 20 | 0.1 | yes | no |
| 0.5 | median_ratio | 0.4736 | 0.8 | 0.408 | yes | no |
| 0.5 | worst_ratio | 1.644 | 1.5 | -0.09627 | no | no |
| 1 | upper | 3.354 | 4.404 | 0.2384 | yes | no |
| 1 | lower | 1.518 | 1.32 | 0.1503 | yes | no |
| 1 | coverage | 0.9865 | 0.95 | 0.0384 | yes | no |
| 1 | better | 20 | 20 | 0 | yes | no |
| 1 | median_ratio | 0.5053 | 0.8 | 0.3684 | yes | no |
| 1 | worst_ratio | 2.166 | 1.5 | -0.4438 | no | no |
| 2 | upper | 4.352 | 4.508 | 0.03461 | yes | no |
| 2 | lower | 1.945 | 1.32 | 0.4733 | yes | no |
| 2 | coverage | 0.9724 | 0.95 | 0.02354 | yes | no |
| 2 | better | 19 | 20 | -0.05 | no | no |
| 2 | median_ratio | 0.5382 | 0.8 | 0.3273 | yes | no |
| 2 | worst_ratio | 2.79 | 1.5 | -0.8597 | no | no |

<!-- gm-tuning-robustness:end -->

What the outcome does not show. The data are synthetic. There are two scenarios, and the visual errors in them are
generated by the simulator, not measured. Only development seeds were used, so the candidate has not been evaluated on
a held-out block, and nothing here stands in for that. The fault matrix has not been re-run for the model. The model
stays off by default, and `vision_enabled` is unchanged.

## Usefulness in scenario S2 with a near-exact model (diagnostic)

The tuning run of the Gauss-Markov model (above) found no point that held the gate of ADR-0030 in both scenarios. Its
best point held the three NEES conditions in scenario S2 and did not hold the usefulness conditions: the candidate was
not better than the no-vision control in enough seeds, and in a few seeds it was much worse. This section asks whether
a model closer to the simulator's own error process changes that. It is a DIAGNOSTIC on development seeds, outside every
decision. [ADR-0036](adr/0036-b1-is-closed-as-characterised-not-solved.md) records the decision that stops this work.

The table is generated by `navkit gate usefulness-s2 --csv docs/data/gm_s2_usefulness.csv --page docs/calibration.md`
from [`data/gm_s2_usefulness.csv`](data/gm_s2_usefulness.csv) and checked against it by a test. The command takes no
seed: it uses development seeds only.

<!-- gm-s2-usefulness:start -->

DIAGNOSTIC, outside every decision. Scenario S2 (visual errors correlated over time), development seeds 25-49. The comparison with the no-vision control is seed by seed, over the GNSS-outage window.

| Subject | Runs | Control window ATE, median (m) | Candidate window ATE, median (m) | Runs with the lower ATE | ATE ratio, median | ATE ratio, 90th percentile | ATE ratio, maximum |
|---|---:|---:|---:|---:|---:|---:|---:|
| plain clone (no model) | 25 | 7.096 | 7.288 | 15 | 0.7089 | 2.997 | 5.895 |
| Gauss-Markov model, tau 2 s, rho 0.9 | 25 | 7.096 | 4.628 | 19 | 0.5382 | 1.984 | 2.79 |
| Gauss-Markov model, tau 2 s, rho 0.99 | 25 | 7.096 | 4.717 | 19 | 0.5396 | 1.966 | 2.725 |

| Subject | Condition | Value | Threshold | Holds | All six hold |
|---|---|---:|---:|---|---|
| plain clone (no model) | upper | 196.6 | 4.771 | no | no |
| plain clone (no model) | lower | 110.6 | 1.32 | yes | no |
| plain clone (no model) | coverage | 0.2519 | 0.95 | no | no |
| plain clone (no model) | better | 15 | 20 | no | no |
| plain clone (no model) | median_ratio | 0.7089 | 0.8 | yes | no |
| plain clone (no model) | worst_ratio | 5.895 | 1.5 | no | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | upper | 4.352 | 4.508 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | lower | 1.945 | 1.32 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | coverage | 0.9724 | 0.95 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | better | 19 | 20 | no | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | median_ratio | 0.5382 | 0.8 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.9 | worst_ratio | 2.79 | 1.5 | no | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | upper | 4.136 | 4.502 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | lower | 1.881 | 1.32 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | coverage | 0.9781 | 0.95 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | better | 19 | 20 | no | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | median_ratio | 0.5396 | 0.8 | yes | no |
| Gauss-Markov model, tau 2 s, rho 0.99 | worst_ratio | 2.725 | 1.5 | no | no |

In scenario S2, for the plain clone (no model): the NEES conditions do not all hold (upper and coverage fail), and the usefulness conditions are not met (better and worst_ratio fail). In scenario S2, for the Gauss-Markov model, tau 2 s, rho 0.9: the NEES conditions hold, and the usefulness conditions are not met (better and worst_ratio fail). In scenario S2, for the Gauss-Markov model, tau 2 s, rho 0.99: the NEES conditions hold, and the usefulness conditions are not met (better and worst_ratio fail). Making the model more exact (tau 2 s, rho 0.99 instead of tau 2 s, rho 0.9) does not change which conditions hold. This is one near-exact model on 25 development seeds. It does not show that no estimator can meet the usefulness conditions in S2: it shows that these did not.

<!-- gm-s2-usefulness:end -->

## Worked example: reading the defect

From the generated benchmark (`python scripts/run_benchmark.py`, GNSS available
throughout, 30 s). This is one run with one start draw (seed 0), so it is descriptive:

| Configuration | ATE RMSE | 1-sigma claimed | Mean NEES | Coverage at 2 sigma |
|---|---:|---:|---:|---:|
| GNSS only (control) | 0.512 m | 0.254 m | 4.2 | 100.0% |
| GNSS + vision, anchor as measurement noise (defect) | 11.405 m | 0.100 m | 13322.0 | 9.0% |
| Vision only, anchor as filter state | 26.605 m | 0.158 m | 31789.6 | 1.5% |

Row 1 is the reference: error and claimed uncertainty are the same order, and
coverage is complete.

Row 2 is the defect. Note the combination: the claimed 1-sigma is far
below the error it is attached to, the mean NEES is thousands of times the
nominal 3, and coverage is a few percent where 99.3% is expected. Any one of these would
warrant investigation. Together they say the filter is confidently wrong, and
the *direction* of the error matters -- it is overconfident, not merely
inaccurate.

Row 3 is the anchor modelled as filter state, and it is the honest failure. It
is not overconfident in the same way, but its mean NEES is still far above the expected value, and its
ATE is worse than the GNSS-only control it was meant to replace. Modelling the
anchor as state is necessary and not sufficient; the numbers are quoted because
they are unflattering, not because they are reassuring.

The same cases also show the accept/reject counts, which is where the defect
was first visible as a *sensor* problem rather than a covariance problem:

| Configuration | GNSS used | GNSS rejected | Vision used | Vision rejected |
|---|---:|---:|---:|---:|
| GNSS only (control) | 151 | 0 | 0 | 0 |
| GNSS + vision, anchor as measurement noise (defect) | 49 | 102 | 599 | 0 |
| Vision only, anchor as filter state | 0 | 0 | 599 | 0 |

The defect row now shows the companion symptom in this run: the visual update shrinks the position covariance far
enough that valid GNSS fixes fail their own gating test, so the filter discards its most reliable sensor. An earlier
version of this page said the generated cases did not reproduce that; that was on the old fixed start. Here it is one
run with one start draw, and it was not swept, so it is an observation and not a rate.
