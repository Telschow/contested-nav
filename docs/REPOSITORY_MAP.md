# Repository map


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29. Filenames were not trusted; each entry was opened and read.

Legend: **[V]** verified by reading the implementation · **[R]** verified by running
it · **[G]** read from Git/config only.

---

## 1. Top level

```
contested-nav/
├── pyproject.toml          [G] hatchling build, 3 runtime deps, pytest config
├── uv.lock                 [G] 293 KB, UNTRACKED — dependency lock
├── README.md               [G] 18 KB, primary portfolio surface
├── ROADMAP.md              [G] 16 KB, staged plan, blockers B1–B5
├── CONSTRAINTS.md          [G] 12 KB, project invariants + ratchets (C1–C6)
├── LICENSE                 [G] MIT
├── configs/benchmark.yaml  [G] 7 scenario definitions
├── src/navkit/             [V] 29 modules, 7,947 LOC
├── tests/                  [R] 14 files, 6,471 LOC, 567 tests
├── scripts/                [R] 5 files, 1,119 LOC
├── docs/                   [G] 8 ADRs, 6 audit docs, 3 PM docs, 4 figures
├── .github/workflows/      [G] ci.yml (4 jobs), pages.yml (build + deploy)
├── .opencode/               agent skills (gitignored)
└── opencode.json            *** CRITICAL: live API key, not gitignored ***
```

---

## 2. Source modules

### `navkit.estimators` — the filter under test

| File | LOC | Contents **[V]** |
|---|---:|---|
| `eskf.py` | 914 | 21-state ESKF. State order `[dθ(0:3), dp(3:6), dv(6:9), db_g(9:12), db_a(12:15), c_p(15:18), c_t(18:21)]`. First-order (not invariant) formulation. Joseph-form covariance. GNSS position, visual relative rotation `Log(R_meas R_predᵀ)`, visual relative translation. Rejection counting, not silent gating. **Working-tree additions:** ADR-0007 lockout + re-expansion (`:507-517`), frozen-anchor cross-check (`:521-548`), outage-start anchor snapshot (`:817-834`), grant counter (`:559-565`). |
| `dead_reckoning.py` | 105 | No-aiding control case. Reports no covariance, so NEES is deliberately absent for it. |

### `navkit.fdir` — detect, isolate, recover

| File | LOC | Contents **[V]** |
|---|---:|---|
| `fdir_manager.py` | 1,107 | Per-channel state machine. `max_consecutive_rejections` (5) before declaring a fault; faulted channels rejected outright, never noise-inflated (the ADR-0003 anti-pattern); recovery by `auto_recovery_count` consecutive accepts. **Working-tree additions:** ADR-0007 `spoof_grant_threshold`, `STATUS_REJECTED_SPOOF`, 60 s lockout. **Defect:** `STATUS_REJECTED_PERSISTENT` imported and exported twice (`:29/:31`, `:55/:57`) — `__all__` has 22 entries, 21 unique. |
| `gating.py` | 336 | `mahalanobis_sq`, chi-square quantiles from a hardcoded table, Wilson–Hilferty for other dof. No SciPy. `MAX_CONDITION_NUMBER` guard. |
| `nis_monitor.py` | 307 | Bounded per-channel window of gate outcomes; `inflation_factor`. Separates an isolated impulse (no relief) from a sustained run (evidence the *filter* is wrong). |

### `navkit.eval` — does the uncertainty hold up

| File | LOC | Contents **[V]** |
|---|---:|---|
| `metrics.py` | 586 | ATE under four alignments (`none`/`rigid`/`rigid_start`/`similarity`) — deliberately never a single number; RPE; drift slope. |
| `calibration.py` | 482 | NEES, 2σ coverage with Wilson intervals, bulk/tail verdicts. Reports disagreement rather than resolving it. |
| `thresholds.py` | 244 | Verdict thresholds. |
| `statistics.py` | 152 | Wilson interval, quantiles. |

### `navkit.analysis` — typed claims

