# ADR-0046: Size the reacquisition inflation by the innovation covariance

- Status: proposed
- Date: 2026-11
- Related: [ADR-0006](0006-nis-window-monitor.md), [ADR-0007](0007-spoof-permanence-hysteresis.md), [ADR-0026](0026-urbannav-as-a-real-gnss-dataset.md), [ADR-0041](0041-a-correlated-error-term-for-the-gnss-update.md), [issue #298](https://github.com/Telschow/contested-nav/issues/298)

This record has its context and options. The decision section is the maintainer's to write. No code is written until it is.

## Context

**What was observed. MEASUREMENT, in the committed rows.** On Deep-Urban-1, after the long imposed outage, the filter rejects every returning fix, in both variants and every seed, and never takes the GNSS channel back (`docs/data/urbannav_imposed.csv`, the UrbanNav page). One sequence, one receiver, the reference's own error unknown.

**What a one-seed development diagnosis found. HYPOTHESIS, not in the CSV and not reproduced by code in the repository (issue #298).**

- The first returning fix sits only just outside the gate, and each later one is slightly worse, because nothing is fused.
- The second pass adds a variance of `(NIS / gate) * reacq_sigma_m^2`. With `reacq_sigma_m` at 3 m that is about 10 m^2, against a claimed covariance of thousands of m^2, so NIS barely moves and the re-gate (at most `reaccept_margin` times the gate) fails.
- The fault is declared at the fifth rejection. Clearing it needs ten consecutive consistent fixes, which cannot arrive while nothing is fused.
- `auto_recovery_count`, `reaccept_margin`, `max_drift_sigma_mps` and `max_consecutive_rejections`, changed one at a time, changed nothing. `reacq_sigma_m` at 30 m together with `reaccept_margin` at 1.0 recovered, and that same sigma with the default margin did not.

**Why it is a decision.** The inflation cap is described in `config.py` as a security control: it bounds the trust a persistent spoof can buy. Any change to the sizing weakens or reshapes the same control, and the spoof and slow-ramp studies were run with the present rule.

## Options

(a) Keep the rule. Say the mechanism on the UrbanNav page (done as a hypothesis). Cost: none. The long outage on this sequence stays unrecovered.

(b) Size the inflation from the innovation covariance, so that the inflated innovation can reach the gate, bounded by the drift bound `max_drift_sigma_mps * blind_s`. Behind a flag, default unchanged. Cost: a rule change in `nis_monitor.py`, tests, and a re-run of the spoof, slow-ramp and outage studies to show the control still holds.

(c) A probation rule for a declared fault, one that does not need unfused fixes to be consistent: for example, fuse one fix under a bounded inflation and judge the next. Cost: a new state in the channel machine, and the same re-runs.

(d) Reduce the overconfidence through the outage first, so the fix is not just outside the gate. Related to the correlated-error work of ADR-0041. Larger, and it does not by itself change the rule.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision. If (b) or (c) is chosen:

- It is behind a flag with the default unchanged, and the existing rows stay byte-identical with it off.
- The spoof, slow-ramp and imposed-outage studies are re-run on development seeds, and the overconfident single-anchor case stays as a control row.
- The settings are declared before any run, and are not tuned on the imposed outages they are scored on.
- No held-out seed is run.
- No runtime dependency changes.
