# ADR-0002: Use the Joseph form for covariance updates

- Status: accepted
- Date: 2026-09

## Context

The ESKF used the common shortcut for the posterior covariance:

```
P = (I - K H) P
```

This is algebraically exact in exact arithmetic, but numerically it is only
symmetric and positive semidefinite in the limit of no floating-point error.
Under strong measurements — a visual update against a nearly-covariance-free
anchor, for instance — the subtraction can drive small eigenvalues negative.
Once `P` is not positive semidefinite, the Cholesky factorisation used for
gating and the NEES computation silently returns garbage, and the filter can
begin rejecting every measurement or, worse, accepting bad ones.

The defect was not theoretical. It was reachable, and it corrupted the
benchmark before it was found.

## Decision

Use the Joseph form, which is symmetric and positive semidefinite by
construction, and apply the reset Jacobian afterwards so the state change
made by the update is reflected in the covariance:

```
P = G (I - K H) P (I - K H)^T + K R K^T
```

where `G` is the reset Jacobian mapping the error-state increment back onto
the corrected state.

## Consequences

- Covariance stays positive semidefinite across adversarial visual runs.
  Pinned by `test_covariance_stays_positive_semidefinite_across_a_visual_run`.
- Slightly more arithmetic per update. Irrelevant at these problem sizes.
- A related bug had to be fixed at the same time: `_commit_anchor_covariance`
  cleared the anchor rows and columns *before* installing the declared prior,
  discarding the update. Ordering now installs, then clears only the
  cross-covariance with the navigation block.
