# Roadmap

Sequenced by dependency, not by ambition. Each item names its exit test.
Status markers: `[x]` done, `[~]` in progress, `[ ]` not started, `[!]`
blocked.

Measured baseline: <!-- metric:tests_collected -->1031<!-- /metric --> tests collected and <!-- metric:coverage_percent -->93.6<!-- /metric -->% line coverage on CPython
<!-- metric:coverage_python -->3.13<!-- /metric --> (`docs/data/metrics.json`, from `scripts/metrics.py` and `scripts/coverage_report.py`). Every
number below re-measures against that, not against a remembered value.

---

## Milestone 1: Honest foundation `[x]`

### Stage 0: The project could build and read data `[x]`

- [x] Fix 6 quaternion-order defects across 4 readers and 1 writer
      (`io/trajectory.py`). TUM, Plotly and EuRoC readers all returned
      rotations of the wrong orientation; `write_tum` wrote `w x y z` into
      columns labelled `qx qy qz qw`. Each result was orthonormal, so no
      structural check caught it.
- [x] Fix `_read_rows` truncating rows to 8 columns, which made the EuRoC
      velocity branch unreachable dead code.
- [x] Fix the EuRoC velocity slice reading `a[:, 14:17]` (accelerometer bias)
      instead of `a[:, 8:11]`.
- [x] Add reader/writer tests including round trips and a check against the
      published TUM VI ATE. `io/trajectory.py` 10.6% -> 90.8%.
- [x] Add `README.md`, which `pyproject.toml` referenced but which did not
      exist, breaking the build.
- [x] Add `.gitignore`; correct the repository URLs in `pyproject.toml`.
- [x] Record invariants and measured ratchets in `CONSTRAINTS.md`.

### Stage 1: 21-state ESKF, and the zero-coverage gaps `[x]`

The error state is 21: `dtheta` (3), `dp` (3), `dv` (3), `db_g` (3), `db_a` (3),
`c_p` (3), `c_t` (3). The last two are the visual anchor (translation and
rotation offset between the last visual frame and the current body frame),
carried as filter state rather than as measurement noise, because the anchor
drifts and a fixed measurement covariance cannot say so.

- [x] Tests for `config.py` (0% -> 98.4%): schema validation, defaults,
      malformed input, unknown keys. `Config.to_yaml()` was writing `dir` at
      the top level instead of nested under `output`; fixed.
- [x] Tests for `analysis/findings.py` (0% -> 97.6%): claim record lifecycle,
      the `FACT`/`HYPOTHESIS` distinction, validation failures, report
      rendering. `render_markdown()` was discarding its body lines; fixed.
- [x] Tests for `eval/metrics.py` (17.8% -> 85.6%): `rigid_start` alignment
      semantics, association strategies, empty-input guards. `ate_bundle`
      mislabelled `rigid_start` as `rigid`; fixed.
- [x] Tests for `eval/thresholds.py` (18.1% -> 96.4%): detector hysteresis,
      false-alarm behaviour on a clean signal.
- [x] Tests for `geometry/align.py` (19.0% -> 76.6%): Umeyama, degenerate input.
- [x] Cover `EskfConfig.as_dict()` for the anchor prior and drift fields, which
      were serialised only partially. A config hash and a YAML round trip agreed
      with each other while disagreeing with the filter that ran.
- [x] Joseph-form covariance update followed by a reset, never the `(I-KH) P`
      shortcut. ADR-0002.
- [x] Commit `scripts/coverage_report.py` so the `CONSTRAINTS.md` ratchets are
      re-measurable by anyone. Its total floor now matches the 75% documented
      in `CONSTRAINTS.md`; it had been set to 44%, which made the gate weaker
      than the claim.

### Stage 2: Visual observation Jacobians, corrected `[x]`

This is the defect worth reading the rest of the repository for.

