# 03 — FDIR and Adversarial Spoofing Strategy

**Document ID:** PM-FDIR-003
**Status:** Architecture whitepaper for review
**Applies to:** `navkit.fdir` — chi-square gate (ADR-0005) and NIS monitor (ADR-0006)
**Date:** 2026-09

---

## 0. Scope and a naming correction

This paper describes the fault detection, isolation and recovery architecture
as **implemented**. Where the programme brief and the code disagree, the code
wins and the disagreement is recorded here rather than smoothed over.

**Naming.** The brief asks this paper to document a `PERSISTENT_DIVERGENCE`
status. **No such status exists.** The five implemented statuses are:

| Status constant | Value | Meaning |
|---|---|---|
| `STATUS_ACCEPTED` | `ACCEPTED` | Innovation is consistent. Update fused. |
| `STATUS_REJECTED_SPOOF` | `REJECTED_SPOOF` | Single failure, no relief sought. Update discarded. |
| `STATUS_REJECTED_PERSISTENT` | `REJECTED_PERSISTENT` | A run of failures, or a channel held out by a declared fault. |
| `STATUS_SENSOR_FAULT` | `SENSOR_FAULT` | Channel excluded after `max_consecutive_rejections`. |
| `STATUS_REACCEPTED_WITH_INFLATION` | `REACCEPTED_WITH_INFLATION` | Re-gated under an inflated covariance and re-fused. |

`REJECTED_PERSISTENT` is the operational counterpart of the brief's
`PERSISTENT_DIVERGENCE` and this paper uses the real name throughout. The
distinction matters to an integrator reading a datalink: a status string that
does not exist in the source cannot be parsed, and a paper that documented one
would have sent them looking for it.

**`REJECTED_SPOOF` is a policy label, not a diagnosis.** The gate cannot
distinguish multipath from spoofing from a miscalibrated filter — all three
present as a large innovation, and ADR-0005 says so explicitly. The name
records what the *filter* did: an unproven channel gets no relief. A ground
station that renders this as "SPOOFING DETECTED" would be making a claim the
architecture cannot support, and on a multipath-afflicted route that claim would
be wrong most of the time.

---

## 1. Threat taxonomy

Four threat classes are distinguished by the signal each leaves behind. This
section states, for each, what is **implemented**, what is **architecturally
identified but not built**, and what is **not addressed**.

### 1.1 GNSS jamming

| | |
|---|---|
| **Vector** | RF denial. No spoofed signal is produced; the receiver goes quiet, or reports a fix that is not a fix. |
| **Signal** | The channel's update rate collapses. Longest inter-sample gap grows. |
| **Status** | **Implemented, verified.** |
| **Mechanism** | Tracked per channel as `longest_silence_s` and `min_gap_s`. A gap wider than `2 × min_gap_s` is a *material silence* and resets the health counters, because a run of accepted updates accumulated before the gap says nothing about the first update after it. |

This is the one threat the architecture is explicitly *built around*, and the
reason is structural: silence is observable from the filter's own state and
requires no assumption about the threat model. Every other threat class needs
an assumption.

Jamming is also the only class that is a **benign** failure. A jammed receiver
is telling the truth by being silent, and the correct response is to coast and
then re-acquire. This is what OUN-01 covers and it is measured: 2.506 m ATE
through a 15 s denial.

### 1.2 Step-bias spoofing

| | |
|---|---|
| **Vector** | Attacker emits a false signal with a constant offset from truth, usually after suppressing the genuine one. |
| **Signal** | A large, abrupt, **sustained** innovation against a covariance that was healthy moments earlier. |
| **Status** | **Implemented, verified across 1–100 m.** |
| **Mechanism** | Stage 1 rejects on the first failure. Stage 2 refuses relief, because a continuously streaming channel has no silence to spend. |

Measured, from SRS OUN-02: **zero re-acquisition grants at 1, 2, 3, 5, 10, 20, 40
and 100 m.** The property that matters is the flatness — magnitude buys
nothing.

