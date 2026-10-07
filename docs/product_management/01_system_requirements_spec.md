# 01: System Requirements Specification

**Document ID:** PM-SRS-001
**Status:** Baseline for review
**Applies to:** `navkit` 21-state error-state Kalman filter and `navkit.fdir`
**Date:** 2026-09

---

## 0. How to read the verdicts in this document

Every requirement below carries a **verification verdict**, and the verdicts are
not decoration. Of the three operational user needs in §1, **exactly one
passes in full**: one passes only on its primary leg and fails its calibration
leg, and one is unverified and partly contradicted by the design as it stands.
A requirements document whose traceability column read "met" across the board
would be describing a different system from this one.

This document is one of three in `docs/product_management/`:

| Document | ID | Contents |
|---|---|---|
| `01_system_requirements_spec.md` | PM-SRS-001 | this document: OUNs, requirements, verdicts |
| `02_swapc_tradeoff_matrix.md` | PM-SWAPC-002 | platform cost study and the ESKF/pose-graph decision rule |
| `03_fdir_and_spoofing_strategy.md` | PM-FDIR-003 | threat taxonomy, two-stage architecture, operator telemetry |

| Verdict | Meaning |
|---|---|
| **MET** | Verified against a committed, reproducible check. |
| **PARTIAL** | The primary leg passes and a stated secondary leg does not. |
| **NOT MET** | Verified to fail. |
| **NOT VERIFIED** | No check exists. Absence of evidence, recorded as absence. |
| **CONTRADICTED** | The requirement as written is incompatible with the current design. |

Provenance is marked on every number, because the distinction decides what a
reader may do with it:

- **[M] Measured**: produced by `scripts/run_benchmark.py` from a
  known-answer synthetic fixture and written to `results/benchmark.json`
  (generated and gitignored, not committed).
- **[D] Derived**: computed from measured or configured values in this
  repository, with the arithmetic shown.
- **[C] Configured**: a default in the source, i.e. a choice, not a result.
- **[P] Proposed**: a target for a future revision. Not a claim about today.
- **[E] Estimate**: external planning judgement, not from this repository.

> The benchmark artifact carries its own disclaimer, reproduced here because it
> governs every **[M]** number in this document:
>
> *"All numbers are from a known-answer synthetic fixture. They are not field
> measurements and must not be presented as real-sensor performance."*
>
> No requirement in §1 is verified against flight hardware, a real IMU, or a
> real optical front end. Ground truth is the analytic trajectory the synthetic
> generator is built from, which is exact but is not the world.

---

## 1. Operational User Needs

### OUN-01: GNSS Denial Tolerance

> Maintain continuous tactical position estimation during a 15 s total GNSS
> outage with maximum ATE < 3.0 m.

**Rationale.** A contested receiver does not fail cleanly. It goes quiet, and
the filter must carry position through the gap and re-converge on return
without discarding the healthy fixes that arrive at the end of it.

**Verification verdict: PARTIAL.**

| Leg | Criterion | Result | Verdict |
|---|---|---|---|
| Accuracy through the gap | ATE RMSE < 3.0 m over `outage_visual` | **2.541 m** [M] | MET |
| Accuracy, degraded front end | ATE RMSE < 3.0 m over `outage_visual_degraded_camera` | **1.872 m** [M] | MET |
| Calibration through the gap | 2σ coverage ≥ 95% | **20.0%** / **18.5%** [M] | **NOT MET** |
| Calibration, bulk | mean NEES within tolerance of expected 3 | **419.4** / **216.6** [M] | **NOT MET** |

The accuracy leg passes on both cases. The calibration leg fails by a factor of
roughly five, and this is the single most important thing in this document. The
filter reports 0.161 m of 1σ uncertainty while being 2.541 m wrong. It
converges, it runs, and it is confidently wrong. This is `CONSTRAINTS.md`
blocker **B1**, still open, and it is not fixed by ADR-0005 or ADR-0006.

