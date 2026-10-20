# ADR-0029: How a single run's verdict is formed

- Status: accepted
- Date: 2026-10
- Related: [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md), [ADR-0028](0028-the-b1-gate.md), [issue #112](https://github.com/Telschow/contested-nav/issues/112)

## Context

The verdict of one run is formed by two tests. The bulk test (`bulk_verdict`) compares the run's mean NEES with the chi-square band for `n_epochs × dof` degrees of freedom. The coverage test (`CoveragePoint.verdict`) puts a Wilson interval over the epochs. Both assume that the epochs are independent.

They are not. Epochs within a run are strongly autocorrelated, so a run carries far fewer independent samples than it has epochs. [PR #134](https://github.com/Telschow/contested-nav/pull/134) measured this per case with `effective_sample_size` in `navkit.eval.statistics`. A test that counts every epoch as independent is overconfident by that ratio: its bands are too narrow, and it rejects calibration too often.

The project has seen the consequence. The verdict strings of the controls change from seed to seed. A control that is the same filter on the same scenario reads underconfident on one seed, mixed on another and overconfident on a third.

Since [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md) each seed draws its own start error, and one run is close to one sample, so a single run is descriptive. This record fixes how its verdict is formed, so that the verdict does not over-reject. The ensemble over seeds ([PR #140](https://github.com/Telschow/contested-nav/pull/140)) and the gate of [ADR-0028](0028-the-b1-gate.md) remain the decision tools.

## Options

1. **Keep the raw epoch count.** Nothing changes. The verdict strings keep flipping between seeds on the controls, and the bands stay narrower than the evidence supports. It is the simplest, and it keeps every published string.
2. **Use the effective sample size in both tests.** The band for the mean NEES and the Wilson interval are built on the number of independent samples the run is worth. The bands widen, so a single run rejects calibration less often and the strings stop flipping on the controls. Cost: the verdict now depends on an estimate, which is noisy and which is only an upper bound when its window is truncated. The published verdict strings change.
3. **Drop single-run verdicts and keep only the ensemble.** No noisy words remain. But a single recorded run, such as a sequence of recorded data, has no ensemble, and the tables, the golden file and the pages all carry a verdict per run. It removes a per-run diagnostic that is useful when read as description.

## Decision

A single run's verdict is formed with the effective sample size of that run's scored NEES series, n_eff, from effective_sample_size. The bulk test compares the run's mean NEES with the 95% two-sided chi-square band for n_eff x dof degrees of freedom, scaled by n_eff, with n_eff at least 1. The coverage test uses the Wilson interval on n_eff trials, with the same n_eff. The verdict word 'calibrated' becomes 'consistent', meaning the run does not reject calibration; a single run cannot establish calibration. The JSON field 'calibrated' is renamed 'consistent'. When the autocorrelation window is truncated, n_eff is an upper bound, the record carries n_eff_truncated: true, and tables mark it with a dagger. A single-run verdict is descriptive. The ensemble over seeds and the gate of ADR-0028 are the decision tools. The per-case effective sample sizes over the development seeds are published as a generated table.

## Consequences

- The verdict strings change in the published tables. The controls are expected to read `consistent` more often, and the clone rows may too. The anchor rows are expected to stay `overconfident`. These are expectations, not results.
- The prose of the pages follows the new strings. No page may call a single run calibrated on the strength of its verdict.
- Pages with recorded data carry verdicts too. The implementation package inventories them first, and handles them there.
- The implementation changes the record, the golden file and the generated tables once, in one package. Nothing is regenerated before this record is merged.
- The gate of ADR-0028 does not change. It uses its own band, built on the same effective sample size over an ensemble.
