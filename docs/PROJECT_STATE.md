# Project state


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29. Describes the repository as it existed when the audit
began: commit `c81c6f9` (since rewritten to `abb62bb`) on `main`, plus a large
uncommitted working tree. See §5 for what changed when the project was later
published.

This document answers "what is true right now" and nothing more. Where the
repository disagrees with itself, both values are recorded rather than one being
silently corrected.

---

## 1. What this project is

`navkit` is a 21-state error-state Kalman filter (ESKF) for fusing GNSS, visual
odometry and inertial data, together with a fault-detection, isolation and
recovery (FDIR) layer and an evaluation harness that measures whether the filter's
stated uncertainty is honest.

The organising question, stated in `docs/architecture.md`:

> The estimator is the test subject, not the product. `navkit` asks one
> question of a navigation filter: *is its stated uncertainty honest?*

**Verified, not inferred:** there is no machine-learning component. A search for
`torch`, `tensorflow`, `keras`, `jax`, `sklearn`, `transformers`, `lightgbm`,
`xgboost`, `catboost` and `onnx` across all Python, TOML, YAML and Markdown
files returns nothing. There are no notebooks, no model checkpoints
(`.pt`/`.pth`/`.onnx`/`.h5`), no pickled artefacts and no datasets. Runtime
dependencies are exactly three: `numpy>=1.26`, `matplotlib>=3.8`, `pyyaml>=6.0`.

This is a classical state-estimation and estimation-theory project. Any
portfolio description implying learning-based methods would be false.

---

## 2. The central finding

The repository's own headline result, verified reproducible:

With GNSS denied for 15 s and visual odometry enabled, the filter reports
**0.161 m** of position uncertainty while being **2.54 m** wrong. Mean NEES
**419.4** against an expected 3; 2σ coverage **20.0%** where 99.2% is required.

**Verified across 10 seeds (2026-09-29, `scripts/seed_sweep.py --seeds 10`):**
the *direction* is a property of the design, not of one fixture. `outage_visual`
is overconfident at every seed — minimum NEES 211.7, maximum coverage 34.8%.
Blocker **B1** (unmodelled visual-anchor error) is real.

**The magnitudes are single draws.** Across 10 noise realisations, NEES spans
211.7–2103.4 (mean 844) for `outage_visual` and 280–12537 for
`vision_anchor_in_measurement_noise`. The shipped tables remain the seed-0
benchmark, which is the committed artefact.

**Scope limit of the sweep, stated because it is easy to overstate:** the
reference trajectory in `synthetic.py` is analytic and takes no seed, so all 10
draws replay the same 30 s motion. The sweep varies *sensor noise on one scene*.
It does not vary geometry, outage timing, or duration. Multi-scene validation
is still open.

Because the failure is structural, the project ships `vision_enabled=False` by
default (ADR-0003) and documents the failure rather than tuning around it. That
is the correct engineering decision and is preserved here.

---

## 3. Architecture in one diagram

```
synthetic.py ──► sensors/models.py ──► estimators/eskf.py ──► eval/calibration.py
   analytic        IMU / GNSS /         21-state ESKF          NEES, coverage
   trajectory      visual noise          + covariance           verdicts
                                                             ▲
                                          degrade/inject.py ───┘
                                          GNSS outage windows
```

| Package | Files | LOC | Role |
|---|---|---:|---|
| `navkit.fdir` | 5 | 1,900 | Chi-square gating, NIS window monitor, channel state machine |
| `navkit.estimators` | 3 | 1,040 | 21-state ESKF, dead reckoning |
| `navkit.eval` | 6 | 1,900 | ATE/RPE metrics, NEES, coverage, Wilson intervals |
| `navkit.analysis` | 2 | 590 | Typed claims (`FACT`/`MEASUREMENT`/`INTERPRETATION`/`HYPOTHESIS`) |
| `navkit.types` | 1 | 449 | Trajectory, IMU, fix and measurement containers |
| `navkit.degrade` | 3 | 727 | Outage, camera-drop and noise injection |
| `navkit.geometry` | 4 | 419 | SE(3), quaternions, Umeyama alignment |
| `navkit.io` | 3 | 587 | TUM/EuRoC/Plotly readers, IMU noise models |
| `navkit.config` | 1 | 333 | Config loading, canonical dict, config hash |
| `navkit.sensors` | 2 | 244 | Measurement models, synthetic observations |
| `navkit.synthetic` | 1 | 171 | Analytic trajectory and IMU generation |

Source: 7,947 LOC across 29 modules. Tests: 6,471 LOC across 14 files.
Scripts: 1,119 LOC across 5 files. Dependency ratio 3 : 1 test-to-source.

