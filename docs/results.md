# Results

Synthetic 30 s run, 5 Hz GNSS, 20 Hz vision, noisy IMU, 21-state ESKF. ATE is
reported with `alignment=none`: the filter is initialised in the reference
frame, so there is no global offset for a fitted transform to absorb. This is
the strictest of the four conventions the code supports.

| Scenario | ATE RMSE (m) | Claimed 1σ (m) | Mean NEES (exp. 3) | Coverage @ 2σ | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| GNSS only (control) | 0.528 | 0.254 | 4.3 | 100.0% | mixed: bulk overconfident, tail underconfident |
| Dead reckoning (no aiding) | 2.359 | n/a | n/a | n/a | no covariance reported |
| Anchor as measurement noise (defect) | 1.063 | 0.094 | 163.7 | 16.3% | overconfident |
| Vision only | 2.321 | 0.158 | 264.2 | 0.7% | overconfident |
| GNSS denied 5–20 s, vision off (control) | 3.760 | 0.567 | 4.1 | 100.0% | mixed: bulk overconfident, tail underconfident |
| GNSS denied 5–20 s, vision on | 2.322 | 0.162 | 286.2 | 20.5% | overconfident |
| GNSS denied, 30% camera frames dropped | 2.008 | 0.192 | 203.7 | 17.8% | overconfident |
| GNSS denied 5–20 s, vision on, stochastic clone | 0.725 | 0.375 | 2.5 | 100.0% | underconfident |
| GNSS denied, 30% frames dropped, re-referenced, single anchor | 1.973 | 0.192 | 191.5 | 17.7% | overconfident |
| GNSS denied, 30% frames dropped, re-referenced, stochastic clone | 0.503 | 0.307 | 2.2 | 100.0% | underconfident |
| Vision only, stochastic clone | 1.959 | 1.326 | 2.3 | 100.0% | underconfident |
| Stochastic clone, 5% gross visual outliers | 0.727 | 0.382 | 2.5 | 100.0% | underconfident |
| Stochastic clone, drifting translation scale | 0.787 | 0.375 | 2.9 | 100.0% | underconfident |
| Stochastic clone, visual errors correlated over 2 s | 1.931 | 0.375 | 13.1 | 58.3% | overconfident |
| Stochastic clone, correlated errors, visual noise assumed 4x | 2.259 | 0.531 | 4.9 | 100.0% | mixed: bulk overconfident, tail underconfident |

Four things deserve more than a glance.

**The defect row is not a gate-threshold problem.** Folding the visual anchor
error into the measurement covariance, rather than treating it as filter state,
drops coverage to 16%. Both variants are in the benchmark so the comparison is
reproducible, and the broken one is kept in the default run on purpose.

**Turning vision on makes the filter much less calibrated, though not much less
accurate.** The outage control with vision off ends at 3.76 m with its
uncertainty grown to match, so coverage stays at 100%. The aided case claims
0.16 m while being 2.32 m wrong. Note what adaptive inflation did to this
comparison: before it, the FDIR gate made the aided case *worse* on ATE (5.06 m),
so a reader sorting by ATE at least got sent to the more honest filter. Recovering
the error put the less-calibrated configuration back on top, and the ATE column no
longer flags it at all. Ranking by error is not a calibration check, and this table is
a demonstration of that rather than an argument against the fix.

**Dead reckoning has no claimed-σ or NEES value.** An integrator with no
uncertainty model has nothing to calibrate. Printing a covariance it never
computed would be the same error as printing one it does not deserve, so the
columns are `n/a` rather than zero.

### Two verdicts, not one

Calibration is reported as a **bulk** test (mean NEES against its expectation)
and a **tail** test (coverage inside the 2σ ellipsoid, by Wilson interval), and
a disagreement is named rather than resolved. A filter can be marginally
overconfident almost everywhere while never once producing a tail escape;
collapsing that into a single "calibrated" boolean discards half the evidence
and hides the shape of the error distribution.

The `mixed` rows are exactly that case: mean NEES of 4.0 against an expected 3
is a real, statistically detectable overconfidence, and yet no epoch escapes
2σ. Both statements are true and only one of them is usually quoted.

![Error against claimed uncertainty](figures/error-vs-claim.png)

![Coverage against expectation](figures/coverage.png)

![Error through the outage](figures/outage-error.png)

![Mean NEES by scenario](figures/nees.png)

### Alignment is not a detail

ATE is reported four ways, because the convention changes the number by metres
and an ATE quoted without its alignment is not a result:

| Alignment | Fitted on | What it hides |
| --- | --- | --- |
| `none` | nothing | nothing; the raw error in the filter's own frame |
| `rigid` | all poses | accumulated drift, absorbed into the fit |
| `rigid_start` | first 20% only | nothing after the first fifth of the run |
| `similarity` | all poses, with scale | a scale error in the estimate |

All headline numbers above use `none`. A rigid fit uses positions only, so
attitude error passes through it untouched and is reported separately; a reader
who assumed "rigid alignment" meant 6-DoF pose alignment would otherwise quote
an attitude error several times smaller than reality.

**A stochastic clone of the previous pose removes the overconfidence on this fixture.** The rows ending in
"stochastic clone" run the same scenarios with the previous visual pose carried as six error states that start
perfectly correlated with the live pose ([ADR-0017](adr/0017-stochastic-clone-for-the-visual-update.md)). With
GNSS denied, the clone is calibrated where the single anchor is not, and its position error is below the
no-vision control's. The two degraded-camera rows use a stream in which each delivered measurement is taken
against the last delivered frame; the single-anchor row on that stream is the control and stays
overconfident, so the generator was not what made the anchor fail. This is a synthetic result with a Gaussian
surrogate front end. The clone is opt-in: the shipped setting is still the single anchor, with visual fusion
off.

**What the clone does not survive.** The last four clone rows depart from the ideal front end one way at a time.
Gross outliers are rejected by the gate and the filter stays calibrated. A drifting translation scale does not
matter, because the inertial unit holds the metric scale. Visual errors correlated over 2 s do break it: the clone
assumes independent errors and is overconfident again. Telling the filter the visual noise is four times larger
restores calibration, at a cost in accuracy. The factor was found by trial, not derived. A 150 s run without GNSS
(`tests/test_clone_long_run.py`) shows the claimed uncertainty still growing and the error inside it, and GNSS
accepted when it returns.
