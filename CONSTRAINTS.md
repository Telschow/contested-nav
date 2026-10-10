# Project constraints

Invariants this project holds itself to. Every entry is either currently true
or is a stated blocker; nothing here is aspirational. Ratchets are measured,
not estimated, and the command to re-measure each one is given.

Last measured: <!-- metric:tests_collected -->1212<!-- /metric --> tests collected, all of which pass except the deliberate
xfails and the skips that `pytest -rs` lists, and <!-- metric:coverage_percent -->93.9<!-- /metric -->%
line coverage (<!-- metric:coverage_lines_hit -->8421<!-- /metric -->/<!-- metric:coverage_lines_total -->8971<!-- /metric --> executable lines) on **CPython <!-- metric:coverage_python -->3.13<!-- /metric -->**, measured
with `python scripts/coverage_report.py`. The figures come from `docs/data/metrics.json`, which `scripts/metrics.py` checks in CI. Coverage is quoted from that script alone:
it is the project's dependency-free tracer (S1 forbids adding `pytest-cov`), and
a number taken from a different tool is not comparable with the module figures
below. The interpreter is named because it is part of the measurement, not a
detail: `dis` decides what counts as an executable line, and the denominator
moves with the bytecode. An earlier revision of this tree measured
3690/4037 (91.40%) on 3.11 and 3678/4196 (87.65%) on 3.14 (not re-measured since). `coverage_report.py`
prints the interpreter it ran on, so a figure is never quoted without the one
thing needed to interpret it. Floors are unaffected by that spread: every total
clears 75% and every module floor sits well below its measured figure.
Two skips are the TUM VI reference checks in
`tests/test_trajectory_io.py`, which need ground truth that is deliberately not
vendored (S2). The third is `tests/test_doc_tables.py`, which needs the generated,
gitignored `results/benchmark.json`; the CI `benchmark` job runs the same check with
`scripts/check_doc_tables.py`. They are skips, not passes, and are counted separately
here so the number cannot read higher than it measures.

## Correctness

- **C1: Quaternions are `(w, x, y, z)` internally.** TUM and Plotly files
  store `(x, y, z, w)`. Conversion happens only in `io/trajectory.py`, via
  `xyzw_to_wxyz` / `wxyz_to_xyzw`. A bare `[3, 0, 1, 2]` slice at a call site
  is a bug: the result is still unit-norm and still orthonormal.
  *Enforced by* `tests/test_trajectory_io.py`, which round-trips every format
  and checks specific known rotations.

- **C2: A wrong-order rotation must fail loudly.** Orthonormality and
  `det == 1` are not sufficient: a permuted quaternion satisfies both. Tests
  assert known matrices, and assert that the ground-truth attitude rate matches the recorded gyroscope.

- **C3: Poses are `T_wb`.** Body frame in world frame, everywhere. No
  inverted convention anywhere in the codebase.

- **C4: Covariance updates must preserve positive semidefiniteness.** The
  ESKF uses the Joseph form
  `G @ (I-KH) P (I-KH)^T + K R K^T` followed by reset, never the
  `(I-KH) P` shortcut. *Enforced by*
  `test_covariance_stays_positive_semidefinite_across_a_visual_run`.

- **C5: No fabricated or extrapolated results.** Every number in README.md
  and `docs/` is reproducible from a committed config and a fixed seed via
  `scripts/run_benchmark.py`. Claims are labelled `FACT`, `MEASUREMENT`,
  `INTERPRETATION`, or `HYPOTHESIS` (`analysis/findings.py`).

- **C6: Synthetic results are never presented as real-sensor performance.**
  The synthetic suite isolates estimator structure; it says nothing about a
  real IMU, a real camera, or a real outage.

## Scope

- **S1: Pure Python + NumPy is the runtime.** Matplotlib for figures, PyYAML
  for configs. No SciPy, GTSAM, `evo`, C++/CMake, neural networks, or cloud
  services. Chi-square quantiles are implemented in `eval/statistics.py`
  because the alternative is an unverifiable dependency.
  S1 constrains the runtime (`[project] dependencies`). Test-only tools in
  `[project.optional-dependencies] dev` are allowed when they add no runtime
  import: pytest, Hypothesis for property tests, ruff and mypy.