---

## 4. Design decisions that must not be reversed casually

These are load-bearing and were made for stated reasons.

- **Zero heavy dependencies.** No SciPy, no GTSAM, no factor-graph library, no
  compiled extension. The incomplete gamma function, chi-square quantiles,
  covariance propagation and metric definitions are implemented in-repo "so every
  number can be traced to code in this repository." This is a deliberate
  auditability property, not an accident of scope. Adding GTSAM to close B1
  would resolve the technical problem and destroy the project's central claim.
  Any such change needs its own ADR.

- **Joseph-form covariance, never the `(I-KH)P` shortcut** (ADR-0002,
  `CONSTRAINTS.md` C4), so positive semidefiniteness is preserved and the
  property is testable.

- **Quaternions are `(w,x,y,z)` internally; `T_wb` everywhere** (ADR-0004, C1–C3).
  Conversion happens only in `io/trajectory.py`. A permuted quaternion still
  satisfies orthonormality and `det == 1`, so only known-matrix tests catch it.

- **Visual anchor as filter state, not measurement noise** (ADR-0001). The
  pre-refactor arrangement is retained as a *regression control case*
  (`vision_anchor_in_measurement_noise`), not deleted, so the failure remains
  reproducible on demand.

- **Textbook first-order error-state formulation, not invariant EKF.** The
  docstring states an invariant EKF gives marginally better behaviour in fast
  rotation and buys it with algebra a reader cannot check by inspection. That
  trade is explicit and reasonable for a project whose value is auditability.

- **Ship visual fusion disabled** (ADR-0003) until the pose-graph work lands.

---

## 5. Git state

> **Status update, 2026-09-29 (after this audit).** Every hash, count and
> relation in this section describes the repository as it stood *before* the
> audit work was committed. The project has since been published to
> `https://github.com/Telschow/contested-nav`. Publishing required a history
> rewrite to purge a personal email address that had been committed in author
> metadata and in two audit documents, so the hashes cited here no longer
> resolve; the current equivalents are given below. The dangling objects
> described further down were removed by that rewrite and are no longer
> recoverable. The unrelated GitHub history has been merged rather than
> discarded, so both roots are ancestors of the published `main`.

| Property | Value at audit time | Value now |
|---|---|---|
| Branch | `main` (only branch) | `main` |
| Commits | 4 | 22 |
| First commit | `466ab48` → now `8f6fcd7` `docs(navkit): reconcile test metrics, correct Jacobians, and update roadmap` | same commit, new hash |
| Latest commit | `c81c6f9` → now `abb62bb` `docs(tpm): add SRS, SWaP-C trade-off matrix, and FDIR strategy whitepaper` | superseded by later release commits |
| Remotes | **none configured** | `origin` → `git@github.com:Telschow/contested-nav.git` |
| Tags | none | none |
| Submodules | none |
| Git LFS | not in use |
| Stashes | none |
| Dangling commits | 2 (dropped stashes, content already in working tree — see below) |
| Tracked files | 70 | 103 |
| Modified (unstaged) | 20 | none |
| Untracked | 8 paths | none tracked; build and result directories ignored |

The four commits were, in reverse chronological order (hashes are the pre-rewrite
values, with their current equivalents):

```
abb62bb  (was c81c6f9) docs(tpm): add SRS, SWaP-C trade-off matrix, and FDIR strategy whitepaper
cc998d1  (was 5d83216) feat(fdir): implement NIS window monitor and adaptive covariance inflation (resolve B5)
c571e91  (was 4fa780b) feat(fdir): implement zero-dependency chi-square innovation gating and sensor fault isolation
8f6fcd7  (was 466ab48) docs(navkit): reconcile test metrics, correct Jacobians, and update roadmap
```

### Dangling commits are not lost work

At audit time `git fsck` reported `1fa6393` and `58bc8eb`, both with the message
form `WIP on main: …`, which is the signature of `git stash` entries that were
later dropped. I verified their content was already present in the working tree
before concluding this:

- `58bc8eb` → `fdir_manager.py`: working tree differed only by added comment
  lines; no removed functionality.
- `1fa6393` → `eskf.py`: the 6 differing removed lines were docstring prose and
  an earlier FDIR import signature that later commits replaced.

The conclusion held and nothing was lost. Neither object was ever reachable
from a branch, and the history rewrite that preceded publication removed both,
so `git show` on them no longer works. This is recorded because it is the reason
those hashes appear nowhere in the current history. No history was modified
during the audit itself.

### Local and GitHub histories were unrelated

