# Implementation plan

Companion to [AUDIT.md](AUDIT.md). Finding IDs (`CI-01`, `TST-03`, ...) refer to the
findings table there. Nothing in this plan is started. Each phase ends with a stop
and a report, and the next phase begins only on approval.

**Sizing.** S under half a day, M 1 to 2 days, L 3 days or more, as relative effort,
not a promise. **One PR per logical change**, Conventional Commits, never push to `main`.

## Decisions I need from you

These change the plan, so I ask once here instead of in every phase. Defaults are what I
will do if you do not answer.

| # | Question | Default |
|---|---|---|
| Q1 | What name should appear as author in `pyproject.toml` and `LICENSE` (now "contested-nav contributors"), and with which git identity should I commit? History will not be rewritten, so older commits stay under the existing name. | Keep metadata as is until you answer. |
| Q2 | `CONSTRAINTS.md` S4 says "No employer or defence-sector framing in any public artefact", yet `docs/defense/` exists and the README links it. Amend S4 to match the positioning you want (my suggestion: "no employer framing; defense relevance is discussed only in `docs/defense/`, unclassified and source-cited")? | Amend as suggested, in its own PR. |
| Q3 | The existing docs contain 407 em dashes. Rewrite only the files I touch, or every file? Rewriting everything produces a large, low-value diff. | Only files I touch. |
| Q4 | `docs/architecture/demo.html` is 11 MB. Regenerate it smaller, or remove it from git and attach it to a release? | Regenerate under about 1 MB if feasible, otherwise move to a release. |
| Q5 | Replace the hand-written `docs/index.html` with an MkDocs Material site (your Phase 4)? This couples to `scripts/check_doc_tables.py`, which currently verifies cells inside `docs/index.html`, so the checker must be updated first. | Yes, with the checker ported in the same PR. |

## Mapping to the attached audit's tasks

| Audit task | Where it lands | Change from the audit |
|---|---|---|
| T-01 stabilise baseline | Phase 1A | Reframed: the real blocker is a red `main`, not stray files. No secret in the tree, key rotated. |
| T-02 harden local and CI gates | Phase 3 | Adds the demo-test fix first. Local ruff is currently failing. |
| T-03 requirements matrix | Phase 5 | Extend the existing SRS identifiers and add a checked link to tests. No parallel `REQ-SYS` scheme. |
| T-04 interface contracts | Phase 2 | Config and result-JSON schema doc, generated from the typed config. |
| T-05 scenario harness, fault docs | Phase 2 | Scenarios and fault injection already exist (`configs/`, `degrade/`). Adds an FMEA-lite doc and the outage-timing sweep. |
| T-06 security scanning, SBOM | Phase 3 | CodeQL and Dependabot already exist. Adds dependency review, pip-audit, SBOM, SHA pins. |
| T-07 README rewrite | Phase 4 | As specified. |
| T-08 PM package | Phase 5 | WBS, RAID, readiness assessment, decision log. Trade study exists already. |
| T-09 release v1.0.0 | Phase 5 | Target changed to v0.2.0. The project is Alpha and ships its headline feature disabled. |
| T-10 interview package | Phase 6 | As specified. |

## Phase 1: stabilise, then clean up

### 1A. Quick wins (unblock `main`)

| PR | Items | Size | Acceptance |
|---|---|---|---|
| 1 | TST-01, TST-02, CI-02: demo tests generate into `tmp_path`; add `artifacts/` to `.gitignore`; fix 33 ruff findings; format | S | A fresh clone passes `pytest` with 0 failures; `ruff check`, `ruff format --check`, `mypy` clean; all 7 CI jobs green on the PR |
| 2 | DOC-01, 03, 04, 05, 06: correct false and stale statements (test counts, 99.3%, ROADMAP Track C, CONSTRAINTS B2 and B3, SRS wording) | S | `check_doc_tables.py` passes; every number quoted has a command beside it |
| 3 | SEC-02, SEC-04: pin actions to SHAs with version comments; fix two contradictory comments | S | CI green; Dependabot still proposes updates |
| 4 | SEC-05, SEC-06, REPO-05, CODE-02, PM-02: neutral platform wording, S4 amendment (Q2), author metadata (Q1), name the `225.0` constant, archive old audit snapshots | S | No weapon-class platform named; `docs/audit/archive/README.md` explains the snapshots |

After PR 1 is merged and `main` is green, merge Dependabot PR 5 (ruff 0.16.10, mypy 2.4.0)
if CI passes with it.

### 1B. Refactor and performance (behaviour preserving)

Dependencies: 1A PR 1.