- **S2: No third-party data is vendored.** Fetch locally; commit seeded
  configs and frozen figures instead.

- **S3: `vision_enabled` stays `False` by default** until the
  GNSS-denial limitation below is resolved. Shipping a confidently-wrong
  filter is worse than shipping no visual fusion.

- **S4: MIT.** No CLA. No employer framing in any public artefact. Defense
  relevance is discussed only in `docs/defense/`, which is unclassified,
  source-cited and generic: no real platform, weapon, operational tactic or
  export-controlled detail. The README links to it rather than restating it.

## Quality ratchets

These are floors, not goals. Each must not regress; raising one is welcome.

| Ratchet | Floor | Current (CPython 3.13) | Re-measure with |
|---|---:|---:|---|
| Tests collected | 405 | <!-- metric:tests_collected -->1212<!-- /metric --> | `pytest`, `scripts/metrics.py --check` |
| Tests passing | 300 | all collected, except the deliberate xfails and the listed skips | `pytest -rs` |
| Line coverage | 75% | <!-- metric:coverage_percent -->93.9<!-- /metric -->% | `scripts/coverage_report.py`, `scripts/metrics.py --check-coverage` |
| `io/trajectory.py` coverage | 85% | 95.0% | as above |
| `analysis/findings.py` coverage | 80% | 99.7% | as above |
| `config.py` coverage | 80% | 98.4% | as above |
| `eval/metrics.py` coverage | 60% | 95.7% | as above |
| `eval/thresholds.py` coverage | 60% | 100.0% | as above |
| `geometry/align.py` coverage | 60% | 92.2% | as above |
| `estimators/eskf.py` coverage | 80% | 97.2% | as above |
| `fdir/gating.py` coverage | 70% | 89.5% | as above |
| `fdir/fdir_manager.py` coverage | 70% | 98.5% | as above |
| `fdir/config.py` coverage | 70% | 100.0% | as above |
| `fdir/records.py` coverage | 70% | 99.2% | as above |
| `hero.py` coverage | 80% | 100.0% | as above |
| `seed_sweep.py` coverage | 75% | 87.0% | as above |
| `scene_sweep.py` coverage | 80% | 97.4% | as above |
| `figures.py` coverage | 70% | 86.0% | as above |
| `outage_sweep.py` coverage | 80% | 98.4% | as above |
| `fdir/nis_monitor.py` coverage | 80% | 98.8% | as above |
| `degrade/` coverage | 50% | 78.0% (`config.py`) / 84.2% (`inject.py`) | as above |
| Docs | README + architecture + calibration + every ADR | <!-- metric:adr_count -->20<!-- /metric --> ADRs, all in the index | `scripts/metrics.py --check` |
| Documented tables match the generated benchmark | exact | yes | `scripts/check_doc_tables.py` |
| Open blockers documented | all | see ROADMAP | manual |

## Known blockers

- **B1: Visual fusion is overconfident under GNSS denial.** Mean NEES 286.2
  over a 15 s outage (`outage_visual`), with 20.5% of epochs inside 2 sigma
  against 99.3% expected. A single anchor cannot represent correlated visual
  drift. Requires a pose graph. Pinned by
  `test_gnss_denial_still_over_trusts_vision_and_that_is_pinned`. B2 did not
  change this number, and neither did ADR-0006: correcting a frame is not the
  same as modelling correlated error, and re-admitting the GNSS fixes that B5
  caused to be discarded shrank the error without repairing the model that made
  `P` wrong. The number fell from 1996.5 to 419.4 as a side effect of taking the
  filter's own uncertainty more seriously, not because the anchor is now
  modelled correctly.

  Spike result ([ADR-0017](docs/adr/0017-stochastic-clone-for-the-visual-update.md), accepted): carrying the
  previous pose as a stochastic clone (`vision_model: clone`) meets the gate on the synthetic fixture. The
  `outage_visual_clone` row is calibrated where `outage_visual` is not, across the seed, trajectory and outage
  sweeps. The default stays `anchor`, `vision_enabled` stays `False`, and this blocker stays open for the
  shipped configuration. The decision (ADR-0017): the clone stays opt-in, because it is calibrated for a front end
  with independent errors and not for a correlated one, and no data here says which a real front end is. Reconsider
  when a front end's error correlation is measured. The single-anchor rows remain as the control.

