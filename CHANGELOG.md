# Changelog

All notable changes to this project. Entries are grouped by kind, and the kind
is part of the point: a reader asking "did the estimator change?" should not
have to read a formatting commit to find out.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- `navkit euroc`: `fetch`, `run` and `selftest`. `fetch` reads only the IMU and ground-truth files of an
  EuRoC sequence out of the Research Collection archives, by HTTP byte range, retrying on 429 with the
  server's `Retry-After`, and writes a `MANIFEST.json` with the SHA-256 of every file. `run` feeds the recorded
  IMU to the filter, simulates GNSS from the ground truth, optionally cuts outages, and scores the run with the
  same ATE, NEES and coverage code as the benchmark. `selftest` runs the whole path on a synthetic sequence in
  the EuRoC layout. Results are labelled `real_imu_simulated_gnss`. No result from real data is quoted in the
  README or the docs. See [ADR-0013](docs/adr/0013-recorded-imu-with-simulated-gnss.md), accepted.
- `ErrorStateKalmanFilter.run(..., initial=InitialState(...))`: start from a given pose, velocity and biases
  instead of the origin at rest. The default is unchanged.
- `navkit euroc run --preset adis16448`: scales the filter's assumed IMU noise by 3 and declares a 0.05 initial
  bias 1-sigma. Chosen on MH_01_easy and checked on the other ten EuRoC sequences (Machine Hall and Vicon
  rooms); a few runs on MH_04, MH_05 and V1_01 still lose GNSS after an outage. Explicit `--noise-scale` and `--bias-sigma` override it. It is a tuning for this sensor, not a filter
  property.
- `navkit euroc compare`: runs the default, the `adis16448` preset and optionally the `legacy` form over every
  fetched EuRoC sequence, one 20 s GNSS outage at a time, and counts the runs that lose GNSS (more than a fifth
  of the fixes rejected). It writes one CSV row per run and a JSON record with the input hashes from the fetch
  manifest, and prints a summary table. The FDIR "faulted" flag is reported next to the count and not used for
  it, since it misses some losses. This is how the statements in ADR-0014 are regenerated.
- `navkit euroc run --preset adis16448-walk` and `--bias-walk-scale`: the second preset leaves the white noise as
  the sensor file gives it and scales only the two bias random walks by 10, with the same bias prior.
  `navkit euroc compare` gains `--first-seed` and a `walk10` configuration, and fills a second page block
  with `--block euroc-validation`. See the follow-up in
  [ADR-0014](docs/adr/0014-textbook-imu-process-noise-by-default.md).
- `navkit sweep attribution` and [`docs/attribution.md`](docs/attribution.md) (P5-06): the falsification experiments the
  research baseline listed and never ran, plus the bias-fault question from limitation L8. On the synthetic fixture,
  removing every inertial error source leaves the peak outage error within two percent, the error grows with the
  same exponent with or without them, and what dominates is the state error the filter has when GNSS is lost (making
  the start exact cuts it by about nine tenths). A source has to be about thirty to a hundred times the unit's before
  it matters. A small or moderate accelerometer bias fault is not noticed; a large one makes the filter reject the
  healthy GNSS on its return and declare it faulty, the lockout behind the lost runs on the recordings.
  `run_case` gains an `imu_hook`, and the benchmark runner accepts the initial-uncertainty keys.
- `navkit euroc timing` and `docs/product_management/04_sensor_sync_and_calibration_spec.md` (P5-07): the timing
  model, the calibration assumptions, and what is measured on the recordings versus assumed in simulation. The tool
  reports each sequence's timestamp regularity, the share of the ground truth lost to dropouts, and the offset
  between the ground truth and the IMU, from the angular rate (a vector comparison that removes gyroscope bias, with a
  magnitude comparison as a cross-check). On the 17 sequences the offsets are within a few milliseconds, far below
  the simulated GNSS noise; the TUM VI motion capture has dropouts of up to a few seconds, which the TUM VI page now
  states. The table is generated from `docs/data/timing.csv` and a test checks it and six statements.
- `navkit tumvi fetch` and `--dataset tumvi` on `navkit euroc run` and `navkit euroc compare`: TUM VI room
  sequences (CC BY 4.0, [ADR-0016](docs/adr/0016-tum-vi-as-a-second-recorded-dataset.md), accepted). The archives
  are whole TARs, so the fetcher downloads them (resuming a partial file), checks the publisher's MD5, keeps the
  IMU, motion-capture and noise files, and deletes the archive. The ground truth has no velocity or bias, so the
  start velocity is a local line fit and the start biases are estimated from the quietest stretch of the first
  seconds; a result says so. The dataset's own noise file is read twice: its inflated active figures and the raw
  figures from its comments.
