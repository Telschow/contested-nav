# ADR-0030: The gate for the next visual-update candidate

- Status: accepted
- Date: 2026-10
- Related: [ADR-0003](0003-ship-visual-disabled.md), [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md), [ADR-0028](0028-the-b1-gate.md), [ADR-0029](0029-how-a-single-runs-verdict-is-formed.md), [issue #44](https://github.com/Telschow/contested-nav/issues/44), [issue #113](https://github.com/Telschow/contested-nav/issues/113)

## Context

The first candidate, the stochastic clone with the measured-front-end noise preset, failed the gate of [ADR-0028](0028-the-b1-gate.md) on the held-out seeds, on the conservative side ([PR #143](https://github.com/Telschow/contested-nav/pull/143)). The maintainer accepted that result as final. B1 stays open and `vision_enabled` stays False.

Seeds 25 to 99 were unused by any published result, and the held-out seeds were not touched. A scratch measurement on them is recorded in [a comment on issue #44](https://github.com/Telschow/contested-nav/issues/44#issuecomment-6346442452). The table is there and is not repeated here. It is MEASUREMENT: scratch runs on synthetic data, not committed, not checked by CI. It says four things.

- The per-run time-mean NEES over the outage window is heavy tailed.
- The mean over the development seeds was driven by a few runs, so the pass on those seeds did not carry over.
- A typical run is more conservative than the tolerance of ADR-0028 allows.
- A fixed noise multiplier cannot be right in both an independent-error regime and a correlated-error regime. The preset sized for correlated errors reads conservative when the errors are independent.

The gate statistic of ADR-0028 is the grand mean with a band built on the effective sample size. It is fragile to heavy tails, because a few runs move it. The statistic below uses robust statistics per run: a percentile and a median.

The synthetic evidence has limits that this record does not change. It is one trajectory family, white and correlated Gaussian visual errors, and one noise preset measured on one front end.

## Options

**(a) Keep the statistic of ADR-0028 and only add the correlated scenario.** The change is small and the old result stays comparable. But the statistic stays fragile to a few heavy-tailed runs, which is the measured problem, and a candidate could pass or fail on which seeds it drew.

**(b) Use a robust statistic per run and two scenarios. (Chosen.)** The upper and lower conditions look at the 90th percentile and the median of the per-run means, so a few runs cannot decide the gate. Requiring one unchanged configuration to pass in an independent-error and a correlated-error scenario removes the fixed-multiplier escape. The cost is a new statistic with no history, which is why its properties are checked by simulation before any candidate is run.

**(c) Tune the multiplier for both regimes.** Rejected. A multiplier that passes both would be found by trial, with no principle behind it, and it would be sized to the scenarios and not to the front end. The fixed factor was already found by trial in [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md).

**(d) Skip the gate for a structural change.** Rejected. A structural change can be overconfident or conservative like any other, and the gate exists to say so. A change that needs no test is a change that cannot be shown to work.

## Decision

Requirement. A visual-update configuration may be proposed as the default only if it passes the B1 gate in both of two scenarios with one unchanged configuration: S1, independent visual errors (the scenario block of outage_visual), and S2, visual errors correlated over time (the scenario block of outage_visual_clone_correlated). The configuration is not told which scenario it faces.

Gate for a new candidate. In each scenario the candidate and the no-vision control (outage_control) run on the same 25 held-out seeds, over the GNSS-outage window. Each run gives y_i, the time-mean NEES over the window (3 degrees of freedom), and n_i, its effective sample size. The gate passes in a scenario when all of these hold: (U) the 90th percentile of the y_i is at most chi2_ppf(0.975, 3m) / m, where m is the median of the n_i, with m at least 1; (L) the median of the y_i is at least 0.44 x 3; (C) pooled 2-sigma per-axis coverage is at least 95%; (P) paired by seed against the control, the candidate has the lower ATE in at least 20 of 25 seeds, the median ratio of candidate ATE to control ATE is at most 0.8, and no seed's ratio exceeds 1.5. A candidate passes only if the gate passes in both scenarios. This replaces conditions (1) and (2) of ADR-0028 for new candidates; the recorded ADR-0028 result stands.

Pre-registered properties. Before any candidate is evaluated, (U) and (L) are checked on simulated runs whose y_i is chi-square with 3 n_i degrees of freedom divided by n_i, with the n_i drawn from the effective sample sizes of the existing candidate on seeds 25 to 99. A consistent filter passes (U) and (L) together in at least 90% of simulated 25-run sets. A filter whose NEES is 2 times too high fails (U) in at least 99%. A filter whose NEES is 0.3 times too low fails (L) in at least 99%. If a property is not met, the only permitted correction is to the confidence level in (U) (0.975 raised to 0.99, then 0.995), chosen as the smallest level that meets all three properties. The 90th percentile, the 0.44 tolerance and the other thresholds do not change.

Seeds and candidates. Seeds 0 to 99 may be used freely for development. Each candidate is frozen (its code commit recorded) before it is evaluated once on its own held-out block of 25 seeds, in both scenarios: the first candidate on seeds 125 to 149, the second on 150 to 174, then continuing in blocks of 25. The candidates, in order, are an adaptive visual noise scale and a Gauss-Markov state for the visual error. Covariance intersection is a baseline, not a candidate. A failing candidate is recorded and not retried on the same seeds. Passing the gate does not change vision_enabled; that remains a separate maintainer decision.

## Consequences

- The gate code (`src/navkit/eval/gate.py` and `src/navkit/b1_gate.py`) has to change to the new conditions and the two scenarios. That is a separate package, with tests first, and the tests include the pre-registered simulation properties.
- The recorded result of ADR-0028 and its old gate stay as dated history. They are not deleted or reworded.
- The first candidate, the adaptive visual noise scale, is a separate design and implementation package. It is not started by this record.
- `CONSTRAINTS.md` B1 stays as it is until a candidate has been evaluated.

Note (2026-10-23): the first candidate, an adaptive visual noise scale, is specified in [ADR-0031](0031-an-adaptive-visual-noise-scale.md).

Note (2026-10-23): the second candidate is specified in [ADR-0034](0034-a-gauss-markov-model-of-the-correlated-visual-error.md).
