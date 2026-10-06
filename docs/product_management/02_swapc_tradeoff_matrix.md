# 02 — SWaP-C and Sensor Selection Trade-off Matrix

**Document ID:** PM-SWAPC-002
**Status:** Planning estimate — **not procurement data**
**Applies to:** platform integration of `navkit` across three assumed deployment profiles
**Date:** 2026-09

---

## 0. Status of the numbers in this document

**Read this before the tables.** This is a trade study, and a trade study is
allowed to reason about hardware that has not been selected. It is not allowed to
present reasoning as measurement.

| Tag | Meaning |
|---|---|
| **[M] Measured** | From `results/benchmark.json`, synthetic known-answer fixture |
| **[D] Derived** | Computed from [M] or [C] values, arithmetic shown |
| **[C] Configured** | A default in the `navkit` source — a choice, not a result |
| **[E] Estimate** | **External planning judgement. Not from this repository.** |
| **[P] Proposed** | Target for a future revision |

**Every unit cost, every watt, and every mass in §2–§3 is [E].** None of it is
measured, quoted, or sourced from a vendor datasheet. Ranges are deliberately
wide — often a factor of three — because a factor-of-three range is honest
about what is not known, where a precise-looking number is not. Before any of
this reaches a budget, every [E] cell must be replaced with a dated quote or a
datasheet citation, and the cells marked accordingly.

The one number in this document that is genuinely measured is the filter's
end-to-end error, and the one genuinely derived number that matters most is in
§4, where a single configured constant turns out to be wrong by three orders of
magnitude depending on which IMU you fit. That finding is the reason to read
this document, and it does not depend on a single [E] figure.

---

## 1. What `navkit` costs the platform

The estimator is a 21-state error-state Kalman filter [C] running a
predict/update loop at 200 Hz over IMU data, with an optional visual anchor
re-commitment at the front-end rate, and a chi-square gate plus an NIS monitor
on every aided update [M].

| Property | Value | Tag | Note |
|---|---|---|---|
| State dimension | 21 | [C] | `_N_STATES = 21` |
| Filter rate | 200 Hz | [M] | 6001 IMU epochs per 30 s case |
| Heavyest case, x86 CPython | 0.897 s estimator runtime per 30 s scenario | [M] | **not a target estimate**; 2.811 s wall including fixture setup |
| Heavyest case, filter only | 0.842–0.897 s | [M] | see caveat below |
| SciPy | none | [M] | hand-rolled χ² and quantiles |
| Learned components | none | [M] | no NN anywhere in the graph |
| Compiled dependencies | `numpy` | [C] | see OUN-03, SRS TR-11 |

**The 0.897 s figure must not be quoted as an A53 budget.** It is CPython on
x86, and CPython overhead would dominate on any target. What it does establish
is that the algorithm is not pathologically expensive: 0.897 s of work spread
over 6001 epochs is 150 µs of x86 per epoch for dense 21×21 algebra, which
leaves a great deal of headroom for a native build on a much slower core. A
real A53 number requires a native build, and no timing, WCET or jitter
measurement exists anywhere in this project (SRS TR-32).

The practical consequence for platform selection: **the filter is not the
reason to choose a compute tier.** On any of the three profiles below, the
power and cost budget is dominated by the sensor suite and the compute module's
standby overhead, not by 21-state linear algebra. Where the filter does impose
a constraint is on the *front end*: 200 Hz of fused IMU with a visual anchor
re-commitment at every keyframe is a real-time deadline, and Python-with-GIL
will not meet it without a native extension. That is a porting task, not an
algorithmic one, and it should be scoped as such.

---

## 2. Platform profiles

### 2.1 Profile definitions

| | **Class 1: Small UAS** | **Class 2: Medium UAS** | **Class 3: UGV** |
|---|---|---|---|
| Representative | Small multirotor | Small fixed-wing aircraft | Autonomous ground vehicle |
| Payload budget | < 250 g | 1–3 kg | > 10 kg |
| Compute power budget | < 5 W | 15–30 W | > 100 W |
| IMU grade | Consumer MEMS | Tactical MEMS | FOG / high-end tactical |
| Primary sensor | Single optical (monocular) | Stereo or stereo + thermal | LiDAR / stereo + wheel odometry |
| GNSS denial of interest | 15 s | 60 s | 60 s+ |
| Compute module class | Cortex-A53 quad, 1–2 GB | Cortex-A72 or A53 octa | x86-64 or equivalent |

