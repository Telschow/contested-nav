# ML / AI baseline


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

Audit date: 2026-09-29.

---

## 1. Headline: this repository contains no machine-learning component

**Verified by search, not assumed from the absence of the words "AI" and "ML".**
A case-insensitive search across all Python, TOML, YAML, YAML-workflow and
Markdown files for `torch`, `tensorflow`, `keras`, `jax`, `sklearn`,
`scikit-learn`, `transformers`, `lightgbm`, `xgboost`, `catboost` and `onnx`
returns **zero matches**.

Also verified absent: notebooks (`*.ipynb` — none anywhere) · model checkpoints
(`*.pt`, `*.pth`, `*.onnx`, `*.h5` — none) · serialised models (`*.pkl`, `*.npz`
— none) · datasets (`data/` does not exist) · GPU/CUDA references · any
`requirements.txt` naming a framework · any training loop, optimiser, loss
function, or gradient step.

**Runtime dependencies, in full:**

```
numpy>=1.26
matplotlib>=3.8
pyyaml>=6.0
```

That is the entire dependency set. There is no deep-learning framework, no
inference runtime, no ONNX export, no model registry, and no ML tooling of any
kind.

**Therefore this document is a scope determination, not an analysis.** Sections
covering model architecture, training procedure, loss/objective, and inference
procedure are not applicable and are listed as such rather than filled with
plausible-sounding content. Inventing an ML framing for a 21-state Kalman filter
would misrepresent the work to exactly the audience this repository is aimed at.

---

## 2. What the project actually is

`navkit` is classical state estimation and estimation theory, with a
security-adjacent fault-detection layer.

| Dimension | Actual content **[V]** |
|---|---|
| **Problem definition** | Is a navigation filter's *reported uncertainty* consistent with its actual error? Concretely: does the filter's covariance `P` describe the world, or does it produce confident nonsense? |
| **Inputs** | Inertial samples (gyro, accel), GNSS position fixes, visual relative-pose updates. Each with a noise model. |
| **Outputs** | Estimated pose (`T_wb`), position covariance, per-channel FDIR verdicts, and typed claims (`FACT`/`MEASUREMENT`/`INTERPRETATION`/`HYPOTHESIS`). |
| **Data flow** | `synthetic.py` (analytic trajectory) → `sensors/models.py` (noise) → `degrade/inject.py` (outages, dropouts) → `estimators/eskf.py` (filter + FDIR) → `eval/` (ATE, NEES, coverage) → `analysis/findings.py` (claims). |
| **Model architecture** | 21-state **error-state** Kalman filter. Nominal state `(R, p, v, b_a, b_g)`; error state `[dθ(0:3), dp(3:6), dv(6:9), db_g(9:12), db_a(12:15), c_p(15:18), c_t(18:21)]`. The last 6 are visual-anchor nuisance parameters — the innovation of ADR-0001. |
| **"Training" procedure** | **None.** Nothing is fit to data. The only fitted quantities are per-run estimates produced online by the filter itself. There is no offline optimisation, no parameter search, no hyperparameter tuning loop. |
| **Inference procedure** | `ErrorStateKalmanFilter.run(imu, gnss, vision)` — batch replay over a trajectory. |
| **Loss / objective** | **None in the learning sense.** The equivalent is a statistical objective: NIS (normalised innovation squared) and NEES, minimised in the Kalman sense by construction. Rejection thresholds are chi-square quantiles at a declared false-alarm rate, not learned parameters. |
| **Metrics** | ATE under 4 alignments, RPE, drift slope, **NEES**, **2σ coverage** with Wilson intervals, rejection counts, buffer health, verdict (bulk vs tail). |
| **Evaluation methodology** | Known-answer synthetic fixture. Ground truth is the *analytic* trajectory the generator is built from, so truth is exact rather than another estimate. The filter is initialised exactly at truth at `t=0` (motion is `1-cos(ωt)` so position, velocity, rotation and angular rate are all zero at `t=0`), so every later error belongs to the filter. |
| **Baselines** | One: `dead_reckoning` (inertial only), answering "how much is the filter and how much is the motion model". A second control, `vision_anchor_in_measurement_noise`, reproduces the pre-ADR-0001 defect as a regression baseline. **No external system is compared against.** |
| **Validation methodology** | Bootstrap-free; the filter's own covariance provides the error ellipsoid, scored by NEES against its expectation. A 10-seed noise sweep (2026-09-29) tests stability. Wilson intervals on coverage. |
| **Failure modes** | The central one is measured and documented: the visual anchor (`c_p`, `c_t`) is a constant body-frame offset that cannot represent correlated drift across frames, so when GNSS is denied the only constraint on the anchor is the anchor itself, and `P` stops describing reality. |

---

## 3. Uncertainty handling — the closest analogue to ML practice, and a genuine strength

In a project with no learned model, the discipline that substitutes for
"how do we know it generalises?" is **"is the uncertainty itself trustworthy?"**
That discipline is implemented, not asserted:

- **NEES against its expectation** — catches systematic over/under-confidence
  that a single error metric hides.
