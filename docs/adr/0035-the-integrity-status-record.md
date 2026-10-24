# ADR-0035: The integrity status record

- Status: accepted
- Date: 2026-10
- Related: [ADR-0003](0003-ship-visual-disabled.md), [ADR-0006](0006-nis-window-monitor.md), [ADR-0028](0028-the-b1-gate.md), [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [issue #164](https://github.com/Telschow/contested-nav/issues/164), [issue #165](https://github.com/Telschow/contested-nav/issues/165)

## Context

Downstream decision logic must not reach into filter internals. It needs one small, stable record per epoch. The record says only what the filter itself can check and what the calibration evidence supports. It does not say that the position is accurate.

"Usable" here is a statement about whether the claimed uncertainty may be believed. The central finding of this repository is that a filter can be confidently wrong. A rule that relied on the filter's own confidence would pass exactly the cases it exists to catch.

**What the NIS window monitor offers, FACT checked before this ADR.** `NisWindowMonitor` in `src/navkit/fdir/nis_monitor.py` has no consistency states. It keeps a rolling window of gate outcomes per channel, pairs of squared Mahalanobis distance and accepted flag. It exposes `is_persistent_divergence(channel)`, which is true when the last three outcomes were all rejections, and `mean_nis(channel)`, which is 0.0 for an empty window. The earlier wording of the issues, with states named consistent, suspect and inconsistent, was wrong and has been corrected. The record derives a three-valued NIS state from these two calls and adds no threshold. The three outcomes come from the default of `NisConfig`, [ADR-0006](0006-nis-window-monitor.md).

**The NIS state is not evidence of calibration.** It says that innovations are not being persistently rejected. A filter that is confidently wrong passes it. The single-anchor case of this repository is the example: its claimed uncertainty is small and its error is large, and the filter is pulled toward the measurements until their innovations pass the gate. That is why the usable rule has a second part that does not depend on the filter at all.

**Which channels are monitored, FACT checked before this ADR.** The FDIR manager calls `add_sample` with the sensor name in `evaluate` and in `evaluate_and_adapt`, in `src/navkit/fdir/fdir_manager.py`. The estimator passes `gnss`, `vision_rot` and `vision_trans` as sensor names to its update function. So there are three monitored channels, and the two visual blocks are separate channels. With vision on and FDIR enabled, which is the default, both visual channels have history after the first visual update that reaches the gate. With vision off they have none. With GNSS denied for the whole run and vision off, no channel has any history. A window does not age: when an outage begins after GNSS has run, the `gnss` window keeps its last outcomes through the outage. So `monitored` is a statement about history, not about the current epoch having a fresh sample. This ADR does not change that.

**What the runner emits today, FACT checked before this ADR.** `EstimatorResult` holds the trajectory, `runtime_s`, `stats`, `name` and `position_cov`. The trajectory metadata holds `sigma_p`, `rotation_cov`, `gnss_innovations`, `bias_log` and `fdir_events`. The stats hold the FDIR counters and the visual scale and Gauss-Markov figures. No integrity record exists.

**Where the time since the last accepted GNSS fix can be derived.** Nowhere directly today. `ChannelState` in `src/navkit/fdir/records.py` counts accepted updates but does not store a time. `gnss_innovations` records every GNSS innovation with its time, accepted or not, and carries no accepted flag. The FDIR events record faults and not clean accepts. The runner decides acceptance in its update function, where a GNSS update is accepted after the FDIR decision and the legacy gate. So the runner has to track the time of the last accepted GNSS update itself. This ADR defines the field. A code package implements the tracking.

## Options

(a) Expose the internals, that is, the covariance, the FDIR state and the monitor windows, and let each consumer decide. Rejected. The interface would be unstable, and every consumer would have to understand the filter.

(b) A record with a single boolean. Rejected. It gives no reason and no evidence flag, so a consumer cannot tell "not checked" from "checked and fine".

(c) A versioned record with a reason code and a NIS state. Chosen.

(d) Add consistent, suspect and inconsistent states to the monitor first. Rejected for now. It needs thresholds that nothing here can support yet.

## Decision

The record. The ESKF runner emits one IntegrityStatus per epoch, a frozen dataclass with schema version 1. Fields: t (seconds), position (3 values), sigma_h (the horizontal claimed standard deviation, the square root of the mean of the two horizontal variances), sigma_v (the vertical claimed standard deviation), nis_state (ok, diverging or unknown), monitored (true when at least one channel has history in its NIS window at that epoch), seconds_since_absolute_fix (the time since the last accepted GNSS fix, or the time since the start if there has been none), aiding (the set of enabled aiding sources, drawn from gnss and vision), usable (a boolean) and reason (a short code).

The NIS state. It is derived from the NIS window monitor of ADR-0006 and adds no threshold. It is diverging when any channel is in persistent divergence as the monitor defines it, ok when at least one channel has history and none is in persistent divergence, and unknown when no channel has history. The NIS state says only that innovations are not being persistently rejected. It is not evidence of calibration, and a filter that is confidently wrong can report ok.

The usable rule. usable is true only when all of these hold, tested in this order, and reason is the code of the first one that fails or the code ok: (1) sigma_h and sigma_v are finite; (2) nis_state is not diverging, where unknown counts as not contradicted; (3) every enabled aiding source other than gnss has passed a calibration gate, which for vision means that vision_enabled is true by a maintainer decision taken after a candidate passed the B1 gate of ADR-0028 or ADR-0030, so with the shipped default, vision off, this condition holds trivially, and with vision on and no such decision it fails. The record says nothing about accuracy. It says whether the claimed uncertainty may be believed under the checks the filter itself can make and the calibration gates that exist. The field monitored tells a consumer when nis_state is unknown because nothing could be checked, as when GNSS is denied and vision is off.

Output and versioning. The records are written beside the trajectory output, one per epoch in time order, as a documented CSV and as the result metadata, with the schema version in both. The schema is documented in the model and interface page. A change of fields, of their meaning or of the usable rule is a new schema version and a new ADR. This ADR adds no threshold: the monitor's thresholds are those of ADR-0006.

## Consequences

- A code package adds the dataclass, the derivation of nis_state, the runner's tracking of the time since the last accepted GNSS fix, the emission and the CSV. Tests come first. Each NIS state and aiding configuration maps to the documented usable value and reason. On the known-answer fixture, usable is false for the single anchor with vision on and true for GNSS denied with vision off, and monitored is false in that second case before any history exists.
- The dead-reckoning horizon ([issue #166](https://github.com/Telschow/contested-nav/issues/166)) and the protection level ([issue #118](https://github.com/Telschow/contested-nav/issues/118)) add fields in later schema versions, each with its own ADR.
- A code package may later add consistent and suspect states to the monitor, if evidence supports thresholds. That is a new schema version and a new ADR.
- No runtime dependency changes.