A range of ±3.0 m that the system can hit only while understating its own error
by 16× is not a satisfied requirement. It is a half-satisfied one, and the
half that is missing is the half a tactical user depends on.

### OUN-02: Spoofing Resilience

> Detect and reject step-bias and subtle drift spoofing attacks (1–100 m)
> without corrupting state estimates.

**Verification verdict: MET, with a documented and non-trivial cost.**

Verified by an injected step-bias probe applied to a 30-fix block on a live
5 Hz channel, sweeping the offset across the full required range:

| Offset | Inflation grants | Peak position error | Channel state |
|---:|---:|---:|---|
| 1 m | **0** | 3.430 m | escalated to `SENSOR_FAULT` |
| 2 m | **0** | 5.441 m | escalated to `SENSOR_FAULT` |
| 3 m | **0** | 1.998 m | rejected, no fault |
| 5 m | **0** | 2.200 m | rejected, no fault |
| 10 m | **0** | 2.200 m | rejected, no fault |
| 20 m | **0** | 2.200 m | rejected, no fault |
| 40 m | **0** | 2.200 m | rejected, no fault |
| 100 m | **0** | 2.200 m | rejected, no fault |

The property that matters is the flat zero. An attacker cannot buy trust with
magnitude: the re-acquisition budget is a function of *silence*, and a
continuously streaming channel has none. Pinned by
`TestInflationLimits::test_a_large_sustained_offset_is_not_followed` and
`test_a_spoof_small_enough_to_drift_toward_is_still_isolated`; the second
exists because the first version of this code was **inverted** over 1–3 m (see
§4, TR-26).

**The cost, stated plainly.** At 1 m and 2 m the system refuses the sensor and
declares a fault, then coasts on the inertial solution, reaching 3.430 m and
5.441 m of error. That is a large transient. It is the correct trade (refusing
a plausible-looking receiver beats following it), but a user who expected a
1 m spoof to cost 1 m of error is wrong, and the operator interface in
PM-FDIR-003 must say so.

Two further honest limits on this verdict:

- The probe is **step-bias on position only**. Gradual false-lock pulling
  (TR-13) is architecturally identified in PM-FDIR-003 §1.3 and is **not
  verified** here.
- The probe runs on a *streamed* channel. A spoof that first suppresses the
  genuine signal for enough seconds to earn a large drift budget, and only then
  injects, is a different attack and is not covered by this table.

### OUN-03: Embedded SWaP-C Execution

> Execute deterministically on embedded ARM Cortex-A53 / micro-controllers
> without third-party C++/compiled libraries or neural network dependencies.

**Verification verdict: NOT VERIFIED, and partly CONTRADICTED.**

| Leg | TR | Criterion | Evidence | Verdict |
|---|---|---|---|---|
| No neural networks | TR-11 | none in dependency graph | `pyproject.toml` [C] | MET |
| No SciPy | TR-11 | chi-square and quantiles hand-rolled | `fdir/gating.py`, `eval/statistics.py` [M] | MET |
| No third-party **compiled** libraries | TR-11 | n/a | `numpy` is a compiled C extension and a hard runtime dependency [C] | **CONTRADICTED** |
| Flight image excludes eval tooling | TR-12 | n/a | `matplotlib` and `pyyaml` are unconditional runtime deps [C] | NOT MET |
| Runs on Cortex-A53 | TR-32 | n/a | no ARM build exists | NOT VERIFIED |
| Deterministic execution | TR-32 | n/a | no timing, WCET or jitter measurement exists | NOT VERIFIED |
| Fits the stated power envelope | TR-32 | n/a | no power measurement exists | NOT VERIFIED |

The design intent is genuinely met in the ways that mattered to the authors:
the chi-square thresholds are **tabulated** specifically so the filter's inner
loop never runs a bisection with an unbounded iteration count, and there is no
learned component anywhere. That work is worth something and is retained.

But the requirement as written says *no third-party compiled libraries*, and
`numpy` is one. It is also unavoidable in practice: the filter is dense linear
algebra over 21 states, and reimplementing that in pure Python to satisfy a
prose requirement would make the product worse. The requirement needs to be
rewritten, not the code. Proposed revision in TR-11.