- `EskfConfig.vision_model = "clone"` (opt-in, default `"anchor"`) and four benchmark cases
  (`outage_visual_clone`, `outage_visual_degraded_camera_rereferenced`, `outage_visual_degraded_camera_clone`,
  `vision_only_clone`): the previous visual pose carried as a stochastic clone, the B1 spike
  ([ADR-0017](docs/adr/0017-stochastic-clone-for-the-visual-update.md), accepted). On the synthetic fixture the clone
  is calibrated under GNSS denial where the single anchor is not, across the seed, trajectory and outage sweeps.
  The default, `vision_enabled` and the single-anchor rows are unchanged. Its Jacobians are checked against
  numerical derivatives.
- `vision.noise_corr_s`, `outlier_fraction`, `outlier_scale`, `scale_sigma`, `scale_tau_s` (scenario settings, all off
  by default, drawn from a stream of their own so no existing number moves) and four benchmark cases
  (`outage_visual_clone_outliers`, `_scale_drift`, `_correlated`, `_correlated_inflated`): stress tests of the
  clone. It survives gross outliers and scale drift. It does not survive visual errors correlated over a couple of
  seconds unless the assumed visual noise is inflated (4x restores calibration here; found by trial). A 150 s run
  without GNSS keeps a growing claimed uncertainty and accepts GNSS on return (`tests/test_clone_long_run.py`).
- `vision.rereference` (scenario setting, default off): after frames are dropped, each delivered measurement is
  taken against the last delivered frame, as a front end tracking against its last keyframe would report. The
  generator otherwise measures against a dropped frame, which a filter comparing with its last received frame
  cannot be consistent with.
- `docs/euroc.md` and `docs/data/euroc_compare.csv`: the comparison of the default and the preset over all eleven
  EuRoC sequences, with the failing runs listed and the caveats of ADR-0013 beside the table. The table is
  generated by `navkit euroc compare --page` and a test checks it, and the statements in the prose, against the
  committed CSV files, including `docs/data/euroc_validation.csv` for the runs made after the settings were chosen. `--from-csv` rebuilds the page without rerunning. The dataset itself is not in the repository.
- `docs/data/metrics.json` and `scripts/metrics.py`: the test, ADR and line-coverage figures the documents
  quote now come from one generated file through `<!-- metric:... -->` markers. CI fails when a marker or the
  JSON is stale, when a count is typed by hand, when an ADR is missing from the index, or when measured
  coverage differs from the recorded figure by more than half a point on the recorded interpreter.
- `navkit sweep separability` and [`docs/separability.md`](docs/separability.md): whether the first GNSS gate can tell
  an honest return after a 20 s outage from a spoofed one, on real recorded IMU data (EuRoC, TUM VI) with
  simulated GNSS. The spoof population is derived from the honest innovations, so no spoof is injected into a
  running filter. With the default noise the two overlap. With a calibrated bias walk they separate, but only for
  spoofs larger than the claimed uncertainty. The filter now records each GNSS innovation before gating, and
  `run_sequence` can return them. [ADR-0018](docs/adr/0018-honest-return-separability.md) is accepted: use the
  calibrated bias walk on recorded IMUs, leave the gate alone, and state the limit.

- `navkit sweep ramp` and [`docs/slow_ramp.md`](docs/slow_ramp.md): a GNSS spoof that grows from 0.05 to 2 m/s, on
  real recorded IMU data with simulated GNSS, healthy before the onset and after a 20 s outage. The filter follows
  the spoof in every spoofed run. With the calibrated bias walk the gate does not react to ramps up to 1 m/s on
  EuRoC. `RunOptions.spoof` applies the ramp. [ADR-0019](docs/adr/0019-slow-ramp-spoofing.md) is accepted: the limit is
  documented in the limitations, the risk log and the roadmap.

- [`docs/product_management/05_work_breakdown.md`](docs/product_management/05_work_breakdown.md): the remaining work
  as packages with a deliverable, a dependency and an exit test, and three options for closing blocker B4 with a
  recommendation. Sizes are judgements, and the page says so.

- `navkit sweep vision-ramp` and [`docs/vision_ramp.md`](docs/vision_ramp.md): the slow-ramp runs with a simulated visual
  source fused by the stochastic clone. With independent visual errors a 2 m/s ramp is caught and not followed. A
  1 m/s ramp is seen and still followed. With correlated errors nothing is caught. `RunOptions.vision` adds the
  source. [ADR-0020](docs/adr/0020-second-source-against-a-ramp.md) is proposed; the decision section is for the
  maintainer to write.

