# ADR-0033: One convention for the synthetic visual translation noise

- Status: accepted
- Date: 2026-10
- Related: [ADR-0024](0024-assumed-noise-for-the-opt-in-clone.md), [ADR-0027](0027-how-the-synthetic-runs-are-initialised.md), [ADR-0028](0028-the-b1-gate.md), [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md), [ADR-0031](0031-an-adaptive-visual-noise-scale.md), [ADR-0032](0032-the-adaptive-visual-scale-takes-every-visual-update.md), [PR #161](https://github.com/Telschow/contested-nav/pull/161), [issue #44](https://github.com/Telschow/contested-nav/issues/44), [issue #113](https://github.com/Telschow/contested-nav/issues/113)

## Context

The third measurement on [issue #44](https://github.com/Telschow/contested-nav/issues/44) followed the failed tuning run of [PR #161](https://github.com/Telschow/contested-nav/pull/161). It found that the synthetic visual translation noise is not drawn with the covariance that the stream declares and the filter assumes. Three facts, each read from the code and checked numerically before this ADR was written.

- **What the generator draws.** In `visual_updates` in `src/navkit/sensors/models.py` (lines 228 to 231) the relative translation noise is a random unit direction times one scalar drawn from a normal with the standard deviation `trans_sigma`. The noise is rank one in each frame, and its per-axis variance is one third of `trans_sigma` squared. The code comment calls the random direction a crude stand-in for depth ambiguity in monocular matching. That is a modelling idea. The declared covariance does not match it.
- **What the stream declares.** The same function returns `trans_cov` as `trans_sigma` squared on each axis (line 252). The function `rereference_visual_updates` in the same file repeats the draw (lines 341 to 344) and keeps that declared covariance.
- **What the filter assumes.** `src/navkit/estimators/eskf.py` builds the translation block of the visual measurement covariance as the identity times `trans_sigma_m` squared (lines 1122 and 1194).

The numerical check, MEASUREMENT: the generator's draw repeated 400 000 times gives a per-axis variance of 0.332, 0.334 and 0.334 times `trans_sigma` squared, with no correlation between the axes. The real `visual_updates` run on a synthetic trajectory (30 000 frames, noisy minus noise-free relative translation) gives 0.332, 0.333 and 0.338 times `trans_sigma` squared per axis. The declared `trans_cov` is exactly 1 times `trans_sigma` squared on each axis. The filter is therefore told a translation variance three times the one the generator produces, in every case that uses synthetic vision. The rotation noise is drawn per axis and matches.

The effect seen, MEASUREMENT from issue #44 (scratch runs on development seeds 0 to 4): the adaptive scale, run with a very small lower bound, settles near one third for the translation block in S1 on all five seeds, and between a quarter and a half in S2, while the rotation scale settles near one. That agrees with a factor of three.

Every result that uses synthetic vision was measured on this fixture. That includes the held-out evaluation of [ADR-0028](0028-the-b1-gate.md) and the tuning run of PR #161. It also includes the development tables, the sweeps and the fault matrix. Results that use recorded data with the real front end, or replay real measurements, do not.

The page `docs/real_front_end.md` reports the lateral error of the real front end, which is the error of the direction times the baseline. It does not state a per-axis standard deviation, so it does not settle the convention. This ADR is about the synthetic generator only.

HYPOTHESIS, until the fixture is corrected and measured again: the conservatism of the plain clone in S1 that the gate of [ADR-0030](0030-the-gate-for-the-next-visual-update-candidate.md) flagged (a median per-run mean NEES near one) is at least partly this mismatch and not a property of the filter.

## Options

(a) The generator draws each axis independently with the declared standard deviation. The generator, the stream and the filter then use one convention, and it is the same one the rotation noise already uses. This is chosen.

(b) Keep the generator and declare `trans_sigma` squared over three on each axis. This is rejected. A rank-one noise declared as isotropic is still an approximation, and the convention would differ from the one of the rotation noise.

(c) Keep both and document the mismatch. This is rejected. The filter would stay told the wrong noise, and every later result would carry the caveat.

## Decision

Convention. The synthetic visual translation noise has the per-axis standard deviation given by trans_sigma_m times the noise multiplier: each axis of the relative translation error is drawn independently from a zero-mean normal with that standard deviation. This is the covariance the stream declares (trans_cov) and the covariance the filter assumes, so the generator, the stream and the filter use one convention. The earlier draw, a random unit direction times one scalar of that standard deviation, had a per-axis variance of one third of the declared value. It is removed, not kept as an option. The translation noise comes from its own random stream, seeded by the scenario seed and separate from the stream of the rotation noise, so the rotation noise samples do not change. The setting names and values in the configs do not change; their documented meaning is the per-axis standard deviation.

Consequences for results. Every result that depends on synthetic vision is regenerated with the code that implements this decision. Results recorded before that are kept as dated history and are labelled as produced under the earlier draw. Recorded-data results that use the real front end, or replay real measurements, are not affected.

Consequences for the gate and the candidates. The seeds 100 to 124 were evaluated on the earlier fixture and stay spent. The block 125 to 149 is unused. The first candidate of ADR-0030, the adaptive visual noise scale of ADR-0031 and ADR-0032, may be tuned one more time on the corrected fixture, with the same twelve-point grid, the same selection rule and the same confirmation blocks, and its earlier failure on the earlier fixture stays on record. No candidate is evaluated on a held-out block until that tuning run and its confirmation have been made and this decision is implemented.

## Consequences

- A code package implements the convention in both generators (`visual_updates` and `rereference_visual_updates`). Tests come first. They include a statistical test of the per-axis variance of the translation noise, and a test that the rotation noise samples do not change. The package inventories every synthetic-vision result, regenerates it, and labels the earlier ones as produced under the earlier draw.
- The tuning run of PR #161 is repeated once, in a later package, on the corrected fixture, as the Decision allows.
- No candidate runs on a held-out block before that, and the block 125 to 149 stays unused.
- `CONSTRAINTS.md` B1 stays as it is until a candidate has been evaluated.
- The failed tuning run on the earlier fixture, and the held-out result of ADR-0028, stay on record as they are. They are history under the earlier draw.
