# Performance

What was measured, how, what was changed because of it, and what was left alone. Every
number below comes from the commands at the end, and the machine they were measured on is
stated. These are timings of this repository's own benchmark scenarios on one machine. They
say nothing about any real-time target, which this project does not have.

## Summary

- A full benchmark case takes about 1.5 to 2.4 s. The estimator itself accounts for only 8% to
  31% of that (0.12 s for dead reckoning, 0.5 to 0.75 s for the filtered cases). The rest is
  trajectory synthesis, the sensor models, the metrics and the calibration scoring.
- The largest single cost outside the filter was `interpolate_trajectory`, called 8 times per
  case. It looped over 6001 samples in Python, doing one SLERP and one quaternion-to-matrix
  conversion each. It is now vectorised.
- Measured back to back on the same machine, the sum of the seven case medians fell from
  15.14 s and 15.07 s (two runs of the old code) to 11.10 s: -26.5%, a speedup of
  1.36x. Estimator time is unchanged (gnss_only 0.534 to 0.534, outage_visual 0.701 to 0.721, in seconds), as it should be, because the
  change does not touch the filter.
- The results are not bit-identical. Of 73,846 numbers in the full benchmark output, 97 differ
  at all, by at most 3.6e-16 absolute. The golden snapshot test passes unmodified.

## Environment

| | |
|---|---|
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical CPUs |
| Python | CPython 3.13.16 |
| NumPy | 2.5.3 |
| OS | Linux-6.18.44-fc-v77-x86_64-with-glibc2.39 |
| BLAS thread variables | unset |

This is a cloud container on shared hardware, so absolute times will differ on other
machines and can drift on this one. The two runs of the unchanged code below agree to
within 0.5% in total, which is the drift to read the change against.

## Method

`benchmarks/bench_cases.py` calls `run_case`, the code path behind `navkit run`, for each
scenario in `configs/benchmark.yaml`. Each case gets one untimed warm-up run and then five
timed runs. It records the wall time of the whole case and the estimator's own run time,
which the result record already carries as `runtime_s`. Medians are used, with the minimum,
maximum and standard deviation kept in the JSON, because a single number hides the spread.

The old and new code were timed in the order old, new, old in one session, so a drift in the
machine would show up as a disagreement between the two old runs.

## Results

Median wall time per case in seconds, five timed runs each after a warm-up.

| Case | Old, run 1 | Old, run 2 | New | Change vs mean of old |
| --- | ---: | ---: | ---: | ---: |
| gnss_only | 2.164 | 2.173 | 1.571 | -27.6% |
| dead_reckoning | 1.527 | 1.538 | 0.973 | -36.5% |
| vision_anchor_in_measurement_noise | 2.376 | 2.348 | 1.803 | -23.7% |
| vision_only | 2.296 | 2.274 | 1.773 | -22.4% |
| outage_control | 2.159 | 2.164 | 1.545 | -28.5% |
| outage_visual | 2.293 | 2.324 | 1.766 | -23.5% |
| outage_visual_degraded_camera | 2.323 | 2.254 | 1.672 | -27.0% |
| **all cases, sum of medians** | **15.138** | **15.074** | **11.103** | **-26.5%** |

The spread within a case is small next to the change: standard deviations are between
0.006 and 0.085 s, against savings per case of 0.51 to 0.62 s.

## Where the time went

`cProfile` on the dead-reckoning case, which has almost no filter cost and so isolates the
pipeline around it (`python -m cProfile scripts/run_benchmark.py --only dead_reckoning`).
Profiler overhead inflates every number, so read the ratios, not the seconds.

| | Total under the profiler | `interpolate_trajectory`, 8 calls | `ate_bundle` |
|---|---:|---:|---:|
| Before | 2.87 s | 1.27 s cumulative | 1.30 s |
| After | 2.00 s | 0.30 s cumulative | 0.79 s |

`ate_bundle` resamples the reference trajectory onto the estimate's timestamps once per
alignment, so the same interpolation ran four times in it, and four more times elsewhere in
a case. One unprofiled call took about 108 ms on 6001 queries before the change.

## What changed

`interpolate_trajectory` in `src/navkit/types.py` now computes the SLERP and the rotation
matrices for all queries at once (`_slerp_batch`, `_quats_to_matrices`) instead of one query
at a time. The same three cases are handled: the short way round (a negative dot product
flips one quaternion), a nearly parallel pair (normalised linear interpolation, because the
sine in the denominator vanishes), and the ordinary SLERP. The slerp coefficients are
computed only for the pairs that need them, so no vanishing sine is ever divided by.

## How equivalence was checked

- `tests/test_interpolate_trajectory.py` keeps the old per-sample code as an oracle and
  requires agreement to 1e-12 on random trajectories built to exercise all three cases, with
  queries at the knots, midpoints, random times and outside the span. A separate test asserts
  that all three cases are in fact reached, so the comparison cannot pass vacuously.
- `tests/test_golden_benchmark.py` passes with the snapshot unmodified.
- A numeric comparison of the full benchmark output against the output of the old code: 73,846
  numbers compared, 97 differ, the largest absolute difference is 3.6e-16.

The output is therefore not byte-identical to before. Vectorising reordered some elementwise
operations, which changes the last bit of a few numbers. That is why the change is checked
against a tolerance, not by identity.

## What was not changed

These are the next costs in the profile after this change. None was touched, and none has a
measured speedup behind it.

- `Trajectory.quaternions` rebuilds the quaternion array with a per-pose Python loop each time
  it is read. `interpolate_trajectory` reads it on every call: 0.27 s of its 0.30 s above.
  Caching it, or vectorising `matrix_to_quat`, is the obvious next step.
- `rot_log_batch` loops over rotations despite its name: 24,006 calls and 0.6 s cumulative in
  the profile above, calling `rot_log` 35,806 times.
- `synthetic_imu` and `analytic_pose` generate the reference motion sample by sample (about
  0.45 s).
- The filter itself, at 0.12 to 0.75 s per case. Nothing here suggests it needs work.

## Reproduce

```bash
python benchmarks/bench_cases.py --repeats 5 --out results/performance.json
python benchmarks/bench_cases.py --only dead_reckoning --repeats 10
python -m cProfile -o prof.out scripts/run_benchmark.py --only dead_reckoning
```

To compare two versions, check out each in turn (or `git archive` one into a scratch
directory), run the same command from the same machine in one session, and alternate old,
new, old so drift is visible.
