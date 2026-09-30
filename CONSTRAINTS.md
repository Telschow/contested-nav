# Project constraints

Invariants this project holds itself to. Every entry is either currently true
or is a stated blocker; nothing here is aspirational. Ratchets are measured,
not estimated, and the command to re-measure each one is given.

Last measured: 601 tests collected — 597 passing, 2 skipped, 2 expected failures —
and 91.61% line coverage (3799/4147 executable lines) on **CPython 3.13**, measured
with `python scripts/coverage_report.py`. Coverage is quoted from that script alone:
it is the project's dependency-free tracer (S1 forbids adding `pytest-cov`), and
a number taken from a different tool is not comparable with the module figures
below. The interpreter is named because it is part of the measurement, not a
detail: `dis` decides what counts as an executable line, and the denominator
moves with the bytecode. The same tree and the same 597 passing tests measure
3674/4022 (91.35%) on 3.11 and 3662/4181 (87.59%) on 3.14. `coverage_report.py`
prints the interpreter it ran on, so a figure is never quoted without the one
thing needed to interpret it. Floors are unaffected by that spread — every total
clears 75% and every module floor sits well below its measured figure.
The two skips are the TUM VI reference checks in
`tests/test_trajectory_io.py`, which need ground truth that is deliberately not
vendored (S2); they are skips, not passes, and are counted separately here so the
number cannot read higher than it measures.

## Correctness

- **C1 — Quaternions are `(w, x, y, z)` internally.** TUM and Plotly files
  store `(x, y, z, w)`. Conversion happens only in `io/trajectory.py`, via
  `xyzw_to_wxyz` / `wxyz_to_xyzw`. A bare `[3, 0, 1, 2]` slice at a call site
  is a bug: the result is still unit-norm and still orthonormal.
  *Enforced by* `tests/test_trajectory_io.py`, which round-trips every format
  and checks specific known rotations.

- **C2 — A wrong-order rotation must fail loudly.** Orthonormality and
  `det == 1` are not sufficient: a permuted quaternion satisfies both. Tests
  assert known matrices, and assert ATE against published TUM VI numbers.

- **C3 — Poses are `T_wb`.** Body frame in world frame, everywhere. No
  inverted convention anywhere in the codebase.

- **C4 — Covariance updates must preserve positive semidefiniteness.** The
  ESKF uses the Joseph form
  `G @ (I-KH) P (I-KH)^T + K R K^T` followed by reset, never the
  `(I-KH) P` shortcut. *Enforced by*
  `test_covariance_stays_positive_semidefinite_across_a_visual_run`.

- **C5 — No fabricated or extrapolated results.** Every number in README.md
  and `docs/` is reproducible from a committed config and a fixed seed via
  `scripts/run_benchmark.py`. Claims are labelled `FACT`, `MEASUREMENT`,
  `INTERPRETATION`, or `HYPOTHESIS` (`analysis/findings.py`).

- **C6 — Synthetic results are never presented as real-sensor performance.**
  The synthetic suite isolates estimator structure; it says nothing about a
  real IMU, a real camera, or a real outage.

## Scope

- **S1 — Pure Python + NumPy is the runtime.** Matplotlib for figures, PyYAML
  for configs. No SciPy, GTSAM, `evo`, C++/CMake, neural networks, or cloud
  services. Chi-square quantiles are implemented in `eval/statistics.py`
  because the alternative is an unverifiable dependency.

- **S2 — No third-party data is vendored.** Fetch locally; commit seeded
  configs and frozen figures instead.

- **S3 — `vision_enabled` stays `False` by default** until the
  GNSS-denial limitation below is resolved. Shipping a confidently-wrong
  filter is worse than shipping no visual fusion.

- **S4 — MIT.** No CLA. No employer or defence-sector framing in any public
  artefact.

## Quality ratchets

These are floors, not goals. Each must not regress; raising one is welcome.

