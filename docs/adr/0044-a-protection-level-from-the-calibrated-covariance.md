# ADR-0044: A protection level from the calibrated covariance

- Status: proposed
- Date: 2026-11
- Related: [ADR-0035](0035-the-integrity-status-record.md), [ADR-0040](0040-staleness-of-the-nis-windows.md), [calibration](../calibration.md), [issue #118](https://github.com/Telschow/contested-nav/issues/118)

This record has its context and options. The decision section is the maintainer's to write. No code is written until it is.

## Context

**What exists today. FACT, checked in the code.** The integrity status record carries `sigma_h` and `sigma_v`, the NIS state and a `usable` flag (ADR-0035, schema version 1). `conformal_radius` in `navkit.eval.calibration` gives a finite-sample bound on the normalised error. It holds only for data exchangeable with its calibration set, and `shift_sensitivity` measures how far the realised coverage falls under a change of distribution. The consistency tests with an ensemble NEES and an effective sample size (issue #112, closed) are in place. There is no protection level anywhere in `src`.

**What the issue asks.** Turn the claimed covariance, and the conformal radius, into a horizontal bound and report how often the error exceeds it, per scenario, labelled synthetic where it is.

**Why it needs a decision.**

- Within one run, epochs are autocorrelated, so they are not exchangeable. The conformal bound has the same independence problem as the consistency tests. The effective sample size says how much that matters.
- "Protection level" is a term from certified aviation integrity. This repository is not a navigation product and makes no integrity claim. The name can read as one.
- Putting a bound in the integrity record changes it, which ADR-0035 says needs a new schema version and a new ADR. ADR-0040 may do the same.
- The filter is overconfident in some cases. On Deep-Urban-1 the imposed outages end with an error above the claimed bound for the middle and long outages (one sequence, one receiver, reference error unknown). A bound derived from that covariance would be exceeded in exactly those cases. That is a result the study should show, not hide.

## Options

(a) Do not add a protection level. `sigma_h` stays the only bound. Cost: none. The question of how often the claimed bound is exceeded stays answerable only through NEES and 2-sigma coverage.

(b) A Gaussian-scaled bound. A multiple of the claimed horizontal sigma, with the multiple taken from the chi-square distribution at a declared miss probability. Simple, and inherits every error of the covariance.

(c) A conformal bound. The calibrated radius times the claimed sigma, with the calibration set and the level declared. It carries the exchangeability caveat, which `shift_sensitivity` can measure.

(d) Both (b) and (c), reported side by side with the exceedance rate per scenario. The bound is a study output only, not a field in the integrity record. Cost: one study, one CSV, one page section.

(e) Option (d) and a field in the integrity record, as schema version 2. Cost: a schema change, possibly together with ADR-0040.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision. If (b), (c), (d) or (e) is chosen:

- The miss probability, the calibration set and the scenarios are declared before any run. Development seeds only.
- The exceedance rate per scenario is generated and checked in CI, labelled synthetic where it is.
- The name is chosen to avoid implying certified integrity, and the page says the repository makes no such claim.
- Every number on the page is stated for the scenarios it was measured on. The conformal bound is not carried over to a different distribution without the shift measurement.
- No runtime dependency changes.
