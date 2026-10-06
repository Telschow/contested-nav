# Verified audit, 2026-10-06

Baseline: `main` at `ef23a72`. Every number below comes from a command run in a
clean virtual environment during this audit (CPython 3.13.16, NumPy 2.5.3,
Matplotlib 3.11.2). The commands are listed in [Reproducing this audit](#reproducing-this-audit).
Older files in this folder (`01-` to `06-`) are point-in-time snapshots from
2026-09-29 and are not updated here.

## Executive summary

**What is strong**

- The central result is honest and reproducible. With GNSS denied, enabling visual
  odometry cuts ATE RMSE from 3.782 m to 2.541 m while mean NEES rises from 4.1 to
  419.4 and 2 sigma coverage falls from 100.0% to 20.0%. I regenerated all seven
  benchmark rows and they match the README to the printed digit.
- Determinism holds. Two benchmark runs were identical after stripping wall-clock
  fields, and the README and `docs/index.html` tables match the generated JSON
  (`scripts/check_doc_tables.py`).
- Quality tooling is serious for a solo project: mypy clean on 29 source files,
  91.69% line coverage on the project's own tracer, `pip-audit` clean, CodeQL and
  Dependabot configured, 8 ADRs, and a requirements spec with per-requirement verdicts.
- The clean-room install works: `pip install -e ".[dev]"` took about 20 s with no
  undocumented step, and a wheel built from the tree installs and imports.

**What is weak**

- **`main` is red.** The CI run for `ef23a72` (run 37147284510) failed in `lint`
  (`ruff check`) and in all three `test` jobs. The `build`, `benchmark` and `sweeps`
  jobs were skipped, so the repo's strongest gates have not run on `main` since
  2026-10-03. I reproduced both causes locally.
- **A fresh clone fails 4 tests.** They read a gitignored directory, `artifacts/demo/`.
  The README says 613 tests pass. On a fresh clone I measured 608 passed, 4 failed,
  3 skipped, 2 xfailed.
- **Documentation has drifted from the code** in several places (see DOC-01 to DOC-07),
  and the README does not put a visual or the headline in the first screen.
- **The program layer is thin.** There are 0 GitHub issues, no board, no tags or
  releases, no risk register or WBS, and the roadmap is partly stale.
- **Supply chain hardening is partial.** Actions are pinned to tags rather than SHAs,
  and there is no dependency review, SBOM or provenance.
- **Open scientific blocker (B1).** Visual fusion under GNSS denial is still
  overconfident and ships disabled. This is documented honestly. See the
  [feasibility assessment](#b1-feasibility-assessment).

**Top 5 actions**

1. Make `main` green: fix the demo tests and the 33 ruff findings, then merge Dependabot PR 5 if its CI passes.
2. Remove false or stale claims (test counts, badges, `artifacts/` gitignore claim,
   duplicated banners, stale roadmap), and make every badge live or delete it.
3. Resolve public-surface issues: one borderline platform description, the author
   metadata, and the `S4` constraint that conflicts with `docs/defense/`.
4. Add the program layer: issues and a board linked from the roadmap, a RAID log,
   a WBS, and a traceability check that ties requirement IDs to tests.
5. Run a time-boxed spike on stochastic cloning for B1 with a go/no-go gate, after a
   golden regression test exists.

## Scores

| Dimension | Score | Justification |
|---|---:|---|
| Code quality | 4 | mypy clean, no `print` in `src/`, no bare `except`, no TODO markers, typed state. Deductions: `ErrorStateKalmanFilter._update` is about 200 lines mixing FDIR, inflation, a spoof cross-check, gating and the Joseph update (`eskf.py:494-690`); `fdir_manager.py` is 1096 lines and `eskf.py` 997; one magic number (`225.0`, `eskf.py:603`); a comment points to a file that does not exist (`.audit/findings.md`, `eskf.py:667`). |
| Performance | 3 | Adequate and unoptimised. Full 7-case benchmark takes 16.2 s on this machine. Per-sample Python loops over tiny NumPy calls dominate (profile below). Not a showcase blocker, and no performance doc or benchmark script exists. |
| Simulation validity | 4 | Seeded, fixed-step, analytic ground truth, deterministic (verified), bootstrap intervals with fixed seed, 10-seed and 8-scene sweeps. Limits, all stated by the repo: filter starts exactly at truth, synthetic only, one trajectory family, Gaussian noise, CI runs on Linux only so cross-OS determinism is unproven. |
| Testing | 4 | 617 tests, 91.69% line coverage, finite-difference Jacobian tests, xfails kept visible. Deductions: no property-based tests, no golden snapshot of benchmark output, 4 tests depend on an untracked directory, CI red. |
| Documentation | 3 | Unusually deep and self-critical. Deductions: contradictions and stale statements (DOC-01 to DOC-07), 497-line README with no hero visual, 407 em dashes across tracked text (against your style rule), no docs site build (hand-written `docs/index.html`). |
| Repo hygiene | 3 | Good `.gitignore`, pinned dev tools, `src/` layout, hatchling. Deductions: no console entry point or CLI (logic lives in `scripts/`), `uv.lock` committed but CI installs with pip and never uses it, runtime deps have lower bounds only, no PR or issue templates, no CODEOWNERS, an 11 MB HTML file in `docs/`. |
| Security and supply chain | 3 | Least-privilege `permissions:`, CodeQL, Dependabot (actions and pip), SECURITY.md, `pip-audit` found no known vulnerabilities. Deductions: a provider key literal exists in history (rotated per owner), actions on tags not SHAs, no dependency review, SBOM or provenance. |
| Showcase value | 3 | The story (accuracy improved, calibration failed, so the feature ships off) is memorable and rare. It is undercut by a red CI badge on the repo page, no hero visual, no tag or release, no issues, and README claims that do not survive a fresh clone. |

## Verification of the attached GitHub audit

| Audit item | Verdict | Evidence |
|---|---|---|
| F-01 visual fusion overconfident, disabled by default | **Confirmed** | `README.md:216-261`, `CONSTRAINTS.md:98-108`, `ROADMAP.md:215-243`. Pinned by `tests/test_estimators.py:581`. Line references in the audit are accurate. |
| F-02 benchmark reproducibility is a strength | **Confirmed, with a caveat** | Reproduced locally (identical runs, tables match). The CI jobs that check this (`ci.yml:106-216`) are skipped on `main` because `test` fails first. |
| F-03 "security scanning, SBOM and signed provenance are missing" | **Partially wrong** | CodeQL (`codeql.yml`), Dependabot (`dependabot.yml`), SECURITY.md and least-privilege permissions exist. Correct: no dependency review, no SBOM, no provenance, actions on tags. |
| F-04 "roadmap and ADRs but not a full PM package" | **Partially correct** | `docs/product_management/` holds a requirements spec, a SWaP-C trade study and an FDIR strategy. No WBS, RAID, TRL table, issues or board exist (grep and GitHub query). The audit missed that `ROADMAP.md:261` still says `docs/product_management/` does not exist. |
| F-05 "requirements, interface contracts, degraded mode analysis incomplete" | **Partially wrong** | The SRS has OUN, TR and AC identifiers, a traceability matrix (section 2) and per-requirement verdicts. The audit's `REQ-SYS-` scheme does not exist, so its `grep -R "REQ-SYS"` check would find nothing. Real gaps: no machine-checked link from requirement to test, no ICD style config and output contract, no FMEA. |
| REQ-SYS-001 deterministic benchmark | **Confirmed** | Two runs identical, 16.2 s. |
| REQ-SYS-003 refuse to claim calibration | **Confirmed** | Test exists at `tests/test_estimators.py:581`. |
| Summary risk 4: "local build not confirmed in a clean environment" | **Outdated** | `python -m build` produced sdist and wheel, and the wheel imported in a second clean venv. `CONSTRAINTS.md:110-117` (B2, B3) is the stale source of this belief. |
| Gap G6: no pre-commit, bootstrap, Docker | **Confirmed** | No `.pre-commit-config.yaml`, `Makefile`, `Dockerfile` or `.devcontainer`. |
| Gap G8 / T-09: release and v1.0.0 | **Confirmed gap, wrong target** | No tags exist. `pyproject.toml:21` classifies the project as Alpha, so v1.0.0 would contradict the repo's own claims. Proposed target is v0.2.0 (matches your Phase 5). |
| T-02 verification: ruff and mypy pass locally | **Wrong today** | mypy passes; `ruff check` reports 33 findings and `ruff format --check` flags 1 file. |
| T-03 new `REQ-SYS` IDs | **Redundant** | Extend the existing SRS identifiers rather than introduce a parallel scheme. |
| Summary: "README too technical, lacks executive readability" | **Confirmed** | 497 lines, two stacked disclaimer banners before the first table, first figure at line 191. |

Items I could not verify: GitHub Pages is live (the probe from this environment
returned no response, which proves nothing either way); repository-level settings such
as secret scanning, branch protection and Pages source; the contents of failed CI logs
(I read job and step conclusions, not log text).

## Prioritised findings

Most rows with IDs `CI-`, `TST-`, `DOC-`, `SEC-01` and `REPO-04` are things the
attached audit did not find. Severity: Critical, High, Medium, Low. Effort: S (under half a day), M (1 to 2 days),
L (3 days or more). Showcase impact: H, M, L.

| ID | Area | Finding | Evidence | Sev | Eff | Show | Proposed fix |
|---|---|---|---|---|---|---|---|
| CI-01 | CI | `main` CI is red: `lint` fails at `ruff check`, all `test` jobs fail at `Test`; `build`, `benchmark` and `sweeps` are skipped. | Run 37147284510 (job and step conclusions); local repro | Critical | S | H | Fix TST-01 and CI-02, then re-run. Merge Dependabot PR 5 after (its CI run is also red; I did not check why). |
| CI-02 | CI | 33 ruff findings (RUF001/2/3: ambiguous Unicode) plus 1 unformatted file, all from the last commit. | `scripts/generate_demo.py`, `tests/test_demo_generation.py`; `ruff check`, `ruff format --check` | High | S | H | Replace the Unicode punctuation, or add a documented per-file ignore as already done for sweeps (`pyproject.toml:101-106`). Run `ruff format`. |
| TST-01 | Testing | 4 tests fail on a fresh clone because they require `artifacts/demo/`, which is untracked and not in `.gitignore`. | `tests/test_demo_generation.py:22`; `.gitignore` has no `artifacts/`; README `:480` claims it is gitignored | Critical | S | H | Generate the demo into `tmp_path` inside a fixture (it takes about 8 s), or mark as slow. Add `artifacts/` to `.gitignore`. |
| TST-02 | Testing | A third skip exists (`tests/test_doc_tables.py:163`, needs `results/benchmark.json`). Docs list only 2 skips. | pytest `-rs` output | Low | S | Generate the benchmark in a fixture, or document the skip. |
| TST-03 | Testing | No golden snapshot of benchmark output, so a refactor that shifts a number is only caught by doc-table matching. No property-based tests. | `git grep` for golden and for the Hypothesis library: none | Medium | M | Add a timing-stripped golden JSON test before any refactor (Phase 1). Add Hypothesis for covariance symmetry, PSD and rotation invariants (Phase 2). |
| DOC-01 | Docs | README claims "613 passed, 2 skipped, 2 xfailed". Fresh clone measures 608 passed, 4 failed, 3 skipped, 2 xfailed. Badge is static text. | `README.md:29,111,336`; pytest run | High | S | Remove the static test badge, or generate it from CI. Quote counts only with the command that makes them. |
| DOC-02 | Docs | The disclaimer "synthetic evidence only" appears twice back to back, and a "Documentation" table is duplicated (`README.md:435-461`). | `README.md:21-24`, `32-35`, `435-461` | Medium | S | Merge during the README rewrite (Phase 4). |
| DOC-03 | Docs | Expected 2 sigma coverage is written as 99.3% and as 99.2%. The exact value is 0.99262, so 99.3% is right. | `README.md:49` vs `:307`; `CONSTRAINTS.md:100`; chi-square (3 dof) CDF at 12 | Low | S | Use 99.3% everywhere. |
| DOC-04 | Docs | `ROADMAP.md` says `docs/product_management/` does not exist and lists SWaP-C and SRS as not started. All three documents exist. | `ROADMAP.md:245-266` | Medium | S | Update Track C status. |
| DOC-05 | Docs | `CONSTRAINTS.md` B2 and B3 say no lint, typecheck or build has run locally. All three now run. | `CONSTRAINTS.md:110-117`; this audit | Medium | S | Move B2 and B3 to resolved. |
| DOC-06 | Docs | The SRS says `results/benchmark.json` is "committed". `results/` is gitignored. | `01_system_requirements_spec.md:39`; `.gitignore` | Low | S | Reword to "generated by". |
| DOC-07 | Docs | README says "No install step is required", then immediately shows `pip install -e`. Quickstart is not in the first screen. | `README.md:104-109` | Low | S | Rewrite quickstart (Phase 4). |
| DOC-08 | Docs | 407 em dashes across tracked text, against the writing rule for this project. Existing docs are not mine to rewrite silently. | `git grep -c` | Low | M | Decide scope (question Q3 in PLAN). I propose rewriting only what Phase 4 touches. |
| SEC-01 | Security | A provider API key literal remains in history in `fbeb429` (and as a removed line in the diff of `ccb812a`). It is redacted in the tree. Owner confirms it is rotated. | `git log -p` scan (value never printed) | High | S | Rotation done. Do not rewrite history without approval. Add a CI secret scan with a custom rule for this key shape, because the earlier gitleaks run was blind to it (`ccb812a` message). |
| SEC-02 | Security | Actions are pinned to tags (`@v7`, `@v4`...), not SHAs. `dependabot.yml:6` says "pinned by digest", `SECURITY.md:44` says tags. | `ci.yml:28` and 15 other `uses:` lines | Medium | S | Pin to SHAs with a version comment. Dependabot updates SHA pins. Fix the contradictory comment. |
| SEC-03 | Security | No dependency review, no SBOM, no provenance, no scheduled `pip-audit`. | `.github/` listing | Medium | M | Add `dependency-review-action`, a `pip-audit` job, a CycloneDX SBOM artifact on release. Attestation only if a release exists. |
| SEC-04 | Security | `codeql.yml` header comment says the query suite is the JavaScript set, but the workflow analyses Python. | `codeql.yml:3-5` | Low | S | Correct the comment. |
| SEC-05 | Public surface | `02_swapc_tradeoff_matrix.md:81` names "Loitering munition" as a representative platform. Platform limits are tagged `[brief]` (lines 89-90, 147, 165, 234), but no brief is in the repo, so the source is unverifiable. | `02_swapc_tradeoff_matrix.md:81`, `:89-90` | Medium | S | Replace with "small expendable multirotor", and label the limits as assumptions. |
| SEC-06 | Public surface | `CONSTRAINTS.md:69` (S4) says "No employer or defence-sector framing in any public artefact", yet `docs/defense/` and README link to a defense relevance document. | `CONSTRAINTS.md:69`; `README.md:93` | Medium | S | Decision needed (Q2 in PLAN): amend S4 to match the intended positioning. |
| REPO-01 | Repo | No console entry point, no CLI. All logic sits in `scripts/` with `sys.path` edits. | `pyproject.toml` has no `[project.scripts]` | Medium | M | Add a `navkit` CLI (`run`, `sweep`, `figures`) wrapping the existing script logic. |
| REPO-02 | Repo | `uv.lock` (293 KB) is committed but CI and docs use pip. A lockfile that nothing consumes is a drift risk. | `ci.yml:39`; `git grep "uv "` | Medium | S | Either use `uv sync --locked` in CI or remove the lockfile. |
| REPO-03 | Repo | No PR template, issue templates, CODEOWNERS, CODE_OF_CONDUCT, pre-commit, Makefile, Dockerfile or devcontainer. | `.github/` listing | Medium | M | Phase 3. |
| REPO-04 | Repo | `docs/architecture/demo.html` is 11,062,340 bytes. The 1920x1080 snapshot is 109 KB. | `ls -la` | Medium | S | Regenerate smaller (strip embedded frames), or keep out of git and attach to a release. Needs your decision (Q4). |
| REPO-05 | Repo | Authorship metadata is inconsistent: commits by "Daniel Telschow", `pyproject.toml:12` and `LICENSE:3` say "contested-nav contributors". | `git log`; files cited | Medium | S | Set your preferred name in `pyproject.toml` and `LICENSE`. Set your git identity for future commits. History is not rewritten. |
| CODE-01 | Code | `_update` combines gating, FDIR inflation, spoof cross-check and the Joseph update. | `eskf.py:494-690` | Medium | M | Extract pure helpers, protected by the golden test (Phase 1). |
| CODE-02 | Code | Magic threshold `225.0 # 15^2`; comment references nonexistent `.audit/findings.md`. | `eskf.py:603`, `:667` | Low | S | Move to `EskfConfig` with a name; fix reference to the right ADR or document. |
| CODE-03 | Code | Two modules near 1,000 lines (`fdir_manager.py` 1096, `eskf.py` 997). Long history-narrating comment blocks inside functions. | `wc -l` | Low | M | Split along existing seams after the golden test. |
| PERF-01 | Performance | No tracked benchmark script or performance doc. Profile of `outage_visual` (4.70 s under cProfile): `interpolate_trajectory` 1.28 s cumulative (27%), 206k `np.linalg.norm` calls, 63k `quat_to_matrix` calls. | cProfile run (see below) | Low | M | Add `benchmarks/` and `docs/PERFORMANCE.md` with before numbers. Optimise only what the numbers justify. |
| SIM-01 | Simulation | Cross-OS determinism is unverified (CI is Linux only), and the README's open items list varying outage timing and duration as not done. | `ci.yml` runs-on; `README.md:411-412` | Medium | M | Add a macOS and Windows test leg with tolerance-based comparison, and a parameter sweep over outage start and length. |
| SHOW-01 | Showcase | First screen has no visual and two banners. The best figure is at line 191. | `README.md` | High | M | Phase 4 rewrite, with the 4-panel result figure above the fold. |
| SHOW-02 | Showcase | No release, no tag, `[Unreleased]` only in the changelog. | `git tag`: empty; `CHANGELOG.md:10` | Medium | S | Tag `v0.2.0` after Phase 5, not `v1.0.0`. |
| PM-01 | Program | 0 issues, no board, roadmap not linked to issues. No RAID log, WBS or readiness table. | GitHub query; grep | High | M | Phase 5. Ask before creating more than 15 issues. |
| PM-02 | Program | `docs/audit/` already holds six snapshot files from an earlier audit with stale counts (for example 567 tests). | `docs/audit/01-executive-summary.md` | Low | S | Move to `docs/audit/archive/` with a README note, in the docs PR. |

## B1 feasibility assessment

This answers your question 4. It is my engineering judgment from reading
`src/navkit/estimators/eskf.py`, not a measurement. I have not prototyped it.

**Where the information is lost.** At each visual update the "previous" pose is a raw
copy of the filter state (`R_vk`, `p_vk`) treated as error-free to first order
(`eskf.py:721-727`), and the covariance between that copy and the live state is set
to zero at every commit (`_commit_anchor_covariance`, `eskf.py:399-433`). The code
comments already give the diagnosis: with zero cross-covariance the Schur complement
collapses to `P_pp`, so each relative measurement is treated as if it carried
absolute information.

**The standard remedy is smaller than a pose graph.** Stochastic cloning keeps the
previous pose as extra error states, with its cross-covariance, and uses a relative-pose
Jacobian with respect to both poses. The existing code already has what it needs:
`_update` is generic in `H` and `R`, the Joseph form is in place, and the 6 clone error
states could occupy the slots now used by `c_p` and `c_t`, so the state stays 21 wide
and the NumPy-only constraint (S1) holds. The roadmap names a pose graph or multi-anchor
filter (`ROADMAP.md:228-229`); I consider cloning the cheaper first step with the same
key property. Treat that as a hypothesis to test.

**Difficulty: medium for a spike, large for full integration.**

| Piece | Sizing |
|---|---|
| Spike behind a config flag, with go/no-go measured on `outage_visual` | M |
| Full integration, tests, ADR, docs, FDIR interaction | L |

**Risks, in order of importance**

1. **It may not meet the gate.** Relative-pose-only fusion has unobservable global
   position and yaw. A standard linearised filter can still gain spurious information
   there, which the README attributes to Hesch et al. (2014). Cloning fixes the missing
   correlation, not necessarily this. If it persists, the next step is first-estimate
   Jacobians or an observability-constrained update, which is more scope. The gate in
   the roadmap (mean NEES below 10, coverage above 90%) is the repo's own proposal and
   unproven as achievable.
2. **Blast radius.** `c_p` and `c_t` appear in the FDIR inflation block, the
   ADR-0008 frozen-anchor cross-check (`eskf.py:586-597`), ADR-0001/0006/0007/0008, the
   four finite-difference Jacobian tests and the pinned B1 test. It must land behind a
   flag so the current model stays as the control row, which the roadmap already requires
   (`ROADMAP.md:238-240`).
3. **Regression safety.** There is no golden snapshot today (TST-03). Build that first.

**Recommendation.** Do not start before `main` is green and a golden test exists.
Then run the spike with a pre-agreed go/no-go: success means the gate is met in
`outage_visual` and holds across the 10-seed and 8-scene sweeps; failure is also a
publishable result ("cloning alone is insufficient, here is the measured residual").
From a program view this is the strongest "what I would do next" in the project, and
either outcome is evidence. For the portfolio, note that the documented, measured
limitation is already a strength; the fix is optional upside, not a prerequisite.

## Performance profile

Command: `python -m cProfile -o prof.out scripts/run_benchmark.py --only outage_visual`.
Total 4.70 s under the profiler (the unprofiled 7-case run takes 16.2 s, about 2.3 s per case).

| Self time (s) | Calls | Function |
|---:|---:|---|
| 0.376 | 206,313 | `numpy.linalg.norm` |
| 0.314 | 3,030 | `eval/statistics.py` `_lower_gamma_p` |
| 0.240 | 63,612 | `geometry/rigid.py` `quat_to_matrix` |
| 0.217 | 87,620 | `geometry/rigid.py` `quat_normalize` |
| 0.216 | 42,608 | `types.py` `_slerp` |
| 0.202 | 36,405 | `geometry/rigid.py` `rot_log` |

There is no algorithmic problem (no neighbour search, no quadratic loop). The cost is
per-sample Python overhead around small NumPy calls, concentrated in trajectory
interpolation (`types.py:368`, 1.28 s cumulative). A vectorised interpolation would
likely help, but at 16 s for the whole benchmark it is not a priority.

## Reproducing this audit

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"          # about 20 s
.venv/bin/python -m pytest -q -rsx                                 # 4 failed, 608 passed, 3 skipped, 2 xfailed, 93.5 s
.venv/bin/ruff check src tests scripts                             # 33 findings
.venv/bin/ruff format --check src tests scripts                    # 1 file
.venv/bin/mypy src --ignore-missing-imports                        # no issues, 29 files
.venv/bin/python scripts/run_benchmark.py --markdown --out a.json  # 16.2 s, 7 cases
.venv/bin/python scripts/check_doc_tables.py --results a.json      # tables match
.venv/bin/python scripts/coverage_report.py --ratchet              # 91.69% (3816/4162), 161 s
.venv/bin/pip install pip-audit && .venv/bin/pip-audit --local     # no known vulnerabilities
.venv/bin/python -m build                                          # sdist and wheel; wheel imports in a clean venv
python -m cProfile -o prof.out scripts/run_benchmark.py --only outage_visual
```

The README and `CONSTRAINTS.md` quote 91.66% coverage (3815 lines). This audit measured
3816 lines on the same denominator. The one-line difference is not investigated and does
not matter for any conclusion here.