**Documented cost.** At 1 m and 2 m the channel escalates to `SENSOR_FAULT` and
the solution coasts, reaching 3.430 m and 5.441 m of error. The filter refuses a
plausible-looking receiver and pays for it in drift. This is the correct trade
and it is a large transient that operators must be told about in advance; see
§4.3.

**Untested variant.** *Jam for 15 s, then inject.* After a 15 s silence the
drift bound admits 7.5 m of 1σ, and on the arithmetic in PM-SWAPC-002 §2.5 a
consumer MEMS platform provably cannot have drifted 7 m in 15 s. The filter has
no way to know that. This attack is **not verified** against the current build
and is the highest-priority probe to add (SRS open item 8).

### 1.3 Gradual false-lock pulling

| | |
|---|---|
| **Vector** | Attacker walks the receiver's reported position smoothly from truth toward an offset, over minutes, keeping every individual innovation inside the gate. |
| **Signal** | **None per-update.** Every innovation is plausible. This is the defining property. |
| **Status** | **Architecturally identified, NOT implemented, NOT verified.** |

This is the most dangerous class in the taxonomy and the one the current
architecture cannot see. A slow ramp that keeps `d²` under the threshold at
α = 0.001 never trips Stage 1, never accumulates a trailing run of failures for
Stage 2, and therefore never reaches the re-acquisition logic at all.

The NIS *monitor* keeps `mean_nis` per channel and the architecture is pointed
at exactly this: a channel whose mean NIS sits persistently near its degrees of
freedom while the solution translates is the signature. **That statistic is
computed and logged today, and nothing acts on it.** It is reported in
`fdir_<channel>_mean_nis` for exactly this reason.

Turning it into a detector is open ROADMAP work and is a genuine research
problem, not a threshold. A false-lock pull is, in the limit, indistinguishable
from the platform genuinely moving — the discriminator has to be a second,
independent sensor, which is why a good inertial grade or an independent
odometry source is a security property and not just an accuracy one
(PM-SWAPC-002 §2.2).

### 1.4 Visual tracking corruption

| | |
|---|---|
| **Vector** | Adversarial or incidental degradation of the optical front end: a step in the relative pose, a drifting anchor, a rolling-shutter artefact, a textural degenerate scene. |
| **Signal** | An innovation inconsistent with the IMU-predicted motion, on one of the two anchor blocks. |
| **Status** | **Implemented for detection, deliberately NOT implemented for relief.** |
| **Mechanism** | Stage 1 gates the rotation and translation blocks **separately**, so a broken translation cannot be vouched for by a healthy rotation. Stage 2 is switched off for these channels. |

The asymmetry is a decision, and it is worth stating plainly because a reviewer
will notice it. ADR-0006 enables adaptive inflation for the GNSS position block
only. Two reasons:

1. **Dimensional.** The drift bound is metres per second of translational
   drift. Applying a metre-derived variance to a radian block is a dimensional
   error that still produces a valid covariance, so nothing downstream would
   object and no test would catch it.
2. **Evidential.** The visual channels are where relaxing protection is most
   expensive, and the relief mechanism has not been shown to be safe there.

Verification: a 10 m step on the translation block is rejected with **zero**
inflation grants
(`test_a_visual_step_still_faults_the_channel`, asserting
`fdir_vision_trans_rejected > 0` and `fdir_inflations == 0`). The test asserts
rejection and non-inflation, not fault escalation, and this document does not
claim more than the test does.

### 1.5 Summary

| Threat | Detected | Isolated | Relieved | Verified |
|---|---|---|---|---|
| Jamming | Yes | Yes | Yes — re-acquire on return | 1–100 m, 15 s case |
| Step bias 3–100 m | Yes | Yes | n/a — no relief earned | Yes |
| Step bias 1–2 m | Yes | Yes | No, by design | Yes |
| Step bias after suppression | Unknown | Unknown | — | **No** |
| Gradual false-lock | No | No | — | **No** |
| Visual step / anchor drift | Yes | Yes | No, by design | Yes |

---

## 2. Two-stage defence architecture

### 2.1 Stage 1 — chi-square innovation gate (ADR-0005)

Every aided update is tested before the Kalman gain is formed.