Mass, power and cost ceilings for all three classes are planning assumptions
(tagged [E]), not taken from a specific programme, platform or datasheet; no
requirements brief is part of this repository. **Class 2 is the one to watch:**
the assumed payload of 1–3 kg and power of 15–30 W may be tight for a small
fixed-wing airframe whose own gross mass could be near 2 kg (also an
assumption, to be confirmed). If so, the full sensor suite plus compute becomes
the binding constraint on the whole profile, and it is worth confirming that the
1 kg end is available rather than assumed.

### 2.2 IMU grade comparison

| Attribute | Consumer MEMS | Tactical MEMS | Fiber Optic Gyro |
|---|---|---|---|
| ARW [°/√hr] | 0.1–1.0 [E] | 0.02–0.1 [E] | 0.005–0.02 [E] |
| VRW [m/s/√hr] | 0.05–0.3 [E] | 0.02–0.1 [E] | < 0.02 [E] |
| Accel bias instability [m/s²] | ~2e-3 [M, validated cfg] | 1e-4–2e-5 [E] | ~1e-5 [E] |
| Gyro bias instability [°/s] | ~5.7e-4 [M, validated cfg] | 1e-5–1e-6 [E] | ~1e-6 [E] |
| **Meets SRS TR-01 (≤0.05 °/√hr)?** | **No** [M] | Marginal [E] | Yes [E] |
| **Meets SRS TR-02 (≤0.1 m/s/√hr)?** | **No, 1.2× over** [M] | Likely [E] | Yes [E] |
| Bias warm-up | none | 1–10 s | 30–300 s |
| Shock survivability | low [E] | high [E] | very high [E] |
| Unit cost [k$] | 0.2–2 [E] | 3–15 [E] | 25–120 [E] |
| Power [W] | 0.05–0.15 [E] | 0.2–0.6 [E] | 2–8 [E] |
| Mass [g] | 1–5 [E] | 15–60 [E] | 80–400 [E] |

**The validated configuration sits at the top of the Consumer MEMS column**:
ARW 0.688 °/√hr and VRW 0.120 m/s/√hr [M, derived in SRS §2.2]. It fails SRS
TR-01 by 13.8× and TR-02 by 1.2×. That is recorded in the matrix rather than
buried because it has a direct consequence: **no performance claim in
`navkit` has been produced on hardware that meets the programme's own IMU
requirement.** The results are encouraging — the filter works on hardware 14×
worse than specified — but an accredited system needs the run repeated on
compliant hardware, and that is open item 5 in the SRS.

Note also the FOG warm-up column. A 30–300 s thermal soak is longer than a
Class 1 mission and comparable to a Class 2 one. FOG on a tactical UAS is
usually disqualified by warm-up and cost simultaneously, not by performance.

### 2.3 Sensor suite and processing comparison

| Attribute | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| Optical sensor | Monocular, global shutter [E] | Stereo global shutter + thermal [E] | LiDAR or stereo [E] |
| Frame rate | 20–30 Hz [C for 20 Hz] | 20–30 Hz [C for 20 Hz] | 10–20 Hz [E] |
| Rotation noise budget | 0.35° 1σ/frame [C] | 0.1–0.35° [C] | 0.05–0.2° [E] |
| Translation noise budget | 0.05 m 1σ/frame [C] | 0.02–0.05 m [C] | 0.01–0.03 m [E] |
| Frame drop tolerance | 30% burst, verified [M] | 30% burst, verified [M] | > 50% [E] |

> Corrected 2026-09: both "verified" cells previously described a 30% burst that
> was never run. The benchmark config misspelled `drop_fraction`, so the case
> executed at the 20% default. The config is fixed and both columns are now
> genuinely 30% (`outage_visual_degraded_camera`: 1.872 m, mean NEES 216.6,
> 2σ coverage 18.5%). The 20%→30% comparison is no longer available, so
> "verified" rests on the single 30% point; see ADR-0008.
| Additional aiding | none | wheel/airspeed optional | wheel odometry, altitude |
| Front-end processing | on SoC, CPU only | on SoC, CPU + NPU optional | dedicated, GPU optional |
| Sensor power [W] | 0.5–1.5 [E] | 2–5 [E] | 10–30 [E] |
| Sensor mass [g] | 10–30 [E] | 80–250 [E] | 500–2000 [E] |
| Sensor unit cost [k$] | 0.5–3 [E] | 3–12 [E] | 15–60 [E] |
| **Net payload** | **< 0.25 kg** [E] | **1–3 kg** [E] | **> 10 kg** [E] |

