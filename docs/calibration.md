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
magnitude and about one (measured once on one machine, not checked by CI, at 7e33158). So the order of magnitude is the right thing to write down, not a single digit.
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
runs, because with 10 the band is too wide to separate a mildly conservative filter from a consistent one.

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
| vision_anchor_in_measurement_noise | full | 6001 | 4.087e+05 | 0.0% | 0.0% | 100.0% |
| vision_only | full | 6001 | 1.931e+05 | 0.3% | 0.0% | 99.7% |
| outage_control | full | 6001 | 3.303 | 96.0% | 0.0% | 4.0% |
| outage_control | outage | 3000 | 3.474 | 100.0% | 0.0% | 0.0% |
| outage_visual | full | 6001 | 8.221e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual | outage | 3000 | 1.822e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera | full | 6001 | 3.669e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera | outage | 3000 | 7962 | 0.0% | 0.0% | 100.0% |
| outage_visual_clone | full | 6001 | 2.346 | 58.8% | 40.6% | 0.7% |
| outage_visual_clone | outage | 3000 | 1.874 | 26.7% | 73.3% | 0.0% |
| outage_visual_degraded_camera_rereferenced | full | 6001 | 3.67e+04 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera_rereferenced | outage | 3000 | 7978 | 0.0% | 0.0% | 100.0% |
| outage_visual_degraded_camera_clone | full | 6001 | 2.35 | 72.3% | 27.0% | 0.7% |
| outage_visual_degraded_camera_clone | outage | 3000 | 2.076 | 47.4% | 52.6% | 0.0% |
| vision_only_clone | full | 6001 | 2.65 | 89.0% | 11.0% | 0.0% |
| outage_visual_clone_outliers | full | 6001 | 2.344 | 57.1% | 42.2% | 0.7% |
| outage_visual_clone_outliers | outage | 3000 | 1.908 | 23.7% | 76.3% | 0.0% |
| outage_visual_clone_scale_drift | full | 6001 | 2.886 | 72.6% | 17.0% | 10.4% |
| outage_visual_clone_scale_drift | outage | 3000 | 2.653 | 55.6% | 33.0% | 11.4% |
| outage_visual_clone_correlated | full | 6001 | 30.43 | 4.0% | 0.0% | 96.0% |
| outage_visual_clone_correlated | outage | 3000 | 43.17 | 0.0% | 0.0% | 100.0% |
| outage_visual_clone_correlated_inflated | full | 6001 | 3.397 | 93.8% | 0.0% | 6.2% |
| outage_visual_clone_correlated_inflated | outage | 3000 | 3.613 | 94.3% | 0.0% | 5.7% |

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
- The clone rows with independent visual errors are inside or below the band for most scored epochs.
- The clone with visual errors correlated over time is above the band for nearly all scored epochs, and the same case
  with the assumed visual noise inflated is inside the band for most of them.

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
| vision_anchor_in_measurement_noise | full | 25 | 6001 | 3.2 | 4.3 | 5.1 | 25 |
| vision_only | full | 25 | 6001 | 3.6 | 4.3 | 4.6 | 25 |
| outage_control | full | 25 | 6001 | 5.8 | 15.9 | 55.8 | 2 |
| outage_control | outage | 25 | 3000 | 3.3 | 4.0 | 14.4 | 23 |
| outage_visual | full | 25 | 6001 | 4.2 | 4.5 | 14.1 | 22 |
| outage_visual | outage | 25 | 3000 | 3.6 | 4.0 | 4.4 | 25 |
| outage_visual_degraded_camera | full | 25 | 6001 | 4.0 | 4.7 | 15.1 | 22 |
| outage_visual_degraded_camera | outage | 25 | 3000 | 3.5 | 4.1 | 4.6 | 25 |
| outage_visual_clone | full | 25 | 6001 | 5.5 | 13.7 | 30.9 | 4 |
| outage_visual_clone | outage | 25 | 3000 | 3.7 | 6.2 | 31.8 | 15 |
| outage_visual_degraded_camera_rereferenced | full | 25 | 6001 | 4.2 | 4.8 | 14.4 | 21 |
| outage_visual_degraded_camera_rereferenced | outage | 25 | 3000 | 3.5 | 4.1 | 4.4 | 25 |
| outage_visual_degraded_camera_clone | full | 25 | 6001 | 5.5 | 13.9 | 40.8 | 4 |
| outage_visual_degraded_camera_clone | outage | 25 | 3000 | 3.3 | 6.2 | 22.5 | 17 |
| vision_only_clone | full | 25 | 6001 | 3.4 | 4.8 | 22.0 | 18 |
| outage_visual_clone_outliers | full | 25 | 6001 | 5.2 | 13.9 | 29.3 | 3 |
| outage_visual_clone_outliers | outage | 25 | 3000 | 3.6 | 7.4 | 18.6 | 13 |
| outage_visual_clone_scale_drift | full | 25 | 6001 | 6.6 | 15.1 | 43.2 | 5 |
| outage_visual_clone_scale_drift | outage | 25 | 3000 | 3.6 | 10.2 | 29.8 | 12 |
| outage_visual_clone_correlated | full | 25 | 6001 | 5.4 | 13.5 | 26.4 | 3 |
| outage_visual_clone_correlated | outage | 25 | 3000 | 3.3 | 10.3 | 17.8 | 11 |
| outage_visual_clone_correlated_inflated | full | 25 | 6001 | 7.3 | 16.0 | 29.2 | 2 |
| outage_visual_clone_correlated_inflated | outage | 25 | 3000 | 3.4 | 5.3 | 17.3 | 16 |

