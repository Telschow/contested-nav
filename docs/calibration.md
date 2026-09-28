# Reading the calibration numbers

This is the guide to interpreting what `navkit` reports, and — more usefully —
to noticing when a result is not what it appears to be.

## The core idea

A trajectory is not a result. A trajectory with a covariance attached is a
claim about how much to trust it. If the covariance is wrong, everything
downstream is wrong, and the failure is silent because the output still looks
smooth.

Three numbers expose it.

## NEES — normalised estimation error squared

```
NEES = e^T P^-1 e
```

where `e` is the error between the estimate and truth, and `P` is the filter's
claimed covariance. If both are right, NEES is chi-square distributed with
`n` degrees of freedom, where `n` is the dimension of the state being scored.

`navkit` scores the 3-D position block, so the nominal mean is **3**, not 21.
The filter state has 21 entries, but the reported NEES is a position-only
statistic: `e^T P_pp^-1 e` with `P_pp` the 3x3 position covariance, and that
reference does not grow with the size of the state vector.

**Read it like this:**

| NEES vs nominal | Meaning |
|---|---|
| near nominal | calibrated |
| far above | **overconfident** — claims more certainty than it has |
| far below | underconfident — claims less certainty than it has |

The number to be suspicious of is the gap, not the value. The generated
`outage_visual` case reports a mean NEES of 1051 against a nominal 3. That is
not a filter that is slightly miscalibrated; it is a filter that is wrong by
two orders of magnitude.

**Why it is decisive:** NEES only blows up when the error is large *and*
`P` is small. A filter that merely tracks badly has a large error but an
honestly large `P`, and its NEES stays near nominal. A NEES in the hundreds
requires both.

## 2-sigma coverage

The fraction of steps where the true error lies inside the claimed 2-sigma
ellipsoid.

```
coverage = mean(||e||^2 <= 2^2 * lambda_max-ish)
```

evaluated over the scored window. For a 3-D position error at 2 sigma, a
calibrated filter covers approximately **99.2%** of the time
(`1 - (2 * erf(2/sqrt(2)) - 1)^3`). The 95% figure belongs to a single axis, and
using it here would make a well-calibrated filter look like it is missing a
quarter of its epochs.

This is the most direct read for a downstream consumer: it is the probability
that a safety check written against this covariance would have been satisfied
by the truth. A filter at 0.7% coverage would fail roughly 99 checks in 100
that it believed it was passing.

**Coverage is also how you catch a filter that is accidentally too
conservative**, which is why it is reported alongside NEES rather than
instead of it. A filter that never updates has perfect coverage and useless
output.

## Calibration verdict

`navkit/eval/calibration.py` classifies each run as overconfident, underconfident
or calibrated, using both NEES against its nominal and a **Wilson interval**
on the coverage fraction.

The Wilson interval matters. A naive coverage estimate from 10 steps that
hits 9/10 looks perfect; a Wilson interval says the 95% interval on that
proportion still includes 0.5, so no verdict should be declared. Without the
interval, short runs produce confident nonsense — which is the same failure
mode as the original bug, one level up.

## Worked example: reading the defect

From the generated benchmark (`python scripts/run_benchmark.py`, GNSS available
throughout, 20 s):

| Configuration | ATE RMSE | 1-sigma claimed | Mean NEES | Coverage at 2 sigma |
|---|---:|---:|---:|---:|
| GNSS only (control) | 0.503 m | 0.252 m | 3.7 | 100.0% |
| GNSS + vision, anchor as measurement noise (defect) | 1.259 m | 0.091 m | 354.6 | 16.0% |
| Vision only, anchor as filter state | 2.309 m | 0.156 m | 331.0 | 0.7% |

Row 1 is the reference: error and claimed uncertainty are the same order, and
coverage is complete.

Row 2 is the defect. Note the combination: the claimed 1-sigma is an order of
magnitude below the error it is attached to, the mean NEES is 355 against a
nominal 3, and coverage is 16.0% where 99.2% is expected. Any one of these would
warrant investigation. Together they say the filter is confidently wrong, and
the *direction* of the error matters -- it is overconfident, not merely
inaccurate.

Row 3 is the anchor modelled as filter state, and it is the honest failure. It
is not overconfident in the same way, but it is still not calibrated, and its
ATE is worse than the GNSS-only control it was meant to replace. Modelling the
anchor as state is necessary and not sufficient; the numbers are quoted because
they are unflattering, not because they are reassuring.

The same cases also show the accept/reject counts, which is where the defect
was first visible as a *sensor* problem rather than a covariance problem:

| Configuration | GNSS used | GNSS rejected | Vision used | Vision rejected |
|---|---:|---:|---:|---:|
| GNSS only (control) | 151 | 0 | 0 | 0 |
| GNSS + vision, anchor as measurement noise (defect) | 151 | 0 | 599 | 0 |
| Vision only, anchor as filter state | 0 | 0 | 599 | 0 |

An earlier ad hoc run of the defective configuration did show the companion
symptom: the visual update shrank the position covariance far enough that valid
GNSS fixes began failing their own gating test, so the filter was discarding its
most reliable sensor. The current generated cases do not reproduce that, because
the scenarios were re-specified with different seeds and rates. It is recorded
here as a mechanism to watch for, not as a current measurement.