**Recommendation: do not present OUN-03 as a capability.** Present it as
"flight software is dependency-light and has no learned components; target-port
work is unstarted." The single most load-bearing unmeasured claim in this
document is that any of this is deterministic on the target.

---

## 2. Technical Requirements Traceability Matrix

Requirement IDs are stable. `TR-nn` rows carry their own verification verdict,
and the OUN roll-up in §2.1 does not average them away.

### 2.1 Roll-up

`TR-nn` IDs are grouped **by discipline** (IMU, optical, dependency, gating,
compute), not by operational user need. An OUN is therefore supported by a
*non-contiguous* set of requirements, and the mapping is given explicitly
rather than as an ID range.

| OUN | Supporting requirements | Met | Not met | Not verified / contradicted |
|---|---|---:|---:|---:|
| OUN-01 denial tolerance | TR-20…TR-25, TR-28, TR-29, TR-31 (support); **TR-30** | 8 | 0 | 1 (TR-30) |
| OUN-02 spoofing resilience | TR-14, TR-23, TR-26, TR-27; **TR-13** | 4 | 0 | 1 (TR-13) |
| OUN-03 embedded SWaP-C | **TR-11** (contradicted), **TR-12** | 0 | 1 | 2 |

Three of the thirty-two requirements are not verified and one is contradicted,
and the distribution matters more than the count. **None of the OUN-01 gaps are
detection gaps**: the mechanism that carries OUN-01 (TR-23) is verified and
working. The OUN-01 failure is calibration, which is carried by the OUN
statement itself and measured by AC-03/AC-04 rather than by any `TR-nn` row.
That asymmetry is the finding: this subsystem is better at refusing bad data
than at describing its own error, and AC-03/AC-04 are the criteria that say so.

**A reader should not infer from this table that OUN-01 is nearly satisfied.**
It is not. Its accuracy leg passes, its calibration leg fails by a factor of
roughly five, and the roll-up row above cannot show that because the failure is
not in a `TR-nn` row. The per-OUN verdicts in §1 govern.

### 2.2 IMU requirements

The noise model in the validated benchmark configuration is
`ImuNoiseModel(2e-4, 2e-3, 2e-6, 1e-4, 1e-5, 2e-3)` in the units
`src/navkit/io/imu.py` documents: rad/s/√Hz, m/s²/√Hz for the noise densities,
the same units for the bias random walks, and rad/s, m/s² for the bias sigmas
[C]. Converting to the industry units a requirement is usually written in
[D]:

| ID | Parameter | Budget | Validated config | Ratio | Verdict |
|---|---|---:|---:|---:|---|
| TR-01 | Angular random walk | ≤ 0.05 °/√hr | **0.688 °/√hr** | **13.8× over** | **NOT MET** |
| TR-02 | Velocity random walk | ≤ 0.1 m/s/√hr | **0.120 m/s/√hr** | **1.2× over** | **NOT MET** |
| TR-03 | Gyro bias random walk | ≤ 0.01 °/√hr [P] | 0.0069 °/√hr | 0.69× | MET |
| TR-04 | Accel bias random walk | ≤ 0.01 m/s/√hr [P] | 0.0060 m/s/√hr | 0.60× | MET |
| TR-05 | Gyro bias 1σ | ≤ 0.001 °/s [P] | 0.00057 °/s | 0.57× | MET |

Conversion, shown so it can be checked or disputed [D]:

```
ARW [°/√hr] = gyro_noise_density [rad/s/√Hz] × √3600 × (180/π)
            = 2.0e-4 × 60 × 57.29578 = 0.6875
VRW [m/s/√hr] = accel_noise_density [m/s²/√Hz] × √3600
              = 2.0e-3 × 60 = 0.1200
```