<!-- ess:end -->

A truncated estimate means that the autocorrelation did not die away within the largest window the estimator allows,
which is half the series. The effective sample size is then an upper bound, because the estimated autocorrelation time
is a lower bound. A band built on it is narrower than it should be. A dagger after a verdict in a table means that the
effective sample size behind that verdict is truncated ([ADR-0029](adr/0029-how-a-single-runs-verdict-is-formed.md)).

## The B1 gate on the development seeds

[ADR-0028](adr/0028-the-b1-gate.md) sets the gate for blocker B1. This section is the development set, seeds 0 to 24.
The decision run is separate. It uses seeds 100 to 124, it is evaluated once, and its result is in the next section.

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
| candidate | outage_visual+clone+measured-front-end | 0-24 | 25 | 3000 | 144.0 | 432 | 22 | yes |
| DIAGNOSTIC | outage_visual | 0-24 | 25 | 3000 | 100.8 | 302 | 25 | no |
| DIAGNOSTIC | outage_visual_clone | 0-24 | 25 | 3000 | 265.1 | 795 | 15 | yes |

| Role | Subject | Condition | Value | Threshold | Holds |
|---|---|---|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at most the upper edge of the band | 1.891 | <= 3.413 | yes |
| candidate | outage_visual+clone+measured-front-end | Grand mean NEES, at least the lower bound | 1.891 | >= 1.32 | yes |
| candidate | outage_visual+clone+measured-front-end | Pooled 2-sigma per-axis coverage | 96.14% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | Median ATE ratio, candidate over control | 0.1185 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | Largest ATE ratio | 0.5476 | <= 1.5 | yes |
| DIAGNOSTIC | outage_visual | Grand mean NEES, at most the upper edge of the band | 1.822e+04 | <= 3.497 | no |
| DIAGNOSTIC | outage_visual | Grand mean NEES, at least the lower bound | 1.822e+04 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | Pooled 2-sigma per-axis coverage | 12.63% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | Runs where the candidate has the lower ATE | 9 | >= 20 | no |
| DIAGNOSTIC | outage_visual | Median ATE ratio, candidate over control | 1.12 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | Largest ATE ratio | 11.27 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual_clone | Grand mean NEES, at most the upper edge of the band | 1.874 | <= 3.302 | yes |
| DIAGNOSTIC | outage_visual_clone | Grand mean NEES, at least the lower bound | 1.874 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual_clone | Pooled 2-sigma per-axis coverage | 98.49% | >= 95.00% | yes |
| DIAGNOSTIC | outage_visual_clone | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| DIAGNOSTIC | outage_visual_clone | Median ATE ratio, candidate over control | 0.07325 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | Largest ATE ratio | 0.3923 | <= 1.5 | yes |

<!-- b1-gate-dev:end -->

This is the development set. It does not decide B1 and it does not change `vision_enabled`.

## The B1 gate: the decision run on the held-out seeds

