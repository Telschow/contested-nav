# Changelog

All notable changes to this project. Entries are grouped by kind, and the kind
is part of the point: a reader asking "did the estimator change?" should not
have to read a formatting commit to find out.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `read_euroc_imu` raised `AttributeError` on every call. `_NUM` was declared as
  a plain string and invoked with `.fullmatch()`, so no row was ever read. The
  documented "run this against EuRoC" path had therefore never executed.
- The nanosecond-detection heuristic in `read_euroc_imu` inspected only the
  first sample, so a stream beginning near `t=0` was read as seconds and a 20 s
  recording became a 20-billion-second one. The decision now uses the maximum
  timestamp.
- `align_trajectory` was annotated as returning `np.ndarray` for its reference,
  but the only caller needs `ref.metadata["index"]`. It returns a `Trajectory`;
  the annotation was wrong.
- Four `pytest.raises(match=...)` patterns in `tests/test_config.py` contained
  unescaped `.`, so `dataset.kind` also matched `datasetXkind`.

### Security

- `opencode.json` is now ignored. It sits at the repository root and holds a
  provider API key; the previous rule covered only `.opencode/`, so the file was
  stageable and a plain `git add .` would have committed a live credential. The
  key was never committed, so no history rewrite is needed. Rotation is still
  owed by its owner.
- CI runs with `contents: read` by default, with only the CodeQL job granted
  `security-events: write` for its upload.
- Added CodeQL analysis for Python on push, pull request, and weekly.
- Added Dependabot for GitHub Actions and pip, grouped so a transitive bump does
  not open a pull request per package.
- Added `SECURITY.md` with a reporting path and a scope that distinguishes a
  silent numerical fault from a documented estimator failure.

### Engineering

- The lint gate is green for the first time. `ruff check` with no configuration
  selected whatever ruff's defaults were that month, and the count went from 14
  to 131 across one upstream release with no change to this repository -- and
  since the `build` job depends on `lint`, packaging was unverified in CI as a
  result. The rule set is now declared in `pyproject.toml` with reasons for
  each exclusion, and `ruff`/`mypy` are pinned so CI and a local checkout
  resolve the same versions.
- `ruff format` applied across 32 files, in a commit of its own so the
  behavioural changes above stay reviewable.
- `FilterState` replaces `dict[str, np.ndarray]` on the ESKF state. That
  annotation was wrong in both directions -- it forbade the two integers, the
  boolean, and the `None` the state genuinely holds. With it in place, the three
  mypy error codes that were disabled in `pyproject.toml` are no longer
  suppressed, and mypy reports no issues.
- `zip(..., strict=True)` at four sites pairing an estimate against its
  reference. A length mismatch there silently truncates and yields plausible
  wrong numbers, so the failure is now loud. The benchmark output is
  bit-identical before and after.
- Duplicate `STATUS_REJECTED_PERSISTENT` import removed from
  `navkit.fdir`; `__all__` had 22 entries for 21 unique names.
- `ClaimType` is a `StrEnum`. Verified first that the only consumer renders
  `.value`, which is identical under both, and that comparison and JSON
  serialisation are unchanged.
- `uv.lock` is committed, so a fresh clone resolves the same versions.
- `python_version` for mypy is 3.13, matching the interpreter the CI lint job
  uses. At the declared minimum of 3.11, mypy rejected numpy's own stubs and
  could not check the code it was written to check.
- CI now verifies that `seed_sweep.py` and `scene_sweep.py` are reproducible
  across runs, at three seeds.
- Added `CONTRIBUTING.md`, including the five local gates and the conventions
  the project holds to (no `# noqa`, no mypy suppression, no hand-typed
  numbers).

### Testing

- Added `tests/test_imu_io.py` (10 tests). The loader it covers had no test at
  all, which is why two independent defects survived in it. Both were confirmed
  to fail the new tests when reverted.
- Added `tests/test_scene_sweep.py` (10 tests) and
  `tests/test_scene_sweep_harness.py` (14 tests).
- `test_sweep_payload_is_labelled_synthetic` asserted `X or True`, so it was
  permanently true and verified nothing -- while nominally guarding the
  constraint that stops a synthetic sweep being quoted as real-sensor
  performance. Both needles were also wrong, so a corrected version would still
  have failed.
- Claim lookups in `tests/test_findings.py` and event lookups in
  `tests/test_thresholds_and_injection.py` indexed with `[0]` or called
  `next()`. Both pass when a duplicate is emitted, which is the duplication
  those assertions exist to catch. Both now assert exactly one match.
- Suite: 563 passed, 2 skipped, 2 xfailed before this release; 597 passed, 2
  skipped, 2 xfailed after. Coverage 86.58% to 87.59%.

### Research

- Added a multi-scene sweep. The existing seed sweep varies *sensor noise* with
  the trajectory pinned to one scene, so a result that was really an artefact of
  that path was indistinguishable from a property of the estimator. This was the
  largest threat to the headline claim and was untested.
- `synthetic.seeded_scene` varies the motion parameters -- radius, turning rate,
  sway, roll -- by a log-uniform multiplier, preserving the exact `t=0` initial
  state that makes the fixture a known-answer test, and leaving duration and rate
  untouched so swept results stay comparable to the published ones.
- `scene_sweep.py` reports bootstrap confidence intervals rather than a standard
  deviation over 8 draws, and reports `verdict_stable` per case with its counts,
  so a split verdict cannot be averaged away.
- `run_benchmark.py` gained `--scene-seed`, an axis independent of `--seed`.

  Result over 8 scenes, noise held fixed:

  | Case | NEES mean (95% CI) | Coverage @2σ | Verdict |
  |---|---|---|---|
  | `gnss_only` | 3.7 [3.7, 3.8] | 100.0% | mixed, stable |
  | `outage_control` | 4.1 [4.0, 4.1] | 100.0% | mixed, stable |
  | `outage_visual` | 419.7 [414.4, 424.9] | 20.0% | overconfident, 8/8 |
  | `vision_anchor_in_measurement_noise` | 383.7 [380.8, 387.4] | 16.1% | overconfident, 8/8 |
  | `vision_only` | 327.9 [316.6, 341.2] | 0.7% | overconfident, 8/8 |
  | `outage_visual_degraded_camera` | 223.5 [217.9, 230.5] | 19.7% | overconfident, 8/8 |

  Path length varies 2-3x across the scenes and every verdict is unanimous, with
  both controls staying calibrated. The overconfidence is therefore a property of
  the filter rather than of one trajectory. This does not address external
  validity: it remains a synthetic known-answer fixture.

### Documentation

- Added a prioritized implementation plan (`docs/IMPLEMENTATION_PLAN.md`) with
  P0-P4 classification and the reasoning for deferring each deferred item.
- Added the audit baseline: `PROJECT_STATE.md`, `REPOSITORY_MAP.md`,
  `ENGINEERING_BASELINE.md`, `ML_BASELINE.md`, `RESEARCH_BASELINE.md`,
  `PUBLICATION_READINESS.md`.
- Corrected 16 GitHub URLs from a non-existent `contested-nav/contested-nav`
  organisation to `Telschow/contested-nav`, so the badges resolve.

### Breaking

- None. No public API changed, no published number changed, and the benchmark
  output is bit-identical to the previous release once the new `scene_seed`
  provenance key is accounted for.

## [0.1.0] and earlier

Commits `c81c6f9`, `5d83216`, `4fa780b`, `466ab48` and their ancestors. No
changelog was kept; see `git log` and `docs/audit/`.
