# Research and References


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

This section documents the state-of-the-art competitive analysis and external recommendations relevant to this repository.

## State-of-the-Art: Single-Anchor EKF Limitations

The fundamental limitation of the single-anchor error-state Kalman filter is well-documented in the literature and confirmed by this repository's measurements.

### Technical Background

- **Visual odometry provides relative transforms**, not absolute position. The absolute pose must be anchored somewhere, so the filter declares an anchor pose at the start of the run and carries its error as estimated states (`c_p`, `c_t`) — ADR-0001.
- **The anchor is constant in the body frame**, which means it cannot represent correlated drift across consecutive frames. Each visual measurement constrains the same constant offset, so the longer the run, the more the anchor error accumulates and corrupts the navigation state.
- **Under GNSS availability**, the anchor is continuously corrected by GNSS position fixes, so the covariance stays honest (mean NEES 3.7 vs 3 nominal, 100% 2σ coverage).
- **Under GNSS denial**, the only constraint on the anchor is the anchor itself. The covariance stops describing reality because the anchor error grows unbounded relative to the navigation state. This is a structural limitation, not a tuning problem.

### Measured Performance from This Repository

| Scenario | Mean NEES | Expected | Ratio | 2σ Coverage | Expected |
|---|---|---|---|---|---|
| GNSS available | 3.7 | 3 | 1.2× overconfident | 100.0% | 99.2% |
| GNSS denied, vision off | 4.1 | 3 | 1.4× overconfident | 100.0% | 99.2% |
| GNSS denied, vision on | 419.4 | 3 | **139.8× overconfident** | 20.0% | 99.2% |

The jump from 4.1 to 419.4 when vision is enabled under GNSS denial is the repository's central negative result and the reason B1 is the open blocker.

### Alternatives Considered and Rejected

| Alternative | Why Rejected | Reference |
|---|---|---|
| **Anchor as measurement noise** (fold `c_p`, `c_t` into R) | Drops coverage to 16%; worse than anchor as filter state. Benchmarked: ATE 1.307 m at 0.091 m claimed vs 0.503 m at 0.252 m claimed with anchor as state. | ADR-0001, benchmark row `vision_anchor_in_measurement_noise` |
| **Single anchor for whole run** | Mean NEES 23 instead of 3. Makes anchor error one unknown shared by every measurement, worsening overconfidence over long runs. | ADR-0001, documented in `CONSTRAINTS.md:S3` |
| **Larger gate / bigger anchor prior** | Inflates uncertainty to acknowledge error instead of fixing it. Does not repair the structural correlation problem. | ADR-0003, decision rationale |
| **Anchor with process noise (drift terms)** | Blurs the symptom rather than fixing the correlation structure. Defaulted to 0.0 because a knob that does not fix the problem should not look like it does. | ADR-0003, decision rationale |
| **Pose graph over visual keyframes** | The actual fix. Not yet implemented; deferred to ROADMAP.md Stage 4. This is the only known approach that models inter-frame correlation. | ROADMAP.md:221-236, B1 blocker |

### External References (Standards & Primary Sources)

| Standard / Source | Relevance | Status |
|---|---|---|
| ** chi-square distribution for integer DOF** | Exact CDF/PPF used in `eval/statistics.py` for NEES and coverage computation. Implemented from published definitions without SciPy dependency (S1). | Fully implemented |
| **Wilson-Hilferty transformation** | Used in `eval/thresholds.py` for confidence intervals on coverage fraction. Closed-form, no SciPy. | Fully implemented |
| **Joseph covariance form** | ADR-0002; used in `src/navkit/estimators/eskf.py:601-602` for posterior covariance. Symmetric positive semidefinite by construction. | Fully implemented |
| **NIS window monitor** | ADR-0006; `src/navkit/fdir/nis_monitor.py` bounded per-channel window + drift bound + reaccept margin. | Fully implemented |
| **chi-square gating with alpha=0.001** | ADR-0005; `src/navkit/fdir/gating.py` tabulated thresholds + Wilson-Hilferty beyond tabulated dof. | Fully implemented |
| **FDIR channel state machine** | ADR-0005; `src/navkit/fdir/fdir_manager.py` per-channel fault exclusion + auto-recovery count + hysteresis. | Fully implemented |

### Competitive/Open-Source Projects

| Project | Relevance | Comparison |
|---|---|---|
| **MSCKF (Multi-State CKF)** | Handles multiple landmarks/anchors; each has its own state. More states = better but higher dimensionality. | Not directly comparable; different architecture. Pose graph is the intended fix per ROADMAP. |
| **Keyframe-based pose graph SLAM** | The structural fix for B1. Models inter-frame correlation via optimization over keyframe poses. | Not implemented in this repository; ROADMAP Stage 4. |
| **GVINS / VINS-Mono** | Full VIO front ends with feature tracking, loop closure, keyframe selection. Far larger codebase; outside S1 (pure Python + NumPy). | Out of scope per CONSTRAINTS.md. |
| **EKF/IKF navigation filters (generic)** | Many open-source implementations; most assume calibrated covariance or provide ad hoc inflation. This repository's distinguishing contribution is the formal FDIR + NIS monitor adaptive inflation pipeline. | This repo is more formal about false-alarm rate and drift bounds. |

### Research Questions (Open)

| Question | Why Unresolved | Path Forward |
|---|---|---|
| **Can a single-anchor EKF ever be well-calibrated under GNSS denial?** | B1 is a structural limitation; the anchor cannot represent correlated drift. | Requires pose graph (ROADMAP Stage 4). Until then, `vision_enabled = False` default. |
| **What is the minimum number of anchors needed?** | Two anchors provide a baseline for relative drift, but still limited. | Not attempted in this repo; outside current scope. |
| **Can an innovation-consistency monitor detect the overconfidence without a second modality?** | ADR-0005's consistency monitor detects under-estimated S but cannot distinguish spoof from overconfident filter. | Partially answered, and negatively: a frozen-anchor cross-check was built as the second modality (ADR-0008) and its arithmetic works, but its guard is unsatisfiable, so it has zero reachable epochs. Separators on the grant-sigma ratio still overlap below ~1.4σ. |
| **Can the drift bound be tightened per-platform?** | `max_drift_sigma_mps=0.5 m/s` is deliberately generous for MEMS-grade IMU; platform-specific values could improve spoof rejection. | Not implemented; named in `FdirConfig` for tunability per CONSTRAINTS.md. |

---
*All references grounded in source files and measured benchmarks. No low-quality blog posts used as primary evidence.*