This is the decision run of [ADR-0028](adr/0028-the-b1-gate.md): seeds 100 to 124, the candidate above, over the
GNSS-outage window. It was run once, with the code at commit 4c88341 on 2026-10-20. The held-out set is single use, so
it is not run again. A second run to a scratch path reproduced the committed file to the tolerance used for the
ensemble; it was a check and not a second decision.

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
| candidate | outage_visual+clone+measured-front-end | S1 | 25-49 | 25 | 4.3 | 0.975 | no | no |
| candidate | outage_visual+clone+measured-front-end | S2 | 25-49 | 25 | 5.9 | 0.975 | yes | no |
| DIAGNOSTIC | outage_visual_clone | S1 | 25-49 | 25 | 6.6 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual_clone | S2 | 25-49 | 25 | 6.8 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual | S1 | 25-49 | 25 | 4.0 | 0.975 | no | no |
| DIAGNOSTIC | outage_visual | S2 | 25-49 | 25 | 4.1 | 0.975 | no | no |

| Role | Subject | Scenario | Condition | Value | Threshold | Holds |
|---|---|---|---|---:|---:|---|
| candidate | outage_visual+clone+measured-front-end | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 1.219 | <= 5.716 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Median of the per-run mean NEES, at least the lower bound | 0.7117 | >= 1.32 | no |
| candidate | outage_visual+clone+measured-front-end | S1 | Pooled 2-sigma per-axis coverage | 100.00% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Median ATE ratio, candidate over control | 0.116 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | S1 | Largest ATE ratio | 0.3733 | <= 1.5 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 4.448 | <= 5.283 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Median of the per-run mean NEES, at least the lower bound | 2.918 | >= 1.32 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Pooled 2-sigma per-axis coverage | 97.17% | >= 95.00% | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Runs where the candidate has the lower ATE | 20 | >= 20 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Median ATE ratio, candidate over control | 0.4389 | <= 0.8 | yes |
| candidate | outage_visual+clone+measured-front-end | S2 | Largest ATE ratio | 1.192 | <= 1.5 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 1.848 | <= 5.145 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Median of the per-run mean NEES, at least the lower bound | 0.9381 | >= 1.32 | no |
| DIAGNOSTIC | outage_visual_clone | S1 | Pooled 2-sigma per-axis coverage | 100.00% | >= 95.00% | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Runs where the candidate has the lower ATE | 25 | >= 20 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Median ATE ratio, candidate over control | 0.07701 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | S1 | Largest ATE ratio | 0.2554 | <= 1.5 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 71.57 | <= 5.102 | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Median of the per-run mean NEES, at least the lower bound | 33.93 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | Pooled 2-sigma per-axis coverage | 41.98% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Runs where the candidate has the lower ATE | 19 | >= 20 | no |
| DIAGNOSTIC | outage_visual_clone | S2 | Median ATE ratio, candidate over control | 0.5126 | <= 0.8 | yes |
| DIAGNOSTIC | outage_visual_clone | S2 | Largest ATE ratio | 1.747 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual | S1 | 90th percentile of the per-run mean NEES, at most the upper edge | 1.886e+04 | <= 5.82 | no |
| DIAGNOSTIC | outage_visual | S1 | Median of the per-run mean NEES, at least the lower bound | 8117 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | S1 | Pooled 2-sigma per-axis coverage | 14.10% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | S1 | Runs where the candidate has the lower ATE | 4 | >= 20 | no |
| DIAGNOSTIC | outage_visual | S1 | Median ATE ratio, candidate over control | 1.489 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | S1 | Largest ATE ratio | 7.122 | <= 1.5 | no |
| DIAGNOSTIC | outage_visual | S2 | 90th percentile of the per-run mean NEES, at most the upper edge | 2.399e+04 | <= 5.808 | no |
| DIAGNOSTIC | outage_visual | S2 | Median of the per-run mean NEES, at least the lower bound | 1.226e+04 | >= 1.32 | yes |
| DIAGNOSTIC | outage_visual | S2 | Pooled 2-sigma per-axis coverage | 12.52% | >= 95.00% | no |
| DIAGNOSTIC | outage_visual | S2 | Runs where the candidate has the lower ATE | 4 | >= 20 | no |
| DIAGNOSTIC | outage_visual | S2 | Median ATE ratio, candidate over control | 1.634 | <= 0.8 | no |
| DIAGNOSTIC | outage_visual | S2 | Largest ATE ratio | 6.379 | <= 1.5 | no |

<!-- candidate-gate-dev:end -->

The candidate row is the candidate of ADR-0028, so that the machinery can be exercised. It is not a new candidate. The
DIAGNOSTIC rows apply the same function to the same seeds: the plain clone and the single anchor. They are not
candidates. They are there to show that the gate can say no. Passing the gate does not change `vision_enabled`; that is
a separate maintainer decision.

## The tuning run of the adaptive visual scale (ADR-0031)

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
