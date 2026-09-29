# Revised Roadmap

Based on the evidence gathered in this audit, the following actionable plan is proposed. Items inherit status from ROADMAP.md and CONSTRAINTS.md; new items are tagged with their evidence level.

## Now (Immediate, within 1 sprint)

| Item | Owner | Evidence | Exit Criteria |
|---|---|---|---|
| **N1: Make the frozen-anchor cross-check reachable** | Estimator team | The code exists (`src/navkit/estimators/eskf.py:521-548`, with outage-start snapshotting at `:817-834`) and its arithmetic is correct: measured d2 of 15.2 at 5 m, 236.7 at 12.5 m, 5454.5 at 60 m, so the `d2 > 225` threshold separates the bands and is pinned by `TestFrozenAnchorCrossCheck`. **It is never reached.** The guard needs `gnss_grants_since_verified > 0` *and* `decision.inflated` on the same epoch, and the grant counter is 0 on every inflation epoch: the grant increments it, and the next epoch is a clean accept that resets it. Measured across a truthful return and 5–100 m of offset — zero reachable epochs. | A run of `_denial_then_spoof(22.0)` in which the cross-check evaluates; `test_the_guard_is_never_satisfied_during_a_sustained_offset_spoof` fails and is rewritten to assert the fix. |
| **N2: Document anchor freeze behavior in README** | Docs team | Add note: "Anchor snapshot frozen at GNSS outage start; cross-check refuses grant if fix disagrees with frozen anchor (N~15). **Currently unreachable — see N1.** Does not replace FDIR; runs concurrently." | `docs/audit/01-executive-summary.md` references the behavior; `check_doc_tables.py` passes. |
| **N3: Verify spoof permanence tests remain xfail** | QA team | ADR-0007: second grant triggers lockout, but measured separators overlap below ~1.4σ. Tests `TestPermanenceIsStillUndetected` marked `xfail(strict=False)`. N1 is the same root cause seen from the other side: one grant, then permanent adoption, so there is no second grant to count. | `uv run pytest tests/test_nis_monitor.py::TestPermanenceIsStillUndetected -v` shows xfail. |
| **N4: Re-baseline the CI lint gate** | Release manager | Running CI's exact commands locally finds **14 ruff errors** (`F401`/`F811`/`F841`, mostly unused imports) and **15 mypy errors** on the committed tree, so the `lint` job is red, not merely unverified. Most mypy errors are one root cause: the run state is annotated `dict[str, np.ndarray]` but holds ints, `None` and bools, which is also why `eskf.py:797` needs a `# type: ignore`. B2 closed the tooling gap; this closes the failures. | `uv run ruff check src tests scripts` and `uv run mypy src --ignore-missing-imports` both exit 0. |

## Next (2-4 sprints)

| Item | Owner | Evidence | Exit Criteria |
|---|---|---|---|
| **N5: Close B1 with pose graph (Track A, Stage 4)** | Core team | B1: mean NEES 419.4 under GNSS denial with vision. The only genuine fix; no threshold in FDIR will move this number. Pose graph over visual keyframes models correlated drift. | Exit criteria from ROADMAP.md:242-243: NEES below 10 with vision enabled and GNSS denied, coverage above 90%, `vision_enabled = True` as shipped default. |
| **N6: Promote `vision_enabled = True` default after B1 resolved** | Release manager | After N5 exit criteria met: calibrated covariance under GNSS denial. `CONSTRAINTS.md:S3` lifted. | `CONSTRAINTS.md` updated; benchmark `outage_visual` shows NEES < 10, coverage > 90%. |
| **N7: Promote `anchor_pos_sigma_m` / `anchor_rot_sigma_deg` as tunable per-platform** | Config team | Currently defaults (1.0 m, 5.0°). Named in `FdirConfig` and `EskfConfig` for platform tuning. | `EskfConfig.as_dict()` serializes both; benchmark can override. |
| **N8: Add per-sensor detection of multipath/spoof/degradation** | Perf team | ADR-0005 open question: gate detects implausibility but not cause. Requires innovation variance analysis (multipath), consistency check (spoof), and bias drift tracking (degradation). | Exit test from ROADMAP.md:208-213: detection rate above 95% per fault type at measured false-alarm rate of zero on control. |

## Later (4-8 sprints)

| Item | Owner | Evidence | Exit Criteria |
|---|---|---|---|
| **N9: Extend analysis/findings.py with typed detection claims** | Research team | ADR-0006: each detection should be a typed claim with measured detection rate and false-alarm rate. Currently only demonstrations that it fires once. | `analysis/findings.py` extends `Claim` type with `detection_rate` and `false_alarm_rate` fields; tests assert both numbers. |
| **N10: Seed sweep — DONE (noise only, not scenes)** | Research team | Run 10 seeds per case. **Result: the conclusion is robust, the specific numbers are not.** `outage_visual` is overconfident at *every* seed (min NEES 211.7 against an expected 3; coverage 6.8–34.8% against 95%), so B1 stands. But NEES spans 211.7–2103.4 (mean 844, not the quoted 419.4) and `vision_anchor_in_measurement_noise` spans 280–12537, so every single-draw number in README.md is one sample, not a property. Two controls flip verdict across seeds (`gnss_only`: 3 underconfident, 4 mixed, 1 overconfident, 1 mixed, 1 mixed; `outage_control` never clean), and the two visual-outage cases are not separable — ranges overlap and the sign favours degraded-camera on only 7/10 seeds. `scripts/seed_sweep.py` + `results/seed_sweep.json` (gitignored, regenerate with `--seeds 10`); `--seed` override added to `run_benchmark.py`, default path bit-identical to the committed baseline. **Still open: this varied noise realisations on ONE deterministic trajectory. Scene geometry, outage timing and duration are unchanged, so generalisation across scenes is untested.** | Multi-scene parameter sweep (outage duration, motion class, rate) |
| **N11: Platform-specific drift bound tuning** | Perf team | `max_drift_sigma_mps=0.5 m/s` is platform-agnostic; could be tuned per IMU grade. | Benchmark runs with 3 IMU grades (low/medium/high) show detection rate adjustment. |

## Research (Ongoing)

| Item | Owner | Evidence | Status |
|---|---|---|---|
| **R1: Tighten spoof detection separatrix** | Research team | Measured: honest band and modest-spoof band overlap below ~1.4σ at grant time. A second modality (cross-check against frozen anchor) or independent drift model is required. | In progress: audit implemented anchor cross-check (N1, since found unreachable); xfail on permanence detection pending. |
| **R2: Multi-anchor ESKF** | Research team | Two anchors provide baseline for relative drift modeling. Not attempted in this repo. | Requires state vector expansion (2×6 anchor states); covariance 27×27 instead of 21×21. |
| **R3: Consistency monitor that responds to genuine spoof** | Research team | ADR-0005: consistency monitor detects under-estimated S but cannot distinguish spoof from overconfident filter. | Requires fusing odometry or IMU-predicted position as second modality. |
| **R4: Monte Carlo validation of FDIR parameters** | Research team | `max_inflation_factor=100`, `max_drift_sigma_mps=0.5 m/s`, `reacq_pos_sigma_m=3.0` chosen from benchmark, not from target error budget. | Re-measure across 10+ seeds; confirm robustness. |

---
*Roadmap revised against audit evidence: 567 tests (563 pass, 2 skip, 2 xfail), 86.58% line coverage, B1 open, B5 closed, ADR-0007 implemented with xfail. All items evidence-backed; no assumptions promoted to facts.*