**This is the most consequential finding in the document, and it is not a
failure of the filter.** The published results are achieved on a *consumer-grade*
MEMS IMU that is 13.8× worse on angular random walk than the budget in the
requirement. Read one way that is good news about the algorithm: it works with
hardware 14× worse than specified. Read the other way (and this is the reading
that governs a requirements document): **the requirement-to-hardware mapping has
never been exercised.** No result in this repository was produced on hardware
that meets TR-01, so the accredited performance of a compliant system is
unknown. A tactical MEMS IMU meeting 0.05 °/√hr will drift far less over 15 s,
which should make OUN-01 easier, but "should" is not a verification and this
document does not record it as one.

TR-03…TR-05 budgets are [P]: this repository proposes them, it does not
inherit them from a customer requirement, and they should be treated as
placeholders pending a real sensor datasheet.

### 2.3 Optical front-end requirements

The validated operating point comes from `configs/benchmark.yaml` [C]. There is
no optical hardware in this project, so only the noise and rate figures exist as
requirements; everything about the physical sensor is [P].

| ID | Parameter | Budget | Validated config | Verdict |
|---|---|---:|---:|---|
| TR-06 | Frame rate | ≥ 10 Hz [P] | 20.0 Hz [C] | MET |
| TR-07 | Rotation noise, per frame | ≤ 0.35 ° 1σ [P] | 0.35 ° 1σ [C] | MET (at budget) |
| TR-08 | Translation noise, per frame | ≤ 0.05 m 1σ [P] | 0.05 m 1σ [C] | MET (at budget) |
| TR-09 | Inter-frame drop rate | tolerates 30% burst loss [P] | 30%, 1 s burst [C] | MET |
| TR-10 | Resolution, optical distortion, hardware sync | n/a | **no hardware exists** | NOT VERIFIED |

TR-07 and TR-08 sit exactly at budget, which means the configuration has no
margin at all. Any front end worse than the synthetic one degrades OUN-01
directly, and `outage_visual_degraded_camera` is a frame-rate test, not an
accuracy-degradation test. TR-10 is where a real integration programme starts:
resolution sets the usable translation-noise floor, distortion sets a systematic
bias that no amount of filter tuning removes, and inter-camera sync error is a
bias that lands directly in the rotation block.

### 2.5 Dependency and threat-coverage requirements

| ID | Parameter | Requirement | Evidence | Verdict |
|---|---|---|---|---|
| TR-11 | Runtime dependency policy | no learned components; no SciPy; third-party compiled libraries permitted only under a declared policy | `pyproject.toml` [C], `fdir/gating.py`, `eval/statistics.py` [M] | **CONTRADICTED** as worded |
| TR-12 | Flight image excludes eval and plotting tooling | eval-only dependencies not required at runtime | `matplotlib` and `pyyaml` are unconditional runtime deps [C] | **NOT MET** |
| TR-13 | Gradual false-lock pulling detected | offset introduced below the gate threshold, undetected by a per-update gate | architecturally identified only; `fdir_<ch>_mean_nis` is logged but nothing acts on it | **NOT VERIFIED** |

TR-11 decomposes into three sub-legs, and the aggregate verdict is the worst of
them:

| Sub-leg | Evidence | Verdict |
|---|---|---|
| No neural networks in the dependency graph | `pyproject.toml` [C] | MET |
| No SciPy | chi-square and quantiles hand-rolled in `fdir/gating.py`, `eval/statistics.py` [M] | MET |
| No third-party **compiled** libraries | `numpy` is a compiled C extension and a hard runtime dependency [C] | **CONTRADICTED** |

**TR-11 needs rewriting, not re-implementing.** The filter is dense linear
algebra over 21 states; reimplementing that in pure Python to satisfy a prose
requirement would make the product worse and slower on the target. The
requirement is the defect, not the code. Proposed revision: *no third-party
C++ libraries, no neural-network dependencies, and no dependency outside a
declared allowlist.* Under that wording all three sub-legs pass and the clause
becomes checkable by a dependency audit rather than by argument.

