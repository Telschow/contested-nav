# Risk register

What could make this project wrong, unreproducible, unsafe to share or unfinished, what is
already done about it, and what is next. It is a working list. Entries marked **Occurred**
happened during this project and link to the evidence.

**How to read it.** Likelihood and impact are my qualitative judgements (Low, Medium, High),
not measurements. Status is one of: **Occurred** (it happened, with the fix noted), **Open**
(not yet mitigated), **Mitigated** (a control exists and is checked), **Accepted** (a
deliberate decision to live with it). A risk's status changes only with evidence.

| ID | Risk | Likelihood | Impact | Status |
|---|---|---|---|---|
| R1 | Results are read as field performance | High | High | Mitigated |
| R2 | Visual fusion is overconfident under GNSS denial | High | High | Accepted |
| R3 | Estimator and generator share a conceptual error | Medium | High | Open |
| R4 | A secret reaches the repository history | Low | High | Occurred |
| R5 | Numbers differ across platforms and break CI | Medium | Medium | Occurred |
| R6 | A snapshot or generated artefact goes stale | High | Medium | Occurred |
| R7 | Tooling drift changes a gate without a code change | Medium | Medium | Occurred |
| R8 | A third-party service fails a check for reasons unrelated to the code | Medium | Low | Occurred |
| R9 | Documentation claims drift from the code | High | Medium | Mitigated |
| R10 | Fault modes the simulator can inject are never measured | High | Medium | Open |
| R11 | Known model defects change published numbers when fixed | High | Medium | Open |
| R12 | Single maintainer | High | Medium | Accepted |
| R13 | Supply chain: unpinned or unattested artefacts | Low | High | Open |
| R14 | Defense-adjacent framing is misread | Medium | High | Mitigated |
| R15 | Scope creeps into SLAM, drivers or learned models | Medium | Medium | Mitigated |
| R16 | The published site is broken and nobody notices | Medium | Low | Open |
| R17 | Prioritisation inputs are wrong | High | Medium | Accepted |

## Details

### R1. Results are read as field performance
- **Cause and effect.** Every input is synthetic, so a reader quotes a number as if it were a
  measurement of a real system.
- **In place.** "Not field validated" is on the README, the social preview and
  [Scope and responsible use](docs/scope.md). [LIMITATIONS](docs/defense/LIMITATIONS.md) L1 and
  L5 state what the data cannot support. [REAL_SYSTEMS](docs/REAL_SYSTEMS.md) lists the
  sim-to-real gap.
- **Early warning.** A quoted number in a doc or issue with no scenario name next to it.
- **Next.** P5-01 and P5-02 add the mismatch and fault evidence a real system would need first.

### R2. Visual fusion is overconfident under GNSS denial
- **Cause and effect.** The single-anchor filter cannot represent correlated visual drift, so
  it reports a small uncertainty while being wrong (headline case: the `outage_visual` row in
  [Results](docs/results.md), mean NEES in the hundreds against an expected 3).
- **In place.** `vision_enabled` ships off ([ADR-0003](docs/adr/0003-ship-visual-disabled.md));
  the failing case is a benchmark row and a pinned test, not a hidden one.
- **Status reason.** Accepted: it is the project's subject. A stochastic clone of the previous pose is
  calibrated on the fixture when the visual errors are independent, and is kept opt-in
  ([ADR-0017](docs/adr/0017-stochastic-clone-for-the-visual-update.md)): it is not calibrated when they are
  correlated over a couple of seconds, and no data here says which a real front end has. So the shipped
  configuration is unchanged and the risk stays accepted.
- **Early warning.** Any change that moves the NEES or coverage of `outage_visual`.

### R3. Estimator and generator share a conceptual error
- **Cause and effect.** One author wrote the filter, the generator and the metrics
  ([LIMITATIONS](docs/defense/LIMITATIONS.md) L10), so a shared wrong assumption would pass.
- **In place.** The generator is analytic and its IMU output is checked against closed-form
  kinematics; Jacobians are checked against finite differences; the filter is told the true
  noise, which is itself a weakness (MODEL.md finding 5).
- **Next.** P5-01 breaks the "filter knows the true noise" assumption. P5-11 would add an
  independent estimator; it is not done. The stochastic clone is a live example: it is calibrated against a
  visual surrogate whose errors are independent, the assumption the filter makes, and it fails when the
  generator's errors are correlated. The stress cases in the benchmark push on that; a real front end would
  settle it.

### R4. A secret reaches the repository history
- **What happened.** A provider API key was committed in an early commit. It was rotated by
  the maintainer; the value is still readable in history (`SECURITY.md`, section "Known incident").
- **In place.** `scripts/scan_secrets.py` runs in CI including history; the one known value is
  listed as accepted by commit and rule name, never printed.
- **Residual.** History was not rewritten. The key is rotated, so the exposure is closed, but
  the string remains visible.

