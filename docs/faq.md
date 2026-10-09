# FAQ

## Is this a navigation system?

No. It is an evaluation harness that happens to contain a filter. It has no sensor drivers, no
live front end and no real-time loop, and it has never seen real sensor data. See
[Scope and responsible use](scope.md).

## Are the numbers real?

They are real in the sense that every one is produced by the code in this repository and can be
regenerated (`make repro`). They are synthetic in the sense that the "sensors" are generated from
an analytic trajectory. No number here is a field measurement.

## Why is visual fusion off by default?

Because with GNSS denied it makes the filter confidently wrong: mean NEES 391.2 against an
expected 3, and 20.0% coverage where 99.3% is expected. A caller who did not ask for that should
not receive it ([ADR-0003](adr/0003-ship-visual-disabled.md)).

## So does vision make the estimate more accurate or not?

It depends on when the outage starts. In the benchmark's outage (5 s to 20 s) it lowers the
error from 3.783 m to 2.506 m. In an outage sweep, vision beat the no-vision control in every seed
for outages of 10 s or longer starting at 5 s, and was worse than the control in all 20 runs
starting at 10 s. The overconfidence did not depend on the window at all. The cause of the
timing dependence has not been tested. See [Results](results.md).

## Why does the "calibrated" control say "mixed"?

Calibration is reported as a bulk test (mean NEES against its expectation) and a tail test
(coverage inside the 2σ ellipsoid), and a disagreement is named instead of resolved. The control
has a mean NEES a little above 3 (a real, detectable overconfidence) while no epoch escapes the
ellipsoid. Both statements are true. See [Results](results.md).

## Why 99.3% coverage for "2σ"?

"2σ means 95%" is a one-dimensional statement. For a 3-D position error and an ellipsoid whose
semi-axes are 2σ, the expected coverage is the chi-square probability P(χ²₃ ≤ 12) = 0.9926. The
code states coverage against that, never against 95%.

## Why no SciPy, GTSAM or pytest-cov?

Constraint S1 keeps the runtime to Python, NumPy, Matplotlib and PyYAML so that every number can
be traced to code in the repository, including the chi-square quantiles. Coverage is measured by
the project's own script for the same reason. Test-only tools (pytest, Hypothesis, ruff, mypy)
are allowed in the dev extra. See [Design constraints](design-constraints.md).

## Why do I get slightly different digits on my machine?

Two runs on the same platform are byte-identical (timing aside). Across platforms the benchmark
agrees to within the tolerances of the golden snapshot, because linear algebra can differ in the
last bits and the covariance amplifies it. See [ADR-0009](adr/0009-cross-platform-numerics.md)
and [ADR-0010](adr/0010-determinism-and-seeding.md).

## Can I run it on my own data?

Not through the benchmark. For the EuRoC MAV dataset there is a separate path that uses the
recorded IMU and the dataset's ground truth, with the GNSS fixes simulated from that ground truth
(EuRoC has no GNSS):

```
navkit euroc selftest                          # no download; checks the pipeline
navkit euroc fetch --sequence MH_01_easy       # IMU and ground truth only, by byte range
navkit euroc run --sequence MH_01_easy --outage 60:20 --markdown
```

The data is not vendored. Its rights statement is "In Copyright - Non-Commercial Use Permitted", so
the files go under `data/raw/`, which git ignores, and only aggregate results may be committed. A
result from this path is labelled `real_imu_simulated_gnss`. It tests the filter against real
inertial noise and a known reference. It is not GNSS-denied navigation in the field. The decision
behind it is [ADR-0013](adr/0013-recorded-imu-with-simulated-gnss.md).

No result from this path is quoted in these pages yet. Two tests compare against the TUM VI
benchmark when its ground truth is present locally. See [Path to real systems](REAL_SYSTEMS.md).

## Does the repository implement the known fixes for the overconfidence?

No. Observability-constrained filters, first-estimate Jacobians, invariant and Schmidt filters and
pose-graph formulations are the established remedies, and none is implemented here. What this
repository adds is a harness that measures the failure and a decision not to ship the broken
configuration. See [Status and limits](status.md).

## How do I report a security problem?

Privately, through the [security policy](security.md). Behaviour that the documentation lists as
a measured limitation, such as overconfidence under GNSS denial, is the subject of the project and
not a vulnerability.