- [x] Fix the rotation and translation observation Jacobians, which were in the
      wrong frame. They read `H_theta = +I` and `H_ct = -I` where the
      conjugation identity

      ```
      rot_log(Q Exp(v) Q^T) = Q v
      ```

      requires `H_theta = R_rel_pred` and `H_ct = -R_rel_pred`: the increment
      is conjugated into the *previous body* frame, so the identity is right
      only when the inter-frame rotation is zero. The translational blocks had
      the same fault for the same reason, since `h(x) = R_prev^T (p_cur −
      p_prev)` gives `H_p = +R_prev^T` and `H_cp = -R_prev^T`.

      At 20 Hz against a smooth trajectory this moved the benchmark only in the
      third decimal, which is why review missed it. Found by finite-difference
      tests written after the fact, against central differences of the filter's
      own residual. Recorded as R1 in `CONSTRAINTS.md`.

- [x] Pin all four blocks numerically, so a frame or sign error cannot return
      quietly.

**Not done:** the 21-state reset Jacobian is covered by a positivity/symmetry
regression rather than by a numerical derivative, because the reset is a
covariance assignment rather than a differentiable map. Stated rather than
left looking finished.

### Stage 3: Reproducible experiment pipeline `[x]`

Numbers that cannot be regenerated are anecdotes. The benchmark tables were
previously produced by ad-hoc scripts that were not in the repository.

- [x] `scripts/run_benchmark.py` with `--all`, `--list` and per-case selection,
      plus `--markdown` for the published table.
- [x] `configs/benchmark.yaml` capturing every seed, noise level, outage window
      and estimator setting behind each published row.
- [x] JSON result schema with the seed recorded alongside every metric, plus a
      config hash so a result cannot be quoted without the config that made it.
- [x] Committed figures under `docs/figures/`, regenerated by a single command
      and checked for drift in CI.
- [x] Outage end-point semantics documented: `Outage.covers` is `start <= t <
      end`, so an outage ending at 20 s leaves the 20 s fix valid. Getting this
      wrong silently benchmarks a different scenario.
- [x] `scripts/check_doc_tables.py` compares every numeric cell of `README.md`
      and `docs/results.md` against the generated JSON, so "these numbers are
      generated, not typed" is a checked claim rather than a promise.
- [x] CI workflow: tests on Python 3.11/3.12/3.13, coverage ratchet, ruff lint
      and format, mypy, sdist/wheel build with a clean-env import, benchmark
      reproducibility (run twice, diff), documented-table check. Pages deploy
      workflow.

### Stage 4: Documentation and epistemic framing `[x]`

- [x] `README.md` with the motivating result and the limitation stated up front.
- [x] `CONSTRAINTS.md`, `ROADMAP.md`.
- [x] ADR-0001 (21-state anchor), ADR-0002 (Joseph covariance form), ADR-0003
      (defer the pose graph, ship visual disabled), ADR-0004 (internal
      quaternion order), ADR-0005 (chi-square FDIR, and the measured cost of
      it), ADR-0006 (NIS window monitor with adaptive covariance inflation,
      which paid that cost back).
- [x] `docs/architecture.md`, `docs/calibration.md`, the documentation site (`mkdocs.yml`).
- [x] GNSS-denial overconfidence framed explicitly as the headline *negative*
      result rather than a caveat: mean NEES 286.2 against an expected 3, 20.5%
      coverage against 99.3% expected, `vision_enabled = False` shipped as the
      default, and the failure pinned by
      `test_gnss_denial_still_over_trusts_vision_and_that_is_pinned`.
- [x] Zero-dependency runtime: NumPy, PyYAML, Matplotlib, pytest. No SciPy, no
      GTSAM, no factor-graph library, no compiled extension. Chi-square
      quantiles and the incomplete gamma function are implemented in
      `eval/statistics.py` because an unverifiable dependency is not a
      dependency.

**Exit test met:** a fresh clone runs `python scripts/run_benchmark.py` and
reproduces every published number to the displayed precision; CI fails if the
tables and the JSON disagree; a stranger can read the README, reproduce the
headline number, and understand the limitation without asking a question.

---

## Milestone 2: Phase 2 roadmap `[~]`