```
S = H P Hᵀ + R
d² = yᵀ S⁻¹ y
accept if d² ≤ χ²_{1-α, dof}
```

| Parameter | Value |
|---|---|
| α | 0.001 |
| dof covered exactly | 1–8 |
| dof 1 / 2 / 3 / 6 thresholds | 10.828 / 13.816 / 16.266 / 22.458 |
| dof > 8 | Wilson-Hilferty, relative error −0.33% at m=4 to −0.005% at m=60 |
| Rejected update cost | returns immediately; `P⁺ = P⁻`, state untouched |
| False alarms, 1212 healthy fixes | **0** — recorded in `fdir/gating.py`, not test-enforced |

The thresholds are **tabulated** rather than computed, and the reason is
specific: this code is on the inner loop, evaluated once per sensor per epoch,
and it must answer for any dof without a bisection loop whose iteration count
is not obviously bounded. That is a real-time argument, not a style preference,
and it is worth stating because it is the kind of decision that otherwise looks
like premature optimisation.

**Why a fixed gate cannot be enough.** The gate is a *correct* implementation
of a test whose premise is a calibrated `S`. In the benchmark's vision-aided
outage case that premise is false: after 15 s of denial the position covariance
has collapsed, so `S` is far too small, and the gate read a returning fix as an
outlier — `mahalanobis_sq` 37.4 against a threshold of 16.266. It rejected **51
of the 76** GNSS updates and the case degraded from 3.428 m to 5.059 m.

The arithmetic was never wrong. The input was. And the tempting fix — widen the
threshold — is precisely the move that discards the false-alarm rate the whole
subsystem exists to provide, while admitting the sustained spoof that Stage 2 is
built to catch. **The premise must be tested, not relaxed.**

### 2.2 Stage 2 — NIS window monitor (ADR-0006)

A rejection is re-tested only when **all** of the following hold. Each condition
closes a hole the others leave.

| # | Condition | Requirement | What it prevents |
|---|---|---|---|
| 1 | A trailing **run** of `reacq_consecutive_rejections` = 3 failures | TR-20 | A 90% rejection rate being mistaken for a run; an old burst staying eligible |
| 2 | The sample is a genuine **outlier** | TR-26 | A declared fault being overturned — see §2.4 |
| 3 | The channel was actually **silent** | TR-23 | A spoof earning trust it did not earn |
| 4 | `P` and `H` supplied, block named | TR-27 | Inflating a covariance the caller cannot see; inflating state the measurement does not constrain |
| 5 | The inflated re-gate passes **with headroom** (≤ 25% of threshold) | TR-24 | A marginal pass, which is exactly the large-gain case |

**The velocity × silence cap** is condition 3, and it is the requirement that
carries the whole design:

```
admitted 1σ  ≤  max_drift_sigma_mps × (longest single gap on that channel)
              =  0.5 m/s × T                              [configured]
```

| T | Admitted 1σ | Situation |
|---:|---:|---|
| 0.2 s | 0.10 m | 5 Hz healthy channel — effectively no budget |
| 1 s | 0.50 m | brief dropout |
| 15 s | 7.50 m | the validated denial; admits the 3.4 m displacement that occurred |
| 60 s | 30.00 m | **outside the validated domain** — see PM-SWAPC-002 §2.5 |

A constant budget cannot draw that line, because the correct limit depends on
how long the filter was blind. That dependence is the design, and it is what
separates a genuine outage from a sustained spoof using no threat-model
assumption at all: **a spoof that never stops transmitting never earns
silence.**

Also bounded: a factor cap of 100× (TR-22, so one grant cannot add more than
30 m of 1σ), and one grant per divergence episode (TR-25, because a filter that
can re-inflate indefinitely is a filter walking itself onto whatever the
measurements say).

### 2.3 The measured result

`outage_visual`, 15 s denial, 76 GNSS updates (71 accepted, 5 rejected):

| | Before ADR-0006 | After | Change |
|---|---:|---:|---|
| Fixes rejected | 51 | 5 | −90% |
| ATE RMSE | 5.059 m | **2.541 m** | −50% |
| Mean NEES | 1996.5 | **419.4** | −79% |
| 2σ coverage | 16.0% | 20.0% | +4 pts |

