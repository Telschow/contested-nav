# Results

Synthetic 30 s run, 5 Hz GNSS, 20 Hz vision, noisy IMU, 21-state ESKF. ATE is
reported with `alignment=none`: the filter is initialised in the reference
frame, so there is no global offset for a fitted transform to absorb. This is
the strictest of the four conventions the code supports.

| Scenario | ATE RMSE (m) | Claimed 1σ (m) | Mean NEES (exp. 3) | Coverage @ 2σ | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| GNSS only (control) | 0.503 | 0.252 | 3.7 | 100.0% | mixed: bulk overconfident, tail underconfident |
| Dead reckoning (no aiding) | 1.877 | n/a | n/a | n/a | no covariance reported |
| Anchor as measurement noise (defect) | 1.307 | 0.091 | 387.3 | 16.0% | overconfident |
| Vision only | 2.309 | 0.156 | 331.0 | 0.7% | overconfident |
| GNSS denied 5–20 s, vision off (control) | 3.782 | 0.567 | 4.1 | 100.0% | mixed: bulk overconfident, tail underconfident |
| GNSS denied 5–20 s, vision on | 2.541 | 0.161 | 419.4 | 20.0% | overconfident |
| GNSS denied, 30% camera frames dropped | 1.872 | 0.190 | 216.6 | 18.5% | overconfident |

Three rows deserve more than a glance.

**The defect row is not a gate-threshold problem.** Folding the visual anchor
error into the measurement covariance, rather than treating it as filter state,
drops coverage to 16%. Both variants are in the benchmark so the comparison is
reproducible, and the broken one is kept in the default run on purpose.

**Turning vision on makes the filter much less calibrated, though not much less
accurate.** The outage control with vision off ends at 3.78 m with its
uncertainty grown to match, so coverage stays at 100%. The aided case claims
0.16 m while being 2.54 m wrong. Note what adaptive inflation did to this
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

The `mixed` rows are exactly that case: mean NEES of 3.7 against an expected 3
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