Three tracks. The first two are engineering against the measured defect; the
third is the documentation a programme needs and does not currently have.

### Track A: FDIR module `[~]`

Today a degraded measurement is only visible after the fact, as a NEES number
that has already been wrong. This track moves detection forward.

- [x] Innovation-based chi-square gating on the GNSS and visual innovations,
      without a SciPy dependency. ADR-0005; `fdir/gating.py` holds the
      thresholds, tabulated for the dof a navigation filter produces and exact
      or Wilson-Hilferty beyond. 87.0% covered, table checked against
      `eval/statistics.py` rather than against itself.
- [x] Per-channel fault state, exclusion after `max_consecutive_rejections`
      consecutive rejections, and recovery after `auto_recovery_count`
      consecutive accepted updates. Transitions are logged, transients are
      not. The two blocks of a relative-pose fix are gated separately, so a
      broken translation cannot be vouched for by a healthy rotation.
- [x] Explicit false-alarm trade. `alpha = 0.001`, because 0.99 confidence
      means 1% of healthy updates are rejected by definition, measured here
      at 13 of 1212. At 0.001 the same 1212 healthy fixes produce zero
      rejections and the broken configuration is still detected. Pinned by
      `test_a_clean_run_produces_zero_false_rejections` and its visual
      equivalent; a gate that rejects everything fails only these.
- [x] Exclusion rather than de-weighting. A rejected update returns before the
      Kalman gain is formed, so `P^+ = P^-`. Inflating `R` to cover a bad
      measurement is the failure ADR-0003 documents.
- [x] An innovation-consistency monitor, and the fix for the collapsed-covariance
      case it was written for (blocker B5, now R2). ADR-0006;
      `fdir/nis_monitor.py` holds a bounded per-channel window and reads a
      *trailing run* of rejections, not a count. `outage_visual` 5.059 m to
      2.541 m with rejections 51 to 5; `outage_visual_degraded_camera`
      3.339 m to 2.005 m (20% drop, key misspelled; corrected 30% measures
      1.872 m; see ADR-0006). Pinned by
      `test_adaptive_inflation_recovers_the_fixes_that_the_plain_gate_threw_away`,
      which asserts the old value as well so the regression fails on its own.
- [x] The gate widened *conditionally*, not globally. The premise is tested
      rather than assumed: relief is available only when the channel was
      actually silent, and is bounded three ways: a factor cap, a drift rate
      per second of the channel's longest single silence, and a re-gate that
      must pass with headroom. One grant per divergence episode. The sustained
      offset earns no silence, so it earns no budget: verified at 40 m and
      100 m with zero grants and no movement of the estimate.
- [!] B5's closure is not B1's. The aided case still over-trusts vision
      (NEES 286.2, 20.5% coverage) because the anchor error is still
      unmodelled, and recovering the GNSS fixes shrank the symptom without
      repairing the cause. Related side effect worth watching: the ATE column
      no longer separates this case from the honest 3.760 m control, so
      `CONSTRAINTS.md` now requires the coverage and NEES columns to be read
      alongside it.
- [ ] Per-sensor detection of multipath (elevated innovation variance without
      a mean shift), spoofing (innovation consistent but GNSS-internally
      inconsistent, e.g. against the IMU-predicted position), and sensor
      degradation (bias drift in `db_g` / `db_a` beyond its declared prior).
      Today the gate detects *implausibility*; it does not yet distinguish
      which of those three causes produced it.
- [ ] Extend `analysis/findings.py` so each detection is a typed claim with a
      measured detection rate and a measured false-alarm rate, not a
      demonstration that it fires once.

**Exit test:** on the degraded scenarios in `degrade/`, detection rate above
95% per fault type at a measured false-alarm rate of zero on the control, both
numbers reproduced by `scripts/run_benchmark.py` and checked into the docs
tables. Currently one fault type (a sustained position step, on either GNSS or
visual translation) is detected and isolated; the three causes behind it are
not yet separated. The [fault matrix](docs/faults.md) measures this and restates the
test: it is not met.

### Track B: Back-end optimisation: sliding-window pose graph `[ ]`

