# ADR-0001: Model the visual anchor as a filter state

- Status: accepted
- Date: 2026-09

## Context

A relative visual measurement is a constraint on the pose, not on the
position alone. The first implementation folded a visual translation update
directly into the inertial position covariance via `H_cp = -R_prev^T`.

Measured behaviour on the generated synthetic benchmark, 20 s, GNSS
available throughout, noisy IMU (`python scripts/run_benchmark.py`):

| Path | ATE RMSE | Claimed 1σ | Mean NEES | 2σ coverage |
|---|---:|---:|---:|---:|
| Anchor folded into `P` (defect) | 1.259 m | 0.091 m | 354.6 | 16.0% |
| Anchor as filter state, GNSS aided | 0.503 m | 0.252 m | 3.7 | 100.0% |

The folded path drives the error an order of magnitude above the uncertainty it
claims, and the coverage says the claimed ellipsoid contains the truth one time
in six where 99.2% of the time is expected.

The first observation of the defect was a *sensor* symptom rather than a
covariance one: the folded path shrank the position covariance so aggressively
that valid GNSS updates failed their own gating test. In an earlier ad hoc run
46 of 101 GNSS fixes were discarded, while the estimator sat 16 m from truth
claiming 3.7 cm. The generated cases above do not reproduce the gating
rejections, so that count is recorded as history rather than as a current
measurement; the mechanism is real and worth watching for.

## Decision

Introduce a constant-in-the-body-frame visual anchor as explicit nuisance
states, extending the filter from 15 to 21 states:

```
c_p : constant body-frame position offset  (3)
c_t : constant body-frame translation offset (3)
```

The visual update constrains `c_t` to the measured relative translation and
leaves the navigation states to the process model, which is what the
measurement actually supports.

## Consequences

- Covariance is honest: mean NEES falls from 354.6 to 3.7 against 3 nominal
  degrees of freedom.
- GNSS updates are no longer spuriously rejected; availability returns to
  101/101.
- The state vector grows 40%, and the transition matrix becomes genuinely
  21x21 rather than padded.
- This is necessary but not sufficient. See ADR-0003 for the residual
  limitation under GNSS denial.