The 20 Hz / 0.35° / 0.05 m figures are the validated operating point from
`configs/benchmark.yaml` [C], and SRS TR-07/TR-08 record them as sitting
*exactly at budget with no margin*. A Class 1 monocular sensor in that noise
band is demanding; a global-shutter sensor with fixed-in-lens distortion
control is effectively mandatory, because a 0.35° rotation budget on a
consumer sensor is consumed by intrinsic distortion before the filter ever sees
a number. That is an optical problem and no filter tuning addresses it.

### 2.4 Compute comparison

| Attribute | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| Module | Quad A53, 1–2 GB [E] | Octa A53/A72, 4–8 GB [E] | x86-64 or equiv. [E] |
| Sustained compute [W] | 2–5 [E] | 10–25 [E] | 40–100 [E] |
| Filter share of budget | < 2% [D] | < 2% [D] | < 2% [D] |
| Unit cost [k$] | 15–45 [E] | 40–120 [E] | 150–500 [E] |
| **Total compute + sensor power** | **< 5 W** [E] | **15–30 W** [E] | **> 100 W** [E] |

The "< 2% share" rows are [D] and follow from §1: the filter's arithmetic is a
small fraction of a module that is mostly running an OS, a front end, and a
communications stack. **The filter is not what forces a platform decision.**
If a profile cannot afford 5 W, it is the OS, the front end and the datalink,
and the estimator is available on all three tiers.

### 2.5 Drift over a 60 s denial

Two different quantities get called "drift", and conflating them produces
nonsense procurement arguments. They are separated here.

**(a) Platform capability — how far the solution actually moves.** Dominated
by accelerometer bias double-integration, `σ_p ≈ ½ · a_bias · t²`, because at
these durations the white-noise term is negligible (with the validated VRW,
the white-noise contribution at 60 s is 0.15 mm [D] — four orders below the
bias term). [D] throughout, from representative `a_bias` per grade:

| Grade | `a_bias` [m/s²] | σ_p at 15 s | σ_p at 60 s |
|---|---:|---:|---:|
| Consumer MEMS, validated cfg | 2.0e-3 [M] | 0.225 m | 3.600 m |
| Consumer MEMS, mid | 1.0e-3 [E] | 0.113 m | 1.800 m |
| Tactical MEMS, low end | 1.0e-4 [E] | 0.011 m | 0.180 m |
| Tactical MEMS, high end | 2.0e-5 [E] | 0.002 m | 0.036 m |
| FOG | 1.0e-5 [E] | 0.001 m | 0.018 m |

**(b) FDIR admission budget — how far the filter is willing to be wrong.** A
*configured* trust decision, not a capability, at
`max_drift_sigma_mps = 0.5` [C]:

| Channel silence | Admitted 1σ | 0.2 s [C] | 1 s | 15 s [C] | 60 s |
|---|---:|---:|---:|---:|---:|
| Budget | 0.5 m/s × T | 0.10 m | 0.50 m | 7.50 m | 30.00 m |

**Put (a) and (b) side by side and the document's main finding appears:**

| Grade | Actual drift at 15 s | FDIR budget at 15 s | Budget ÷ actual |
|---|---:|---:|---:|
| Consumer MEMS (validated) | 0.225 m | 7.50 m | **33×** |
| Tactical MEMS | 0.011 m | 7.50 m | **685×** |
| FOG | 0.001 m | 7.50 m | **7 500×** |

A single `max_drift_sigma_mps = 0.5` default is simultaneously 33× too loose
for the consumer MEMS it was tuned against and 7 500× too loose for a FOG. It
is one constant serving three orders of magnitude of hardware.