- `navkit sweep faultclass` and [`docs/fault_classification.md`](docs/fault_classification.md): whether the GNSS
  innovations can name the cause of a fault, on real recorded IMU data with simulated GNSS. Multipath is called
  correctly in 99% of runs and large degradation in 98%. Spoofing is called in 74% of runs after five features were
  added to the first five (38% before), about one in six control runs is called a fault, and weak faults are missed. `RunOptions.fault` injects the faults.
  The Track A exit test is not met. [ADR-0021](docs/adr/0021-fault-classification-from-innovations.md) is proposed;
  the decision section is for the maintainer to write.

### Changed

- Blocker B4 is resolved by retiring the claim. The two tests that compared a published Basalt estimate of TUM VI
  room1 with a subsampled ground truth always skipped, because neither file could be fetched. They are removed. The
  claim of a reproduction of the published 0.069 m is dropped. `tests/test_recorded_orientation.py` takes over the
  purpose: the ground-truth attitude rate must match the recorded gyroscope, and a mis-ordered quaternion must not.
  It always runs on a synthetic sequence and runs on every fetched sequence.

- The initial IMU bias sigmas are read ([ADR-0015](docs/adr/0015-initial-imu-bias-sigmas-are-read.md), accepted).
  `gyro_bias_sigma` and `accel_bias_sigma` were accepted and read by nothing. The generator now draws an initial
  bias from each, on its own random stream, and the benchmark filter is told the same sigmas through the new
  `initial_gyro_bias_sigma` and `initial_accel_bias_sigma`, which fall back to `initial_bias_sigma` when unset.
  The synthetic numbers move, most for the vision cases, and no verdict changes. The golden snapshot, the
  tables, the sweeps and the figures were regenerated. One fault-matrix count moved: the 22 m GNSS spoof after an
  outage earned an inflation grant in one seed of five before and in none after.
- `ErrorStateKalmanFilter` now defaults to `process_noise_form="textbook"` ([ADR-0014](docs/adr/0014-textbook-imu-process-noise-by-default.md)):
  IMU white noise enters the process covariance as `sigma_g^2 dt` on attitude and `sigma_a^2 dt` on velocity
  with the matching position terms. The earlier form had no velocity term and used `dt^3 / 3` on attitude, and
  grew the covariance far below the white-noise theory. `"legacy"` reproduces the old behaviour. Every
  benchmark, sweep, figure and table was regenerated: the synthetic numbers move a little (the headline
  `outage_visual` case still has mean NEES in the hundreds against an expected 3) and no verdict changes.
  Numbers in older ADRs, the roadmap's completed items and the dated baselines were measured with the legacy
  form and were not recomputed. The golden snapshot was regenerated.
- `CONSTRAINTS.md`, `ROADMAP.md` and `CONTRIBUTING.md` no longer carry hand-typed passing and skipped counts,
  which went stale (860 collected there against 888 measured, 629 in the ratchet table and in `ROADMAP.md`,
  "8 of 8 docs" for twelve ADRs). They quote the collected count, the coverage figure and the ADR count
  from the JSON and say that all collected tests pass except the declared xfails and skips.
- The revised-roadmap audit snapshot no longer names teams that do not exist (Estimator, Docs, QA, Core, Config,
  Perf and Research teams, a Release manager) as owners; the owner is the maintainer. The open-item tables in the
  SRS and the SWaP-C matrix label the column Area, since they name workstreams. The engineering baseline no
  longer quotes the first characters of a provider key. A test fails if a table names a team or manager as owner
  or a document quotes the start of a provider key.
- `uv.lock` is removed. ADR-0011 called it stale, and CI never used it.

### Found, not fixed

- The synthetic IMU uses the opposite gravity sign to a physical z-up accelerometer. The EuRoC path passes
  gravity explicitly; a test shows the default would be wrong by orders of magnitude on a physical IMU.
- The FDIR layer's "channel faulted" flag misses long runs of rejected GNSS fixes: some EuRoC runs reject hundreds
  of fixes and are never declared faulty (ADR-0014).

### Fixed

- The two anchor drift strengths were named per second and are per square-root second (P5-05). They are now
  `anchor_pos_drift_sigma_m_sqrt_s` and `anchor_rot_drift_sigma_deg_sqrt_s`. The old names
  (`anchor_pos_drift_sigma_m_s`, `anchor_rot_drift_sigma_deg_s`) are still accepted by the `EskfConfig` constructor and
  as benchmark estimator keys, with a `DeprecationWarning`; giving an old and a new name with different values is an
  error. The value and the filter are unchanged. The serialised config uses the new names, so every `config_hash`
  changes and the golden snapshot was regenerated: the diff is the hashes and the two key names, and no number moves.
