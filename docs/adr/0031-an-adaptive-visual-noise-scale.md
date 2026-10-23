# ADR-0031: An adaptive visual noise scale for the stochastic clone

- Status: accepted
- Date: 2026-10
- Related: [ADR-0006](0006-nis-window-monitor.md), [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0028](0028-the-b1-gate.md), [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [issue #44](https://github.com/Telschow/contested-nav/issues/44), [issue #113](https://github.com/Telschow/contested-nav/issues/113)

## Context

[ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md) fixes the gate for the next visual-update candidate: one unchanged configuration must pass in a scenario with independent visual errors (S1) and in one with visual errors correlated over time (S2). It names the adaptive visual noise scale as the first candidate. This record specifies it before any code is written.

The evidence is MEASUREMENT: scratch runs on synthetic data, not committed, not checked by CI. The tables are in the issue and are not repeated here.

- The first candidate, the clone with the measured-front-end preset, failed the B1 gate on the held-out seeds on the conservative side ([PR #143](https://github.com/Telschow/contested-nav/pull/143)). The unused seeds say it is conservative in a typical run, not by bad luck ([first measurement on issue #44](https://github.com/Telschow/contested-nav/issues/44#issuecomment-6346442452)).
- The plain clone, without the preset, is already conservative in S1, and its assumed visual noise equals the injected noise, so the conservatism is not a noise mismatch and its cause is not diagnosed ([second measurement on issue #44](https://github.com/Telschow/contested-nav/issues/44#issuecomment-6357356880)). That comment also draws the consequence for this candidate: the scale has to be able to go below one as well as above it.
- Correlated visual errors need about four times the assumed noise ([ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md)). The development table of the candidate gate shows the preset candidate failing S1 on the lower bound and passing S2, and the plain clone failing S1 on the lower bound and failing S2 on the upper side ([PR #156](https://github.com/Telschow/contested-nav/pull/156), development seeds).
- So no single multiplier passes both scenarios.

The repo already adapts a covariance from the filter's own quantities once: for GNSS, [ADR-0006](0006-nis-window-monitor.md) inflates the covariance after a silent channel, and it explains why a wider gate is not the fix: it would admit a sustained spoof. Admitting larger innovations can hide a sensor that is wrong. That lesson is built into the decision below: a bounded scale, a reported scale, and a fault-matrix check before any held-out run.

## Options

**(a) A fixed multiplier.** Rejected. The evidence above is that the independent-error scenario wants a little under one and the correlated one wants about four. A fixed number passes one scenario and fails the other, and the gate asks for both.

**(b) An adaptive scale on the visual measurement covariance, estimated from the innovations. (Chosen.)** The filter has the innovations and can see whether its assumed visual noise is too small or too large, without reading the reference. The cost is the one ADR-0006 recorded: a catch-all scale can absorb a fault. The decision bounds it, reports it, and tests detection.

**(c) A Gauss-Markov state for the visual error.** The second candidate of ADR-0030. It models the correlation instead of absorbing it, at the cost of a larger state and a new model. Deferred, not rejected: it is evaluated on its own held-out block if this candidate fails.

**(d) Adapting the process noise instead.** Rejected for this record. The evidence points at the visual channel, and the visual error regime is what differs between S1 and S2.

## Decision

What it is. The stochastic-clone visual update gets an adaptive scale on its measurement covariance, with one scalar for the rotation block and one for the translation block: s_rot and s_trans. The covariances used in the update are s_rot times the base rotation covariance and s_trans times the base translation covariance. The base covariances are the declared ones (vision_rot_sigma_deg and vision_trans_sigma_m) with no preset. The scale is opt-in through a new setting (vision_adaptive_scale, off by default), applies only to vision_model clone, and is refused together with vision_noise_preset. With the setting off, every output is byte-identical to the previous behaviour.

How it is estimated. At each visual update, for each block, before the update is applied, compute d = y^T S0^-1 y / 3, where y is the block's innovation and S0 = H P H^T + R0 is the innovation covariance with the base covariance R0 (the unscaled one). If the filter is consistent with its base noise, the expectation of d is 1. The scale is an exponentially weighted mean of d over time: s moves toward d by the fraction 1 - exp(-dt / tau) at each update, where dt is the time since the previous visual update and tau is the forgetting time. The scale starts at 1 and is clipped to the interval from s_min to s_max. Only innovations of updates that the chi-square gate accepted enter the mean. The scale is held, not changed, while no visual update arrives. The estimator uses only quantities the filter has; it never reads the reference trajectory.

What it is not. The scale is a catch-all for model error in the visual channel, which includes visual errors correlated over time and the conservatism of the clone. It is not an estimate of the sensor's noise, and the documentation says so. The gate's innovation covariance for the visual channel uses the scaled covariance, so the false-alarm rate of the gate keeps its meaning, and a larger scale lets larger innovations through. Because that can hide a visual fault, the scale is bounded, it is reported (mean, minimum, maximum and final s_rot and s_trans in the run statistics), and the fault matrix is re-run for the candidate before any held-out evaluation, with the detection of the visual faults compared with the clone without the scale. A drop in detection is reported and goes into the record of the candidate.

How the parameters are chosen. The parameters are tau, s_min and s_max. They are chosen only on development seeds, by a procedure fixed here before it is run. The grid is tau in {2, 5, 10} seconds, s_min in {0.25, 0.5}, s_max in {8, 16}: twelve points, and no others. Each point is evaluated with the candidate gate of ADR-0030 in both scenarios on seeds 0 to 24. A point qualifies if the gate passes in both scenarios. Among qualifying points the one with the largest smallest margin is chosen, where the margin of a condition is its distance from its threshold in units of the threshold, and ties go to the smaller tau, then the larger s_min, then the smaller s_max. The chosen point must also pass the gate on seeds 25 to 49, 50 to 74 and 75 to 99 as confirmation, in both scenarios. If no point qualifies, or the chosen point fails a confirmation block, the candidate is recorded as failed on development seeds and is not taken to a held-out block; it is not repaired by adding grid points. Otherwise the chosen parameters are frozen with the code commit, and the candidate is evaluated once on the next unused held-out block in both scenarios, as ADR-0030 requires.

What stays open. Whether the held-out evaluation passes, and whether vision_enabled ever changes, are not decided here. The Gauss-Markov candidate of ADR-0030 is evaluated on its own block if this candidate fails.

## Consequences

- A code package adds the setting, the estimator, the run statistics and a test that the outputs are byte-identical with the setting off. Tests come first and include known answers:
  - a synthetic filter whose true visual noise is k times the assumed noise has `s` converge to about k, within a stated tolerance;
  - `s` stays at one when the filter is consistent;
  - rejected updates do not move `s`;
  - the scale is held while no update arrives;
  - the bounds clip.
- A tuning package runs the stated grid once and records the table.
- The fault matrix is re-run for the candidate, and the change in detection of the visual faults is reported.
- The held-out run is a separate, single-use package, on the next unused block.
- `CONSTRAINTS.md` B1 stays as it is until a candidate has been evaluated.
- The fixed preset of ADR-0024 remains as it is. This candidate does not use it.

Note (2026-10-23): the rule that only accepted updates enter the mean is replaced by [ADR-0032](0032-the-adaptive-visual-scale-takes-every-visual-update.md).