This is not a bug in the constant — ADR-0006 is explicit that it is
"deliberately generous", because the cost of setting it too low is refusing a
genuine re-acquisition, which is the failure the mechanism exists to remove.
Generosity is the right default when the hardware is unknown. It **is** a bug
in shipping one value across three platforms, and the corrective is named in
§5.

**The security consequence, stated so it is not discovered in the field:** after
a 15 s outage, a Class 1 platform using the default bound would admit a
spoofed offset of up to 7.5 m. SRS OUN-02's zero-grant table does **not** cover
that case, because that probe ran on a *streaming* channel where the budget is
0.1 m. The untested attack is *jam for 15 s, then inject 7 m* — and on the
arithmetic above, a consumer MEMS platform physically cannot have drifted 7 m
in 15 s, so the offset would be provably fake and the filter would have no way
to know that. On a FOG it would be provably fake by a factor of 7 500.

---

## 3. Consolidated comparison

| Attribute | Class 1 UAS | Class 2 Recon UAS | Class 3 UGV |
|---|---|---|---|
| Payload | < 250 g [E] | 1–3 kg [E] | > 10 kg [E] |
| Compute power | < 5 W [E] | 15–30 W [E] | > 100 W [E] |
| IMU grade | Consumer MEMS | Tactical MEMS | FOG / high-end tactical |
| IMU cost [k$] | 0.2–2 [E] | 3–15 [E] | 25–120 [E] |
| Sensor suite cost [k$] | 0.5–3 [E] | 3–12 [E] | 15–60 [E] |
| Compute cost [k$] | 15–45 [E] | 40–120 [E] | 150–500 [E] |
| **Subtotal, sensor+compute [k$]** | **15.7–50** [E] | **46–147** [E] | **190–680** [E] |
| IMU power [W] | 0.05–0.15 [E] | 0.2–0.6 [E] | 2–8 [E] |
| Sensor power [W] | 0.5–1.5 [E] | 2–5 [E] | 10–30 [E] |
| Compute power [W] | 2–5 [E] | 10–25 [E] | 40–100 [E] |
| 60 s denial drift | 3.6 m [D] | 0.18 m [D] | 0.018 m [D] |
| Meets OUN-01 (< 3.0 m @ 15 s)? | Marginal, evidence favours yes [M] | Yes, large margin [D] | Yes, very large margin [D] |
| Meets SRS TR-01/02? | **No** [M] | Likely [E] | Yes [E] |
| Pose graph affordable? | No | Yes, at effort | Yes |
| **Recommended role** | Short-denial intercept | **Primary GNSS-denied platform** | Long-endurance, contested-nav reference |

Cost subtotals exclude the airframe, the datalink, the antenna and
integration labour, and the wide ranges are a deliberate reflection of how
little is actually known. Treat the ordering as reliable and the magnitudes as
indicative.

---

## 4. Product management recommendation

### 4.1 Which platform to develop against

**Develop against Class 2.** The reasoning is not that Class 2 is the best
platform; it is that Class 2 is the only tier where the primary operational
need is actually verifiable.

- **Class 1** is a demonstration vehicle. Consumer MEMS is 13.8× over the ARW
  budget [M], which means the filter runs, but it means the programme's own
  sensor requirement is unmet and no accredited result can be claimed from it.
  Its value is regression testing the FDIR stack cheaply and continuously.
- **Class 2** is where tactical MEMS closes TR-01/TR-02, where a stereo front
  end has enough mass budget to hold 0.35° and 0.05 m without compromise, and
  where a pose graph is affordable. It should carry the OUN-01 and OUN-02
  evidence.
- **Class 3** should be the **reference implementation**, not the development
  target. It has the compute and power headroom to run the full stack including
  a pose graph, and its drift is two orders below the requirement, which makes
  it the only profile where filter defects are not masked by platform
  behaviour. Debugging a filter on hardware that drifts 3.6 m in 60 s is
  debugging two things at once.

### 4.2 ESKF dead reckoning versus sliding-window pose graph

The decision rule below is derived from what the project has measured, not from
general SLAM practice.

**The trigger is the deadline, not the SWaP envelope.**

A pose graph over visual keyframes is a memory-bounded optimisation whose cost
is `O(k)` in the window size and which must be re-solved as each keyframe is
added. The ESKF is `O(1)` in memory and a fixed cost per epoch. The question is
therefore not "can this platform afford a pose graph" but "how long is the
platform denied, and what does the ESKF do at the end of it".

