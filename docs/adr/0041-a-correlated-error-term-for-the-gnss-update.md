# ADR-0041: A correlated-error term for the GNSS update

- Status: proposed
- Date: 2026-10
- Related: [ADR-0034](0034-a-gauss-markov-model-of-the-correlated-visual-error.md), [ADR-0026](0026-urbannav-as-a-real-gnss-dataset.md), [issue #183](https://github.com/Telschow/contested-nav/issues/183), [issue #184](https://github.com/Telschow/contested-nav/issues/184), [issue #244](https://github.com/Telschow/contested-nav/issues/244)

## Context

The GNSS update treats each fix error as white, with the declared variance. On Deep-Urban-1 the page reports that the receiver's fix errors are correlated over tens of seconds, that the gate rejected none of the fixes, and that the mean NIS stayed far below its level. The page calls the link between these an interpretation. The filter was not run with a model of correlated error.

ADR-0034 handles the same problem for the visual error: states that carry the correlated part, a declared correlation time and a declared share of the variance, not an estimate from the data.

The code slice of issue #244 adds the same kind of term for GNSS, off by default. Three error states `e_gnss` are appended. Each is a first-order Gauss-Markov process with a declared correlation time `gnss_gm_tau_s` and stationary standard deviation `gnss_gm_sigma_m`. The measurement becomes `p + e + n`, where `n` keeps the declared GNSS variance, so the amplitude is added on top of it. The states share the slot of the visual model's states, so the two are refused together. With the term off, every output and the config hash are byte-identical to before. The aided run in `src/navkit/urbannav_run.py` has two variants with the term on (`--gnss-gm`). Their settings are declared in code before any run. The values are those of the synthetic study of issue #183, which were declared before that study was run.

No run on the real data is made here. That belongs to issue #184.

## Options

(a) No term. The filter stays as it is, and the page keeps saying the model was not run.

(b) Gauss-Markov states in the filter, as in the code slice. The correlation is declared in advance. The white part keeps the receiver's own sigma and the amplitude is added to it.

(c) The same states, with the declared variance split into a correlated share and a white share, as ADR-0034 does with `vision_gm_rho`. The total claimed variance of a fix then stays what the receiver reports.

(d) Inflate the receiver sigma by a fixed factor. No state, no correlation, and the same trade-off ADR-0034 records for the visual multiplier: one factor does not fit both an independent and a correlated error.

(e) Estimate the correlation time and amplitude from the innovations. Needs a rule for when the estimate is trusted. ADR-0034 notes that correlated errors are absorbed into the state and hide in the innovations.

## Decision

To be written by the maintainer.

## Consequences

To be confirmed with the decision.

- The term stays optional and off by default whatever is decided.
- If (b) or (c) is kept, the values of `gnss_gm_tau_s` and `gnss_gm_sigma_m` need a source other than the run they are scored on.
- The run rows and the page statements belong to issue #184 and need their own CSV and tests.
- No runtime dependency changes.
