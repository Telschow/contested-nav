# A multipath signature on the GNSS innovations

[ADR-0021](adr/0021-fault-classification-from-innovations.md) chose to ship at most a multipath detector, because
multipath was the one cause the [fault-classification study](fault_classification.md) separated cleanly. This page
measures a simple detector: two numbers computed on a window of GNSS innovations. It is a function in
`navkit.fdir.multipath`. It is not wired into the filter ([ADR-0022](adr/0022-multipath-signature.md)).

## The signature

Over a 20 s window of innovations:

- **NIS**: the mean normalised innovation squared, divided by 3. About 1 when the channel is healthy.
- **Lag-1 autocorrelation** of the whitened innovation. Near 0 for noise, near 1 for a persistent offset.

Multipath is noise on the fixes: a large NIS with little correlation. A step or a ramp also inflates the NIS but its
innovations are strongly autocorrelated. The call is a large NIS and an autocorrelation of at most 0.8.

Two rules differ in the NIS they need. The **sensitive** rule needs 2, twice the healthy value. The **specific** rule
needs 6, the value the classification tree learned on its training runs. Both were fixed in code, and the shipping
criteria were written, before the fresh runs were made.

## What counts as success

A rule is shipped only if, on fresh runs, it calls at least 95% of the multipath runs of 3 m and above, and at most 2%
of every other run, controls included. The criteria are in `CRITERIA` in `navkit.multipath_study`.

## The floor

Multipath of 0.5 to 2 m, and extra controls, on seeds 6 and 7. These runs were seen before the fresh set was
designed.

<!-- multipath-floor:start -->

| Multipath m | Runs | Sensitive rule calls | Specific rule calls | Median NIS | Median lag-1 autocorrelation |
|---:|---:|---:|---:|---:|---:|
| 0 | 34 | 0% | 0% | 0.88 | -0.04 |
| 0.5 | 34 | 0% | 0% | 1.31 | -0.01 |
| 1 | 34 | 100% | 0% | 2.48 | 0.05 |
| 1.5 | 34 | 100% | 0% | 4.49 | 0.19 |
| 2 | 34 | 94% | 62% | 6.59 | 0.46 |

<!-- multipath-floor:end -->

## The confirmation runs of the classification study

Unseen sizes and seeds, by true class. The 6 in the specific rule came from that study's training runs. These runs
were seen before the rules were fixed.

<!-- multipath-confirm:start -->

| Class | Runs | Sensitive rule calls multipath | Specific rule calls multipath |
|---|---:|---:|---:|
| control | 68 | 0% | 0% |
| multipath | 68 | 100% | 100% |
| spoofing | 238 | 13% | 0% |
| degradation | 170 | 3% | 0% |

<!-- multipath-confirm:end -->

## The fresh runs

New seeds (8 and 9) and a mixed set of cases, run after the rules and the criteria were fixed. This is the clean
test of the rule that is chosen.

<!-- multipath-fresh:start -->

| Class | Fault | Level | Runs | Sensitive rule calls multipath | Specific rule calls multipath |
|---|---|---:|---:|---:|---:|
| control | none | 0 | 34 | 0% | 0% |
| multipath | multipath | 1 | 34 | 100% | 0% |
| multipath | multipath | 2 | 34 | 100% | 62% |
| multipath | multipath | 3 | 34 | 100% | 100% |
| multipath | multipath | 5 | 34 | 100% | 100% |
| spoofing | step | 5 | 34 | 65% | 0% |
| spoofing | step | 10 | 34 | 9% | 0% |
| spoofing | ramp | 3 | 34 | 9% | 0% |
| spoofing | ramp | 5 | 34 | 6% | 0% |
| degradation | accel_bias | 0.7 | 34 | 3% | 0% |
| degradation | gyro_bias | 0.02 | 34 | 12% | 0% |

<!-- multipath-fresh:end -->

<!-- multipath-criteria:start -->

| Rule | Recall, multipath of 3 m and above (needs 95%) | Called multipath, all other runs including controls (needs at most 2%) | Criteria met |
|---|---:|---:|---|
| sensitive | 100% | 15% | no |
| specific | 100% | 0% | yes |

<!-- multipath-criteria:end -->

## Control runs

<!-- multipath-false-alarms:start -->

| Control runs | Runs | Sensitive rule calls | Specific rule calls | 95% upper bound on the specific rule's rate |
|---|---:|---:|---:|---:|
| floor | 34 | 0 | 0 | 9% |
| confirmation | 68 | 0 | 0 | 4% |
| fresh | 34 | 0 | 0 | 9% |
| all | 136 | 0 | 0 | 2% |

<!-- multipath-false-alarms:end -->

## What it shows

1. **The specific rule meets the criteria.** On the fresh runs it calls all multipath of 3 m and above, and none of
   the other runs: no control, no step, no ramp, no bias.
2. **The sensitive rule does not.** It calls multipath from 1 m, but it also calls about two thirds of the 5 m steps
   and a few ramps and bias steps, so 15% of the other fresh runs are called multipath.
3. **The cost of the specific rule is sensitivity.** Multipath of 2 m is called in about two thirds of runs, 1.5 m
   in a few, and 1 m and below in none. The detector sees multipath of about 3 m and above, which is several times the
   0.8 m noise of the simulated GNSS.
4. **No control run in any set is called multipath.** None of 136 control runs, which bounds the false-alarm rate at
   about 2% with 95% confidence.

## Limits

Injected white noise on simulated GNSS, 20 s windows, two datasets, and the calibrated bias-walk setting. Real
multipath is correlated over seconds and comes with reflections that bias the position, so a real multipath run will
have a higher autocorrelation than the injected noise and may fall above 0.8. That is not tested here. Only the
specific rule was chosen on clean data, and its floor of about 3 m is a measurement of this injection, not of a
receiver.
