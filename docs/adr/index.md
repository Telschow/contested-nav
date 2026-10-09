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