TR-13 is the most consequential unverified row in this table and the only one
that is **architecturally identified as a gap rather than missing**. A gradual
pull that keeps every innovation under the α = 0.001 threshold never trips
Stage 1, never accumulates the trailing run Stage 2 requires, and so is
invisible to the current architecture. That it is the hardest threat in the
taxonomy and the one the design cannot see is the most important qualification
on OUN-02's MET verdict, which is scored on step bias alone. See
PM-FDIR-003 §1.3.

### 2.6 Gating and re-acquisition requirements

All values are `[C]` (defaults in `FdirConfig`) and are choices, not results.
Their justification is ADR-0005 and ADR-0006.

| ID | Parameter | Value | Basis | Verdict |
|---|---|---:|---|---|
| TR-14 | False-alarm rate α | 0.001 | 0/1212 healthy updates rejected [M] | MET |
| TR-15 | Gate threshold, dof 1 | 10.828 | χ² table, exact-verified to 5e-4 [M] | MET |
| TR-16 | Gate threshold, dof 2 | 13.816 | as above | MET |
| TR-17 | Gate threshold, dof 3 | 16.266 | as above | MET |
| TR-18 | Gate threshold, dof 6 | 22.458 | as above | MET |
| TR-19 | dof coverage | exact ≤ 8, Wilson-Hilferty above | relative error −0.33% at m=4 to −0.005% at m=60 [M] | MET |
| TR-20 | Persistence threshold | 3 consecutive | ADR-0006: 2 separable from multipath bursts, 4 too late | MET |
| TR-21 | Re-acq window | 5 samples | reporting and `mean_nis`; the decision reads a trailing run only | MET |
| TR-22 | Inflation factor cap | 100× | bounds a single grant to 30 m 1σ | MET |
| TR-23 | Drift bound, σ per second of silence | 0.5 m/s | the bound that does the real work | MET |
| TR-24 | Re-gate headroom | ≤ 25% of threshold | marginal passes are large-gain steps | MET |
| TR-25 | Grants per episode | 1 | a filter that can re-inflate forever follows anything | MET |
| TR-26 | Eligible sample class | genuine outlier only | the fault-hold ambiguity, §4 and PM-FDIR-003 §2.4 | MET |
| TR-27 | Inflation scope | GNSS position block only | dimensional and evidential | MET |

**The velocity × silence grant cap (TR-23)** deserves restating because it is
the requirement that carries OUN-02, and because it is a *bound* rather than a
tuning value:

```
admitted 1σ ≤ max_drift_sigma_mps × (longest single gap on that channel)
           = 0.5 m/s × T
```

At 5 Hz a healthy channel has T = 0.2 s and a 0.1 m granted σ. After the 15 s
denial that validated OUN-01, T = 15 s and a 7.5 m granted σ, enough to admit
the 3.4 m displacement the case actually produced, and nowhere near a 60 m
offset. A constant budget cannot draw that line, because the correct limit
depends on how long the filter was blind. That dependence is the requirement.

**The granted σ is not the admitted offset, and the distinction is
load-bearing.** TR-23 bounds the *increment* the filter adds to the position
block. The filter then re-gates the same update against the inflated
covariance and accepts anything up to `reaccept_margin × χ²₃(0.001)` =
`0.25 × 16.266` = 4.0665 in the inflated metric, which is √4.0665 ≈ 2.02
granted σ of reach beyond the drift bound. In the `S → 0` limit the admitted
offset is therefore `7.5 × (1 + 2.02)` ≈ **22.6 m**, not 7.5 m.

Measured directly [M]: constant-x offset applied to every fix returning after
the validated 15 s denial, `outage_visual` geometry:

| Offset | Verdict | Offset | Verdict |
|---:|---|---:|---|
| 7.5 m | admitted | 20.0 m | admitted |
| 12.0 m | admitted | 21.0 m | admitted |
| 16.0 m | admitted | **22.0 m** | **refused, fault declared** |
| 18.0 m | admitted | 25.0 m | refused |