A single grant at t = 20.4 s carried the recovery:

```json
{"t_s": 20.4, "sensor": "gnss", "status": "REACCEPTED_WITH_INFLATION",
 "mahalanobis_sq": 37.378, "threshold": 16.266,
 "inflation_variance": 20.681, "mahalanobis_sq_inflated": 1.158}
```

The distance collapsed from 37.4 (an outlier) to 1.16 (comfortably inside).
The log records *how much trust was surrendered* — 20.681 m² — not merely that
something happened, which is the difference between an auditable event and a
number an operator has to trust.

### 2.4 The failure this design nearly shipped

Stage 2's first implementation **was inverted over 1–3 m**. It granted relief
to 1 m and 2 m step biases and refused 3 m and above.

The cause was a real ambiguity, not a typo. A channel is excluded for one of two
reasons and both return `accepted = False`:

- the innovation was an **outlier**, or
- the numbers were **fine** and a declared fault is holding the channel out.

Stage 2 could not tell them apart. A 1 m spoof does not stay a 1 m innovation:
the filter is pulled toward it until the residual falls *inside* the threshold,
at which point the gate is entirely happy and the exclusion is the fault hold.
Stage 2 then spent the drift budget buying back a channel it had correctly
condemned.

The fix is `GatingDecision.outlier`, and the requirement it encodes is TR-26.
It is called out here because **the benchmark never caught it** — the benchmark
has no spoof case, and the failing range was *below* the offsets the security
test exercised. The defect was found by a probe, not by regression.

The transferable lesson, and the reason this section exists in a strategy paper
rather than only in the ADR: *for a security mechanism, the test suite must
include the case where the mechanism is inverted, and "no false positives" is
not the same claim as "no false negatives."* SRS keeps AC-05 and AC-06 as
separate criteria for exactly this reason.

---

## 3. Operator telemetry

### 3.1 What the system emits today

Transitions, not transients — a filter that silently drops 40% of its fixes is
indistinguishable from one that has degraded gracefully until you read a
counter.

**Event record** (`trajectory.metadata["fdir_events"]`), one per transition:

| Field | Type | Meaning |
|---|---|---|
| `t_s` | float | Time of the transition |
| `sensor` | str | `gnss`, `vision_rot`, `vision_trans` |
| `status` | str | One of the five statuses in §0 |
| `mahalanobis_sq` | float | The distance the innovation actually had |
| `threshold` | float | The gate threshold that was applied |
| `consecutive_rejections` | int | Rejection count at the transition |
| `inflation_variance` | float | m² or rad² surrendered; `0.0` unless re-accepted |
| `mahalanobis_sq_inflated` | float | The distance under the inflated covariance |

**Per-channel counters** (`stats`), for `fdir_<channel>_<metric>`:

`accepted`, `rejected`, `reaccepted`, `faulted`, `consecutive_rejections`,
`inflation_variance`, `mean_nis`; plus `fdir_inflations` and `fdir_events`
globally.

`mean_nis` is the statistic for §1.3 — computed and logged, not yet acted on.
**Do not present it to an operator as a spoof indicator until something acts on
it.** A number on a display that implies a conclusion the system has not drawn
is worse than an absent number.

### 3.2 Proposed ground-station presentation

**Not implemented.** This is a specification for a datalink and a UI, and it
carries the same honesty constraints as the estimator.

| Status | Operator display | Colour | Action required |
|---|---|---|---|
| `ACCEPTED` | — | none | None. Not transmitted unless verbose. |
| `REJECTED_SPOOF` | `REJECTED` + d²/threshold ratio | amber | None. A single failure is normal at α=0.001. |
| `REJECTED_PERSISTENT` | `CHANNEL EXCLUDED` + duration + rejection count | amber | Watch. Auto-clears on 10 consecutive accepts. |
| `SENSOR_FAULT` | `SENSOR FAULT` + channel + onset time | red | **Investigate. Do not override.** |
| `REACCEPTED_WITH_INFLATION` | `RE-ACQUIRED (COVARIANCE WIDENED)` + variance in m² | blue | None, but **log it for the mission record.** |

