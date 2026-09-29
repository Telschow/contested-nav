# Research baseline


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29. Extracts what the repository claims to address, using the
taxonomy the project itself defines in `src/navkit/analysis/findings.py`:
`FACT` · `MEASUREMENT` · `INTERPRETATION` · `HYPOTHESIS`.

**No novelty claim is made in this document, and none should be inferred from it.**

---

## 1. Stated research question

From `docs/architecture.md`, the organising question is:

> The estimator is the test subject, not the product. `navkit` asks one
> question of a navigation filter: *is its stated uncertainty honest?*

`pyproject.toml` describes the package as "Replay, evaluation and uncertainty
calibration for GNSS-denied navigation". `README.md` states the commitment as
"a filter that reports its uncertainty should be correct about that
uncertainty."

**Refinement worth making explicit:** this is closer to a *measurement-methodology
research programme* than to a filter-design research programme. The deliverable
that matters is the instrument (calibration metrics, FDIR, claim typing, gates)
plus one worked demonstration of what the instrument reveals. The ESKF is the
subject, not the thesis.

---

## 2. Hypotheses

### 2.1 Stated hypothesis (explicit in the docs)

**H1 — Covariance collapse in a fused filter is structural, not a tuning defect.**

Under GNSS denial, a filter that fuses relative-pose visual measurements against
a single stored anchor cannot constrain that anchor's error, because the only
constraint on the anchor is the anchor itself. `P` therefore stops describing
reality, and when GNSS returns the filter is confidently wrong.

*Status: **experimentally demonstrated** for the existence and direction of the
failure; the causal attribution is a **hypothesis** with a stated falsification
test (§5).*

### 2.2 Implicit hypotheses (present in the design, not stated as hypotheses)

**H2 — A gate built on a calibrated innovation covariance is only as sound as
that covariance.** ADR-0005's chi-square gate assumes `S = HPHᵀ + R` is
calibrated. Once `P` collapses, the gate is arithmetically correct and
practically wrong. *Status: **MEASUREMENT** — this is blocker B5, closed by
ADR-0006.*

**H3 — Rejection count is a signal about the filter, not just the sensor.** A
single rejected epoch is ambiguous (multipath vs dead sensor); a sustained run
of rejections is evidence the *filter* is wrong. This is the NIS window monitor.
*Status: **implemented** (ADR-0006); its thresholds are **not** derived from a
formal optimum, so effectiveness is **MEASUREMENT** on synthetic cases only.*

**H4 — Spoofing is distinguishable from honest re-acquisition only by a second
independent modality.** After one inflated grant the innovation collapses to ~0
for both an honest return and a modest spoof, so no threshold on a single
channel's residuals can separate them. *Status: **MEASUREMENT** — 1.4σ overlap
below which no separator exists, per `docs/audit/05`.*

**H5 — Refusing a plausible-looking sensor is a smaller error than following it.**
ADR-0003's rule: a faulted channel is rejected outright rather than
noise-inflated, because inflating covariance until the innovation fits is the
mechanism that produces *confident* wrongness. *Status: **INTERPRETATION**,
backed by measurements on the 1–2 m case (49/60 rejections then fault).*

---

## 3. Claimed contributions

### 3.1 Engineering contributions (defensible as engineering)

| # | Contribution | Where | Status |
|---|---|---|---|
| E1 | 21-state ESKF modelling the visual anchor as filter state rather than measurement noise, so the anchor's error is a tracked unknown instead of an assumed-zero bias | ADR-0001 | **Implemented + measured.** The pre-fix configuration is retained as a regression control. |
| E2 | Joseph-form covariance with reset, PSD enforced by test | ADR-0002, C4 | **Implemented + tested** |
| E3 | Per-channel NIS window + adaptive covariance inflation, re-gating a returning fix under an inflated covariance | ADR-0006 | **Implemented + measured** (ATE 5.059→2.541 m, rejections 51→5, single-draw) |
| E4 | Spoof-permanence hysteresis: second grant in an episode escalates to `REJECTED_SPOOF` with 60 s lockout | ADR-0007 | **Implemented; detection path does not currently fire** (see E5) |
| E5 | Frozen-anchor cross-check: refuse an inflated grant that disagrees with the anchor frozen at outage start | ADR-0008 | **Implemented but UNREACHABLE** — zero reachable epochs. Contributes nothing today. |
| E6 | Calibration reporting as two verdicts (bulk NEES, tail coverage) with disagreement named, not resolved | `eval/calibration.py` | **Implemented + tested.** Genuinely good practice. |
| E7 | Typed claims with mandatory `falsification_test` fields | `analysis/findings.py` | **Implemented + tested** |
| E8 | Zero-heavy-dependency stack: incomplete gamma, chi-square quantiles, covariance propagation all in-repo | whole repo | **Implemented.** Makes every number traceable to code. |
| E9 | CI gates that make honesty mechanical: doc-table checker, coverage ratchet, benchmark-double-run diff | `.github/workflows/ci.yml` | **Implemented.** Doc-table and benchmark gates pass; lint gate is red (`ENGINEERING_BASELINE.md` F2). |