This is the structural fix for B1, the only genuine unknown in the project.
Everything in Milestone 1 makes the limitation reproducible and documented;
this removes it.

- [!] Blocker, unchanged: a single-anchor ESKF cannot represent correlated
      visual drift. Mean NEES 286.2 on `outage_visual`, 20.5% coverage against
      99.3% expected. Not attempted yet, because a pose graph is a piece of
      engineering rather than a patch. (The figure was 1996.5 before ADR-0006;
      the number fell because the filter began taking its own uncertainty more
      seriously, not because the anchor is now modelled correctly. See
      `CONSTRAINTS.md:B1`.)
- [ ] Decide the formulation: a factor graph over visual keyframes, a
      multi-anchor ESKF, or a loosely-coupled inertial/visual filter.
- [ ] NumPy-only implementation. S1 holds. A sliding window of keyframes with
      a periodic marginalisation is the intended shape: it bounds the growth of
      the cross-correlation terms that currently make the filter overconfident
      the longer the outage runs.
- [ ] Define "fixed" quantitatively *before* building. Proposed gate: under the
      15 s GNSS-denied scenario, mean NEES below 10 and 2-sigma coverage above
      90%, with `vision_enabled` able to default to `True`.
- [ ] Hold `vision_enabled = False` until that gate is met.
- [ ] Keep the overconfident single-anchor case in the benchmark as a control
      row after the fix lands. Deleting the number that motivated the work would
      destroy the evidence that the work mattered.

**Exit test:** NEES below 10 with vision enabled and GNSS denied, coverage above
90%, `vision_enabled = True` as the shipped default. Current value 286.2.

### Track C: TPM / PM deliverables `[~]`

The engineering is ahead of the paperwork, which is a schedule risk rather than
a technical one.

- [x] SWaP-C trade-off matrix (`docs/product_management/02_swapc_tradeoff_matrix.md`): size, weight, power, cost against accuracy, for
      the estimator configurations actually benchmarked. Computed from
      `EskfConfig` and the runtime measurements `run_benchmark.py` already
      records, not estimated.
- [x] System Requirements Specification (SRS) (`docs/product_management/01_system_requirements_spec.md`): the interface, the failure
      modes, the detection requirements from Track A, and the acceptance
      thresholds from Track B, written as testable requirements.
- [ ] Sensor synchronisation and calibration specification: the timing model
      between IMU, GNSS and camera streams; the time-offset handling; the
      intrinsic and extrinsic calibration assumptions; what is measured on the
      bench versus what is assumed in simulation.
- [x] The documents above live in `docs/product_management/`, together with the FDIR
      and spoofing strategy (`03_fdir_and_spoofing_strategy.md`). Still missing: the
      sensor synchronisation specification above, a risk log, and a work breakdown.

**Exit test:** a reviewer can trace every requirement in the SRS to a test, a
configuration, or an explicitly declared gap. The SRS has a traceability matrix
(section 2), now checked by `scripts/check_srs_trace.py` against `docs/product_management/srs_trace.csv`:
every requirement and criterion has a test, a checked configuration value or a declared gap, and the
roll-up counts follow from the verdicts. The check is structural; it does not re-measure a number.

## Phase 5 backlog

The next work is ordered by RICE score in [docs/prioritisation.md](docs/prioritisation.md). The inputs are judgements, and the page shows how stable the order is.

---

## Open blockers

`CONSTRAINTS.md` holds the authoritative list. In short:

- **B1**: visual fusion is overconfident under GNSS denial. Needs Track B.
- **B4**: full TUM VI room1 ground truth unavailable, so two tests skip and
      the ATE figure is not a verified reproduction of the published 0.069 m.

## Deliberately not planned

- Real sensor drivers, SLAM front ends, or a ROS integration. Out of scope; the
  project is an evaluation and calibration harness.
- Learned uncertainty models. Would undercut the point: the question is whether
  a classical estimator is honest about itself.
- Large vendored datasets. Breaks S2 and makes the repository unusable offline.
