# Security and Performance Audit


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

This section catalogs attack paths, vulnerabilities, and measured performance bottlenecks with file/line evidence.

## Security Audit

### Threat Model: GNSS Spoofing During Outage

The primary adversarial scenario is a sustained GNSS spoof during a denial period, where an attacker transmits counterfeit GNSS position fixes that the filter accepts, displacing the estimate toward the spoofed position. The filter's inability to distinguish a genuine re-acquisition from a modest spoof is the central security gap.

### Attack Paths

| Attack Vector | Description | Measured Impact | Detection Status |
|---|---|---|---|
| **Sustained position offset** (e.g. +22 m x-offset) | 15 s GNSS outage, then every returning fix has constant bias in x | 22 m offset admitted with **one** grant; no second rejection ever occurs; filter coasts 9 s on inertial solution after lockout. Measured in `tests/test_nis_monitor.py:_denial_then_spoof(22.0)`. | ❌ Not detected. NIS window + drift bound (ADR-0006) is in place; the frozen-anchor cross-check (ADR-0008) is implemented but **unreachable** — zero reachable epochs across 0–100 m of offset. See N1. |
| **Multipath spike** (temporary bias) | Short-duration biased fix; gate correctly rejects; recovery needs `auto_recovery_count` clean updates. | Correctly rejected by FDIR gate. Measured: 0 false rejections on control at `alpha=0.001`. | ✅ Detected by FDIR gate |
| **Sustained spoof at 1–2 m** | Offset small enough that innovation stays within gate after filter is pulled toward it. | At 1 m and 2 m: 49 and 60 fixes rejected before channel escalates to `SENSOR_FAULT`. After rejection, filter coasts on inertial solution. | ⚠️ Partially detected; offset earns no drift budget, but channel still follows until fault declared |
| **Sustained spoof at 40 m / 100 m** | Large offset; zero grants; at 1 m and 2 m channel escalates to declared fault. | Verified at 40 m and 100 m with zero grants and no estimate movement. At 1 m and 2 m: 49/60 rejections then fault. | ✅ Detected at >= 1 m offset; < 1 m not reliably detected |

### Key Security Properties

| Property | Implementation | Evidence |
|---|---|---|
| **False-alarm rate at alpha=0.001** | `DEFAULT_CONFIDENCE = 0.999` in `src/navkit/fdir/gating.py:128` | Measured: 0 of 1212 healthy GNSS fixes rejected. `CONSTRAINTS.md:R2` |
| **Consecutive rejection threshold** | `max_consecutive_rejections=3` in `src/navkit/fdir/fdir_manager.py:160` | Distinguishes re-acquisition from multipath: multipath = single-sample bursts; re-acquisition needs >=2 accepted updates to correct. |
| **Drift budget per silence** | `max_drift_sigma_mps=0.5 m/s` in `src/navkit/fdir/nis_monitor.py:126` | At 5 Hz, 15 s denial → 7.5 m 1-sigma drift envelope. A 3.4 m offset (outage_visual case) admitted; 60 m offset refused. Verified across 1–100 m offsets. |
| **One grant per divergence episode** | Enforced in `src/navkit/fdir/fdir_manager.py:884` `spoof_grant_threshold=2` | More than one grant per episode is refused; sustained offset earns no budget. Verified at 1–100 m. |
| **Lockout + re-expansion** | `spoof_lockout_s=60.0` + `reexpansion_variance` in `src/navkit/fdir/fdir_manager.py:867` | 60 s lockout on 5 Hz channel discards ~300 measurements by the denial the system is trying to survive. Shorter lockout would admit every working receiver from a real outage. |
| **SENSOR_CHANNELS separation** | `("gnss", "vision_rot", "vision_trans", "altimeter")` in `src/navkit/fdir/fdir_manager.py:96` | Vision blocks gated separately; broken translation cannot be vouched for by healthy rotation. |

### Unresolved Security Gaps

