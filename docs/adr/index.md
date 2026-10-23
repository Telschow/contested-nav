# Architecture decision records

A decision is recorded when it closes off an alternative. Each record says what the choice was,
what it cost, and what was rejected.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-anchor-as-filter-state.md) | Model the visual anchor as a filter state | accepted |
| [ADR-0002](0002-joseph-covariance-form.md) | Use the Joseph form for covariance updates | accepted |
| [ADR-0003](0003-ship-visual-disabled.md) | Ship with visual fusion disabled | accepted |
| [ADR-0004](0004-quaternion-order.md) | Fix the internal quaternion order and centralise conversion | accepted |
| [ADR-0005](0005-chi-square-fdir-gating.md) | Chi-square innovation gating with per-channel fault isolation | accepted |
| [ADR-0006](0006-nis-window-monitor.md) | NIS window monitor with adaptive covariance inflation | accepted |
| [ADR-0007](0007-spoof-permanence-hysteresis.md) | Mitigating Spoof Permanence via Hysteresis and NIS Recovery Window | accepted (implementation partial; detection trigger still open) |
| [ADR-0008](0008-frozen-anchor-cross-check.md) | The frozen-anchor cross-check is implemented but unreachable | accepted |
| [ADR-0009](0009-cross-platform-numerics.md) | Cross-platform numerics and the golden tolerance | accepted |
| [ADR-0010](0010-determinism-and-seeding.md) | Determinism and seeding policy | accepted |
| [ADR-0011](0011-ci-and-supply-chain.md) | CI and supply-chain strategy | accepted |
| [ADR-0012](0012-every-scenario-is-injected.md) | Every scenario goes through the injection layer | accepted |
| [ADR-0013](0013-recorded-imu-with-simulated-gnss.md) | Evaluate on recorded IMU data with GNSS simulated from the ground truth | accepted |
| [ADR-0014](0014-textbook-imu-process-noise-by-default.md) | IMU white noise enters the process covariance in the textbook form | accepted |
| [ADR-0015](0015-initial-imu-bias-sigmas-are-read.md) | The initial IMU bias sigmas are read | accepted |
| [ADR-0016](0016-tum-vi-as-a-second-recorded-dataset.md) | TUM VI as a second recorded dataset | accepted |
| [ADR-0017](0017-stochastic-clone-for-the-visual-update.md) | A stochastic clone for the visual update | accepted |
| [ADR-0018](0018-honest-return-separability.md) | Honest returns after an outage and the GNSS gate | accepted |
| [ADR-0019](0019-slow-ramp-spoofing.md) | Slow-ramp GNSS spoofing is not detectable with IMU and GNSS alone | accepted |
| [ADR-0020](0020-second-source-against-a-ramp.md) | A second source against a slow-ramp spoof | accepted |
| [ADR-0021](0021-fault-classification-from-innovations.md) | Fault classification from the GNSS innovations | accepted |
| [ADR-0022](0022-multipath-signature.md) | A multipath signature on the GNSS innovations | accepted |
| [ADR-0023](0023-clone-against-a-measured-front-end.md) | The clone against a measured front end | accepted |
| [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md) | The assumed visual noise of the opt-in clone | accepted |
| [ADR-0025](0025-calibrated-stage-one-for-fault-detection.md) | A calibrated stage 1 for fault detection | proposed |
| [ADR-0026](0026-urbannav-as-a-real-gnss-dataset.md) | UrbanNav as a dataset with real GNSS outages | proposed |
| [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md) | How the synthetic runs are initialised | accepted |
| [ADR-0028](0028-the-b1-gate.md) | The B1 gate: when visual fusion may ship | accepted |
| [ADR-0029](0029-how-a-single-runs-verdict-is-formed.md) | How a single run's verdict is formed | accepted |
| [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md) | The gate for the next visual-update candidate | accepted |
| [ADR-0031](0031-an-adaptive-visual-noise-scale.md) | An adaptive visual noise scale for the stochastic clone | accepted |
| [ADR-0032](0032-the-adaptive-visual-scale-takes-every-visual-update.md) | The adaptive visual scale takes every visual update | accepted |