Three rules the UI must follow:

1. **Never render `REJECTED_SPOOF` as "spoofing".** Render it as a rejection.
   The label is a policy, not a diagnosis (§0), and on a multipath route a
   confident "SPOOF" is wrong most of the time — which trains the operator to
   ignore the field, which is exactly the failure mode the whole subsystem
   exists to prevent.
2. **Make the variance visible on the inflation event.** It is the only record
   of how much the filter's confidence was reduced on the operator's behalf. A
   mission review should be able to reconstruct the trust the system spent.
3. **`SENSOR_FAULT` is a stop condition, not a warning.** A faulted channel is
   coasting on inertial integration. The measured cost of doing that with a
   spoofed 1 m signal is 3.4 m of error (SRS OUN-02), and it is larger than the
   1 m the operator was trying to avoid. An override should be a deliberate,
   logged action.

### 3.3 Human-in-the-loop: what the system should *not* do

A contested-navigation filter with a human override has a specific failure
mode: the operator learns to override the alarm, and the override becomes the
attack surface.

- **No auto-recovery override.** Recovery is already hysteretic
  (`auto_recovery_count` = 10 consecutive accepts) and requires no human input.
  Adding one would let a single decision defeat a mechanism whose entire value
  is that it is not immediately reversible.
- **Threshold changes are not a ground-station control.** `alpha`,
  `reacq_consecutive_rejections` and `max_drift_sigma_mps` are
  flight-configuration, not operator settings. A datalink that can raise
  `max_drift_sigma_mps` can turn off spoof resistance, and it can do so without
  the estimator emitting anything unusual.
- **Inflation is logged, not prompted.** The operator is *told* the filter
  widened its covariance; they are not asked to approve it. Approval on a
  200 Hz loop is not a human task.

---

## 4. Known limitations

Stated as a register, because a strategy paper that ends on a summary of
success is not useful to the person deciding whether to rely on it.

| # | Limitation | Impact | Status |
|---|---|---|---|
| L-1 | Calibration fails under visual aiding: NEES 391.2, 2σ coverage 20.0% against 95% required | The filter is confidently wrong through an outage. **Not an FDIR defect** — B1, needs a pose graph. | Open |
| L-2 | Gradual false-lock pulling is not detected | The most dangerous threat class is invisible to the current architecture | Open, ROADMAP |
| L-3 | Jam-then-inject spoof is untested; after 15 s silence the bound admits 7.5 m against ~0.2 m of real platform drift | A provably-fake offset could be admitted | Open, highest priority probe |
| L-4 | `max_drift_sigma_mps` = 0.5 is a single default, 33× loose for consumer MEMS and 7 500× for FOG | Spoof resistance is not matched to the installed hardware | Open, PM-SWAPC-002 action 2 |
| L-5 | No benchmark case exceeds a 15 s denial | Everything beyond 15 s is extrapolation | Open, PM-SWAPC-002 action 3 |
| L-6 | 1–2 m step bias costs a fault and 3.4–5.4 m of coast | Correct, but a large transient operators must expect | Documented, §1.2 |
| L-7 | No target-port timing, WCET or jitter measurement | 200 Hz deadline unverified on hardware | Open, OUN-03 |
| L-8 | The visual channels have no relief path | Detection without recovery | By design, §1.4 |
| L-9 | All evidence is synthetic; no flight or bench hardware | No accredited performance claim is possible | Fundamental, §0 of PM-SRS-001 |

**The single most important sentence in this paper:** L-1 is not an FDIR problem.
The fault detection and isolation architecture works, and it is measurably why
the outage case improved by 50%. But the filter is still overconfident by a
factor of ~140 under visual aiding, no threshold in this subsystem will move
that, and upgrading the platform hardware will make it *harder to notice* rather
than fixing it. Anyone reading a green OUN-01 ATE number and concluding the
platform is safe to fly under contested conditions has read one of the two
columns.