| ID | Work | Size | Depends on | Acceptance |
|---|---|---|---|---|
| P1-1 | TST-03: golden snapshot test of the full benchmark output (timing fields stripped) and of both sweeps at 3 seeds | S | PR 1 | Fails when any metric changes in the 6th significant digit; passes on 3.11, 3.12, 3.13 |
| P1-2 | CODE-01: split `_update` into gate, inflate, cross-check and apply steps | M | P1-1 | Golden test unchanged, bit for bit; coverage ratchet holds |
| P1-3 | CODE-03: split `fdir_manager.py` along its existing seams | M | P1-1 | As above |
| P1-4 | REPO-01, REPO-02: `navkit` console entry point (`run`, `sweep`, `figures`) wrapping existing script logic; use `uv.lock` in CI or delete it | M | P1-1 | `navkit run --case outage_visual` reproduces the README row; old script paths still work |
| P1-5 | PERF-01: `benchmarks/` script and `docs/PERFORMANCE.md` with measured before numbers; optimise trajectory interpolation only if the measurement justifies it | M | P1-1 | Before and after numbers from the committed script, on the same machine and Python version, with variance reported |

**Risks.** A refactor shifting a number silently (mitigated by P1-1). The audit found
no algorithmic bottleneck, so I will not promise a speedup; if the measured gain is
small, the performance doc will say that.

## Phase 2: simulation quality

Much of this phase already exists: seeded and deterministic runs, 7 named scenarios in
`configs/benchmark.yaml`, NEES, coverage and ATE metrics, bootstrap intervals, a 10-seed
and an 8-scene sweep, and noise, dropout and fault injection in `degrade/`. I propose no new realism features.
The work is the gaps.

| ID | Work | Size | Depends on | Acceptance |
|---|---|---|---|---|
| P2-1 | Hypothesis property tests: covariance symmetry and PSD, rotation orthonormality, no NaN, NEES non-negativity | M | P1-1 | Tests run in CI under a fixed Hypothesis seed profile, under 60 s added |
| P2-2 | Outage start and duration sweep (closes the open item at `README.md:411`), with bootstrap intervals and a results CSV | M | P1-4 | One command writes the table and figure; CI runs a reduced version twice and diffs |
| P2-3 | SIM-01: macOS and Windows test legs with a documented tolerance policy for floating point | M | PR 1 | Matrix green; any tolerance is justified in an ADR |
| P2-4 | Model assumptions page: units, frames, time stepping, seeding, limits. Config and result-JSON contract generated from the typed config (T-04). FMEA-lite for the fault modes already implemented | M | none | Every config key has a unit and default shown; checked against `EskfConfig` by a test |
| P2-5 | Visuals: one hero figure, a short GIF or MP4 under 5 MB, consistent palette, regenerated by one command; resolve REPO-04 per Q4 | M | P1-4 | `navkit figures` rebuilds every committed image; sizes listed in the PR |
| P2-6 | "Limitations and path to real systems" section: how the interfaces would map to ROS 2 topics and where the sim-to-real gap sits. A note only, since the roadmap marks a ROS bridge out of scope | S | none | Reviewed against `docs/defense/LIMITATIONS.md` for consistency |

**Acceptance for the phase.** One command regenerates every figure and table in the docs
from scratch, and CI fails if the committed copies differ.

## Phase 3: CI and quality gates

Existing: `ci.yml` (7 jobs), `codeql.yml`, `pages.yml`, `dependabot.yml`. Baseline CI wall
time from the last green run on `main` (`78df5df`, run 36775590074, workflow dispatch):
about 11 minutes end to end; the three test jobs took roughly 1 to 2 minutes each in the
failing run for `ef23a72`.

| ID | Work | Size | Acceptance |
|---|---|---|---|
| P3-1 | `.pre-commit-config.yaml` mirroring CI (ruff, ruff format, mypy), `Makefile` (`install test lint docs bench demo repro`), `Dockerfile` or devcontainer | M | `make install && make test` works from a fresh clone and in the container |
| P3-2 | `security.yml`: dependency review on PRs, scheduled `pip-audit`, secret scan including a custom rule for the `freellmapi-` key shape, CycloneDX SBOM as an artifact | M | Workflows green; a test PR adding a known-vulnerable pin fails dependency review |
| P3-3 | Governance files: CODEOWNERS, PR template, three issue templates (bug, feature, roadmap item), CODE_OF_CONDUCT, updated CONTRIBUTING and SECURITY, CHANGELOG kept in Keep a Changelog format | S | Files present; templates render in the GitHub UI |
| P3-4 | Link checker in CI for README and docs | S | Fails on a deliberately broken link in a test PR |
| P3-5 | Branch protection recommendation as exact settings, for you to apply | S | Written in `CONTRIBUTING.md`; I change no repository setting |
| P3-6 | Coverage: keep the project's tracer-based ratchet (constraint S1 forbids `pytest-cov`). No coverage badge unless a live source for it exists | S | Ratchet runs in CI; badge decision recorded |