### 3.2 Research contribution

**None claimed, and none demonstrated.** The repository does not assert novelty
anywhere. This audit finds no basis for such a claim: the 21-state anchor
formulation, chi-square gating with NIS monitoring, and covariance inflation on
re-acquisition are all established techniques applied competently to a real and
under-reported failure mode. The *framing* — treating filter self-report as the
thing under test, and refusing to ship a capability that fails it — is a
contribution to engineering practice, not to estimation theory.

A defensible research contribution would require at least: a generalisation
study across scenes (not one trajectory), a comparison against an established
alternative, or a formal analysis of the estimator's consistency under the
modelled dynamics. None exists yet.

---

## 4. Known limitations (as stated by the repository itself)

This is the strongest section of the project's self-reporting, and it is
unusually candid:

- **Not field validated.** Synthetic fixture only; no real capture vendored or
  evaluated; no number is a field measurement.
- **Visual aiding under GNSS denial is untrustworthy and disabled by default.**
- **FDIR detects implausible updates; it does not explain them.** It cannot
  separate multipath from spoofing from sensor degradation (ADR-0005).
- **The calibrated-covariance failure is mitigated, not fixed** (B1 open).
- **Single-draw numbers** (2026-09-29 sweep).
- **One trajectory fixture, one scene.**
- **Not flight-ready**: no sensor driver, no live front end, no real-time loop,
  no failure-mode handling beyond a measurement gate.
- **TUM VI regression is partial** — 2 tests skip.
- The SRS records that of three operational user needs, **exactly one passes in
  full**; the others are `PARTIAL`, `NOT VERIFIED` or `CONTRADICTED`.

**Verified: no claim in the repository is stronger than its evidence.** Every
number I checked is traceable to a committed config and a fixed seed, and
`check_doc_tables.py` fails CI if a table disagrees with a live run.

---

## 5. Open questions

| # | Question | Type | Status |
|---|---|---|---|
| Q1 | Is the anchor error truly the dominant contributor to the outage failure? | Causal, falsifiable | `MECHANISM_LIBRARY` states the test: *"Run the same outage with a known zero initial bias. If peak drift is unchanged, accelerometer bias is not the dominant contributor and the explanation above is wrong."* **Not run.** This is the single most valuable unexecuted experiment in the repository. |
| Q2 | Does the frozen-anchor cross-check help once reachable? | Design + measurement | Needs the N1 guard decision, then re-measure. Its ~12 m reach means it will not close the 1–2 m case regardless. |
| Q3 | Do error and claimed uncertainty grow at different rates over outage duration? | Falsifiable, tractable | `MECHANISM_LIBRARY`: "Plot error against time over outages of 5, 15, 45 and 90 s. Linear supports bias-dominated; convex refutes it." **Not run.** |
| Q4 | Does drift track the longest visual gap or the mean frame rate? | Falsifiable, tractable | "Hold the mean usable frame rate fixed while varying only the burst length." **Not run.** |
| Q5 | Does a constant visual/IMU time offset produce error proportional to speed × offset? | Falsifiable, tractable | "Sweep the offset at two platform speeds." **Not run.** |
| Q6 | Is the ESKF or a pose graph the right answer for B1? | Architectural | ROADMAP Track B. Cost/benefit argued in `02_swapc_tradeoff_matrix.md`; not decided. |
| Q7 | Does the overconfidence generalise beyond one trajectory? | **Generalisability** | The 10-seed sweep varies noise only; `synthetic.py` takes no seed so all draws replay identical motion. **Open, and the main threat to the project's headline claim.** |
| Q8 | Is the two-verdict bulk/tail scheme better than a single verdict in practice? | Methodological | Implemented and argued in `docs/calibration.md`; never compared against an alternative. |
| Q9 | What is the actual false-alarm rate of the composed gate under a real multipath model? | Measurement | Declared `alpha=0.001` analytically; only measured on synthetic noise. |

**Pattern worth noting: `MECHANISM_LIBRARY` contains at least five falsification
tests that were written down and never run.** The project has an unusually good
hypothesis-register mechanism and a poor habit of closing the loop. Running Q1
and Q3 would cost hours and would materially strengthen the causal claims.

---

## 6. Taxonomy of every substantive claim

Applying the project's own types. This is the "what may a reader do with this"
table.