- The mechanism library said that a constant accelerometer bias gives linear error growth. It gives quadratic growth;
  linear growth is a velocity error. The `gnss_denied` entries now state the textbook exponents, name the experiment
  that tests them, and record that the accelerometer-bias explanation is falsified on the fixture. Limitation L8 is
  rewritten to match.
- Two CodeQL findings on the recorded-dataset code: `navkit euroc compare` read a variable it had not set on the
  `--from-csv` path (unreachable, since `--json` is refused there, but fragile), and `euroc_eval`, `tumvi_data` and
  `euroc_compare` imported one another. The shared sequence type, its error and the z-up gravity vector moved to
  `navkit.recorded`, and the `navkit euroc` router to `navkit.euroc_cli`. A test now fails on any import cycle,
  lazy imports included.
- `navkit.types.finite_difference` returned twice the slope at interior samples for a first derivative (a ramp of
  slope 2 gave 4). Interior points now use the central difference over their two neighbours, exact for a line on
  a non-uniform grid. `Trajectory.velocities()` inherited the defect; nothing in the benchmark called it.

## [0.2.0] - 2026-10-08

### Added

- A release workflow (`.github/workflows/release.yml`): on a version tag it checks that the tag, the version, the
  notes and the changelog agree, builds and attests the sdist and wheel, and creates a draft release with a CycloneDX SBOM
  and checksums; a manual run is a dry run that publishes nothing. The Dockerfile base image is pinned by digest.
  ([#51](https://github.com/Telschow/contested-nav/issues/51))
- `navkit` command line: `navkit run`, `navkit sweep seeds|scenes|outages`, `navkit figures`
  (`--animate`). The scripts under `scripts/` remain as wrappers. The default scenario file
  ships inside the wheel. ([#16](https://github.com/Telschow/contested-nav/pull/16), [#19](https://github.com/Telschow/contested-nav/pull/19), [#22](https://github.com/Telschow/contested-nav/pull/22), [#25](https://github.com/Telschow/contested-nav/pull/25))
- Outage sweep: the GNSS outage start and duration swept for the control and the visual case,
  with bootstrap intervals, a CSV and a figure. ([#22](https://github.com/Telschow/contested-nav/pull/22))
- Noise-mismatch sweep (`navkit sweep mismatch`): the filter is told sensor noise that is a factor of the
  true value, with the estimator keys `gnss_sigma_scale` and `vision_sigma_scale` (default 1, no change to
  any result). New page [Noise mismatch](docs/mismatch.md). ([#42](https://github.com/Telschow/contested-nav/issues/42))
- Fault matrix (`navkit sweep faults`): eight fault modes measured against a clean control over five
  seeds, with detection and false-alarm counts from the FDIR event log. New page
  [Fault matrix](docs/faults.md); the FMEA-lite rows are updated from the results.
  `run_case` gains `gnss_hook`, `fdir_events` and `force_inject`, all off by default.
  ([#43](https://github.com/Telschow/contested-nav/issues/43))
- SRS traceability check (`scripts/check_srs_trace.py`, `docs/product_management/srs_trace.csv`): every
  requirement and acceptance criterion has a test, a checked configuration value or a declared gap, and
  the roll-up counts follow from the verdicts. It found two wrong roll-up counts and stale prose, now
  fixed. ([#49](https://github.com/Telschow/contested-nav/issues/49))
- Project tooling: a `Makefile`, pre-commit hooks, a `Dockerfile` and a devcontainer, a secret scanner that also reads
  history, a security workflow (dependency review, `pip-audit`, a CycloneDX SBOM), a relative-link checker, CODEOWNERS and
  issue and pull request templates. ([#29](https://github.com/Telschow/contested-nav/pull/29))
- MkDocs Material site with an API reference, a strict build in CI and a Pages deployment that checks the documented tables
  first; the README is rewritten from 516 to 129 lines and gains a "Scope and responsible use" section; ADR-0010 (determinism)
  and ADR-0011 (CI and supply chain). `docs/index.html` is removed. ([#36](https://github.com/Telschow/contested-nav/pull/36))
- A social preview image and its generator. ([#37](https://github.com/Telschow/contested-nav/pull/37))
- A RICE-ordered roadmap with a stability check ([#40](https://github.com/Telschow/contested-nav/pull/40)) and a risk register
  ([#41](https://github.com/Telschow/contested-nav/pull/41)).
- Golden snapshot test of the seeded benchmark ([#12](https://github.com/Telschow/contested-nav/pull/12)); Hypothesis property tests for
  rotations, the filter's covariance and attitude, NEES and the chi-square functions ([#21](https://github.com/Telschow/contested-nav/pull/21)).
- macOS and Windows test legs, and ADR-0009 on cross-platform numerics. ([#24](https://github.com/Telschow/contested-nav/pull/24))
- Hero figure and animation of error against the claimed bound. ([#25](https://github.com/Telschow/contested-nav/pull/25))
- `benchmarks/` timing harness and `docs/PERFORMANCE.md` with measured numbers. ([#17](https://github.com/Telschow/contested-nav/pull/17))

### Changed

- The synthetic IMU is derived analytically instead of by a finite difference whose rounding
  error moved with the math library. Headline ATE moves by at most 1.1e-5 m and mean NEES by at
  most 3.6e-3; coverage, counts and verdicts do not change. ([#26](https://github.com/Telschow/contested-nav/pull/26))
- `interpolate_trajectory` is vectorised: the sum of the seven benchmark case medians fell from
  about 15.1 s to 11.1 s (1.36x), with 97 of 73,846 numbers differing by at most 3.6e-16. ([#17](https://github.com/Telschow/contested-nav/pull/17))
- `ErrorStateKalmanFilter._update` and `fdir_manager.py` are split into named pieces with the
  benchmark output byte-identical to before. ([#14](https://github.com/Telschow/contested-nav/pull/14), [#15](https://github.com/Telschow/contested-nav/pull/15))
- Third-party GitHub Actions are pinned to commit SHAs. ([#9](https://github.com/Telschow/contested-nav/pull/9))
- The README headline is qualified: the overconfidence of visual aiding holds for every outage
  window tried, but the accuracy gain holds only for outages that start early. ([#22](https://github.com/Telschow/contested-nav/pull/22))

### Removed

- `docs/architecture/demo.html` (11 MB) and `demo.workflow.json`: the page embedded a raw pixel
  buffer labelled as a PNG that a browser cannot render, and typed its headline numbers. ([#27](https://github.com/Telschow/contested-nav/pull/27))

### Fixed

- Every benchmark scenario now goes through the injection layer. The runner skipped it for a scenario
  with no outage or camera drop, which ran `gnss_only`, `dead_reckoning`,
  `vision_anchor_in_measurement_noise` and `vision_only` with a noiseless IMU and ignored a scenario
  that set only a timestamp offset. Those four cases move slightly (ATE by 0.003 m to 0.371 m) and no
  verdict changes; the three outage cases and the headline result are bit-identical.
  [ADR-0012](docs/adr/0012-every-scenario-is-injected.md), golden snapshot regenerated.
  ([#56](https://github.com/Telschow/contested-nav/issues/56))
- Five scenario descriptions in `configs/benchmark.yaml` contradicted the measured results and
  were copied into every result record: `vision_only` was "calibrated, and much better than
  dead reckoning" (it is overconfident and less accurate), `outage_visual` was "tens of metres
  wrong" (2.541 m), `gnss_only` and `outage_control` were "calibrated" and "nominal" (their
  verdict is mixed), and the degraded-camera case "checks the anchor model does not collapse" (it
  does not change the result). The text now says what the numbers say. Only the `description`
  fields and `config_sha256` change in the golden snapshot.
- The demo reported mean NEES 1.4e10 and a claimed sigma of 7 mm while the README said 419.4 and
  0.161 m, because it ran its own copy of the filter configuration. It now runs the benchmark case
  and a test compares its headline with the golden snapshot. ([#27](https://github.com/Telschow/contested-nav/pull/27))

Earlier entries, from the 2026-09-29 audit:

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
- The `outage_visual_degraded_camera` case specified `camera_drop.fraction`, but
  `CameraDropConfig` names that field `drop_fraction`. The key was not
  recognised and the dataclass default was used instead, so the case ran with
  20% of camera frames dropped in 2 s bursts instead of the 30% in 1 s bursts the
  case intends. The benchmark config now sets `drop_fraction`, and the case's
  published numbers are those of the scenario it claims to measure.

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

- None. No public API changed. One published number changed: see the
  `outage_visual_degraded_camera` correction under Fixed.

## [0.1.0] and earlier

Commits `abb62bb`, `cc998d1`, `c571e91`, `8f6fcd7` and their ancestors. (These
were `c81c6f9`, `5d83216`, `4fa780b` and `466ab48` until the history rewrite
described in `docs/PROJECT_STATE.md` §5 replaced the author identity.) No
changelog was kept; see `git log` and `docs/audit/`.