| File | LOC | Contents **[V]** |
|---|---:|---|
| `findings.py` | 568 | `ClaimType` = `FACT`/`MEASUREMENT`/`INTERPRETATION`/`HYPOTHESIS`; `Claim` records carry `confidence` and `falsification_test`; `MECHANISM_LIBRARY` holds per-scenario causal hypotheses, **each paired with the experiment that would refute it** (e.g. GNSS-denied claim → "run with zero initial bias; if peak drift is unchanged, the explanation is wrong"). This is the strongest research-integrity mechanism in the repository. **Quirk:** `base == base` at `:418` is an intentional NaN check, correct but non-idiomatic (ruff `PLR0124`). |

### Supporting modules

| File | LOC | Contents **[V]** |
|---|---:|---|
| `types.py` | 449 | `Trajectory`, `ImuSample`, `GnssFix`, `VisionUpdate`. Each has a `time_offset` method — a uniform interface, not duplication. |
| `synthetic.py` | 171 | Analytic trajectory (deterministic, **takes no seed**), analytic IMU by differentiation (removes discretisation error). |
| `sensors/models.py` | 225 | GNSS/vision measurement models; both generators seeded. |
| `degrade/inject.py` | 366 | Outage windows, camera-drop bursts, timestamp offsets. |
| `degrade/config.py` | 326 | Scenario dataclasses → dict, incl. `CameraDropConfig` (working-tree addition). |
| `config.py` | 333 | YAML load, `canonical_dict`, sha256 `config_hash` (16 hex chars). |
| `geometry/rigid.py` | 259 | SE(3), quaternion ops, Umeyama. |
| `geometry/align.py` | 113 | ATE alignment variants. |
| `io/trajectory.py` | 270 | TUM/EuRoC/Plotly. **The only** quaternion-order conversion point (C1). |
| `io/imu.py` | 280 | Bias random walk, scale factor, axis misalignment, white noise. **Lowest coverage at 63.6%.** |
| `geometry/__init__.py` | 47 | Re-exports. |
| `*/__init__.py` | — | Package docstrings double as architecture documentation. |

---

## 3. Scripts — all five verified runnable **[R]**

| Script | LOC | Command | Result |
|---|---:|---|---|
| `run_benchmark.py` | 373 | `python scripts/run_benchmark.py` | 7 cases; **bit-reproducible** across two runs (only `runtime_s`/`wall_s`/`realtime_factor` differ) |
| `seed_sweep.py` *(untracked)* | 217 | `python scripts/seed_sweep.py --seeds 10` | 10 seeds × 7 cases |
| `check_doc_tables.py` | 177 | `python scripts/check_doc_tables.py` | README + `index.html` tables match `benchmark.json` |
| `coverage_report.py` | 152 | `python scripts/coverage_report.py --ratchet` | 86.58% total, ratchet OK |
| `make_figures.py` | 200 | `python scripts/make_figures.py` | 4 PNGs; **deterministic run-to-run** but differ from committed (matplotlib version metadata) |

`run_benchmark.py` gained a `--seed` override in the working tree; the default
path is **bit-identical** to the committed `results/benchmark.json`.

---

## 4. Test suite **[R]**

567 collected · **563 passed** · 2 skipped · 2 xfailed · ~87 s.

| File | LOC | Focus |
|---|---:|---|
| `test_nis_monitor.py` | 1,110 | NIS window, adaptive inflation, ADR-0007 permanence (**2 deliberate xfails**), ADR-0008 cross-check (5 tests) |
| `test_fdir.py` | 964 | Gating, isolation, recovery, spoof hysteresis |
| `test_estimators.py` | 894 | ESKF convergence, Jacobians, frame conventions, Joseph PSD |
| `test_thresholds_and_injection.py` | 596 | Verdict thresholds, outage/camera-drop injection |
| `test_metrics.py` | 544 | ATE/RPE against known values |
| `test_findings.py` | 446 | Claim typing and falsification records |
| `test_config.py` | 438 | Config round-trips, hashing |
| `test_trajectory_io.py` | 337 | TUM/EuRoC/Plotly round-trips (**2 skips** — TUM VI absent) |
| `test_calibration.py` | 334 | NEES, Wilson intervals |
| `test_seed_sweep.py` *(untracked)* | 199 | Sweep invariants: override reaches every stream, `n=1` refused, missing NEES stays `None` |
| `test_geometry.py` | 154 | SE(3), quaternions, alignment |
| `test_doc_tables.py` | 164 | The doc-table checker itself |
| `test_imu_noise.py` | 91 | IMU noise models |