| Ratchet | Floor | Current (CPython 3.13) | Re-measure with |
|---|---:|---:|---|
| Tests collected | 405 | 601 | `pytest` |
| Tests passing | 300 | 597 (2 skipped, 2 xfail, see below) | `pytest -rs` |
| Line coverage | 75% | 91.61% | `scripts/coverage_report.py` |
| `io/trajectory.py` coverage | 85% | 95.0% | as above |
| `analysis/findings.py` coverage | 80% | 99.7% | as above |
| `config.py` coverage | 80% | 98.4% | as above |
| `eval/metrics.py` coverage | 60% | 95.7% | as above |
| `eval/thresholds.py` coverage | 60% | 100.0% | as above |
| `geometry/align.py` coverage | 60% | 92.2% | as above |
| `estimators/eskf.py` coverage | 80% | 97.2% | as above |
| `fdir/gating.py` coverage | 70% | 89.5% | as above |
| `fdir/fdir_manager.py` coverage | 70% | 98.8% | as above |
| `fdir/nis_monitor.py` coverage | 80% | 98.8% | as above |
| `degrade/` coverage | 50% | 78.0% (`config.py`) / 84.2% (`inject.py`) | as above |
| Docs | README + architecture + calibration + ADR-0001..0008 | 8 of 8 docs | manual |
| Documented tables match the generated benchmark | exact | yes | `scripts/check_doc_tables.py` |
| Open blockers documented | all | see ROADMAP | manual |

## Known blockers

- **B1 — Visual fusion is overconfident under GNSS denial.** Mean NEES 419.4
  over a 15 s outage (`outage_visual`), with 20.0% of epochs inside 2 sigma
  against 99.3% expected. A single anchor cannot represent correlated visual
  drift. Requires a pose graph. Pinned by
  `test_gnss_denial_still_over_trusts_vision_and_that_is_pinned`. B2 did not
  change this number, and neither did ADR-0006: correcting a frame is not the
  same as modelling correlated error, and re-admitting the GNSS fixes that B5
  caused to be discarded shrank the error without repairing the model that made
  `P` wrong. The number fell from 1996.5 to 419.4 as a side effect of taking the
  filter's own uncertainty more seriously, not because the anchor is now
  modelled correctly.

- **B2 — No lint or typecheck gate has ever run locally.** `ruff` and `mypy`
  are not installed in the working environment, so no style or type error is
  caught outside the test run. CI installs them and runs both; see ROADMAP.

- **B3 — Package build is unverified locally.** `pip` and `setuptools` are
  absent here, so `pyproject.toml` metadata and the Hatchling build path have
  never been executed, only reasoned about. CI builds an sdist and a wheel and
  imports the wheel in a clean environment; see ROADMAP.

- **B4 — Full TUM VI room1 ground truth is unavailable.** The published
  mocap trajectory was not obtained, so the ATE comparison uses a subsampled
  Plotly ground truth and the ATE figure is not a verified reproduction of the
  published 0.069 m. The claim is typed accordingly. This is also why two tests
  skip when the data is absent.

## Resolved engineering blockers

Kept here rather than deleted, because the reason each defect was invisible is
the useful part. A defect that runs, fuses, and is wrong without raising is not
found by review; it is found by a test that differentiates the filter's own
residual numerically.

- **R1 (was B2) — Rotation Jacobians were in the wrong frame.** `H_theta` and
  `H_ct` were `+I` and `-I` rather than `R_rel_pred` and `-R_rel_pred`.

  The residual is `rot_log(R_rel_meas · Exp(dtheta) · R_rel_predᵀ)`. By the
  conjugation identity `rot_log(Q Exp(v) Qᵀ) = Q v`, that equals
  `R_rel_pred · dtheta`, not `dtheta`. The increment is conjugated into the
  previous body frame, so the identity is correct only when the inter-frame
  rotation is zero — which it is not in general, only in the trivial case. The
  translational pair was wrong in the same way for the same reason:
  `h(x) = R_prevᵀ (p_cur − p_prev)` so `∂h/∂p = +R_prevᵀ`, not `−R_prevᵀ`.

  The four blocks are therefore:

  | Block | Value | Frame |
  |---|---|---|
  | `H_theta` | `R_rel_pred` | previous body |
  | `H_ct` | `-R_rel_pred` | previous body |
  | `H_p` | `R_prevᵀ` | previous body |
  | `H_cp` | `-R_prevᵀ` | previous body |

  At 20 Hz against a smooth trajectory the error moved the benchmark only in the
  third decimal, which is why it survived review. Pinned by central
  differences of the filter's own residual in `tests/test_estimators.py`
  (`test_attitude_jacobian_is_the_exact_derivative`,
  `test_anchor_attitude_jacobian_is_the_exact_derivative`,
  `test_position_jacobian_is_the_exact_derivative`,
  `test_translation_anchor_jacobian_is_the_exact_derivative`). B1 is unchanged
  by this fix.

