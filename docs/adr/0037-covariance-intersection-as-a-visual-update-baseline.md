# ADR-0037: Covariance intersection as a visual-update baseline

- Status: proposed
- Date: 2026-10
- Related: [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [ADR-0034](0034-a-gauss-markov-model-of-the-correlated-visual-error.md), [ADR-0036](0036-b1-is-closed-as-characterised-not-solved.md), [issue #116](https://github.com/Telschow/contested-nav/issues/116), [issue #44](https://github.com/Telschow/contested-nav/issues/44)

This record has its context and options. The decision section is the maintainer's to write. No code is written until it is.

## Context

**Why a baseline.** [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md) and [ADR-0034](0034-a-gauss-markov-model-of-the-correlated-visual-error.md) both name covariance intersection as a baseline and not a candidate. [ADR-0036](0036-b1-is-closed-as-characterised-not-solved.md) closed B1 as characterised, stopped work towards a default-on visual configuration, and left [issue #116](https://github.com/Telschow/contested-nav/issues/116) open as independent work. A baseline answers a different question from a candidate: how does a method that assumes nothing about the correlation compare with the single anchor and the stochastic clone? It is not a proposal to switch vision on, and `vision_enabled` stays False.

**What exists today. FACT, checked in the code.** There is no covariance intersection anywhere in `src`. The words appear only in ADR-0030 and ADR-0034. The visual update has two models. The single anchor drops the correlation between the stored pose and the live state at every commit (ADR-0001). The stochastic clone keeps it through the filter's own covariance, with six clone error states `c_t` and `c_p`, and updates the rotation and translation halves one after the other with a Joseph-form update.

**What covariance intersection is.** For two estimates of the same quantity with covariances `P1` and `P2` and an unknown cross-correlation, it fuses them with `P^-1 = w P1^-1 + (1 - w) P2^-1` for a weight `w` between 0 and 1. The result is consistent for every cross-correlation. That is a known result for the linear case. Whether it carries over to a relative pose measured against a linearised clone is not shown by anything in this repository. It is the first thing a baseline run would have to check.

**What the decision has to settle.** Each item below changes the result, so each needs an answer before a run.

1. What is fused with what. The live pose against the pose implied by the stored pose plus the relative measurement is one reading. A bound on the innovation covariance is another.
2. How the weight `w` is chosen: a fixed value, the one that minimises the trace, or the one that minimises the determinant. The rule must be declared before any run.
3. Whether it applies to the rotation half, the translation half, or both.
4. The scenes, seeds, columns and the control rows. The single anchor stays as the overconfident control row after any change.
5. Which seeds are allowed. A baseline is not gated by ADR-0030, but the held-out seeds are a ledger, and a baseline should not spend them.
6. The name of the flag, its refusals (for example, together with `vision_gm_error`, with a noise preset, or with the adaptive scale), and the proof that with the flag off every output is byte-identical to today.

## Options

(a) Covariance intersection of the live pose with the pose implied by the stored pose and the measurement, with the weight chosen by a rule declared in advance. This is the standard form of the method. It needs the cross-term between the live state and the stored pose to be treated as unknown, which means it replaces the clone's own bookkeeping of that term for the update.

(b) Covariance intersection used only to bound the innovation covariance. The update keeps the Kalman gain and inflates the measurement covariance to the intersection bound. It is closer to the existing update and touches less code. It is not the standard method, and the page would have to say so.

(c) A fixed inflation of the visual noise. Rejected by [ADR-0034](0034-a-gauss-markov-model-of-the-correlated-visual-error.md) option (a): no single multiplier passes both scenarios. Listed here only so it is not proposed again as the baseline.

(d) No baseline. Leave covariance intersection named in ADR-0030 and ADR-0034 and say in the documents that it was not run. Cheapest, and it leaves the question in the table of limitations open.

## Decision

The maintainer writes this section.

## Consequences

To be written with the decision. The acceptance criteria of [issue #116](https://github.com/Telschow/contested-nav/issues/116) apply: an ADR before the run, a flag with defaults unchanged, the same columns as the single anchor and the stochastic clone, the single-anchor control row kept, generated rows tied to page statements by tests, and no new runtime dependency.