The measured envelope (~21 m) is 2.8× the granted σ (7.5 m). The code is
correct and self-aware: `nis_monitor.py` says the drift bound "is the
difference between bounding the increment and bounding the total", so this is a
specification error, not an implementation error: TR-23 as written is true about
the increment and misleading as a security envelope. AC-05 and AC-06 are scored
against offsets of 1–100 m, which straddle this boundary rather than probing it,
so their PASS verdicts survive; but the OUN-02 "0 grants" claim should be read as
"0 grants at the offsets tested", not as a bound on admitted error.

### 2.7 Compute and platform requirements

| ID | Parameter | Budget | Evidence | Verdict |
|---|---|---:|---|---|
| TR-28 | State dimension | 21 | `_N_STATES = 21` [C] | MET |
| TR-29 | Filter update rate | n/a | 200 Hz over 30 s = 6001 IMU epochs [M] | MET |
| TR-30 | Per-run compute | n/a | 0.897 s estimator runtime / 2.811 s wall, heaviest case, x86 CPython [M] | NOT VERIFIED |
| TR-31 | Rejected-update cost | n/a | returns before gain formation; `P⁺ = P⁻` [M] | MET |
| TR-32 | Target-port determinism | n/a | n/a | NOT VERIFIED |

TR-30 is the number most likely to be quoted out of context, so: 0.897 s of
**estimator runtime** (2.811 s wall, the difference being fixture setup and
metrics) for a 30 s scenario is **not** a Cortex-A53 budget. It tells you the
algorithm is not pathologically expensive (300 µs of x86 per epoch of dense
21×21 algebra) and nothing else. An A53 figure requires a native build, and
TR-32 cannot be written at all until one exists. The compute/FR requirements
are costed per profile in PM-SWAPC-002 §1, which reaches the opposite
conclusion from the obvious one: at these sizes the filter is under 2% of the
compute budget on all three platform tiers, so it is not the reason to choose a
tier.

---

## 3. Verification and Acceptance Criteria

### 3.1 Criterion set

| ID | Criterion | Method | Threshold |
|---|---|---|---|
| AC-01 | Position accuracy through denial | `outage_visual` ATE RMSE | < 3.0 m |
| AC-02 | Accuracy, degraded front end | `outage_visual_degraded_camera` ATE RMSE | < 3.0 m |
| AC-03 | Bulk calibration | mean NEES / expected, `outage_visual` | ratio ≤ 2.0 |
| AC-04 | Coverage calibration | 2σ ellipsoid coverage, all vision-aided cases | ≥ 95% |
| AC-05 | Spoof rejection, large | grants across 3–100 m step bias **delivered continuously** | 0 grants |
| AC-06 | Spoof rejection, small | grants across 1–2 m step bias **delivered continuously** | 0 grants |
| AC-07 | Rejection leaves state untouched | `P⁺ == P⁻` on rejection | exact |
| AC-08 | False alarms on healthy data | rejected / total, 1212 healthy fixes | 0 |
| AC-09 | Documentation integrity | `scripts/check_doc_tables.py` | exit 0 |
| AC-10 | Regression floor | `pytest` | 0 failures |
| AC-11 | Coverage floor | `scripts/coverage_report.py` | ≥ 75% (script floor) |

### 3.2 Current acceptance status

| AC | Threshold | Measured | Verdict |
|---|---|---|---|
| AC-01 | < 3.0 m | 2.541 m | **PASS** |
| AC-02 | < 3.0 m | 1.872 m | **PASS** |
| AC-03 | ratio ≤ 2.0 | 139.8 (419.4 / 3) | **FAIL** |
| AC-04 | ≥ 95% | 20.0%, 18.5%, 0.7%, 16.0% | **FAIL** |
| AC-05 | 0 grants | 0 grants at 3/5/10/20/40/100 m; **21 m admitted after a 15 s denial** | **PASS at the tested offsets** |
| AC-06 | 0 grants | 0 grants at 1/2 m | **PASS** |
| AC-07 | exact | holds | **PASS** |
| AC-08 | 0 | 0 of 1212 | **PASS**, but see note |
| AC-09 | exit 0 | matches `results/benchmark.json` | **PASS** |
| AC-10 | 0 failures | 624 passed, 3 skipped, 2 xfailed (fresh clone); 625, 2, 2 once `results/benchmark.json` exists | **PASS** |
| AC-11 | ≥ 75% (script floor) | 91.69% (CPython 3.13) | **PASS** |