- **R2 (was B5) — The FDIR gate's premise did not hold in the configurations
  this project exists to study.** A chi-square test on the innovation assumes a
  calibrated `S = H P Hᵀ + R`. When the position covariance has collapsed
  (ADR-0001) `S` is far too small, so the gate rejected *healthy* measurements
  systematically rather than at the stated `alpha`: 51 of 75 GNSS fixes in
  `outage_visual`, degrading that case from 3.428 m to 5.059 m. Widening the
  gate would have fixed it and lost the false-alarm rate ADR-0005 exists to
  provide.

  Fixed by ADR-0006: a per-channel NIS window monitor and a bounded adaptive
  covariance inflation, applied only when the channel was actually silent. The
  distinction that makes it decidable is the silence, not the size of the
  innovation — silence comes from the filter's own state and needs no
  assumption about the threat model, and a channel streaming at 5 Hz earns no
  drift budget however long the attack runs.

  Measured: `outage_visual` 5.059 m to 2.541 m, 51 rejections to 5, mean NEES
  1996.5 to 419.4. `outage_visual_degraded_camera` 3.339 m to 2.005 m, 931.4
  to 264.8 (20% drop; the config key was misspelled, see ADR-0006 correction).
  Re-measured at the intended 30%: 1.872 m and 216.6. Pinned by
  `test_adaptive_inflation_recovers_the_fixes_that_the_plain_gate_threw_away`,
  which asserts the improvement *and* the old value, so a regression to it
  fails even while the new assertions pass.

  Two limits, both stated in the ADR rather than left to the reader:

  - **This is not calibration.** 2.541 m of error against 0.161 m claimed is
    still overconfident. B1 is untouched and remains the open blocker. What is
    closed is the filter's refusal to hear a working sensor, not the modelled
    visual anchor error that made the covariance wrong.
  - **The ATE column stopped being an accidental honesty check.** Before this
    fix the dishonest aided case was also the more inaccurate one, so sorting
    by error happened to separate them. Recovering the error put the dishonest
    filter back on top of the table, and `outage_visual` now reports a
    *lower* ATE than the honest 3.782 m control while being less calibrated.
    Any comparison in this repository must read the coverage and NEES columns
    too, and a table sorted on ATE alone is not evidence of a good filter.

  Original text, kept for the record:

> - **B5 — The FDIR gate's premise does not hold in the configurations this
>   project exists to study.** A chi-square test on the innovation assumes a
>   calibrated `S = H P Hᵀ + R`. When the position covariance has collapsed
>   (ADR-0001) `S` is far too small, so the gate rejects *healthy* measurements
>   systematically rather than at the stated `alpha`.
>
>   Measured, not estimated: in `outage_visual` the GNSS fixes that return at
>   `t = 20 s` after the 15 s denial are metres from a filter that believes it
>   knows its position to centimetres, and FDIR rejects 51 of the 75 available.
>   The case degrades from 3.428 m to 5.059 m, and `outage_visual_degraded_camera`
>   from 2.545 m to 3.339 m. The false-alarm rate of 0/1212 quoted for `alpha =
>   0.001` is measured on a *calibrated* filter and does not transfer.
>
>   This is a cost, accepted rather than hidden, and it is why the numbers in
>   the docs tables are the degraded ones. Pinned by
>   `test_fdir_throws_away_the_absolute_fixes_that_would_rescue_a_displaced_filter`,
>   which asserts the direction it happened. The fix is an
>   innovation-consistency monitor that detects the under-estimated `S` and
>   widens the gate when the chi-square premise is void; tracked in `ROADMAP.md`
>   Track A. It is deliberately not implemented here: a consistency monitor that
>   also responds to a genuine spoof has to be told the two apart, and that
>   distinction is a larger design question than the gate itself.

## Adding a constraint

Add it above with a stable id, a statement that is true or explicitly a
blocker, and how it is enforced. If it cannot be enforced, it is a wish, and
belongs in `ROADMAP.md` instead.