- **2σ coverage with a Wilson interval** — catches a filter that is well-calibrated
  in bulk but produces tail escapes, and vice versa. Reported as **two verdicts**
  (bulk and tail) with disagreement *named rather than resolved*, because
  collapsing them to one boolean discards half the evidence.
- **Gating with a declared false-alarm rate** (`alpha=0.001`) and the rejection
  count reported, never silently applied — "silent gating would hide a divergence."
- **A coverage ratchet** as a build gate, so a coverage regression fails CI
  instead of needing to be noticed in a diff.
- **`scripts/check_doc_tables.py`**, which fails CI if any numeric cell in the
  README or `index.html` tables disagrees with a live benchmark run. This is what
  makes "no number here is hand-typed" *checkable* rather than a promise.

**Uncertainty is not claimed where it is absent.** `dead_reckoning` has no
covariance, so the benchmark omits NEES for it entirely rather than reporting
zero or a meaningless value. The seed sweep's `_collect` has an explicit
null-safe path for the same reason, and a test pins it.

---

## 4. Which claims are actually supported

`analysis/findings.py` already implements the right taxonomy. Applying it to the
repository's own headline claims:

| Claim | Status | Evidence |
|---|---|---|
| The filter is overconfident under visual aiding during GNSS denial | **Experimentally demonstrated** | 10/10 seeds; min NEES 211.7 vs expected 3; max coverage 34.8% vs 99.3%. Robust. |
| The specific figures (NEES 419.4, ATE 2.541 m) | **Implemented (measurable) but single-draw** | Seed-0 only. Range across seeds 211.7–2103.4. Now caveated in all docs. |
| Root cause is the unmodelled anchor error | **Hypothesis with a stated falsification test** | `MECHANISM_LIBRARY` pairs it with an experiment that would refute it. Not yet run. |
| Closing B1 requires a pose graph | **Interpretation** | Design judgement, reasoned in ROADMAP Track B. Not demonstrated. |
| ADR-0008 cross-check detects sustained spoof | **Hypothesised, currently false** | Zero reachable epochs. Arithmetic verified in a forced-grant harness only. |
| No threshold in FDIR can separate multipath from spoof | **Hypothesis, partially tested** | `docs/audit/05` reports overlapping separators below ~1.4σ. |

**Nothing in the repository claims to be novel, and nothing should be upgraded to
novel on the strength of this audit.**

---

## 5. Data leakage, distribution shift, robustness

| Concern | Assessment |
|---|---|
| **Data leakage** | **Structurally impossible.** Ground truth is an analytic function; the filter is not fit to it. There is no train/test split because there is no training. The one place leakage *could* appear — the anchor being re-derived from the filter's own corrected state — is precisely the defect ADR-0001 exists to fix, and the pre-fix configuration is retained as a regression control. |
| **Distribution shift** | **Present and unmitigated.** One deterministic 30 s analytic trajectory, one 15 s outage at t=5–20 s, one GNSS rate (5 Hz), one visual rate (20 Hz). The seed sweep varies *noise* only; `synthetic.py` takes no seed, so all draws replay identical motion. Generalisation across scenes, motions, outage durations and rates is untested and is correctly listed as open. |
| **Robustness** | Tested to a meaningful degree *within* the fixture: FDIR is exercised against spike, sustained offset, and camera-drop scenarios; the 10-seed sweep establishes the overconfidence is not seed-specific. Untested: real sensor characteristics, time sync error beyond the synthetic offset, extrinsic calibration error, temperature effects, any real RF or spoofing environment. |
| **Reproducibility** | Strong for a project this size. Every number regenerates from a committed config and a fixed seed; the benchmark is verified bit-reproducible across two runs; `uv.lock` exists (293 KB, **currently untracked** — should be committed); Python 3.11/3.12/3.13 are all exercised in CI. `matplotlib` and `numpy` are floored (`>=`) but not pinned, so a future release can move figure bytes and package resolution. |

---

## 6. Hardware requirements

None beyond a CPU. The largest case replays 3,000 IMU samples at 200 Hz with
21×21 covariance propagation and runs in single-digit seconds; the whole suite
(567 tests) takes ~87 s; the 10-seed sweep over 7 cases completes in minutes.
There is no GPU path, no training cost, and no dataset download in the default
workflow. The project is runnable on a laptop or in a free CI runner.

This is a genuine advantage for a portfolio project: a reviewer can reproduce
every claim in under two minutes on any modern machine.

---

## 7. Summary judgement

The absence of ML is not a weakness to be corrected — it is the project's
identity, and the README says so plainly. For the stated audience
(autonomous-systems, robotics, aerospace, defense-tech), the demonstrated
strengths are:

1. **Measurement honesty about uncertainty** — the discipline most robotics
   stacks skip, implemented and gated in CI.
2. **A documented, structural failure mode** — not tuned around, measured,
   published, and worked around by shipping the feature disabled.
3. **Auditability** — three dependencies, no compiled extensions, every
   statistical function traceable to in-repo code, every number regenerable, and
   claims typed and paired with falsification tests.

**The weakest claim surface** is quantitative rigor: single-draw numbers, a
one-scene fixture, no external comparison, and no statistical test. Those are
addressable with the tools already present (`seed_sweep.py`, Wilson intervals)
and are the highest-value next steps for research credibility.