`https://github.com/Telschow/contested-nav` existed and was reachable, but it
contained **one commit** (`4b7be00`, "Initial commit", 2026-09-29 18:06) whose
entire content is a `README.md` containing the single line `# contested-nav`.
That commit is still in the published history and is still an ancestor of
`main`.

The local history and the remote shared **no commits**, so the repository was
*ahead by 4 and behind by 1* in the sense of unrelated histories and could not
be reconciled by a normal push or pull. `ENGINEERING_BASELINE.md` §2 recorded
the recommended non-destructive sequence. Publication followed it: the remote
commit was merged in rather than discarded, so the push was an ordinary
fast-forward.

---

## 6. The uncommitted working tree

Roughly 1,000 changed lines of substantive work exist only in the working tree.
It is coherent, well-tested and worth keeping:

| Area | What is uncommitted |
|---|---|
| `src/navkit/estimators/eskf.py` | ADR-0007 spoof lockout + covariance re-expansion; ADR-0008 frozen-anchor cross-check (~61 lines) |
| `src/navkit/fdir/fdir_manager.py` | ADR-0007 hysteresis state machine, ~189 lines |
| `src/navkit/degrade/config.py` | `CameraDropConfig` support |
| `scripts/seed_sweep.py` *(new)* | 10-seed sweep harness, 217 LOC |
| `tests/test_seed_sweep.py` *(new)* | 15 tests pinning the sweep's invariants |
| `tests/test_nis_monitor.py` | +455 LOC: `TestFrozenAnchorCrossCheck`, ADR-0007 xfails |
| `docs/adr/0007`, `0008` *(new)* | Spoof-permanence and cross-check decision records |
| `docs/audit/` *(new, 6 files)* | Prior audit round, 42 KB |
| Docs + configs | 11 tracked files updated (README, ROADMAP, CONSTRAINTS, SRS, calibration, index.html) |
| `pyproject.toml` | `dev` extra with `ruff`/`mypy` |
| `uv.lock` *(new, 293 KB)* | Untracked lockfile |

**One hazard:** `opencode.json` sits in the same directory, untracked *and not
gitignored*, holding a live API key. `git add .` stages it. See
`PUBLICATION_READINESS.md` §1.

> **Resolved.** The hazard was real: the file was staged by an unqualified
> `git add .` during the audit and the fix was to gitignore it. It has never
> been committed, and it is absent from the published history, which
> `gitleaks` confirms across all 22 commits. The credential in it is still the
> owner's to rotate; ignoring a file is not the same as rotating a key.

---

## 7. Known divergences *within* the repository

Documented rather than silently fixed, because each is a decision to be made
deliberately:

| # | Divergence | Detail |
|---|---|---|
| 1 | Test count | Badge and `CONSTRAINTS.md` say 563 passing / 567 collected (correct). README code block and repo-map line still say "534 collected: 532 pass" and "534 tests (532 pass)". Measured truth is 567 / 563. |
| 2 | Repo URL | 16 references to `contested-nav/contested-nav`; actual is `Telschow/contested-nav`. |
| 3 | ADR inventory | `CONSTRAINTS.md` says "ADR-0001..0008 / 8 of 8 docs" — correct. No stale inventory found. |
| 4 | NEES baseline | 1996.5 (pre-inflation) vs 419.4 (post) are both correct at different commits; `ROADMAP.md` now records 419.4 as current with 1996.5 kept only as a historical value. Verified by grep. |
| 5 | Single-draw numbers | README, ADR-0006 and `calibration.md` quote seed-0 figures. Each now carries an explicit note that the value is one draw of a wide distribution. |

---

## 8. What is *not* established

Stated explicitly so no reader infers it from the project's confidence.

- **No real sensor data has ever been evaluated.** Every number is from a
  known-answer synthetic fixture. Two tests skip because TUM VI reference
  ground truth is not vendored.
- **No statistical power claim is defensible.** 10 seeds gives a range, not a
  distribution. No confidence interval, no hypothesis test, no sample-size
  justification.
- **No comparison against any external baseline.** No published EKF, VIO or
  odometry system is run on the same fixture. The `docs/audit/05` review
  summarises the literature; it does not benchmark against it.
- **No novel algorithm is demonstrated.** The 21-state anchor formulation and
  the NIS window monitor are engineering contributions applied to a known
  failure mode. Novelty is unclaimed in the repository and should stay
  unclaimed.
- **The spoofing results are unit-level only.** They come from a forced-grant
  test harness, not a spoofing simulator, RF model, or attack campaign.
- **`vision_enabled=True` is not shippable.** The project says so; the failure
  is measured, not speculated.