## Resolved engineering blockers

Kept here rather than deleted, because the reason each defect was invisible is
the useful part. A defect that runs, fuses, and is wrong without raising is not
found by review; it is found by a test that differentiates the filter's own
residual numerically.

- **R1 (was B2): Rotation Jacobians were in the wrong frame.** `H_theta` and
  `H_ct` were `+I` and `-I` rather than `R_rel_pred` and `-R_rel_pred`.

  The residual is `rot_log(R_rel_meas · Exp(dtheta) · R_rel_predᵀ)`. By the
  conjugation identity `rot_log(Q Exp(v) Qᵀ) = Q v`, that equals
  `R_rel_pred · dtheta`, not `dtheta`. The increment is conjugated into the
  previous body frame, so the identity is correct only when the inter-frame
  rotation is zero, which it is not in general, only in the trivial case. The
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

- **R2 (was B5): The FDIR gate's premise did not hold in the configurations
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
  innovation: silence comes from the filter's own state and needs no
  assumption about the threat model, and a channel streaming at 5 Hz earns no
  drift budget however long the attack runs.

  Measured: `outage_visual` 5.059 m to 2.541 m, 51 rejections to 5, mean NEES
  1996.5 to 419.4. `outage_visual_degraded_camera` 3.339 m to 2.005 m, 931.4
  to 264.8 (20% drop; the config key was misspelled, see ADR-0006 correction).
  Re-measured at the intended 30%: 2.008 m and 203.7. Pinned by
  `test_adaptive_inflation_recovers_the_fixes_that_the_plain_gate_threw_away`,
  which asserts the improvement *and* the old value, so a regression to it
  fails even while the new assertions pass.

  Two limits, both stated in the ADR rather than left to the reader:

  - **This is not calibration.** 2.322 m of error against 0.162 m claimed is
    still overconfident. B1 is untouched and remains the open blocker. What is
    closed is the filter's refusal to hear a working sensor, not the modelled
    visual anchor error that made the covariance wrong.
  - **The ATE column stopped being an accidental honesty check.** Before this
    fix the dishonest aided case was also the more inaccurate one, so sorting
    by error happened to separate them. Recovering the error put the dishonest
    filter back on top of the table, and `outage_visual` now reports a
    *lower* ATE than the honest 3.760 m control while being less calibrated.
    Any comparison in this repository must read the coverage and NEES columns
    too, and a table sorted on ATE alone is not evidence of a good filter.

  Original text, kept for the record:

> - **B5: The FDIR gate's premise does not hold in the configurations this
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

- **R3 (was an open "B2", not R1's B2): no lint or typecheck gate had run
  locally.** `ruff` and `mypy` are now pinned in the `dev` extra
  (`pyproject.toml`), so `pip install -e ".[dev]"` provides both. Verified
  2026-10-06 in a clean virtual environment: `mypy src --ignore-missing-imports`
  reports no issues in 29 source files, and `ruff check` and `ruff format --check`
  pass once the findings in `scripts/generate_demo.py` are cleared.

- **R4 (was the open B3): package build was unverified locally.** Verified
  2026-10-06: `python -m build` produced an sdist and a wheel, and the wheel
  installed and imported in a second clean virtual environment. CI repeats this in
  the `build` job.

- **R5 (was B4): the published TUM VI estimate was unavailable.** Two tests compared a published Basalt estimate
  of room1 with a subsampled ground truth, and neither file could be fetched, so both always skipped. The claim of
  a reproduction of the published 0.069 m is retired. Its purpose, a check that fails loudly on a wrong quaternion
  order, is served by `tests/test_recorded_orientation.py`: the ground-truth attitude rate must match the recorded
  gyroscope, and a mis-ordered quaternion must not. It always runs on a synthetic sequence and runs on every
  fetched EuRoC and TUM VI sequence. The TUM VI paper lists 0.09 m for Basalt on room1, a different figure from
  0.069 m, and nobody checked why.

## Adding a constraint

Add it above with a stable id, a statement that is true or explicitly a
blocker, and how it is enforced. If it cannot be enforced, it is a wish, and
belongs in `ROADMAP.md` instead.