### FACT (verifiable by inspection; no experiment needed)

- The filter is 21-state; the state ordering is as documented.
- Quaternions are `(w,x,y,z)` internally; conversion occurs only in `io/trajectory.py`.
- Covariance uses the Joseph form, never the `(I-KH)P` shortcut.
- The chi-square quantiles, incomplete gamma, and metric definitions are implemented in-repo.
- `vision_enabled` defaults to `False`.
- The frozen-anchor cross-check guard is unsatisfiable given the counter/reset sequence (`eskf.py:559-565`).
- Runtime dependencies are exactly numpy, matplotlib, pyyaml.
- Every reported number regenerates from `configs/benchmark.yaml` at a fixed seed.

### MEASUREMENT (produced by a committed, reproducible check)

- `outage_visual` overconfident: NEES 419.4, coverage 20.0% (seed 0); min NEES 211.7 across 10 seeds.
- ATE 5.059 → 2.541 m and rejections 51 → 5 under ADR-0006 (seed 0 only).
- 30% camera drop: 3.339 → 1.872 m (seed 0 only).
- `dead_reckoning` ATE 1.877 m, identical across all 10 seeds (deterministic — no noise input).
- Overconfidence holds at 10/10 seeds.
- Cross-check reaches zero epochs across 5–100 m of offset.
- Chi-square gate: 0 false rejections at `alpha=0.001` on the synthetic control.

### INTERPRETATION (reasoned judgement over measurements)

- The root cause is the unmodelled anchor error (a constant body-frame offset cannot represent correlated drift).
- Closing B1 needs a pose graph, not a better threshold.
- A second independent modality is required for spoof discrimination.
- Refusing a plausible sensor is a smaller error than following it.
- The posture "ship the failing feature disabled" is preferable to tuning around a structural defect.

### HYPOTHESIS (stated with a falsification test; not established)

- Accelerometer bias is the dominant outage error contributor (Q1 — test written, not run).
- Error growth should be linear in outage duration if bias-dominated (Q3 — not run).
- Drift tracks the longest visual gap rather than the mean rate (Q4 — not run).
- Time-offset error scales with speed × offset (Q5 — not run).
- A frozen-anchor check would catch sustained spoof of magnitude >~12 m if reachable (E5 — arithmetic verified in a forced harness; never fires in the real path).
- The bulk/tail two-verdict scheme is superior to a single boolean (Q8 — asserted, never compared).

### UNKNOWN

- Generalisation to any trajectory, motion class, outage duration, or sensor rate other than the one fixture.
- Real-sensor behaviour: noise characteristics, time sync, extrinsic calibration, temperature, vibration.
- Behaviour under a real RF spoofing or multipath environment.
- Whether a pose graph actually resolves B1, and at what complexity cost.
- Anything about TUM VI / EuRoC ground truth, since those datasets are not vendored and 2 tests skip.

---

## 7. Research-integrity assessment

**Genuine strengths, verified:**

1. **Hypotheses ship with refuters.** `MECHANISM_LIBRARY` is a real scientific
   register: each causal claim is paired with the experiment that would kill it.
   This is rarer than it should be and is the most valuable asset for a
   research-facing reviewer.
2. **Claims are typed in code**, and CI enforces that doc tables match a live
   run — so a stale or hand-typed number fails the build.
3. **Negative results are published.** The project documents a mitigation that
   does not work (ADR-0008), keeps a deliberately wrong configuration as a
   regression control, ships its flagship feature disabled, and records that only
   one of three user needs passes.
4. **Scope is stated honestly.** "All results are synthetic" is the first
   substantive paragraph of the README.

**Genuine weaknesses:**

1. **Five written falsification tests are unexecuted** (Q1, Q3, Q4, Q5, and
   effectively E5). Good hypothesis generation, poor hypothesis testing.
2. **n=1 for the headline numbers.** Correctly caveated now, but a 10-seed sweep
   with no confidence interval and no significance test is a range, not a
   distribution.
3. **One scene.** `synthetic.py` is deterministic and takes no seed, so the
   sweep cannot address generalisation. This is the largest threat to the
   headline claim.
4. **No external comparison.** No published EKF, VIO or odometry system is run on
   the same fixture, so "this is bad" is established but "this is as good as it
   could be" is not.
5. **No adversarial input model.** The spoofing results come from a forced-grant
   unit-test harness, not a simulator, RF model, or attack campaign.

**Bottom line:** the project is honest about what it has not shown, which is the
precondition for being trusted about what it has. The gap is not integrity — it
is experimental follow-through. Running Q1 and Q3, adding a multi-scene sweep,
and adding one external baseline would move the work from "well-instrumented
case study" to "credible research contribution" without any change to the filter
itself.
