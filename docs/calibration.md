# Reading the calibration numbers

This is the guide to interpreting what `navkit` reports, and, more usefully,
to noticing when a result is not what it appears to be.

## The core idea

A trajectory is not a result. A trajectory with a covariance attached is a
claim about how much to trust it. If the covariance is wrong, everything
downstream is wrong, and the failure is silent because the output still looks
smooth.

Three numbers expose it.

## NEES: normalised estimation error squared

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
| far above | **overconfident**: claims more certainty than it has |
| far below | underconfident: claims less certainty than it has |

The number to be suspicious of is the gap, not the value. The generated
`outage_visual` and `vision_only` cases report a mean NEES that is thousands of times the nominal 3 in the seed-0
run, which is one run with one start draw
([ADR-0027](adr/0027-how-the-synthetic-runs-are-initialised.md)). That is not a filter that is slightly
miscalibrated.

The gap once fell when ADR-0006 stopped the filter discarding the GNSS fixes that B5 caused it to reject (R2 in
`CONSTRAINTS.md`, measured on the old fixed start). The remaining gap is the unmodelled visual anchor error, which
is a separate defect: the filter was more honest then because it stopped throwing away evidence, not because the
model behind `P` was repaired. Read NEES and the coverage column together with ATE. On the old fixed start ATE alone
stopped flagging this case; with the start drawn from the declared prior it flags it again, but that is no reason to
rank by error.

A 10-seed sweep changes the reading of the digits, not the verdict. Over 10 seeds, each with its own start draw,
`outage_visual` and `vision_only` were overconfident at every one, and their mean NEES spanned about two orders of
magnitude and about one (measured once on one machine, not checked by CI, at e94c107). So the order of magnitude is the right thing to write down, not a single digit.
A control's verdict string is also one draw: `outage_control` was underconfident in 5 of the 10 seeds and mixed or
overconfident in the others.

**Why it is decisive:** NEES only blows up when the error is large *and*
`P` is small. A filter that merely tracks badly has a large error but an
honestly large `P`, and its NEES stays near nominal. A NEES in the hundreds
requires both.

## 2-sigma coverage

The fraction of steps where the true error lies inside the claimed 2-sigma
ellipsoid.

```
coverage = mean(e^T P^-1 e <= 2^2 * 3)
```

evaluated over the scored window, where `e^T P^-1 e` is the squared Mahalanobis
distance and 3 is the number of position axes. For a 3-D position error at 2 sigma
per axis, a calibrated filter covers `P(chi2_3 <= 12) = 0.9926`, about **99.3%** of
the time. The 95% figure belongs to a single axis (`erf(2/sqrt(2)) = 0.9545`), and
using it here would make a well-calibrated filter look like it is missing a
quarter of its epochs. The same number comes from
`navkit.eval.statistics.ellipsoid_coverage(2.0, 3)`.

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
interval, short runs produce confident nonsense, which is the same failure
mode as the original bug, one level up.

## Worked example: reading the defect

From the generated benchmark (`python scripts/run_benchmark.py`, GNSS available
throughout, 30 s). This is one run with one start draw (seed 0), so it is descriptive:

| Configuration | ATE RMSE | 1-sigma claimed | Mean NEES | Coverage at 2 sigma |
|---|---:|---:|---:|---:|
| GNSS only (control) | 0.512 m | 0.254 m | 4.2 | 100.0% |
| GNSS + vision, anchor as measurement noise (defect) | 11.405 m | 0.100 m | 13322.0 | 9.0% |
| Vision only, anchor as filter state | 26.605 m | 0.158 m | 31789.6 | 1.5% |

Row 1 is the reference: error and claimed uncertainty are the same order, and
coverage is complete.

Row 2 is the defect. Note the combination: the claimed 1-sigma is far
below the error it is attached to, the mean NEES is thousands of times the
nominal 3, and coverage is a few percent where 99.3% is expected. Any one of these would
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
| GNSS + vision, anchor as measurement noise (defect) | 49 | 102 | 599 | 0 |
| Vision only, anchor as filter state | 0 | 0 | 599 | 0 |

The defect row now shows the companion symptom in this run: the visual update shrinks the position covariance far
enough that valid GNSS fixes fail their own gating test, so the filter discards its most reliable sensor. An earlier
version of this page said the generated cases did not reproduce that; that was on the old fixed start. Here it is one
run with one start draw, and it was not swept, so it is an observation and not a rate.