| Gap | Impact | Status |
|---|---|---|
| **Modest spoof (1–2 m post-outage) undetected by single grant** | Filter follows offset; no second rejection to trigger lockout. | ❌ Open. The ADR-0007 cross-check would not close it even if reachable: its measured reach is ~12 m of displacement, and it shares the one-grant-per-episode root cause. ADR-0007 test remains `xfail`. |
| **Multipath vs spoof vs degradation discrimination** | Gate detects implausibility but not cause. | ❌ Open: ADR-0005 notes this is a design question beyond the gate. |
| **Sustained spoof at 1–2 m earns no drift budget but still follows** | Filter is pulled toward offset; residual shrinks; within few epochs innovation comfortably inside threshold; gate happy; channel excluded by declared fault — but offset already applied. | ⚠️ Measured trade-off: refusing a plausible-looking sensor is smaller error than following it. |

## Performance Analysis

### Benchmark Performance (30 s synthetic run, 5 Hz GNSS, 20 Hz vision, noisy IMU)

| Scenario | ATE RMSE (m) | Claimed 1σ (m) | Mean NEES (exp 3) | 2σ Coverage | Verdict |
|---|---|---|---|---|---|
| gnss_only (control) | 0.503 | 0.252 | 3.7 | 100.0% | mixed: bulk overconfident, tail underconfident |
| dead_reckoning (no aiding) | 1.877 | n/a | n/a | n/a | no covariance reported |
| vision_anchor_in_measurement_noise (defect) | 1.307 | 0.091 | 387.3 | 16.0% | overconfident |
| vision_only | 2.309 | 0.156 | 331.0 | 0.7% | overconfident |
| outage_control (GNSS denied, vision off) | 3.782 | 0.567 | 4.1 | 100.0% | mixed: bulk overconfident, tail underconfident |
| outage_visual (GNSS denied, vision on) | 2.541 | 0.161 | 419.4 | 20.0% | overconfident |
| outage_visual_degraded_camera | 1.872 | 0.190 | 216.6 | 18.5% | overconfident |

### Performance Regression: FDIR Impact

| Scenario | ATE w/o FDIR | ATE w/ FDIR (ADR-0006) | Rejections w/o FDIR | Rejections w/ FDIR | Change |
|---|---|---|---|---|---|
| outage_visual | 3.428 m | 2.541 m | 51 | 5 | ✅ 50 fewer rejections, ATE improved |
| outage_visual_degraded_camera | 2.545 m | 1.872 m | 931 (20% drop misspelled as 30%) | 264.8 (30% corrected) | ✅ Better with monitor |

### Calibration Degradation (Unresolved)

| Scenario | Mean NEES | Expected 3 | Ratio | 2σ Coverage | Expected 99.2% |
|---|---|---|---|---|---|
| outage_visual | 419.4 | 3 | **139.8× overconfident** | 20.0% | 99.2% |
| outage_visual_degraded_camera | 216.6 | 3 | **72.2× overconfident** | 18.5% | 99.2% |
| gnss_only | 3.7 | 3 | 1.2× slightly overconfident | 100.0% | 99.2% |
| vision_only | 331.0 | 3 | **110.3× overconfident** | 0.7% | 99.2% |

**Performance Assessment**: The filter is performant in terms of compute (no unusual latency or resource usage), but **severely miscalibrated** under GNSS denial with vision enabled. The claimed uncertainty is 10–140× too small, and the true error is 2–20× larger than claimed. The only scenario with honest calibration is `gnss_only` (control, no vision).

### Runtime

- Typical 30 s benchmark run: ~2–5 seconds wall-clock time
- Memory usage: < 50 MB peak (21-state EKF, no large buffers)
- No SciPy, no compiled extensions, no cloud dependencies — pure Python + NumPy per S1

---
*All measurements from `scripts/run_benchmark.py` with fixed seed=0, 7 cases, reported in `results/benchmark.json` and rendered in `README.md` table. No real sensor capture; all synthetic fixture.*