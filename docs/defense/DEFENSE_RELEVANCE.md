# Defense relevance

**Question.** Where does `contested-nav` sit relative to publicly documented
work in navigation resilience, and what does it actually contribute?

**Short answer.** The technical area is publicly documented and commercially
active. The specific problem this repository demonstrates is a known failure
mode with established remedies. The repository's contribution is a
*measurement and disclosure harness*, not a new algorithm, and it should be read
that way.

---

## 1. The problem area, in public terms

Navigation that depends on satellite positioning degrades when that signal is
jammed, spoofed, or geometrically blocked — indoors, in urban canyons,
underground, or under interference. This is a matter of public record: GNSS
interference and spoofing against civil aviation is tracked and published by
organisations such as OPSGROUP, and a 2025 peer-reviewed review of receiver
autonomous integrity monitoring cites ship groundings attributed to excessive
positioning deviation and an estimate of up to roughly 1,500 flights per day
subjected to spoofing across the first three quarters of 2024.

**VERIFIED BY EXTERNAL SOURCE** — [S1](SOURCES.md#s1), [S8](SOURCES.md#s8).

The engineering response is publicly termed *resilient* or *assured* PNT
(alternative-PNT, "A-PNT"). It is an active commercial category: Hexagon
completed its acquisition of Septentrio in March 2025 explicitly to expand
"resilient, assured positioning" and lists robotics, UAVs and autonomy among the
target segments; Safran has marketed a resilient-PNT product line since at
least June 2025.

**VERIFIED BY EXTERNAL SOURCE** — [S4](SOURCES.md#s4), [S5](SOURCES.md#s5),
[S9](SOURCES.md#s9).

Government-funded work in the same space is also public. DARPA's Adaptable
Navigation Systems programme addressed jamming, blocked environments, improved
inertial measurement units, signals of opportunity, and plug-and-play sensor
reconfiguration; DARPA's Subterranean Challenge ran autonomous navigation in
GPS-degraded environments and describes autonomy, perception, networking and
mobility as its four technical gaps. The National Institute of Standards and
Technology has solicited public comment on backup and complementary PNT
capabilities.

**VERIFIED BY EXTERNAL SOURCE** — [S2](SOURCES.md#s2), [S3](SOURCES.md#s3),
[S6](SOURCES.md#s6), [S7](SOURCES.md#s7).

**Consequence for how this repository should be described:** the surrounding
domain is neither secret nor novel. Any claim that work in this area is unusual
or unprecedented is false and is not made here.

---

## 2. The specific finding in this repository

`contested-nav` implements a 21-state error-state Kalman filter. When a visual
front end is fused, it introduces an *anchor* pose at the start of the run and
carries the anchor's error as six additional filter states (`c_p`, `c_t`),
because a monocular visual front end supplies only relative transforms and the
absolute pose must come from a reference.

With GNSS available, that model is well behaved. With GNSS denied, the anchor is
constrained only by itself, and the filter's covariance stops describing its
actual error.

**VERIFIED BY REPOSITORY** — with GNSS denied for 15 s and visual odometry on,
the filter reports 0.161 m of 1σ position uncertainty while being 2.54 m wrong;
mean NEES 286.2 against an expected 3; 2σ coverage 20.5% where 99.3% is
expected. The result holds at all 10 noise realisations and in all 8 scenes
tested, with a 4.65× range of path length.

---

## 3. This is a known failure mode, not a discovery

**VERIFIED BY EXTERNAL SOURCE.** Overconfidence of EKF-based visual-inertial
estimators caused by a mismatch between the observability of the linearised
estimator and the observability of the true system has been characterised in the
peer-reviewed literature since at least 2014. Hesch and colleagues published the
consistency analysis in *IEEE Transactions on Robotics*; subsequent work by
Huang, Li, Mourikis, Roumeliotis, Chen, Geneva and others produced a family of
remedies — observability-constrained EKF, first-estimate Jacobians and FEJ2,
invariant and right-invariant error-state formulations, and the Schmidt Kalman
filter. The problem was still being actively re-analysed in 2025.

**VERIFIED BY EXTERNAL SOURCE** — [S10](SOURCES.md#s10) through
[S16](SOURCES.md#s16).

### What this repository does and does not add

| | Status |
|---|---|
| Identifies the failure class in its own formulation | **VERIFIED BY REPOSITORY** |
| Measures it with an independent metric suite (NEES, ellipsoid coverage, Wilson intervals, conformal radius, bootstrap intervals) | **VERIFIED BY REPOSITORY** |
| Establishes robustness across 10 noise realisations and 8 scene geometries | **VERIFIED BY REPOSITORY** |
| Ships the failing configuration **disabled** by default and documents why | **VERIFIED BY REPOSITORY** |
| Discovers the failure | **UNSUPPORTED** — it is prior art, cited above |
| Proposes a novel remedy | **UNSUPPORTED** — no remedy is implemented |
| Compares against an established consistent estimator (FEJ, OC-EKF, invariant EKF, OpenVINS, VINS-Mono) | **UNSUPPORTED** — not done; this is the single largest gap |
| Demonstrates performance on real sensor data | **UNSUPPORTED** — synthetic fixture only |

**INFERENCE.** The honest characterisation of the contribution is *engineering
and epistemic discipline*: a testable claim, an independent measurement of
whether the code meets it, a failure that is published rather than hidden, and a
default that refuses to serve the broken configuration. That is a legitimate and
valuable kind of work. It is not algorithmic novelty, and this document does not
present it as such.

---

## 4. Capability-level mapping

Stated at the level of publicly documented capability, with no platform or
mission extrapolation. "Implemented" refers to code in this repository.

| Capability area | What exists publicly | This repository |
|---|---|---|
| Inertial navigation | Standard dead reckoning and strapdown integration; well-established | Implemented and measured (`estimators/dead_reckoning.py`, `eskf.py`) |
| Multi-sensor fusion | Mature research and commercial field; many published formulations | Implemented for GNSS + visual + IMU, in a specific anchor formulation |
| Consistency measurement | NEES, coverage, integrity monitoring — established diagnostics and survey literature | Implemented from published definitions, no SciPy, with bulk/tail split |
| GNSS interference detection | Commercial anti-jam/anti-spoof receivers; RAIM survey literature | **Not implemented** — receiver-level, not estimator-level |
| Integrity monitoring | RAIM, fault detection and isolation are established research areas | Partial: chi-square innovation gating and per-channel isolation, no formal integrity target |
| Signals of opportunity | Active DARPA and commercial research (LEO PNT, cellular, broadcast) | **Not implemented** |
| Cold-atom / advanced inertial | Active DARPA and NIST research programmes | **Not implemented** |
| Autonomous platform integration | Open stacks exist, e.g. Autoware's open L2 ADAS stack | **Not implemented** — this is a library, not a system |
| Formal safety assurance | Established discipline with its own standards | **Not implemented** |

**VERIFIED BY REPOSITORY** for the implementation column.

---

## 5. Language discipline

Words that would overstate this repository, and why, with the permitted
alternative:

| Do not use | Because | Use instead |
|---|---|---|
| "military-grade", "defence-grade" | No qualification against any standard has been attempted | "no certification or qualification evidence" |
| "defense-ready", "flight-ready" | No platform, no hazard analysis, no safety case | "a research library evaluated on synthetic data" |
| "state of the art" | The relevant methods are two decades old and this repository implements none of them | "a reproducible evaluation of one filter formulation" |
| "novel", "new approach" | No novelty claim survives contact with the cited literature | omit |
| "robust" without a scope | Robustness is only demonstrated over 10 seeds and 8 synthetic scenes | "verdicts stable across 10 noise seeds and 8 scenes" |
| "real-time" | There is no timing requirement, budget, or measurement | "synchronous, offline" |
| "production-ready" | Nothing has been integrated into anything | omit |
| "AI-powered" | No machine learning is present | omit |
| "military solution" / "for the battlefield" | No operational context exists | describe the technical capability only |

**AUTHOR-STATED** — this table is the project's own editorial policy, adopted
because the audit found the underlying claims unsupported.

---

## 6. Where this is genuinely useful

**AUTHOR-STATED**, offered as a positioning judgement rather than a claim:

1. **As a worked example of calibration discipline.** Most navigation code
   reports error and reports covariance, and never checks whether the two
   disagree. This repository checks, and publishes the result when they do.
2. **As a teaching artefact.** A filter that runs, converges, and is confidently
   wrong is a better lesson than one that crashes, because the failure is
   invisible without measurement.
3. **As a test harness.** The evaluation stack — seeded scenes, deterministic
   bootstrap intervals, bulk and tail verdicts, typed claims, claim auditing —
   is reusable independent of the filter under test.
4. **As an honest entry to the field.** For a reader who wants to work in
   navigation resilience, this shows how a claim is specified, how it is
   falsified, and what it costs when it fails.

**UNSUPPORTED** and deliberately not claimed: that this constitutes
contribution to any programme, contract, or product line.
