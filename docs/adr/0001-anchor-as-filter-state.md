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
  c_t : constant body-frame attitude offset  (3)
  ```

  The two blocks are constrained by different halves of the visual update: the
  translation half constrains `c_p` against the measured relative translation, and
  the rotation half constrains `c_t` against the measured relative rotation. (An
  earlier revision of this ADR described `c_t` as a translation offset and
  attributed both measurements to it. That was wrong: `c_t` is initialised from
  `anchor_rot_sigma_deg` and appears only in the rotation Jacobian,
  `eskf.py` `H_rot[:, _IDX_CT]`. Corrected 2026-09 against the implementation.)

  The intended behaviour is that the visual update moves `c_p` and `c_t` to
  explain a constant anchor error, leaving the navigation states to the process
  model, which is what the measurement actually supports.

  ## Known limitation: the anchor error is not currently estimated

  The decision above describes the intended design. The implementation does not
  yet deliver it. `_update` forms the gain over all 21 states and computes
  `dx[_IDX_CP]` and `dx[_IDX_CT]`, but the write-back does not apply them, so
  `c_p` and `c_t` remain at zero while their covariance is reduced by the Joseph
  update as though they had been estimated. This is tracked as CN-003 in the
  independent audit and is recorded in the source at the write-back.

  It is **not** a safe one-line omission to repair. Both states carry no process
  noise by default, so with an anchor that is not re-committed every frame they
  are not identifiable: a corrected anchor error latches onto any persistent
  discrepancy and absorbs real navigation drift instead of letting the filter
  correct for it. Measured on `outage_visual` with the anchor held fixed,
  applying the correction moved ATE from 35.9 m to 217.5 m and mean NEES from
  28.4 to 7118.5. At the shipped configuration, `vision_keyframe_interval: 1`
  re-commits the anchor immediately after each visual update, so the states are
  reset to zero anyway and the correction is inert either way.

  Closing this requires an identifiability decision -- a bounded estimation
  window, a scheduled re-commit, or process noise on the anchor blocks with the
  corresponding loss of relative-measurement power -- not a patch. Until then,
  `vision_anchor_modelled` must not be described as estimating an anchor error.

  ## Consequences

  - Covariance is honest: mean NEES falls from 354.6 to 3.7 against 3 nominal
    degrees of freedom. This improvement comes from the anchor covariance
    participating in the gain, not from an estimated anchor error, and the
    measurement is unaffected by the limitation above because of the per-frame
    re-commit.
  - GNSS updates are no longer spuriously rejected; availability returns to
    101/101.
  - The state vector grows 40%, and the transition matrix becomes genuinely
    21x21 rather than padded.
  - This is necessary but not sufficient. See ADR-0003 for the residual
    limitation under GNSS denial, and the "Known limitation" section above for
    the part of this decision that is not yet implemented.
