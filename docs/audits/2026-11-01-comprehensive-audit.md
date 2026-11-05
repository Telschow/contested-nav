# Comprehensive audit, 2026-11-01

> **Status note, 2026-11-05, at `881f039`.** The report below describes `49d4310` and is left as written.
> The current status of each item is in [the comment on #250](https://github.com/Telschow/contested-nav/issues/250).
> In short: the seed-policy and EuRoC-notice items are fixed, the shared-stream choice is recorded in ADR-0010,
> the B1 wording is separated, and the ADR decisions (#282), the EuRoC rights question (#278) and the
> UrbanNav real-data runs (#274) wait for the maintainer.

## 1. Commit and scope

- Commit: `49d431064e49c06474c389cd70ff69a92c7f55b5` (`main`, merge of PR #249). Working tree clean.
- Scope: ESKF, sensor models, FDIR, calibration harness, studies and gates, recorded-data
  integrations, docs, CI and supply chain. Read-only: no code changed, no seed of 100 or more run.
- Method: an independent source audit with executed checks (finite-difference Jacobians, long-run
  covariance health, a seed-overlap probe; throwaway scripts outside the repo), the full suite in
  its CI form, `make docs-fast`, and a fresh `navkit run` checked by `scripts/check_doc_tables.py`;
  plus a lead review that re-read the P2 evidence and the issue backlog. Part of the work was done
  by AI agents (Claude Code); every claim cites file and line.

## 2. Executive summary

This is the most technically mature of the three repositories. Everything that could be executed
passed: lint, format, mypy, the full suite (no failures; every skip is an unfetched dataset; two strict
xfails), docs-fast, and the generated tables. The ESKF mathematics was verified numerically (GNSS
and clone Jacobians to about 1e-10, reset Jacobian with the expected second-order residual,
covariance PSD and symmetric over 20000 steps in five configurations). The FDIR false-alarm rate
(5 in 3775 updates) is consistent with its nominal 0.1%. B1 is honestly represented as
characterised, not solved; vision stays off; the overconfident control row is kept.

The one material finding is in the experiment design: at equal seeds the GNSS white noise and the
visual rotation noise are the same random sequence (CN-01, P2), contrary to ADR-0010. Its effect
on the published numbers is not yet measured. The other P2s protect the held-out protocol (generic
sweeps have no held-out guard, CN-02) and correct a stale published status page (CN-03).

## 3. Readiness

| Dimension | Assessment |
|---|---|
| Technical correctness | Strong, verified numerically. CN-05 (anchor `c_t` convention) is a documentation-versus-convention question on the control model. |
| Architecture | `estimators/eskf.py` (1648 lines) carries two optional state augmentations in one slot behind 21 branches; seed policy duplicated in seven modules. |
| Experimental validity | Excellent protocol (ledger, pre-registered gates, held-out block spent once, n_eff-aware intervals). Weakened by CN-01 (shared streams) and CN-02 (unguarded sweeps). |
| Tests and CI | Very strong; documentation numbers are checked by CI. Suite takes about 10 min with xdist. |
| Security | SHA-pinned actions, scoped permissions, pip-audit, SBOM, history secret scan; Pages build job over-privileged (CN-15). |
| Product maturity | SRS, risks, roadmap, an ADR series; SRS status section stale (CN-03); six ADRs await a decision with merged code. |
| Documentation | Rigorous but dense; first screen hard for non-experts; some unscoped physical-cause wording (CN-12). |
| Visual quality | Strong generated hero figure and GIF; no plain-language framing, no feed format. |
| Readiness for a first read | High for technical reviewers; low for a 60-second reader until #256. |

## 4. Subsystem inventory

Appendix section (b).

## 5. Strengths worth preserving

Appendix section (c) and NAD-01 to NAD-10.

## 6 to 10. Findings register

| ID | Sev | Class | Finding | Issue |
|---|---|---|---|---|
| CN-01 | P2 | Confirmed defect | GNSS and visual rotation noise share one random stream at equal seeds (195 of 453 GNSS normals reappear) | #251 (decision) |
| CN-02 | P2 | Confirmed gap | `navkit sweep seeds/outages` run held-out seeds without a guard; constants duplicated | #252 |
| CN-03 | P2 | Confirmed gap | SRS "current acceptance status" stale: true tally 7 pass, 4 fail, not 9 and 2 | #253 |
| CN-04 | P3 | Likely issue | "2σ coverage" names two statistics; AC-04 applies 95% to the 99.3% one | #253 |
| CN-05 | P3 | Likely issue | Anchor-model `c_t` is exact under its own convention, not the documented one; translation omits `[t]x c_t` | maintainer question (appendix f.4); no ticket |
| CN-06 | P3 | Confirmed defect | Second `run()` on one filter object carries logs and FDIR state | none (production builds a fresh filter); candidate A4 |
| CN-07 | P3 | Confirmed defect | Frozen-anchor cross-check rebuilds the fix without the GNSS GM term (path declared unreachable) | none |
| CN-08 | P3 | Confirmed defect | Generated fault-classification table: 6 headers, 7 cells | #254 |
| CN-09 | P3 | Confirmed defect | Separability prose contradicts its generated table | #254 |
| CN-10 | P3 | Confirmed defect | CONSTRAINTS interpreter label mismatch | #254 |
| CN-11 | P3 | Confirmed gap | First-read pages understate UrbanNav (real receiver fixes) | #254 |
| CN-12 | P3 | Likely issue | Surrogate fault classes described as physical causes | #254 |
| CN-13 | P3 | Confirmed gap / Unverified | EuRoC not cited; derived per-frame rows committed (licence question) | #254, parent #250 |
| CN-14 | P3 | Confirmed gap | Six proposed ADRs with merged code | parent #250 |
| CN-15 | P3 | Strategic opportunity | Pages build job holds deploy permissions | #255 |
| CN-16 | P3 | Confirmed defect | Docstring typo `eskf.py:31` | #254 |

## 11. Documentation inconsistencies

CN-03, CN-08 to CN-12; CONSTRAINTS describes B1 as both "closed as characterised" and "Open, work
stopped" (parent #250).

## 12. Product and usability

The decision framing ("Should camera aiding be on when GNSS is denied? No, because it is
confidently wrong") is the clearest product decision in the project, and it is backed by a
pre-registered gate. The intended user (a navigation or autonomy engineer deciding whether to
trust a filter's uncertainty) is implicit; one sentence would make it explicit. The SRS is the
weakest product artifact because its status section is typed (CN-03).

## 13. Visual presentation

Existing: `docs/figures/hero.png`, `hero.gif`, `docs/assets/social-preview.png`, generated study
figures, MkDocs Material site on Pages. Gap: the first screen speaks to experts only. Workstream:
#256.

## 14. Prioritised recommendations

1. #252 (P2, S to M): cheapest protection of the most valuable asset, the held-out protocol.
2. #251 step 1 (measure CN-01 on development seeds), then the maintainer decision.
3. #253 (P2, M). 4. #256 (P2, M). 5. #254 (P3). 6. #255 (P3, XS).

Do not build now: a new visual-aiding candidate, pose graph or sliding window (named as the
structural fix but a large research effort), more fault classes. Consolidating docs (#119) is
worth more than new pages.

## 15. Existing issue mapping

| Issue | State before | Audit view | Action |
|---|---|---|---|
| #182, #184, #185 | Open | Code slices #242, #244, #245 closed; commits `fc19ddf`, `ab43cdd`, `08428df` on `main` | Recommend maintainer verify and close (parent #250); not closed by the audit |
| #186 | Open | Slice #243 closed; `3d12bbd` adds attribution variants | Same |
| #181 Integrity record v2 | Open, ready-for-human | Consistent | No change |
| #166, #118 Dead-reckoning horizon, protection level | Open, research | High-value for the nav-trust-c2 link (an integrity output a supervisor can act on) | No change; see the roadmap |
| #116, #117 | Open, research | Consistent with B1 closure; low priority | No change |
| #119 Consolidate docs | Open | Supports readability | No change |

## 16. New issues

Parent #250; children #251 to #256.

## 17. Dependency graph

```
#251 step 1 (measure) ──> maintainer decision ──> #251 step 3 (switch streams) ──> regenerate #256 figure
#252 ──> natural home for #251's per-stream seeds
#253, #254, #255 independent
```

## 18. Quality gates

Before quoting NEES or coverage numbers in public material: #251 step 1 posted, so the effect of
the shared stream is known. Before any new held-out use: #252 closed.

## 19. Unverified

Effect size of CN-01; EuRoC licence for derived rows; branch protection settings; whether the
social preview image is uploaded in repository settings.

## 20. Handoff

Start with #252 (tdd). Use the worktree recipe in CLAUDE.md. Run `make docs-fast` and the full
suite once at the end. Never run seeds of 100 or more. ADR decision sections are maintainer-written.

---

## Appendix: independent source audit (verbatim)

### contested-nav: independent source-level audit

- Repository: `contested-nav` (fresh clone), commit `49d431064e49c06474c389cd70ff69a92c7f55b5` (verified with `git rev-parse HEAD`).
- Mode: read only. No repository file was changed (`git status --porcelain` empty before and after). No commit, no GitHub action.
- Held-out seeds: not touched. No command with seeds 100 and up was run. The pytest suite was inspected first: its held-out tests only exercise the refusals (`tests/test_b1_gate.py:279-289`, `tests/test_candidate_gate_cli.py:150-167`) with a ledger built in memory.
- Throwaway scripts (outside the repo): `(audit scratch) fd_check.py`, `.../reuse_check.py`, `.../seed_overlap.py`. Logs in the same folder (`pytest.log`, `docsfast.log`, `bench.log`, `benchmark.json`).

## (a) Check results

| Command | Result |
|---|---|
| `python3 -m venv /tmp/cnvenv && /tmp/cnvenv/bin/pip install -e ".[dev]"` | installed, no error |
| `ruff check src tests scripts` | `All checks passed!` |
| `ruff format --check src tests scripts` | `237 files already formatted` |
| `mypy src --ignore-missing-imports` | `Success: no issues found in 84 source files` |
| `python -m pytest -q -n 4 --dist loadfile -rs --durations=15` (the CI form, `.github/workflows/ci.yml:83`) | no failures, about 10 minutes, exit 0. The collected count is consistent with the "more than 2700" marker. |
| `make docs-fast PYTHON=python` | `metrics.json and every marker in the documents match`; no failures, about 2 minutes, exit 0 |
| `navkit run --out <scratch>/benchmark.json` then `python scripts/check_doc_tables.py --results <scratch>/benchmark.json` | 23 s; "documentation tables match ... (15 cases) in README.md, docs/results.md", Configuration tables and named-row tables match, exit 0 |

Notes on the test run.

- A first serial run (`python -m pytest -q`) reached about 7% after roughly ten minutes and was stopped; the suite was then run once to completion with xdist as CI does. This is the single complete run.
- The 36 skips are all data-dependent (EuRoC, TUM VI, UrbanNav not fetched; `results/benchmark.json` absent for `tests/test_doc_tables.py:145`; `tests/test_gm_tuning_page.py:252` "no candidate was frozen"). The 2 xfails are strict known-gap markers (`tests/test_known_gaps.py:70`, `tests/test_nis_monitor.py:886`).
- Slowest tests: `tests/test_vo_page.py` (three tests at 108 to 114 s each).

## (b) Subsystem inventory

| Subsystem | State | Evidence |
|---|---|---|
| 21-state ESKF (IMU propagation, GNSS position update, Joseph update, reset) | Implemented | `src/navkit/estimators/eskf.py`; FD checks below |
| Visual relative pose, single anchor (`vision_model: anchor`) | Implemented, known overconfident, shipped default model with vision disabled | `eskf.py:1146-1289`, ADR-0001, ADR-0003 |
| Visual relative pose, stochastic clone | Experimental, opt-in | `eskf.py:1291-1396`, ADR-0017, ADR-0030 S1 pass on dev seeds, S2 fail |
| Gauss-Markov visual error states (27 states) | Experimental, opt-in, failed on dev seeds | ADR-0034, ADR-0036 |
| Gauss-Markov GNSS error states (24 states) | Experimental, off by default, ADR proposed with no decision | `eskf.py:206-209`, ADR-0041 |
| Adaptive visual noise scale | Experimental, failed on dev seeds | ADR-0031, ADR-0032 |
| FDIR: chi-square gate, consecutive-rejection declaration, recovery, NIS window, bounded inflation, spoof lockout | Implemented | `src/navkit/fdir/` |
| FDIR: frozen-anchor cross-check (ADR-0008) | Implemented, unreachable (declared) | `docs/status.md:46` |
| Multipath signature | Partial: function exists, not wired into the filter | ADR-0022, `docs/multipath.md:5-6` |
| Fault classification (multipath / spoofing / degradation) | Experimental feasibility study, not shipped | `docs/fault_classification.md`, ADR-0021, ADR-0025 (proposed) |
| Calibration harness (NEES, ellipsoid coverage, Wilson on n_eff, ensemble band, B1 and ADR-0030 gates) | Implemented | `src/navkit/eval/calibration.py`, `src/navkit/eval/statistics.py`, `src/navkit/b1_gate.py`, `src/navkit/eval/candidate_gate.py` |
| B1 (vision under GNSS denial) | Closed as characterised, not solved; `vision_enabled` False | `eskf.py:370`, ADR-0036, CONSTRAINTS B1 block |
| Recorded IMU (EuRoC, TUM VI) with simulated GNSS | Implemented, data not vendored | `docs/euroc.md`, `docs/tumvi.md` |
| UrbanNav real F9P GNSS + recorded IMU | Implemented, ADR-0026 proposed with no decision | `docs/urbannav.md` |
| Two-view front end on real EuRoC frames | Experimental, measured once, not in CI | `docs/real_front_end.md:194` |
| Pose graph / sliding window | Planned only (named as the structural fix) | `eskf.py` module docstring, ROADMAP |
| Real-time loop, sensor drivers, lever arm, camera-IMU extrinsic | Out of scope (declared) | `eskf.py:148`, `docs/status.md` "Not flight-ready" |

## (c) Verified strengths

- Lint, format, strict type check and the full suite are green; the generated documentation tables match a fresh benchmark at this commit.
- Measurement Jacobians of the GNSS update and of the clone update (with and without the Gauss-Markov visual states) match central finite differences to 1e-10 (see NAD-03, NAD-04).
- Covariance stayed symmetric and positive semidefinite to rounding over 20000 steps in five configurations (NAD-05).
- The statistics are careful: exact integer-dof chi-square by incomplete gamma, Wilson intervals on an effective sample size (Sokal windowing, truncation flagged with a dagger), ensemble band on `floor(dof * sum n_eff)` degrees of freedom.
- The FDIR false-alarm study measures what the gate promises: 5 rejections in 3775 healthy GNSS updates (0.13%), Wilson 95% interval 0.057% to 0.31%, which contains the nominal alpha of 0.1% (`docs/data/fdir_false_alarm.csv`, `gnss_only,all,all` row).
- Held-out discipline is real: a ledger (`docs/data/heldout_ledger.csv`, one block used, 100-124), refusals in the gate code, the B1 status block generated from the decision CSV, and B1 recorded as "characterised, not solved".
- The overconfident single-anchor control row is preserved: `outage_visual` in `configs/benchmark.yaml:151-182` with `vision_model` defaulting to `anchor`, pinned by `tests/test_estimators.py:641` and quoted on README via generated markers.
- Supply chain basics are good: every action SHA-pinned, top-level `contents: read` in every workflow, no `pull_request_target`, release write permissions scoped to the tag-only job, weekly pip-audit, SBOM, history secret scan.

## (d) Findings

Severity scale: P0 wrong safety-relevant result shipped; P1 a published conclusion is wrong; P2 experimental validity or a published status is materially affected; P3 local, latent or documentation-level.

### CN-01 GNSS white noise and visual rotation noise reuse the same random draws when their seeds are equal

- Classification: Confirmed defect. Severity: P2. Confidence: high on the mechanism, low on the size of its effect (not measured).
- Evidence:
  - `src/navkit/sensors/models.py:173` `rng = np.random.default_rng(cfg.seed)` and `:178` `white = rng.standard_normal((len(t), 3)) * cfg.sigma_m` (GNSS).
  - `src/navkit/sensors/models.py:225` `rng = np.random.default_rng(cfg.seed)` and `:240` `rot_noise[1:] = rng.standard_normal((steps, 7))[:, :3] * rot_sigma` (vision rotation).
  - `src/navkit/benchmark.py:355-356` `scenario.gnss.seed = seed` / `scenario.vision.seed = seed` for every seeded run; `configs/benchmark.yaml` uses `seed: 0` for both streams in the base cases (for example lines 55 and 71).
  - `docs/MODEL.md:66` "Every stochastic stream has its own seed" and `:70` "`navkit sweep seeds` overrides all three streams with the same integer". ADR-0010 item 2 states the same intent.
- Observed: with equal seeds the two generators produce the same normal sequence. GNSS draw index `3k+a` and vision rotation draw index `7i+b` coincide, so many GNSS errors are exact scaled copies of visual rotation errors at other epochs.
- Reproduction: `python -I .../scratchpad/audit/seed_overlap.py` prints `gnss normals: 453 vision-rot normals: 1797 identical values shared: 195` and `first gnss draw 0.1257302210933933 == first vision rot draw 0.1257302210933933 True`.
- Expected: independent sensor noise streams, as the filter assumes and ADR-0010 intends. ADR-0033 already gave the translation noise its own `SeedSequence([seed, TRANSLATION_NOISE_STREAM])` stream (`models.py:243`), so the remedy pattern exists.
- Recommended fix: derive every sensor stream from `SeedSequence([seed, STREAM_ID])` with distinct ids (GNSS, vision rotation, camera drop, rereference). This changes every committed number, so it needs an ADR-0010 amendment by the maintainer and a full regeneration; ADR-0028 records the B1 decision on the old streams and that result should stand as dated history.
- Acceptance criteria: a test asserts that at equal seeds the GNSS and visual noise arrays share no values; all generated tables and the golden snapshot regenerated; a one-line note in the calibration page says which results were produced on the shared-stream fixture.

### CN-02 Generic sweeps can run unused held-out seeds without any guard

- Classification: Confirmed gap. Severity: P2. Confidence: high (code read; not executed, to protect the seeds).
- Evidence: `src/navkit/seed_sweep.py:95` `ap.add_argument("--seeds", type=int, default=10, help="number of seeds, starting at 0")` and `:154` `for seed in range(args.seeds):`; `src/navkit/outage_sweep.py:188` and `:218` the same pattern. A grep for `held|reserv|SEED_LIMIT` returns 0 hits in `seed_sweep.py`, `outage_sweep.py`, `ensemble.py`, `fault_matrix.py`, `mismatch_sweep.py`, `multipath_study.py`, `slow_ramp.py`, `vision_ramp.py`, `benchmark.py`, `attribution.py`. The policy constants are instead duplicated per module: `b1_gate.py:39`, `candidate_gate.py:55,59`, `correlated_gnss_study.py:53`, `start_draw_study.py:48`, `fdir_false_alarm.py:60`, `scale_tuning.py:65`.
- Observed: `navkit sweep seeds --seeds 150` would run seeds 100 to 149, which includes the unused block 125 to 149 that CONSTRAINTS B1 says "stay unused".
- Expected: no code path runs a seed of 100 or more without the explicit held-out procedure of ADR-0028 / ADR-0030.
- Reproduction (read only, do not run with a large count): `grep -n "range(args.seeds)" src/navkit/seed_sweep.py src/navkit/outage_sweep.py`.
- Recommended fix: one seed-policy module (see architecture candidate A2) with `require_development(seeds)`; call it from every sweep CLI, and either from `run_case` or from a single sweep adapter.
- Acceptance criteria: `navkit sweep seeds --seeds 101` and `navkit sweep outages --seeds 101` exit 2 with a held-out message; one test walks every sweep entry point with a seed of 100 and expects a refusal; the duplicated constants are imported from one place.

### CN-03 The SRS "current acceptance status" is stale and contradicts the generated benchmark

- Classification: Confirmed gap. Severity: P2 (a published status page, in the MkDocs nav at `mkdocs.yml:174`). Confidence: high.
- Evidence: `docs/product_management/01_system_requirements_spec.md:416` `| AC-01 | < 3.0 m | 2.322 m | **PASS** |`, `:417` `| AC-02 | < 3.0 m | 2.008 m | **PASS** |`, `:418` `| AC-03 | ratio ≤ 2.0 | 95.4 (286.2 / 3) | **FAIL** |`, `:453` `**9 pass, 2 fail.**`; `docs/project-management.md:17` "Start with the SRS if you want one number: **AC-03 and AC-04 fail**". The document is dated `2026-09` (line 6) but the heading is "Current acceptance status".
- Observed at this commit (fresh `navkit run`, values that `check_doc_tables.py` confirms against README): `outage_visual` ATE RMSE 17.568 m, mean NEES full run 14018.6; `outage_visual_degraded_camera` ATE RMSE 7.434 m. AC-01 and AC-02 therefore fail their `< 3.0 m` thresholds, so the status is 7 pass, 4 fail, not 9 pass, 2 fail. AC-08 ("0 of 1212") also differs from the generated false-alarm study (5 of 3775 on `gnss_only`, seeds 0 to 24), which `docs/status.md:15-17` already describes as "not zero".
- Expected: either the table is generated, or it is labelled as dated history ("measured at <sha>").
- Recommended fix (maintainer-owned page, CLAUDE.md): relabel section 3.2 as measured at its date and add a generated current-status row set, or regenerate it from the benchmark JSON as the README tables are.
- Acceptance criteria: a docs test fails if an AC verdict in the SRS disagrees with the benchmark; `docs/project-management.md:17` agrees with it.

### CN-04 "2-sigma coverage" names two different statistics, and AC-04 applies a 95% threshold to the 99.3% one

- Classification: Likely issue. Severity: P3. Confidence: high on the facts, medium on the impact.
- Evidence: the calibration report uses the isotropic ellipsoid `squared <= 4 * dof` with expectation `P(chi2_3 <= 12) = 0.9926` (`src/navkit/eval/calibration.py:384-386`, `statistics.py` `ellipsoid_coverage` docstring), shown on README as "2σ-per-axis coverage ... (expected 99.3%)" (`README.md:48`). The B1 and ADR-0030 gates use the marginal per-axis share, expectation 0.9545: `src/navkit/eval/candidate_gate.py:164` `coverage = float(np.mean(np.abs(err_a) <= CANDIDATE_GATE_COVERAGE_SIGMA * sig_a))`, ADR-0028 "Coverage" definition. `docs/status.md:32-33` "a 2σ coverage of 5.0% where the SRS requires 95% (AC-04)", and SRS line 403 sets AC-04 at `≥ 95%` on "2σ ellipsoid coverage".
- Observed: the same label carries two expectations (99.3% and 95.4%). Under the ellipsoid convention a filter that is overconfident can still reach 95% and pass AC-04; the project's own `ellipsoid_coverage` docstring warns about exactly this.
- Recommended fix: name them distinctly ("2σ ellipsoid coverage" vs "2σ per-axis marginal coverage") everywhere, and set AC-04 against the expectation of the statistic it uses (maintainer decision).
- Acceptance criteria: no page uses "per-axis" for the ellipsoid statistic; AC-04 states its expected value.

### CN-05 Anchor-model Jacobians do not match the documented meaning of `c_t`, and the anchor translation omits the anchor attitude term

- Classification: Likely issue. Severity: P3 (the anchor model is the declared-broken control and vision is off by default). Confidence: high on the algebra, impact not measured.
- Evidence: `docs/MODEL.md:57` "`c_t` | error of the stored visual anchor attitude"; `eskf.py:1219-1221` comment "the predicted relative rotation is Exp(-c_t) R_rel_true"; but `eskf.py:1240` `H_rot[:, _IDX_CT] = -R_rel_pred @ rot_right_jacobian(x["c_t"])` and the anchor translation block `eskf.py:1265-1270` has `H_trans[:, _IDX_CP] = -R_prev.T` and no `c_t` column. The clone model, which treats the same states as the stored pose's errors, has `H_rot[:, _IDX_CT] = -np.eye(3)` and `H_trans[:, _IDX_CT] = _skew(t_pred)` (`eskf.py:1350`, `:1371`).
- Numeric result (`fd_check.py`, central differences, eps 1e-6, measurement generated from the perturbed true state):
  - anchor, under the convention that makes the code exact (`c_t` on the right of the relative rotation in the current frame, `R_meas = R_vk^T R_true Exp(-c_t)`): max |FD - H| 1.6e-11 (rotation), 1.4e-10 (translation). The code is self-consistent.
  - anchor, under the documented convention (true anchor attitude `R_vk Exp(c_t)`, as the clone uses): max |FD - H| 0.177 (rotation, column 19) and 0.910 (translation, column 19).
- Observed vs expected: the state is effectively a perturbation of the relative rotation expressed in the current body frame, not the anchor attitude error, and the translation measurement ignores the anchor attitude error, which removes the `[t]x c_t` variance (with the 5 degree anchor prior, about 0.087 times the inter-frame translation) and pushes towards overconfidence. With `vision_keyframe_interval: 1` (`configs/benchmark.yaml:31`) the state lives one update, which limits but does not remove the effect.
- Recommended fix: do not change the control row's behaviour silently (CLAUDE.md keeps it as the control). Correct the documentation of `c_t` for the anchor model, and if desired add the `[t]x c_t` column behind a flag and measure it as a new row, keeping the current row as the control.
- Acceptance criteria: MODEL.md and the `eskf.py:1219` comment describe the convention the code implements; a FD test of the anchor Jacobian against that stated generative model.

### CN-06 Reusing one filter object for two `run()` calls carries state across runs

- Classification: Confirmed defect (latent). Severity: P3 (every production caller constructs a fresh filter: `benchmark.py:404,406`, `euroc_eval.py:586`). Confidence: high.
- Evidence: `eskf.py:627` `self.fdir = FdirManager(config.fdir_config)`, `:633` `self.gnss_innovations ... = []`, `:635` `self.bias_log ... = []` are created in `__init__` only; `run()` (from `eskf.py:1429`) does not reset them or `fdir_inflations`, and `eskf.py:1637` `traj.metadata["gnss_innovations"] = self.gnss_innovations` hands out the same list object, so a second run also mutates the first result's metadata.
- Reproduction: `PYTHONPATH=src python .../scratchpad/audit/reuse_check.py` prints `gnss_innovations accumulated on shared object: 152` after two runs of 76 updates.
- Recommended fix: reset `gnss_innovations`, `bias_log`, `fdir`, `fdir_inflations` at the start of `run()`, and copy the lists into the metadata.
- Acceptance criteria: a test runs one instance twice and gets identical stats and metadata lengths.

### CN-07 The frozen-anchor cross-check reconstructs the fix without the GNSS Gauss-Markov term

- Classification: Confirmed defect (latent). Severity: P3 (the check is documented as unreachable, `docs/status.md:46`). Confidence: high.
- Evidence: `eskf.py:997` `p_meas = residual + x["p"]`, while with `gnss_gm_error` the residual is `p_meas - (p + e_gnss)` (`eskf.py:1139-1144`).
- Recommended fix: pass `p_meas` into `_frozen_anchor_disagrees` instead of reconstructing it.
- Acceptance criteria: a unit test with `gnss_gm_error=True` and a non-zero `e_gnss` gives the same distance as one built from the raw fix.

### CN-08 Generated fault-classification levels table has six header columns and seven cells

- Classification: Confirmed defect. Severity: P3. Confidence: high.
- Evidence: `src/navkit/fault_classification.py:351` header `| Class | Fault | Level | Runs | Called correctly | Called control (missed) |`, `:360` row with three percentages `{_pct(ok)} | {_pct(miss)} | {_pct(1.0 - miss)}`; committed in `docs/fault_classification.md:94` (for example the row `| control | none | 0 | 34 | 88% | 88% | 12% |`). The confirmation table at `fault_classification.py:414` has the seventh header "Detected (any fault called)".
- Observed: the rendered table drops or misaligns the detection column.
- Fix: add the seventh header and separator to `level_markdown`, regenerate the block.
- Acceptance: a page test asserts equal column counts for every generated table row and its header.

### CN-09 Typed prose on the separability page contradicts its generated table

- Classification: Confirmed defect. Severity: P3. Confidence: high.
- Evidence: `docs/separability.md:53` generated row `| walk10 -> file-walk10 | 3.6 | 6% | 13% | 50 m |`; `docs/separability.md:62` "At 5% false alarms on EuRoC it rejects 16% of honest TUM VI returns."
- Fix: generate the sentence from the same rows or quote the table (6% and 13%).
- Acceptance: a test ties the sentence to the CSV, as other pages do.

### CN-10 CONSTRAINTS ratchet header names a different interpreter from the generated coverage figure

- Classification: Confirmed defect. Severity: P3. Confidence: high.
- Evidence: `CONSTRAINTS.md:9` "on **CPython <!-- metric:coverage_python -->3.12<!-- /metric -->**"; `CONSTRAINTS.md:92` `| Ratchet | Floor | Current (CPython 3.13) | Re-measure with |`, whose line-coverage cell is the 3.12 metric. `docs/data/metrics.json` has `"coverage_python": "3.12"`.
- Fix: put the header interpreter behind the same metric marker.
- Acceptance: `scripts/metrics.py --check` covers it.

### CN-11 First-read pages say recorded-data runs use simulated GNSS only, while UrbanNav uses real receiver fixes

- Classification: Confirmed gap (understatement, not an overclaim). Severity: P3. Confidence: high.
- Evidence: `docs/status.md:3-5` "Recorded IMU data (EuRoC, TUM VI) and one set of real camera frames ... are used with GNSS simulated from the ground truth"; `README.md:25` "recorded IMU data (EuRoC and TUM VI) with GNSS simulated from the ground truth"; but `README.md:231` links "UrbanNav (real GNSS outage)" and `docs/urbannav.md` uses the u-blox F9P NMEA fixes and a real outage.
- Fix: add one clause on UrbanNav (real fixes, one recording, one receiver, not field performance) to both places.
- Acceptance: a front-page claims test mentions all three datasets and the GNSS source of each.

### CN-12 The "multipath" class is a white-noise injection, but pages state physical-cause conclusions

- Classification: Likely issue. Severity: P3. Confidence: medium.
- Evidence: `docs/fault_classification.md:11` "**Multipath**: extra white noise of 3, 10 or 30 m per axis on every fix for 20 s. No mean shift."; `:212` "**Multipath is separable.**"; `docs/multipath.md:15` "Multipath is noise on the fixes"; `docs/status.md:15` "Spoofing and degradation are called correctly in most injected runs". Real multipath is typically biased and time-correlated; the project itself labels its correlated GNSS bias "A surrogate, not a multipath model" (`docs/MODEL.md:246`). "Spoofing" is likewise a position step or ramp, which other causes (datum error, receiver jump) also produce.
- Observed vs expected: classifier labels are injected signatures; conclusions should be scoped to them ("white-noise inflation is separable from steps and ramps"), not to physical causes. The methodology sections are honest; the headline sentences are not scoped.
- Fix: rename the classes on the pages (for example "noise inflation (multipath surrogate)", "position step or ramp (spoof surrogate)") and scope the "What it shows" sentences.
- Acceptance: no first-read or study page states a physical cause without the surrogate qualifier.

### CN-13 Dataset attribution is incomplete for EuRoC, and derived per-frame EuRoC data is committed

- Classification: Confirmed gap (attribution); the licence question is Unverified. Severity: P3. Confidence: high on the attribution gap.
- Evidence: `grep -rn -i burri docs README.md src/navkit/io/euroc_fetch.py` returns nothing; `docs/euroc.md:29-30` gives the rights statement ("In Copyright - Non-Commercial Use Permitted") but no citation. `README.md:249` "Acknowledgements" names UrbanNav only; the TUM VI CC BY 4.0 attribution is on `docs/tumvi.md:32-34` only. `docs/data/vo_errors.csv` has 8903 per-frame rows derived from EuRoC MH frames and ground truth (`wc -l` 8904 with header), committed in an MIT repository. Note: `docs/attribution.md` is an error-attribution study, not dataset attribution.
- Fix: cite Burri et al. (IJRR 2016) on `docs/euroc.md` and in the README acknowledgements alongside TUM VI and UrbanNav; record the maintainer's reading of whether per-frame derived rows are permitted under InC-NC.
- Acceptance: each dataset has a citation and licence line in README and on its page.

### CN-14 Merged code and dependencies rest on ADRs whose decision section is empty

- Classification: Confirmed gap (governance). Severity: P3. Confidence: high.
- Evidence: ADR-0025, 0026, 0037, 0039, 0040, 0041 have `- Status: proposed` and "To be written by the maintainer." in the Decision section. ADR-0039 is "pytest-xdist in the dev extra", yet `pyproject.toml:39` already ships `pytest-xdist>=3.5` (and `pre-commit>=3.7`), while `CONSTRAINTS.md:72` lists the allowed dev tools as "pytest, Hypothesis for property tests, ruff and mypy". ADR-0026 (UrbanNav as a real GNSS dataset) is proposed while `docs/urbannav.md` and its code are live.
- Fix: maintainer decides or marks these as provisional on the pages that depend on them; extend the S1 list or make it explicitly non-exhaustive.
- Acceptance: no accepted behaviour depends on a proposed ADR without a visible note.

### CN-15 CI hardening opportunities

- Classification: Strategic opportunity. Severity: P3. Confidence: high.
- Evidence: `.github/workflows/pages.yml:14-17` grants `pages: write` and `id-token: write` at workflow level, so the `build` job (`pages.yml:26-41`), which runs `pip install -e ".[dev,docs]"` and project code, holds them although only `deploy` needs them. No `actions/checkout` step sets `persist-credentials: false`. Runtime dependencies are lower bounds only (`pyproject.toml:29-33`), and CI installs are not hash-locked.
- Fix: move `pages: write` and `id-token: write` to the `deploy` job; set `persist-credentials: false` on checkouts that do not push; consider a constraints file with hashes for CI.
- Acceptance: `build` runs with `contents: read` only.

### CN-16 Docstring typo in the process model

- Classification: Confirmed defect (documentation). Severity: P3. Confidence: high.
- Evidence: `eskf.py:31` `dv'    = dv - R [a]x dt dp_theta - R dt db_a`. The code (`eskf.py:821`) is `F[_IDX_V, _IDX_THETA] += -R @ _skew(a) * dt`, i.e. the term multiplies `dtheta`.
- Fix: `dp_theta` to `dtheta`.

### Not a defect (verified)

- NAD-01 State ordering and conventions. `[dtheta, dp, dv, db_g, db_a, c_p, c_t]` (`eskf.py:8-9` docstring and slices at `eskf.py:180-195`, `docs/MODEL.md:51-57`); right (body-side, local) attitude error `R_true = R Exp(dtheta)`; quaternions `(w, x, y, z)` with the Hamilton product (`geometry/rigid.py` `quat_mul`, `quat_to_matrix` is the active body-to-world matrix). Consistent with ADR-0004 and C1 to C3.
- NAD-02 Propagation F and Q. `F_pv = I dt`, `F_vtheta = -R [a]x dt`, `F_vba = -R dt`, `F_thetatheta = Exp(-omega dt)`, `F_thetabg = -I dt` (`eskf.py:816-824`, blocks at `:819-823`) are the correct first-order right-perturbation blocks. Textbook Q (`eskf.py:772-780`): `sigma_g^2 dt` on attitude, `sigma_a^2 dt` on velocity with `dt^3/3` and `dt^2/2` position terms, random-walk biases `sigma^2 dt`; isotropic noise makes the missing `R` rotation exact. Gauss-Markov blocks use the exact `exp(-dt/tau)` and `sigma^2 (1 - a^2)` via `expm1`. The legacy form stays as a strict xfail (`tests/test_known_gaps.py:70`).
- NAD-03 GNSS Jacobian. No lever arm (declared, `docs/urbannav.md` "antenna offset ... is not corrected"). FD: max |FD - H| 1.4e-10 for 21 states and for 24 states with `gnss_gm_error`.
- NAD-04 Clone visual Jacobians (stochastic cloning). FD max |FD - H|: rotation 3.5e-11, translation 1.2e-10; with the Gauss-Markov visual states (27 states) 3.5e-11 and 1.3e-10. The clone covariance copy `P' = T P T^T` (`eskf.py:735-740`) preserves the live-to-clone correlation.
- NAD-05 Joseph form and reset. `G @ (I-KH) P (I-KH)^T + K R K^T @ G^T` (`eskf.py:1069`). `G = I - 0.5 [dx_theta]x` matches the FD derivative of `Log(Exp(-a) Exp(dtheta))` to 1.7e-4 at |a| = 0.036 rad, which is the expected second-order residual. Long-run health, 20000 IMU steps with GNSS at 10 Hz and vision at 20 Hz: minimum eigenvalue at worst -1.9e-16 and relative asymmetry at worst 2.9e-15 across gnss only, anchor vision, clone vision, gnss GM, clone with vision GM.
- NAD-06 Chi-square, NEES and coverage arithmetic. Tabulated thresholds match exact quantiles; NEES is position-only with `dof = 3`; the per-run bulk verdict uses `chi2(n_eff * dof) / n_eff`; ensemble band `chi2_ppf(.., N * dof) / N`; Wilson intervals on `n_eff` (`calibration.py:232-240`). Correlation is handled, and the truncated `n_eff` (22 of 25 held-out runs, `docs/data/b1_gate_heldout.csv`) is flagged, not hidden.
- NAD-07 B1 representation and held-out separation. `vision_enabled: bool = False` (`eskf.py:370`); ADR-0036 "closed as characterised, not solved"; held-out decision 1.176 against a lower bound of 1.32 (failed as too conservative), recorded in CSV, ledger and generated status block. The note that it ran before ADR-0033 is present.
- NAD-08 Unsafe I/O. Only `yaml.safe_load`; no pickle, no `eval`; `ast.literal_eval` only in `scripts/check_srs_trace.py:187`. TUM VI tar and EuRoC zip extraction write to fixed target paths, not member names (`io/tumvi_fetch.py:88-131`). UrbanNav has no publisher checksum and records a first-seen SHA-256, as its docstring states.
- NAD-09 Secret grep. `git grep -nE '(ghp_|AKIA|BEGIN .*PRIVATE|api[_-]?key|/Users/|/home/[a-z])'` matches only the scanner's own patterns (`scripts/scan_secrets.py:32-33`), synthetic test tokens built by concatenation (`tests/test_scan_secrets.py:30-57`) and container paths `/home/agent` in `.sandcastle/Dockerfile`. No credential found.
- NAD-10 FDIR semantics are declared honestly. "Isolation" means excluding the gated channel, and `fdir_manager.py:31-40` says it does not diagnose the cause; the ESKF docstring documents the case where vision corrupts the state and GNSS is the channel rejected. ADR-0008 is declared unreachable. Inflation adds to diagonal entries only (`P[idx, idx]` fancy indexing).

## (e) Architecture candidates

Hot spots over the last 150 commits (`git log -150 --name-only`): `CONSTRAINTS.md` 18, `docs/data/metrics.json` 17, `ROADMAP.md` 12, `ci.yml` 9, `urbannav_run.py` 8 (987 lines), `mismatch_sweep.py` 7, `fault_matrix.py` 6, `cli.py` 6. The largest module is `estimators/eskf.py` (1648 lines).

- A1 State layout as a deep module. Strength: Strong. Today the error-state layout is fixed slices plus two optional augmentations that share one slot (`eskf.py:203-209`), selected by `self._gm` / `self._gg` (`eskf.py:625`) and 21 `if self._gm` / `if self._gg` / `if gm` branches across initial covariance, Q, F, H, injection, reset and stats. The shared slot is the only reason `gnss_gm_error` and `vision_gm_error` are refused together (`eskf.py:514`). A small `StateLayout` module with named blocks, where each augmentation contributes its F, Q, H columns, injection and reset rows through one interface, would give depth (callers ask for `layout["e_gnss"]`), locality (a new block touches one file) and leverage (the GNSS and visual models could coexist). It respects ADR-0001, 0017, 0034 and 0041 because the numerics do not change; the existing FD tests are the seam to prove it.
- A2 Seed policy as one module. Strength: Strong. Held-out ranges are encoded in at least seven modules (CN-02) and absent from the generic sweeps. A `navkit.seeds` module owning `DEVELOPMENT`, `SPENT`, `next_block(ledger)` and `require_development(seeds)`, used through a single sweep adapter, concentrates the ADR-0028 / ADR-0030 protocol at one seam and closes CN-02. It is also the natural home for the per-stream `SeedSequence` derivation of CN-01.
- A3 Finish the ADR-0038 report migration. Strength: Worth exploring. Nine study modules use `navkit.report.runner`; fourteen modules with a `--page` option do not (`b1_gate`, `candidate_gate`, `correlated_gnss_study`, `ensemble`, `euroc_compare`, `gm_tuning`, `gm_usefulness`, `multipath_study`, `scale_tuning`, `timing_check`, `urbannav_check`, `urbannav_fix_errors`, `urbannav_run`, `vo_error`). ADR-0038 already chose expand-contract; finishing it would let one table writer enforce header and row widths (CN-08) and tie prose to rows (CN-09).
- A4 Typed `RunResult` instead of shared mutable metadata. Strength: Speculative. `traj.metadata` carries innovations, bias log, FDIR events and integrity records by reference (CN-06). A frozen result record per run would remove aliasing; low priority because production callers construct a fresh filter.

## (f) Open questions

1. CN-01: what is the size of the effect of the shared GNSS and visual draws on the published NEES and coverage? A dev-seed rerun with separated streams would answer it; it changes every committed number, so it is a maintainer decision.
2. Does the maintainer intend AC-04 to use the ellipsoid or the marginal per-axis statistic, and with which expectation?
3. Is committing per-frame rows derived from EuRoC (`docs/data/vo_errors.csv`) compatible with the "In Copyright - Non-Commercial Use Permitted" statement in an MIT repository?
4. Should the anchor control row keep its current `c_t` convention (documented as such) or gain the `[t]x c_t` coupling as a separate, measured row?
5. ADR-0026, 0039 and 0041: which of them does the maintainer accept, given that their code is merged?
6. CONSTRAINTS B1 says both "closed as characterised" and "Current status. Open, work stopped". ADR-0036 asks for the second wording in CONSTRAINTS; a one-line reconciliation would help readers.