**AC-03 and AC-04 are not seed artefacts.** Both were re-measured after this table
was first written, under two independent sweeps: 10 noise realisations of the
benchmark scene (`scripts/seed_sweep.py`) and 8 scenes with the trajectory
geometry varied over a 4.65x path-length range (`scripts/scene_sweep.py`). All 7
case verdicts are identical in all 8 scenes, and `outage_visual` is overconfident
at every noise seed. The *verdicts* are therefore robust; only the magnitudes are
single draws. This strengthens the FAILs; it does not soften them.

**AC-08 is the one PASS here that no test enforces.** The 0-of-1212 result is
recorded in the `fdir/gating.py` module comment, which also documents the
contrast that justifies the default: at `alpha = 0.01` the same 1212 healthy
fixes produce 13 rejections (1.07%, matching the nominal rate), and at
`alpha = 0.001` they produce zero while a genuinely broken configuration still
rejects 68 of 101 and trips a fault. The measurement is sound and the reasoning
is sound, but it is a comment, and a comment does not fail a build.

By this document's own argument in §3.3, *a number in a document is a claim
about a measurement, and the check keeps the claim attached to the
measurement*, AC-08 is the one acceptance criterion that should be promoted to
an enforced test. It is the criterion that protects the false-alarm rate the
entire FDIR subsystem depends on, and a future refactor of `gating.py` could
raise the nuisance rate without turning anything red.

**9 pass, 2 fail.** The two acceptance criteria that define "safe to fly",
AC-03 and AC-04, both fail, and they fail for one root cause: the visual
anchor error is folded into filter state but is not a state the filter models
completely. A single anchor cannot represent correlated visual drift. The fix is
a pose graph over visual keyframes, which is `CONSTRAINTS.md` B1 and the top
item in `ROADMAP.md`. It is not an FDIR problem and no threshold tuning will
move AC-04.

### 3.3 The documentation checker as an acceptance gate

AC-09 deserves a note, because it is the cheapest gate in the set and the one
most often skipped.

`tests/test_doc_tables.py::test_the_real_documents_match_the_committed_benchmark`
re-parses `results/benchmark.json` and compares every published figure in
`README.md` and `docs/index.html` against the generated value, failing on any
disagreement. It is not a formatting check. It exists because during ADR-0006
the benchmark was regenerated repeatedly with `--only` flags, which silently
reduced the artifact to 2 of 7 cases, and the first symptom was a documentation
test failing rather than a benchmark test.

A number in a document is a claim about a measurement, and this is the check
that keeps the claim attached to the measurement. Any product document that
quotes a benchmark figure must sit behind the same gate, which is why the
figures in this SRS are **[M]**-tagged with the case name, so a future reader
can find the source row.

---

## 4. Traceability to defects and decisions

| Req | Implementation | Record | Residual |
|---|---|---|---|
| TR-01…TR-05 | `io/imu.py`, `configs/benchmark.yaml` | this document, PM-SWAPC-002 §2.2 | never exercised on compliant hardware |
| TR-06…TR-10 | `configs/benchmark.yaml`, `eval/scenarios.py` | this document, PM-SWAPC-002 §2.3 | no optical hardware; budgets [P] |
| TR-11 | `pyproject.toml` | this document §2.5 | needs rewriting, not re-implementing |
| TR-12 | `pyproject.toml` | ROADMAP | eval deps are unconditional |
| TR-13 | `fdir/nis_monitor.py` (statistic only) | ROADMAP, PM-FDIR-003 §1.3 | **no detector exists** |
| TR-14…TR-19 | `fdir/gating.py` | ADR-0005 | tabulated; dof > 8 is approximate |
| TR-20…TR-27 | `fdir/nis_monitor.py`, `fdir/fdir_manager.py` | ADR-0006 | GNSS position only |
| TR-28…TR-32 | `estimators/eskf.py` | this document, PM-SWAPC-002 §1 | no target-port build |
| OUN-01 accuracy | `estimators/eskf.py` | ADR-0006 | AC-03/AC-04 still fail |
| OUN-02 | `fdir/` | ADR-0006, PM-FDIR-003 | small offsets cost a fault and a coast |
| OUN-03 | `pyproject.toml` | n/a | **unstarted** |
| AC-04 | n/a | B1, ROADMAP stage 3 | pose graph, not a filter change |