### R5. Numbers differ across platforms and break CI
- **What happened.** The claimed-sigma series differed by 1.1e-8 between runners and turned
  test legs red ([#33](https://github.com/Telschow/contested-nav/pull/33)).
- **In place.** The IMU is analytic so it does not depend on platform trigonometry; the golden
  snapshot compares with stated tolerances ([ADR-0009](docs/adr/0009-cross-platform-numerics.md));
  CI runs Linux, macOS and Windows.

### R6. A snapshot or generated artefact goes stale
- **What happened.** Two merged changes disagreed about the golden file and `main` went red
  ([#28](https://github.com/Telschow/contested-nav/pull/28)). Documented test counts also fell
  behind ([#38](https://github.com/Telschow/contested-nav/pull/38)).
- **In place.** Generated tables are checked against a fresh benchmark in CI and on every Pages
  deploy; the golden file has a regeneration procedure in
  `CONTRIBUTING.md`.
- **Residual.** Hand-typed counts in prose still go stale until someone re-measures them.

### R7. Tooling drift changes a gate without a code change
- **What happened.** An unpinned linter went from 14 to 131 findings with no change in this
  repository, which is why CI installs the pinned extras (see the comment in
  `.github/workflows/ci.yml`). MkDocs Material warns that MkDocs 2.0 removes plugins; the docs
  extra pins `mkdocs<2`.
- **In place.** Pinned extras, SHA-pinned actions, Dependabot for actions, pip and docker.
- **Next.** Review Dependabot [#5](https://github.com/Telschow/contested-nav/pull/5) (P5-12).

### R8. A third-party service fails a check for reasons unrelated to the code
- **What happened.** The `github-advanced-security` check failed on every pull request with a
  402 monthly-quota error from GitHub's own code-scanning job.
- **In place.** It is excluded from the recommended required checks in
  `CONTRIBUTING.md`, section "Branch protection".

### R9. Documentation claims drift from the code
- **In place.** `scripts/check_doc_tables.py`, `tests/test_model_doc.py`,
  `tests/test_scenarios_doc.py`, `tests/test_rice.py` and the link checker each turn a class
  of claim into a failing test.
- **Residual.** Prose that quotes a number with no generator behind it. The early baseline
  records are excluded from the public site for this reason (P5-09).

### R10. Fault modes the simulator can inject are never measured
- **Cause and effect.** The FMEA-lite table in [MODEL.md](docs/MODEL.md) shows spoofing, slow
  GNSS bias, IMU loss, timestamp offsets and vision outages as unit-tested only. One spoofing
  case (a modest offset after an outage) is an open problem with an expected-failure test.
- **Next.** P5-02 measures them and reports detection and false-alarm rates.

### R11. Known model defects change published numbers when fixed
- **Cause and effect.** MODEL.md records six as-implemented findings (inert bias sigmas,
  mis-named drift keys, no velocity process noise and others). Fixing any moves the golden
  snapshot and so every published number.
- **Next.** P5-04 and P5-05, each with a deliberate regeneration and a review of the diff.

### R12. Single maintainer
- **Cause and effect.** One person owns every path (`.github/CODEOWNERS`). GitHub
  does not let an author approve their own pull request, so review is by CI only.
- **Status reason.** Accepted for a portfolio project. The mitigation is that the gates, not a
  person, are the reviewer, and that decisions are written down as ADRs.

### R13. Supply chain: unpinned or unattested artefacts
- **In place.** SHA-pinned actions, dependency review, `pip-audit`, a CycloneDX SBOM, CodeQL.
- **Not done** ([ADR-0011](docs/adr/0011-ci-and-supply-chain.md)): signed releases or build
  provenance, a base image pinned by digest. `uv.lock` exists but nothing uses it.
- **Next.** P5-10 before a tagged release.

### R14. Defense-adjacent framing is misread
- **Cause and effect.** The subject is navigation under contested GNSS. A reader could take
  the repository as operational or as controlled content.
- **In place.** Everything is synthetic, generic and unclassified; the README and
  [Scope and responsible use](docs/scope.md) say so; [DUAL_USE_ANALYSIS](docs/defense/DUAL_USE_ANALYSIS.md)
  records the reasoning.
- **Residual.** Wording is the control, so every new doc needs the same care.

### R15. Scope creeps into SLAM, drivers or learned models
- **In place.** The roadmap lists these as deliberately not planned, because the question is
  whether a classical estimator is honest about itself.

### R16. The published site is broken and nobody notices
- **In place.** `mkdocs build --strict` runs on every pull request and on every deploy.
- **Not verified.** Deploys succeed in Actions, but the live site has not been opened from the
  development environment, which cannot reach `github.io`. The maintainer should open it.

### R17. Prioritisation inputs are wrong
- **Cause and effect.** The RICE inputs are judgements, so the order can be wrong.
- **In place.** [Prioritisation](docs/prioritisation.md) states this, and shows how many
  single-input perturbations would change the top three.
- **Status reason.** Accepted: the score orders the argument, it does not settle it.

## Review

Update this file in the same pull request as the change that creates or retires a risk. Re-read
the whole list before tagging a release.
