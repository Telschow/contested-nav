# ADR-0008: The frozen-anchor cross-check is implemented but unreachable

- Status: accepted
- Date: 2026-09
- Builds on: ADR-0007 (spoof-permanence escalation), ADR-0006 (NIS window monitor)
- Partially addresses: the ADR-0007 open question on the detection signal
- Does **not** address: B1 in `CONSTRAINTS.md`

## Context

ADR-0007 measured that a 22 m post-outage offset is admitted with exactly one
inflation grant, and that no threshold on a single channel's residuals can
separate an honest re-acquisition from a modest spoof, because after one
inflated update the innovation collapses to ~0 for both. It named the way out:

> A second modality (cross-check against the visual anchor) or an independent
> drift model is required, and that is a larger change than this ADR
> authorises.

That change was then made, in `src/navkit/estimators/eskf.py`, without an ADR.
It has two parts:

- The visual anchor pose and its covariance are snapshotted at the first IMU
  sample inside a GNSS outage (`:817-834`).
- Every *inflated* GNSS grant is checked against that frozen anchor, and refused
  when the Mahalanobis distance of the fix from the anchor exceeds `15^2 = 225`
  (`:521-548`).

This ADR records what it does, because the code and the comment above it both
read as though it were working.

## Decision

**Keep the code, and document it as not yet contributing.**

The arithmetic is correct and worth keeping. In the forced-grant state pinned by
`TestFrozenAnchorCrossCheck`, the distance separates the bands cleanly:

| Fix offset from frozen anchor | `d2` | Outcome |
|---|---:|---|
| 5 m | 15.2 | accepted |
| 12 m | 87.3 | accepted |
| 12.5 m | 236.7 | refused |
| 60 m | 5454.5 | refused |

The threshold is not decorative: a mutant at 100 or 200 or 250 or 400 is caught
by the suite, and so is one at 0 or 1 that refuses honest fixes.

**But the branch is never reached.** The guard requires
`gnss_grants_since_verified > 0` *and* `decision.inflated` on the same epoch.
That conjunction is unsatisfiable in the measured case:

- The inflation grant is what increments the counter (`:559-561`).
- The epoch after a grant is a clean accept, and the clean-accept branch resets
  the counter to zero (`:563-565`).

So the counter reads 0 on every epoch where a grant is actually offered, and the
cross-check never runs. Measured across a truthful return and 5 m, 12 m, 20 m,
22 m, 40 m and 100 m of offset: **zero reachable epochs.**

On the 22 m case that motivated ADR-0007 the branch is entered once, with
`d2 = 217.3` — under the 225 threshold — and the grant is applied.

This is the same root cause the ADR-0007 xfails describe from the other side.
One grant, then permanent adoption, means there is no second grant to count. The
escalation trigger and the cross-check guard are both waiting for a second grant
that the NIS monitor's one-grant-per-episode policy never produces.

## Consequences

- **The mitigation is not counted as working anywhere.** The ADR-0007
  permanence case stays `xfail`, and B1 is untouched: this check was never
  capable of moving the covariance calibration, because it does not execute.
- **Reaching it is a one-line change, not a redesign.** Either count the grant
  on the epoch it is issued rather than after it, or drop the `inflated`
  conjunct and cross-check on any accepted fix after a grant. The arithmetic
  and the threshold are already pinned. Which of the two is correct is a
  security decision, not a mechanical one, and is tracked as N1 in
  `docs/audit/06-revised-roadmap.md` — it must not be made as a drive-by.
- **`test_the_guard_is_never_satisfied_during_a_sustained_offset_spoof` is
  `strict=True` on purpose.** It asserts the gap is still open, so the day the
  guard is fixed the suite fails loudly and forces the ADR-0007 xfails, the
  audit's security table, and the B1 discussion to be revisited deliberately.
  A test that quietly kept passing after the gap closed would be the failure
  mode this project is built to avoid.
- **The threshold's real resolution is 0.5 m**, between 12 m and 12.5 m, at
  `d2` 87.3 and 236.7. "About 15 sigma" is not the same claim as 15 sigma, and
  the check's reach — roughly 12 m of displacement in this configuration — is
  narrower than the modest-spoof band ADR-0007 says is the hard case. Even
  reachable, it would not have closed the 1–2 m case.

## What this ADR does not decide

Whether to fix the guard. Fixing it makes a security-relevant refusal path
start firing, which changes what the filter does with post-outage GNSS. That
belongs with the pose-graph work in `ROADMAP.md` Track B rather than in a
follow-up patch, and the measured effect on the 22 m and 1–2 m cases should be
recorded before the change is accepted.