### The inversion, recorded because specs should carry their own postmortems

ADR-0006's first implementation passed AC-05 and AC-06 *differently than
intended*: 1 m and 2 m step biases obtained a re-acquisition grant while 3 m and
above did not. The mechanism was backwards across the most attacker-relevant
range, and the benchmark never showed it because the benchmark has no spoof
case.

The cause was a genuine ambiguity in the design, not a typo. A channel is
excluded for one of two reasons, and both return `accepted = False`: the
innovation was an outlier, or the numbers were fine and a declared fault is
holding the channel out anyway. The second pass could not tell them apart, so a
1 m spoof (which the filter is pulled toward until the residual falls *inside*
the threshold) was "relieved" by spending the drift budget on a fault it
should have respected.

The fix is `GatingDecision.outlier`, and the requirement it encodes is TR-26.
AC-06 exists specifically so that a large-offset-only test cannot be mistaken
for a passing spoof test. Both halves of the range are now asserted together,
and both fail against the broken code.

This is the argument for keeping AC-06 as a separate criterion from AC-05
rather than folding them into one "spoof resilience" pass: the vulnerability
was in the *small* case, and a single aggregate criterion would have reported
health.

---

## 5. Open items for the next revision

| # | Item | Blocks | Owner |
|---|---|---|---|
| 1 | Pose graph for visual anchor error | AC-03, AC-04, B1 | Estimation |
| 2 | Native ARM build, then WCET and jitter measurement | TR-30, TR-32, OUN-03 | Platform |
| 3 | Rewrite OUN-03 to a dependency policy that `numpy` can satisfy | TR-11, OUN-03 | Product |
| 4 | Split `matplotlib` / `pyyaml` into an eval extra | TR-12, TR-30, flight image | Platform |
| 5 | Real IMU on a bench, then re-run the benchmark | TR-01, TR-02 | Validation |
| 6 | Optical front-end spec: resolution, distortion, sync | TR-10 | Vision |
| 7 | Gradual false-lock detector; step bias is not the only threat | TR-13, OUN-02 | FDIR |
| 8 | Spoof-after-suppression probe (earn silence, then inject) | OUN-02 | FDIR |
| 9 | **Derive `max_drift_sigma_mps` per IMU grade from fitted bias instability** | TR-23, OUN-02 | FDIR |
| 10 | Add a 60 s benchmark case; 15 s is a data limit, not a physical one | TR-29, OUN-01 | Estimation |
| 11 | **Promote the 0-of-1212 false-alarm result to an enforced test** | AC-08, TR-14 | FDIR |
| 12 | **Probe AC-05/AC-06 inside the 7.5–22 m admitted envelope**; the current offsets straddle the boundary rather than testing it | TR-23, OUN-02 | FDIR |
| 13 | **Bound admitted offset, not just granted increment**: either cap the re-gate reach in metres or add cross-modal validation | TR-23, OUN-02 | FDIR |

Items 2, 5 and 6 are the ones that decide whether this is a research artifact
or a flight-candidate baseline. Items 7–10 are cheap, are unblocked by any
platform decision, and each closes a specific named gap rather than a general
one. Until they are done, the honest summary of this specification is: **the
contested-navigation problem is well posed and partly solved, and the remaining
gap is honest bookkeeping rather than a missing idea.**
