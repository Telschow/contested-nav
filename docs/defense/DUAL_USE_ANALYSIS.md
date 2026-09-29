# Dual-use analysis

**Question.** Could this repository cause harm, and are the design decisions
taken here appropriate for something in the navigation-resilience space?

This is a self-assessment, written in public, by the author. It is not a
security review and not a certification.

---

## 1. What the software actually is

A Python library implementing:

- a 21-state error-state Kalman filter with IMU bias states;
- chi-square innovation gating and per-channel fault detection, isolation and
  recovery;
- a synthetic sensor and trajectory generator;
- an evaluation stack (ATE/RPE under four alignment conventions, NEES,
  ellipsoid coverage, Wilson intervals, conformal radius, inflation factor,
  deterministic bootstrap intervals);
- CLI scripts and a documentation site.

**VERIFIED BY REPOSITORY.** Runtime dependencies are NumPy, Matplotlib and
PyYAML. There is no compiled extension, no network access, no sensor I/O, no
model inference, and no data beyond a synthetic generator.

---

## 2. Dual-use risk assessment

The honest framing is that **this specific repository is not the risk; the
general capability is.** The capabilities it touches — inertial navigation,
sensor fusion, and the observation that a filter can be confidently wrong — are
all either public-domain textbook material or published research. A reader who
wanted to do harm would not need this repository.

That said, the question deserves a real answer rather than a dismissal.

| Risk considered | Assessment | Classification |
|---|---|---|
| Enables navigation in a GNSS-denied environment | It does, and this is the entire point of the field, which is publicly funded and commercially served. The capability is not scarce information. | **INFERENCE** |
| Provides a method for spoofing or jamming | No. It contains no transmitter, no signal generation, no RF modelling, and no attack logic. Its detection capability is chi-square gating, which is textbook. | **VERIFIED BY REPOSITORY** |
| Provides a targeting or weapons-navigation capability | No. No platform model, no trajectory generation beyond a smooth analytic path, no actuator or control interface, no target model. | **VERIFIED BY REPOSITORY** |
| Enables surveillance | No. No capture, no recording, no environment modelling, no data collection of any kind. | **VERIFIED BY REPOSITORY** |
| Could be repurposed with modest effort | Yes, as with any navigation library. The barrier is low, and pretending otherwise would be dishonest. | **INFERENCE** |
| Contains sensitive information about a system | No. It contains no information about any real system. | **VERIFIED BY REPOSITORY** |
| Reveals exploitable vulnerabilities in deployed systems | No. It runs against a synthetic fixture it generates itself. | **VERIFIED BY REPOSITORY** |

### Net position

**INFERENCE.** This is ordinary open-source scientific software in a publicly
researched area. It carries no disproportionate risk. The realistic
misuse scenario — someone wanting a navigation filter under GNSS denial — is
served by a large amount of existing public literature and by commercial
products, so the marginal contribution of this repository to that scenario is
small.

The one thing worth guarding is not the code but the *framing*. A repository
that implied it was novel, or that implied it was qualified for a specific
class of use, could mislead. Section 5 of
[Defense relevance](DEFENSE_RELEVANCE.md#5-language-discipline) exists to
prevent that.

---

## 3. Design decisions that reduce risk

Not a security feature list. These are engineering choices with a side effect of
limiting what the software can be used for.

| Decision | Effect |
|---|---|
| Synthetic fixture only; no real capture vendored | Nothing to leak; no recording capability exists |
| `vision_enabled=False` by default | The known-broken configuration cannot be reached by accident |
| FDIR isolates and times a fault but does not classify its cause | The library cannot distinguish jamming from multipath from sensor failure, so it cannot select a response on an operator's behalf |
| No output that commands anything | The library produces state and covariance. It drives nothing. |
| Typed claims with a claim audit | Prose in the documentation cannot silently become a stronger claim than the measurements support |
| Full history and provenance | A reader can see what changed, when, and why, including this assessment |
| No obfuscation, no compiled artefacts | The code is the code |

**VERIFIED BY REPOSITORY.**

---

## 4. What a deployer would still have to do

To move from this repository to anything operational, someone would have to
supply all of the following. None is present here, and none is a matter of
configuration.

1. Real sensor interfaces and drivers.
2. Real measurement characterisation — bias stability, noise spectra,
   temperature dependence, vibration, shock, time synchronisation.
3. Time synchronisation and latency budgets across every sensor.
4. Online extrinsic calibration between camera and IMU.
5. A correct solution to the problem this repository documents as unsolved — an
   observability-consistent formulation or a pose-graph backend, neither of
   which exists here.
6. Formal integrity targets and an argument that they are met.
7. Hazard analysis, failure-mode coverage, and a safety case appropriate to the
   domain.
8. Qualification evidence: environmental, lifetime, and software-integrity
   testing.
9. Security engineering for a connected system, which this repository has not
   had.

**VERIFIED BY REPOSITORY** for the absence of each item.

---

## 5. Intent

**AUTHOR-STATED.** The purpose of this repository is to make a falsifiable claim
about estimator calibration, test it, and publish the result — including the
result that fails. It is a portfolio and research artefact. It is not a product,
and it is not offered as a component for integration.

If it is useful to someone working on navigation resilience, that is a good
outcome. If it is not, the value was in the measurement discipline being
transferable.

---

## 6. How to challenge this assessment

This document makes claims that a reader can check:

- Every statement about what the code does is checkable by reading the code or
  running the test suite.
- Every statement about the surrounding field carries a citation with an access
  date in [Sources](SOURCES.md).
- Every claim about what is *not* implemented is checkable by searching for it.

The claim most worth challenging is the "net position" in section 2. If a reader
believes this repository creates disproportionate risk, the specific step
argumenting otherwise should be identified. Absent that, the assessment should
be treated as the author's judgement rather than as an independent review.