What is actually known [M]:

| Outage length | ESKF behaviour, measured | Pose graph needed? |
|---|---|---|
| ≤ 15 s | ATE 2.541 m, and the healthy fixes are re-admitted (ADR-0006). Works. | **No** |
| 15–60 s | **No data.** No benchmark case exceeds 15 s. | **Yes** — the ESKF is extrapolating a linearising approximation well outside its validated domain |
| > 60 s | **No data.** | **Yes**, unconditionally |

The 15 s boundary is not a physical limit; it is the length of the outage the
benchmark exercises, and the reason the ESKF survives it is the drift bound in
§2.5(b): 15 s of silence buys 7.5 m, which covers the 3.4 m displacement that
actually occurred. At 60 s the same bound buys 30 m, which on a FOG platform is
15 000× the real drift, and the gate has lost essentially all discriminating
power.

**Concrete rule:**

| Condition | Configuration | Rationale |
|---|---|---|
| Denial ≤ 15 s, or Class 1 SWaP | ESKF, `vision_enabled` per the profile | Verified. AC-01, AC-02 pass. |
| Denial 15–60 s, Class 2+ SWaP | **Sliding-window pose graph**, 20–40 keyframes | Outside the validated domain; the anchor error is not a state the 21-state filter models |
| Denial > 60 s, any platform | Pose graph + external aiding; ESKF only as the propagation front end | Inertial-only is not viable at this duration |
| **Always, any denial length** | ESKF for propagation, pose graph for the visual factor | They are not alternatives; the ESKF is the real-time inner loop and the graph is the batch correction |

### 4.3 The hard constraint that does not move

**AC-03 and AC-04 currently fail** (SRS §3.2): mean NEES 419.4 against an
expected 3, and 2σ coverage of 20.0% where 95% is required. This is blocker
B1, it is a pose-graph problem, and it is true on *all three* platform profiles
because it is a model error rather than a hardware limit.

No sensor selection in §2 fixes it. A Class 3 platform with a FOG and a LiDAR
will still over-trust a single visual anchor, because the error is correlated
across frames and a single anchor cannot represent it — no matter how good the
hardware is. It will be *harder* to notice on good hardware, which is the worse
outcome. **Do not let a platform upgrade be read as closing B1.**

---

## 5. Required actions before this document is used for planning

| # | Action | Owner | Blocks |
|---|---|---|---|
| 1 | Replace every [E] cell with a dated quote or datasheet citation | Procurement | All cost rows |
| 2 | **Derive `max_drift_sigma_mps` per IMU grade from fitted bias instability** | FDIR | §2.5 finding; OUN-02 residual |
| 3 | Add a 60 s benchmark case; the 15 s bound is a data limit, not a physical one | Estimation | §4.2 decision rule |
| 4 | Add a jam-then-inject spoof probe (§2.5(b) attack) | FDIR | OUN-02 completeness |
| 5 | Confirm Class 2 payload ceiling against a specific airframe | Systems | §2.1 |
| 6 | Native build, then A53 timing and jitter | Platform | SRS TR-30, TR-32 |
| 7 | Repeat the benchmark on TR-01/TR-02-compliant hardware | Validation | OUN-01 accreditation |

Item 2 is the one with a security consequence rather than a planning
consequence, and it is cheap: the constant already exists and is already a
named config field. It needs a per-platform value derived from a bench-fitted
bias instability, and the value should be *tighter* than 0.5 m/s wherever the
platform can support it, because every factor of tightness is a factor of
spoof resistance.

**Provisional values for planning only, to be replaced by bench fit [P]:**

| Grade | `max_drift_sigma_mps` | Basis |
|---|---:|---|
| Consumer MEMS | 0.05 | ~3× the validated 0.015 m/s equivalent |
| Tactical MEMS | 0.005 | ~7× the 0.00073 m/s equivalent |
| FOG | 0.001 | ~15× the 0.000067 m/s equivalent |

Each retains a deliberate 3–15× safety factor over the platform's own drift
capability, preserving the "generous by design" property ADR-0006 requires,
while removing the three-orders-of-magnitude looseness that a single default
carries across platforms.
