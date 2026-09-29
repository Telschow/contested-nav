# ADR-0007: Mitigating Spoof Permanence via Hysteresis and NIS Recovery Window

- Status: proposed
- Date: 2026-09
- Builds on: ADR-0006 (adaptive inflation), ADR-0005 (chi-square gating)

## Context

ADR-0006 lets a channel buy bounded covariance after silence, so a healthy
receiver can re-enter a filter whose covariance has collapsed. The inflation
is bounded per-grant and per-block, but the permanence the attack exploits is
different and worse: the grant is large, the filter moves most of the way to
the offset in one update, and every later spoofed fix is then *small* relative
to the corrupted mean. Measured in `tests/test_nis_monitor.py` (`_denial_then_spoof`):
a 22 m post-outage offset is admitted with exactly **one** grant, and no second
rejection ever occurs to count.

The proposed trigger in the original write-up — escalate a channel that needs
inflation grants on **consecutive updates** — provably does not fire on the
measured case: it never requires a second consecutive grant. The grants are
one-off.

## Decision

- Implement the escalation machinery: a `REJECTED_SPOOF` status, a
  `spoof_lockout_s` cooldown on the channel, and covariance re-expansion on
  the block the channel constrains, so a walked-off filter does not coast on a
  covariance that no longer describes where it is.
- Do **not** pretend the consecutive-grants trigger works. The open question
  below is the trigger itself.

### Open question: the detection signal

Measured separators of a spoofed return from an honest one, at grant time:

| Post-outage offset | Innovation / grant sigma |
|---|---:|
| 0 m (truth) | 1.09 |
| 10 m | 1.09 |
| 15 m | 1.44 |
| 20 m | 1.95 |
| 22 m | 1.99 |

The honest band and the modest-spoof band overlap below ~1.4 sigma, so a
threshold on this ratio cannot separate a genuine re-acquisition from a modest
spoof. Post-grant re-gating does not help either: after one inflated update the
innovation collapses to ~0 for both truthful and spoofed channels, so there is
no signal left in the channel's own residuals. A second modality (cross-check
against the visual anchor) or an independent drift model is required, and that
is a larger change than this ADR authorises. Until one lands, the escalation
machinery is implemented and unit-tested but the permanence case is pinned as
`xfail` (`TestPermanenceIsStillUndetected`), not silently passed.

> **Update (ADR-0008).** That larger change was made, in
> `src/navkit/estimators/eskf.py`, after this ADR was written. It does not
> change this conclusion. The frozen-anchor cross-check has correct arithmetic
> and an unsatisfiable guard, so it never runs; the one-grant-per-episode
> policy named above is what starves both this trigger and that check. The
> permanence case below therefore remains open, and the `xfail` stands.

## Consequences

- A second grant in one episode escalates to `REJECTED_SPOOF` and a 60 s
  cooldown the ordinary recovery hysteresis cannot express.
- The cooldown expires the lockout but not the fault: recovery still needs
  `auto_recovery_count` clean updates.
- The measured permanence case remains undetected (`xfail`), and should stay
  red-on-purpose until it is not.