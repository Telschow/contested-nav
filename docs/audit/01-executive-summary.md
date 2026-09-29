# Executive Summary


> **Point-in-time snapshot (2026-09-29).** This document records the
> repository as the audit found it, before the remediation in
> `CHANGELOG.md` was applied. Counts, line numbers, and findings here are
> deliberately not updated: several of them are what the work was for. For
> the current state see `CHANGELOG.md` and re-run the commands quoted
> above.

**Baseline Health**: 567 tests collected — 563 passing, 2 skipped, 2 expected failures. Line coverage 86.58%. The test suite is the strongest evidence of repository health, with 99.3% pass rate.

**Critical Architectural Gap**: Visual-aided GNSS navigation under 15s denial is **not trustworthy**. The 21-state anchor model is well-calibrated with GNSS available (mean NEES 3.7 vs 3 nominal, 100% 2σ coverage), but becomes dramatically overconfident during GNSS denial (mean NEES 419.4 vs 3 nominal, 20.0% 2σ coverage vs 99.2% expected). The filter reports 0.161 m uncertainty while being 2.54 m wrong — confident nonsense.

**Root Cause**: The visual anchor (`c_p`, `c_t`) is a constant body-frame offset that cannot represent correlated drift across frames. When GNSS disappears, the only constraint on the anchor is the anchor itself, and the covariance stops describing reality. This is a structural limitation of the single-anchor ESKF, not a tuning problem.

**Mitigations Applied**:
- **ADR-0006 (NIS window monitor + adaptive covariance inflation)**: Rejects GNSS fixes returning after outage under collapsed covariance, re-gating under inflated covariance. ATE 5.059 m → 2.541 m, rejections 51 → 5. However, this does **not** fix the overconfidence: 2.541 m error against 0.161 m claimed is still overconfident. B1 (anchor error unmodelled) remains open.
- **ADR-0007 (Spoof permanence via hysteresis + NIS recovery)**: Second grant in an episode escalates to `REJECTED_SPOOF` with 60 s lockout. First grant alone is insufficient to detect spoof; second modality (cross-check against visual anchor) or independent drift model is required.
- **ADR-0008 (Frozen-anchor cross-check)**: That second modality was built — anchor frozen at outage start, grant refused if the fix disagrees by more than `15²`. **It is implemented but unreachable**: the guard needs a positive grant counter and an inflated verdict on the same epoch, and the one-grant-per-episode policy never produces both. Zero reachable epochs measured across 0–100 m of offset. It contributes nothing today; making it reachable is N1.
- **Default `vision_enabled = False`**: Ships with visual fusion disabled until the structural limitation is resolved via a pose graph (ROADMAP.md Stage 4).

**Key Metrics (outage_visual, 15s GNSS denial, vision enabled)**:
| Metric | Value | Expected | Status |
|--------|-------|----------|--------|
| Mean NEES | 419.4 | 3 | **Overconfident** |
| 2σ Coverage | 20.0% | 99.2% | **Underconfident** |
| ATE RMSE | 2.541 m | 3.782 m (control) | Better trajectory, worse calibration |
| Position claimed 1σ | 0.161 m | — | 158× too small |

**Status**:
- Not field-validated; synthetic fixture only.
- Visual aiding under GNSS denial is untrustworthy and disabled by default.
- FDIR detects implausible updates but does not explain them (cannot separate multipath from spoofing from sensor degradation).
- The calibrated-covariance failure is mitigated, not fixed. The ADR-0005 gate assumed calibrated innovation covariance the filter does not have once position covariance has collapsed.
- B1 is the open blocker: visual fusion is overconfident under GNSS denial. Requires Track B (pose graph) to resolve.

**Audit Scope**: This report documents the current verified state, cross-references every claim against source files and test output, and provides an actionable roadmap. No assumptions are turned into facts; every conclusion identifies its evidence level (verified/partially verified/inferred/unknown).

---
*Last measured: 567 tests collected — 563 passing, 2 skipped, 2 expected failures — and 86.58% line coverage. The two skips are TUM VI reference checks in tests/test_trajectory_io.py, which need ground truth that is deliberately not vendored (S2).*