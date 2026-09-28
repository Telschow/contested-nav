# Architecture

## The question

The estimator is the test subject, not the product. `navkit` asks one
question of a navigation filter: *is its stated uncertainty honest?*

Everything in `eval/` exists to answer that. Everything in `estimators/`
exists to be asked it.

## Layers

```
synthetic.py ──► sensors/models.py ──► estimators/eskf.py ──► eval/calibration.py
   analytic        IMU / GNSS /         21-state ESKF          NEES, coverage
   trajectory      visual noise          + covariance           verdicts
                                                             ▲
                                          degrade/inject.py ───┘
                                          GNSS outage windows
```

Supporting layers:

- `geometry/` — SE(3) transforms, quaternions, Umeyama alignment. Convention
  owner: everything is `(w, x, y, z)` and `T_wb` (ADR-0004).
- `io/` — TUM, EuRoC and Plotly readers and writers. The only place that
  converts between quaternion orders.
- `io/imu.py` — IMU noise models. Bias random walk, scale factor, axis
  misalignment, white noise.
- `analysis/findings.py` — typed claim records (`FACT`, `MEASUREMENT`,
  `INTERPRETATION`, `HYPOTHESIS`) with validation, so published claims are
  structurally distinguishable from assertions.
- `config.py` — application configuration loading and validation.

## The estimator

### State vector (21)

| Index | Symbol | Meaning | Units |
|---|---|---|---|
| 0:3 | `dtheta` | orientation error | rad |
| 3:6 | `dp` | position error | m |
| 6:9 | `dv` | velocity error | m/s |
| 9:12 | `db_g` | gyroscope bias | rad/s |
| 12:15 | `db_a` | accelerometer bias | m/s^2 |
| 15:18 | `c_p` | visual anchor position offset | m |
| 18:21 | `c_t` | visual anchor translation offset | m |

The first 15 are the conventional error-state IMU/GNSS ESKF. The last six
are the visual anchor from ADR-0001.

### Prediction

Standard error-state IMU propagation with a 21x21 transition matrix. The
anchor states are constant in the body frame and therefore carry no process
noise by default. Optional drift terms
(`anchor_pos_drift_sigma_m_s`, `anchor_rot_drift_sigma_deg_s`) exist but
default to `0.0`; see ADR-0003 for why they are not the fix.

### Visual update

A relative visual measurement is expressed in the previous camera frame:

```
R_rel = R_prev^T R_cur
t_rel = R_prev^T (p_cur - p_prev)
```

This is not a measurement of world position. It constrains the constant
body-frame offset `c_t`. The Jacobians encode that distinction:

| Block | Jacobian | Rationale |
|---|---|---|
| rotation | `H_theta = R_rel_pred` | the increment is conjugated into the previous body frame |
| anchor rotation | `H_ct = -R_rel_pred` | the anchor error enters with the opposite sense, same frame |
| translation | `H_p = R_prev^T`, `H_cp = -R_prev^T` | the same relative quantity constrains position and the anchor in opposite senses |

The asymmetry in signs is the whole point. `-R_rel_pred` with `+R_rel_pred` is
what makes the anchor absorb the measurement instead of the navigation state
collapsing.

Note that the rotation blocks are `R_rel_pred` and not the identity. The
identity is correct only in the special case `R_rel_pred == I`, because
`rot_log(Q Exp(v) Q^T) == Q v`: the conjugation identity rotates the increment
into the previous body frame, and that is the frame the residual is expressed
in. Getting this wrong is a frame error rather than a sign error, so it is
harder to spot and it stays small whenever the inter-frame rotation is small.

On the first accepted visual measurement the filter is *initialised*: the
anchor is set from the measurement, no residual is applied to the navigation
state, and the anchor covariance is seeded from the declared prior
(`anchor_pos_sigma_m`, `anchor_rot_sigma_deg`). Subsequent measurements
constrain the anchor normally.

### Covariance

Posterior covariance uses the Joseph form (ADR-0002):

```
P = G (I - K H) P (I - K H)^T + K R K^T
```

followed by the reset Jacobian `G`. The non-Joseph shortcut `(I - K H) P` is
not used anywhere; it is not guaranteed positive semidefinite in floating
point and was reachable in practice.

Anchor covariance is re-committed on `vision_keyframe_interval` visual
updates, which defaults to `1`. The prior is installed, and cross-covariance
with the navigation block is set to zero. That zeroing is the honest
conservative choice; a perfectly-correlated alternative was tested and
produces a degenerate covariance (ADR-0003).

### Gating

Visual updates are gated on their innovation. GNSS updates are gated
separately, and their accept/reject counts are reported as a first-class
metric — in the defect configuration, 46 of 101 GNSS updates were rejected
because the visual update had already collapsed the position covariance.
That coupling was the diagnostic that exposed the original bug, so the
counters are part of the public result, not debug output.

### FDIR

`fdir/` answers a question the residual gate cannot: not "is this update
implausible" but "has this sensor stopped producing usable data". Every
update is tested with a chi-square innovation gate before anything is
applied.

