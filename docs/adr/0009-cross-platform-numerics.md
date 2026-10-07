# ADR-0009: Cross-platform numerics and the golden tolerance

- Status: accepted
- Date: 2026-10

## Context

CI ran Linux only. Two legs, macOS and Windows at Python 3.13, were added to find platform
dependence in the numbers. Both failed the golden benchmark test on the first run.

The failures were not last-bit noise. Against the Linux snapshot the benchmark differed by
about 1e-7 to 1e-6 relative (for example `outage_visual` ATE 2.540699 against 2.540698), and
macOS and Windows agreed with each other to every printed digit. Two things were wrong:

1. **The synthetic IMU was a second finite difference.** The accelerometer was
   `(p(t+e) - 2 p(t) + p(t-e)) / e^2` of the analytic position with `e = 1e-5 s`. That divides a
   rounding error of about 1e-16 by 1e-10. Perturbing `np.cos` by one ulp, which is the size of
   the difference between math libraries, moved the accelerometer by up to 7.4e-5 m/s^2 (typical
   magnitude 0.7). Every platform generated a slightly different "known-answer" fixture. The
   earlier Linux-to-Linux gap of up to 4e-11 that set the absolute floor in
   `tests/test_golden_benchmark.py` was the same effect at a smaller size.
2. **A Windows checkout rewrites line endings.** `config_sha256` in every result is the hash of
   `configs/benchmark.yaml`, and `autocrlf` changed the bytes, so the hash differed.

## Decision

- **Remove the cause, do not widen the tolerance.** The synthetic IMU is derived analytically
  (`navkit.synthetic.analytic_kinematics`). A test perturbs `cos` by one ulp and requires the
  IMU to move by less than 1e-12; the old implementation moved by 7e-5.
- **Keep the golden tolerance** at a relative 1e-9 plus an absolute floor of 1e-9, with one exception below. With the IMU
  fixed, all three operating systems pass at that tolerance (CI run on the pull request that
  added this ADR). The actual cross-platform gap was not measured below the tolerance, so no
  tighter claim is made.
- **The claimed-sigma series gets 1e-6.** It was added to the snapshot later and is read directly
  from the covariance. On a later CI run of the same commit it differed from the committed values
  by up to 1.1e-8 relative on one runner while passing on another, and every other quantity
  still agreed at 1e-9. GitHub runners are not identical machines, and the covariance depends on
  which CPU kernel the linear algebra uses. The series now has a relative tolerance of 1e-6, about
  100 times the largest gap seen. A real change (1e-4) is still caught, and the same 2e-8 on a
  headline number is still a difference; both are tests.
- **Pin line endings** of the hashed configuration and the golden snapshot to LF with
  `.gitattributes`.
- **Scope of the new legs.** macOS and Windows run the full test suite at Python 3.13 only. The
  Linux matrix (3.11, 3.12, 3.13) remains the full gate, and the coverage ratchet stays on
  Linux because its measurement depends on the interpreter's bytecode.

## Consequences

- Benchmark numbers moved by at most 1.1e-5 m in ATE and 3.6e-3 in mean NEES; coverage, counts
  and verdicts did not change, and every documented table still matches.
- A future change that makes the fixture sensitive to the math library again will fail on macOS
  or Windows, not only on a developer's machine.
- Anything else that differentiates numerically at a small step has the same hazard. The other
  finite differences in `src/` are the generic `Trajectory` velocity and acceleration helpers
  in `types.py` and the IMU-from-trajectory path in `io/imu.py`. They use the sample spacing of
  their input, so they are only exposed if given dense, noise-free input; none of them feeds the
  benchmark.
- Floating-point results on other architectures (for example 32-bit) are not tested.