**Demonstrating the gates.** I will open a throwaway PR containing one deliberate lint
error and one deliberate failing test, show the red checks, and close it unmerged. I will
ask before opening it.

## Phase 4: README, docs site, GitHub Pages

Depends on Phase 2 (hero figure, repro command) and Phase 3 (live badges).

| ID | Work | Size | Acceptance |
|---|---|---|---|
| P4-1 | README rewrite to the structure you specified. Headline result and hero figure in the first screen. Short "Scope and responsible use" section. Only live badges (CI, license, Python versions, docs) | M | A 60-second read yields problem, result and limit; every number passes `check_doc_tables.py`; quickstart timed from a fresh clone and recorded |
| P4-2 | MkDocs Material site (Q5): Getting Started, Concepts, Scenarios, API reference from docstrings, Evaluation, Performance, Roadmap, ADRs, Risks, FAQ, Changelog. Dark and light, Mermaid, copy buttons. Port `check_doc_tables.py` first | L | `mkdocs build --strict` passes; deployed to Pages by workflow; link checker green |
| P4-3 | ADRs: 8 exist. Add two: determinism and seeding policy; CI and supply chain strategy | S | Standard ADR format, linked from the site |
| P4-4 | Social preview image (1280x640) in `docs/assets/`, plus exact repo description and topics text for you to set | S | Image under 300 KB; text delivered in the phase report |

**Not verifiable from here.** Whether Pages is currently live and which source it uses.
I will check the settings page with you or via the workflow deployment URL.

## Phase 5: roadmap, program layer, features, release

| ID | Work | Size | Acceptance |
|---|---|---|---|
| P5-1 | Restructure `ROADMAP.md` into Now, Next, Later with a stated prioritisation framework (RICE or WSJF, inputs shown, no invented precision). Create labelled issues and milestones, and a board if the token allows. Ask before creating more than 15 issues | M | Every roadmap item links to an issue and every issue to a roadmap line |
| P5-2 | `docs/RISKS.md` (RAID log), WBS, decision log, success metrics definition. A technology-readiness table only with evidence-backed levels, written conservatively | M | Each risk has likelihood, impact, mitigation, owner and status; reviewed with you |
| P5-3 | Traceability check: SRS requirement IDs mapped to tests, enforced by a script in CI | M | CI fails if a requirement ID has no test or declared gap |
| P5-4 | Implement the top 2 to 3 features (agree after seeing the RICE table). Candidates below | L each | Each has an ADR first, tests, docs, changelog, one PR, linked issue |
| P5-5 | Release `v0.2.0` with notes from the changelog, SBOM attached, after your approval | S | Tag and release notes match the changelog |

**Feature candidates.** Chosen from items the repo itself already names, and excluding what
it declares out of scope (ROS, learned models, real drivers).

| Candidate | Source | Value | Risk |
|---|---|---|---|
| Stochastic cloning spike for B1, behind a flag, with go/no-go | `AUDIT.md`, `ROADMAP.md` Track B | Only path to the headline fix | May miss the gate; see audit section. Outcome is evidence either way |
| Make the ADR-0008 frozen-anchor cross-check reachable (N1) | `README.md:397`, audit snapshot | Closes a documented security gap | Interacts with ADR-0007 hysteresis |
| Classify fault cause: multipath, spoofing, degradation | `ROADMAP.md:198-203` | Moves FDIR from detection to diagnosis | Needs measured detection and false-alarm rates |

## Phase 6: cold review

Fresh clone, follow only the README, record time to first demo; check CI, Pages, links,
leftover debris; write `docs/audit/FINAL_REPORT.md` with before and after metrics; the
2-minute pitch and 10 interview questions grounded in the repo.

## Plan risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Refactor changes a number | Medium | High | P1-1 golden test lands first and gates every refactor PR |
| `check_doc_tables.py` couples to README and `docs/index.html` structure, so a docs rewrite breaks it | High | Medium | Port the checker before the rewrite (Q5) |
| macOS and Windows floating-point differences make the matrix flaky | Medium | Medium | Tolerance policy in an ADR; compare derived metrics, not raw bytes |
| B1 spike consumes the schedule | Medium | Medium | Time-box, define the gate in advance, keep behind a flag |
| Large doc diffs from style changes bury real changes | Medium | Low | Q3 default: rewrite only touched files |
| Residual key in history is found by a scanner | Low | Low | Key is rotated; add a custom scan rule so it is flagged knowingly, not silently |
| Pages or repo settings differ from what the workflows assume | Medium | Low | Verify with you in Phase 4 |