```
        y, S = H P H^T + R
                |
                v
        d_M^2 = y^T S^-1 y      via Cholesky; inf if S is not SPD
                |                or is conditioned past 1e12
                v
        d_M^2 <= chi2_{1-alpha, m}?
           /                    \
         yes                    no
          |                      |
      ACCEPTED            consecutive_rejections += 1
                                 |
                    +------------+------------+
                    |                         |
              < max_consecutive        >= max_consecutive
                    |                         |
         REJECTED_TRANSIENT          REJECTED_PERSISTENT
                                 -> SENSOR_FAULT: channel excluded
                                              |
                              consecutive_accepts >= auto_recovery_count
                                              |
                                    channel returns to ACCEPTED
```

A rejected update returns before the Kalman gain is formed: `P^+ = P^-`
and the state is untouched. The alternative — inflating `R` until the
innovation fits — is the failure ADR-0003 documents, where the filter ends
up confidently wrong rather than merely uncertain.

Three properties are load-bearing and each has a test named after it:

- **The false-alarm rate is stated, not chosen.** `alpha = 0.001` is the
  default, not the conventional 0.01, because 0.01 rejects 1% of healthy
  updates *by definition* — measured here at 13 of 1212 healthy fixes. See
  `gating.DEFAULT_CONFIDENCE`.
- **Rotation and translation are gated separately.** They arrive as two
  blocks of one transform, so a single `vision` channel would let the
  healthy half vouch for the broken one. At a 10 m translation step the
  translation channel faults and the rotation channel records nothing.
- **A fault clears.** A channel excluded by a 20-frame step is not a dead
  sensor. Recovery requires `auto_recovery_count` consecutive accepted
  updates, and the counter for "updates actually used" stops crediting
  whatever the gate refused.

The premise is a *calibrated* innovation covariance, and this filter is
not calibrated in exactly the configurations that matter — see the
benchmark note below and blocker B4.

## Evaluation

`eval/calibration.py` is the centre of the project.

- **NEES** — normalised estimation error squared,
  `e^T P^-1 e`, against a chi-square distribution with `n` degrees of
  freedom. A well-calibrated filter sits near the nominal value.
- **2-sigma coverage** — the fraction of steps where the true error falls
  inside the claimed 2-sigma ellipsoid. The most direct read on whether a
  downstream consumer can trust the output.
- **Calibration verdict** — over/underconfident classification with a Wilson
  interval on the coverage fraction, so a verdict is not declared from a
  handful of steps.
- **Conformal radius** — empirical coverage-preserving radius at a chosen
  confidence, which is what you would actually hand to a downstream planner.

`eval/statistics.py` implements exact integer-dof chi-square quantiles
directly, so the project has no SciPy dependency for its central claim
(S1).

`eval/metrics.py` provides trajectory-level metrics: ATE under several
alignment conventions, relative pose error, drift, and time-to-recovery.
Alignment convention matters and is always reported, never implied — an ATE
without its alignment is not a result.

## Rejected design: convex combination

A linear blend of GNSS and visual estimates, `T = T_gnss (w) inv(T_vis (1-w))`,
was implemented and measured. It gives a smooth trajectory and consistently
understates variance, because it ignores the correlation between the two
sources. A filter that agrees with this baseline on trajectory smoothness
while disagreeing on variance is telling you the variance is the hard part,
not the trajectory.

## Known limitation

Visual fusion is overconfident under GNSS denial; see ADR-0003. `navkit`
ships with `vision_enabled = False` for that reason. The fix is a pose graph
over visual keyframes, tracked in `ROADMAP.md` stage 3.

FDIR interacts with that limitation rather than being independent of it. In
`outage_visual`, the 15 s denial ends with the filter displaced and holding a
collapsed covariance, and the ADR-0005 gate rejected the returning GNSS fixes
at `t = 20.8 s` onwards — 51 of them — because a gate that trusts a
covariance of a few centimetres reads a healthy 3 m fix as an outlier. ATE
3.428 m without FDIR, 5.059 m with it. The gate was behaving as specified; the
specification assumed calibration the filter did not have. That was blocker B5.

ADR-0006 fixed it without touching the false-alarm rate. `FdirManager` keeps
the ADR-0005 gate as the first pass and adds a second one, reached only when a
per-channel NIS window (`fdir/nis_monitor.py`) reports a trailing run of
rejections *and* the channel was actually silent. It then inflates the GNSS
position block, recomputes `S' = S + H ΔP Hᵀ` — the covariance the estimator
will actually have, not an approximation of it — and re-gates with headroom. The
grant is bounded by a factor cap, by a drift rate per second of the channel's
longest single silence, and by one grant per episode. In `outage_visual` this
takes ATE 5.059 m to 2.541 m and rejections 51 to 5.

A channel streaming at 5 Hz has no silence, so it earns no budget and a
sustained spoof never becomes plausible: verified at 40 m and 100 m with zero
grants. Pinned by `test_adaptive_inflation_recovers_the_fixes_that_the_plain_gate_threw_away`
and `tests/test_nis_monitor.py`. The residual overconfidence is the unmodelled
anchor error above, which this does not touch.