The 2 skips are honest: `test_trajectory_io.py:317,335` require TUM VI reference
files that are deliberately not vendored. The 2 xfails are `strict=False` by
design — ADR-0007 spoof permanence stays red until a second detection modality
works. A `strict=True` test in `TestFrozenAnchorCrossCheck` pins the ADR-0008
unreachable guard so it fails loudly when fixed.

---

## 5. CI/CD **[G]** — `ci.yml`, 4 jobs

| Job | Needs | Steps | Status |
|---|---|---|---|
| `test` | — | pytest on **3.11, 3.12, 3.13**; coverage ratchet | pass locally |
| `lint` | — | `ruff check`, `ruff format --check`, `mypy src` | **FAIL: 131 / 35 files / 15** |
| `build` | `test`, `lint` | sdist+wheel, install in clean venv, import | builds locally; **never runs in CI while lint is red** |
| `benchmark` | `test` | run twice, diff; check doc tables | reproducible locally |

`pages.yml` regenerates the benchmark and figures, then deploys `docs/` to GitHub
Pages with least-privilege OIDC.

`ruff` and `mypy` are installed **unpinned**, so the gate moves with upstream
releases. See `ENGINEERING_BASELINE.md` F2.

---

## 6. Benchmark configuration **[V]** — `configs/benchmark.yaml`

7 cases, each `seed: 0` except `camera_drop: seed: 3`:

| Case | Estimator | Purpose |
|---|---|---|
| `gnss_only` | ESKF | Reference; filter calibrated when aiding is available |
| `dead_reckoning` | DeadReckoning | How much is the filter vs the motion model |
| `vision_anchor_in_measurement_noise` | ESKF, `vision_anchor_modelled: false` | **Regression control** for the pre-ADR-0001 defect; intentionally wrong config |
| `vision_only` | ESKF | Visual, no GNSS; calibrated but freezes position uncertainty |
| `outage_control` | ESKF, no vision | 15 s denial, vision off — honest baseline |
| `outage_visual` | ESKF, vision on | **The case this project is about** |
| `outage_visual_degraded_camera` | ESKF, 30% burst drop | Anchor model under intermittent visual |

`results/` is gitignored; the committed figures under `docs/figures/` are the
evidence, and `check_doc_tables.py` keeps the prose tables honest against a live
benchmark run.

---

## 7. Documentation **[G]** — 25 files

| Group | Count | Notes |
|---|---:|---|
| ADRs | 8 | 0001 anchor-as-state · 0002 Joseph form · 0003 ship vision disabled · 0004 quaternion order · 0005 chi-square gating · 0006 NIS window · 0007 spoof permanence *(untracked)* · 0008 frozen-anchor cross-check *(untracked)* |
| Audit | 6 | `docs/audit/01`–`06` *(untracked)*, from a prior round |
| Product mgmt | 3 | SRS, SWaP-C trade matrix, FDIR/spoofing strategy |
| Reference | 3 | `architecture.md`, `calibration.md`, `index.html` |
| Figures | 4 | PNGs, committed deliberately |
| Root | 2 | `README.md`, `ROADMAP.md`, plus `CONSTRAINTS.md` |

**Every `file:line` reference in the 6 audit docs was machine-verified in range
during the prior session**, and two stale references (`fdir_manager.py:867`,
`:160`) were found and corrected. Documentation discipline here is genuinely
unusually high.

---

## 8. What does *not* exist

Verified absent, and worth stating so their absence is not mistaken for an
oversight in the map: no ML frameworks · no notebooks · no model checkpoints ·
no datasets · no `Dockerfile` · no container or deployment config · no
`Makefile` · no `[project.scripts]` CLI entry point · no pre-commit config ·
no `CONTRIBUTING.md` · no `SECURITY.md` · no `CITATION.cff` · no
`requirements.txt` · no `setup.py`/`setup.cfg` · no `.pre-commit-config.yaml` ·
no submodules · no Git LFS · no changelog.
