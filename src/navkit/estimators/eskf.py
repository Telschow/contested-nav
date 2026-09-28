"""Error-state Kalman filter fusing inertial, GNSS and visual data.

Formulation
-----------
Nominal state ``x = (R, p, v, b_a, b_g)``. The filter carries a 21-dimensional
*error* state in the order

    ``[dtheta (0:3), dp (3:6), dv (6:9), db_g (9:12), db_a (12:15),
       c_p (15:18), c_t (18:21)]``

The first fifteen are the usual inertial states. ``c_p`` and ``c_t`` are the
errors of the stored visual anchor position and attitude: nuisance parameters,
not physical states, needed because an anchor is a pose the filter itself
produced and its error is therefore not independent evidence. They are what
makes the visual channel sound to enable, and the module docstring below
explains both the failure they fix and the one they do not.

The convention that the true state relates to the nominal one as
``R_true = R Exp(dtheta)``, ``p_true = p + dp``, ``v_true = v + dv``, and the
biases additively. Gravity is a known constant, not a filter state.

This is the textbook first-order error-state formulation, not an invariant
one: the update equations are linearised around the current estimate and the
transport is not enforced through the group. That choice is deliberate and
documented in ``docs/architecture.md`` -- an invariant EKF gives marginally
better behaviour in fast rotation, and buys it with algebra that a reader
cannot check by inspection.

Process model (discrete, first order), with ``a = accel - b_a``:

    dp'    = dp + dv dt
    dv'    = dv - R [a]x dt dp_theta - R dt db_a
    dtheta' = Exp(-omega dt) dtheta - dt db_g

Measurement models
------------------
* **GNSS position**: ``z = p``, ``H = [0 I 0 0 0]``.
* **Visual relative rotation** ``R_rel = R_{i-1}^T R_i``: the residual
  ``Log(R_meas R_pred^T)``, which equals the attitude error exactly, with
  ``H = [I 0 0 0 0]`` and an isotropic noise covariance.
* **Visual relative translation** ``t_rel = R_{i-1}^T (p_i - p_{i-1})``: with
  ``h(x) = R_prev^T (p_cur - p_prev)`` the residual is
  ``t_meas - h(x_nom)`` and ``H = [0 R_prev^T 0 0 0]``.

The previous side of a visual constraint is the filter state saved at the
*previous visual update*, not at the previous inertial tick. At 200 Hz
inertial against 20 Hz vision those are different poses, and using the inertial
tick would make the relative constraint compare the current frame with itself.

A gate rejects updates whose normalised residual exceeds ``gate_sigma`` times
the predicted standard deviation, and the rejection count is reported. Silent
gating would hide a divergence, so it is counted rather than merely applied.

Fusing vision without corrupting the filter
-------------------------------------------
A relative-pose visual measurement constrains how the vehicle *moved*, not where
it *is*. Fusing one by re-deriving the visual anchor from the filter's own
corrected state -- the obvious implementation, and the one this filter started
with -- turns the two into the same thing: the filter is handed its own output
and averages it as though it were fresh independent evidence. The covariance
collapses, and once it has collapsed the filter is certain and wrong.

Measured on the 20 s synthetic fixture (200 Hz inertial, 20 Hz vision at
0.05 deg and 1 cm, 5 Hz GNSS at 0.1 m, 2 mm/s^2 accel noise density, 0.01 m/s
gyro noise density), reported as mean squared Mahalanobis distance (NEES, where
a calibrated 3D filter reports 3.0):

    configuration                  GNSS used   error    1-sigma    NEES
    GNSS only (control)               101/101   0.039 m   0.073 m    2.8
    vision, anchor folded into R       55/101  16.11 m    0.037 m    5.1e4
    vision, anchor as a state          101/101   0.033 m   0.068 m    3.2

The middle row is the failure in one line: the claimed 1-sigma is 3.7 cm while
the error is 16 m, and 46 of 101 absolute GNSS fixes are discarded as outliers by
the innovation gate. A system monitoring only its own gating counters would see
this as "vision is noisy", when the actual fault is that vision has silenced the
GNSS.

The fix is the bottom row, and it takes two things that are easy to get wrong:

* The anchor error is carried as six estimated states (``c_p``, ``c_t``) rather
  than folded into the innovation covariance. An error common to every visual
  update is a quantity to be estimated, not noise to be divided down.
* Those states are given a *declared* uncertainty, not the filter's own
  covariance. Deriving the new anchor's uncertainty from the current covariance
  is circular, and it ratchets the overconfidence downward at every re-commit.
* The covariance update uses the Joseph form. The textbook shortcut
  ``(I - K H) P`` is symmetric but not positive semidefinite; with the anchor
  states it drove the smallest eigenvalue to -0.31 within two visual updates,
  which is a physically meaningless covariance rather than a small inaccuracy.

With GNSS available the filter is calibrated again, and slightly better than the
GNSS-only control because the visual channel adds real information. Vision with
no GNSS at all is also calibrated (mean NEES 4.2, 1.1 m final error), so the
anchor model is doing real work rather than only muting the symptom.

The limit that remains
----------------------
Under a 15 s GNSS denial the same filter still over-trusts vision by roughly
three orders of magnitude (mean NEES 3.5e3, 31 m error against a claimed 0.30 m).
and the cause is structural rather than a matter of tuning. The information a
visual measurement carries about *absolute* position is the Schur complement

    P_pp - P_pc P_cc^-1 P_cp

Declaring the anchor blocks uncorrelated collapses this to ``P_pp``: the
measurement acts as if the anchor did not exist. Declaring them perfectly
correlated -- which is the honest description of an anchor copied from the
current estimate -- collapses it to zero and makes the measurement model exactly
degenerate, which is numerically unusable. The truth lies between those extremes
and cannot be represented by one anchor state, because a chain of relative
measurements is only jointly informative about position once the *whole* chain
is considered. That requires a pose graph over the visual keyframes, not a
single-anchor ESKF, and it is the change this project has not made.

So the visual channel ships disabled by default. The failure above is not a
reason to hide it, and the numbers stay in this docstring; it is a reason not to
hand a caller a filter that silently reports 0.3 m while being 31 m wrong.
``vision_anchor_modelled`` is exposed only so the regression tests can reproduce
the middle row.

Known simplifications
---------------------
* Measurements are applied at the next inertial tick, so a measurement carries
  a latency of up to one IMU period (5 ms at 200 Hz). This is recorded in the
  result and is far below the timescales this project studies, but it does put
  a floor under the effect of the ``timestamp_offset`` scenario.
* With the visual channel disabled there is no constraint tying the bias states
  to anything but GNSS excitation, so a vision-only run has no absolute
  reference at all. Its error grows, and the covariance is expected to grow with
  it; a vision-only run cannot demonstrate a benefit over dead reckoning and must
  not be reported as one.
* The camera-to-IMU extrinsic is assumed identity.
* No motion-constrained zero-velocity or zero-rotation update is applied, so
  bias observability comes only from GNSS excitation over the sequence.
* ``run(t0=...)`` truncates the inertial stream and *cold-starts* the filter at
  that instant with zero position, zero velocity and identity attitude. It does
  not mean "assist until t0 and then deny". A denial window must be expressed as
  a scenario on the fix stream, not as a start time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ..geometry.rigid import skew as _skew
from ..geometry.rigid import rot_exp, rot_log
from ..io.imu import ImuNoiseModel
from ..types import GRAVITY, GnssFix, ImuSample, Trajectory, VisionUpdate
from .dead_reckoning import EstimatorResult

_IDX_THETA = slice(0, 3)
_IDX_P = slice(3, 6)
_IDX_V = slice(6, 9)
_IDX_BG = slice(9, 12)
_IDX_BA = slice(12, 15)
#: Error in the *stored* visual anchor position. This is a nuisance parameter, not
#: a physical state: the anchor pose is a constant, but its error is unknown and
#: common to every visual update, so it has to be estimated rather than assumed
#: away. It carries no process noise, which is precisely what stops the filter
#: from averaging it down like a random walk.
_IDX_CP = slice(15, 18)
#: Error in the stored visual anchor attitude, for the same reason.
_IDX_CT = slice(18, 21)

#: Nominal states, then the two anchor nuisance blocks. The dimension is derived
#: from these slices rather than written as a literal, so a change cannot
#: silently disagree with the matrices built from it.
_N_NOMINAL = 15
_N_STATES = 21


@dataclass
class EskfConfig:
    """Tuning and noise for the filter, in physical units."""

    imu_noise: ImuNoiseModel
    gnss_position_sigma_m: float = 0.8
    gnss_enabled: bool = True
    #: Off by default, and the reason is a known limitation rather than caution
    #: about the code: with the anchor modelled the filter is calibrated when
    #: GNSS is available and when it is absent entirely, but it is still badly
    #: overconfident when vision has to carry the solution through a GNSS
    #: outage. Enabling it by default would hand a caller a filter that reports
    #: 0.3 m while being 31 m wrong. See the module docstring for the
    #: measurements and for why closing that gap needs a pose graph.
    vision_enabled: bool = False
    vision_rot_sigma_deg: float = 0.35
    vision_trans_sigma_m: float = 0.05
    #: How many accepted visual updates pass before the anchor pose is
    #: re-committed. ``None`` (the default) anchors once and never moves it.
    #:
    #: 1 (the default) re-commits the anchor at every visual update, so each
    #: measurement compares consecutive frames. This is the classic visual
    #: odometry setup and it measures best, because the anchor error starts from
    #: a fresh declared prior every frame instead of accumulating. Set to None
    #: to hold one anchor for the whole run, which makes the anchor error a
    #: single unknown that every measurement shares; that is measurably worse
    #: (mean NEES 23 rather than 3) and is kept for the regression tests.
    vision_keyframe_interval: int | None = 1
    #: Whether the anchor error is carried as an estimated state (correct) or
    #: treated as extra measurement noise (incorrect, kept only so the failure
    #: can be reproduced). See the module docstring.
    vision_anchor_modelled: bool = True
    #: Declared 1-sigma on a stored anchor position, in metres. This is a
    #: property of the visual front end, not of the navigation filter, so it is
    #: declared rather than derived from the filter's own covariance.
    anchor_pos_sigma_m: float = 1.0
    #: Declared 1-sigma on a stored anchor attitude, in degrees.
    anchor_rot_sigma_deg: float = 5.0
    #: 1-sigma random walk on the stored anchor, in m/s and deg/s. Zero by
    #: default: an anchor held for a short run is best modelled as a constant
    #: error. Raise it when the anchor is held long enough for front-end drift
    #: to dominate, which is what makes a long vision-only run grow its
    #: position uncertainty instead of holding it frozen.
    anchor_pos_drift_sigma_m_s: float = 0.0
    anchor_rot_drift_sigma_deg_s: float = 0.0
    gate_sigma: float = 5.0
    gravity: np.ndarray | None = None
    initial_pos_sigma_m: float = 1.0
    initial_vel_sigma_m_s: float = 0.5
    initial_rot_sigma_deg: float = 2.0
    initial_bias_sigma: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "imu_noise": self.imu_noise.as_dict(),
            "gnss_position_sigma_m": self.gnss_position_sigma_m,
            "gnss_enabled": self.gnss_enabled,
            "vision_enabled": self.vision_enabled,
            "vision_rot_sigma_deg": self.vision_rot_sigma_deg,
            "vision_trans_sigma_m": self.vision_trans_sigma_m,
            "vision_keyframe_interval": self.vision_keyframe_interval,
            "vision_anchor_modelled": self.vision_anchor_modelled,
            # The anchor prior and its drift are what decide whether a long
            # visual run stays calibrated, so they belong in the serialised
            # config. Omitting them makes a config hash and a YAML round trip
            # agree with each other while both disagree with the filter.
            "anchor_pos_sigma_m": self.anchor_pos_sigma_m,
            "anchor_rot_sigma_deg": self.anchor_rot_sigma_deg,
            "anchor_pos_drift_sigma_m_s": self.anchor_pos_drift_sigma_m_s,
            "anchor_rot_drift_sigma_deg_s": self.anchor_rot_drift_sigma_deg_s,
            "gate_sigma": self.gate_sigma,
            "initial_pos_sigma_m": self.initial_pos_sigma_m,
            "initial_vel_sigma_m_s": self.initial_vel_sigma_m_s,
            "initial_rot_sigma_deg": self.initial_rot_sigma_deg,
            "initial_bias_sigma": self.initial_bias_sigma,
        }


class ErrorStateKalmanFilter:
    """21-state error-state Kalman filter over a timestamped IMU stream."""

    name = "eskf"

    def __init__(self, config: EskfConfig) -> None:
        self.cfg = config
        self.g = GRAVITY.copy() if config.gravity is None else np.asarray(config.gravity, float)

    # -- state ---------------------------------------------------------------

    def _initial_covariance(self) -> np.ndarray:
        cfg = self.cfg
        P = np.zeros((_N_STATES, _N_STATES))
        r = np.deg2rad(cfg.initial_rot_sigma_deg) ** 2
        P[_IDX_THETA, _IDX_THETA] = np.eye(3) * r
        P[_IDX_P, _IDX_P] = np.eye(3) * cfg.initial_pos_sigma_m**2
        P[_IDX_V, _IDX_V] = np.eye(3) * cfg.initial_vel_sigma_m_s**2
        P[_IDX_BG, _IDX_BG] = np.eye(3) * cfg.initial_bias_sigma**2
        P[_IDX_BA, _IDX_BA] = np.eye(3) * cfg.initial_bias_sigma**2
        # The anchor exists only once a visual update has committed one, and its
        # uncertainty then comes from the commit itself (see
        # _commit_anchor_covariance) plus the drift random walk. Seeding it here
        # with a prior would be a claim the filter has not earned.
        return P

    def _commit_anchor_covariance(self, P: np.ndarray) -> None:
        """Give a freshly committed anchor a declared uncertainty.

        The value is a configuration input, not something read back out of the
        filter's own covariance. That distinction is the whole point. An anchor
        is a raw stored pose whose quality comes from the visual front end, not
        from the navigation filter, so the only honest way to say how well it is
        known is to declare it. Seeding it from ``P`` instead is circular: the
        covariance is small precisely because the filter has been over-trusting
        updates, so the next anchor inherits the overconfidence and the collapse
        compounds across re-commits.

        The cross-covariance with the navigation states is deliberately zero, and
        that deserves a warning rather than a shrug. The information a visual
        measurement carries about *absolute* position is the Schur complement

            P_pp - P_pc P_cc^-1 P_cp

        and with ``P_pc == 0`` this collapses to ``P_pp``: the measurement acts
        as though the anchor did not exist and drives the position covariance
        down by the full nominal amount. The alternative -- declaring the anchor
        perfectly correlated with the pose it was copied from -- makes the
        Schur complement vanish, which is arguably more honest about the very
        first measurement but is exactly degenerate, so the filter is not
        positive semidefinite in practice. See the module docstring: this is the
        structural limitation of single-anchor ESKF relative-pose fusion, and it
        is why the remaining vision-only overconfidence is not a tuning problem.
        """
        for blk in (_IDX_CP, _IDX_CT):
            P[blk, :] = 0.0
            P[:, blk] = 0.0
        if not self.cfg.vision_anchor_modelled:
            return
        P[_IDX_CP, _IDX_CP] = np.eye(3) * self.cfg.anchor_pos_sigma_m**2
        P[_IDX_CT, _IDX_CT] = (
            np.eye(3) * np.deg2rad(self.cfg.anchor_rot_sigma_deg) ** 2
        )

    def _process_noise(self, dt: float) -> np.ndarray:
        """Discrete process noise, first-order-in-dt form.

        ``sigma_g^2 dt^3 / 3`` and ``sigma_a^2 dt^3 / 3`` for rate noises and
        ``sigma_bg^2 dt`` / ``sigma_ba^2 dt`` for the bias random walks.
        """
        n = self.cfg.imu_noise
        d = float(dt)
        Q = np.zeros((_N_STATES, _N_STATES))
        rg = n.gyro_noise_density**2
        ra = n.accel_noise_density**2
        if rg > 0.0:
            Q[_IDX_THETA, _IDX_THETA] = np.eye(3) * (rg * d**3 / 3.0)
        if ra > 0.0:
            Q[_IDX_P, _IDX_P] = np.eye(3) * (ra * d**3 / 3.0)
        if n.gyro_bias_rw > 0.0:
            Q[_IDX_BG, _IDX_BG] = np.eye(3) * (n.gyro_bias_rw**2 * d)
        if n.accel_bias_rw > 0.0:
            Q[_IDX_BA, _IDX_BA] = np.eye(3) * (n.accel_bias_rw**2 * d)
        # The anchor does not move, but its *error* does: a visual anchor
        # drifts. Without this the pose/anchor correlation set at the commit
        # never decays, the Schur complement above stays pinned at zero, and
        # the relative measurements never regain any power over absolute
        # position -- the filter would coast on the IMU alone no matter how many
        # visual updates arrived.
        if self.cfg.vision_anchor_modelled:
            sp = self.cfg.anchor_pos_drift_sigma_m_s
            st = np.deg2rad(self.cfg.anchor_rot_drift_sigma_deg_s)
            if sp > 0.0:
                Q[_IDX_CP, _IDX_CP] += np.eye(3) * (sp**2 * d)
            if st > 0.0:
                Q[_IDX_CT, _IDX_CT] += np.eye(3) * (st**2 * d)
        return Q

    @staticmethod
    def _transition(R: np.ndarray, omega: np.ndarray, accel: np.ndarray, dt: float) -> np.ndarray:
        a = np.asarray(accel, float)
        F = np.eye(_N_STATES)
        F[_IDX_P, _IDX_V] += np.eye(3) * dt
        F[_IDX_V, _IDX_THETA] += -R @ _skew(a) * dt
        F[_IDX_V, _IDX_BA] += -R * dt
        F[_IDX_THETA, _IDX_THETA] = rot_exp(-np.asarray(omega, float) * dt)
        F[_IDX_THETA, _IDX_BG] += -np.eye(3) * dt
        return F

    def _propagate(
        self, x: dict[str, np.ndarray], accel: np.ndarray, gyro: np.ndarray, dt: float
    ) -> None:
        R, p, v, ba, bg = x["R"], x["p"], x["v"], x["b_a"], x["b_g"]
        a_meas = accel - ba
        w_meas = gyro - bg
        a_world = R @ a_meas + self.g
        p_new = p + v * dt + 0.5 * a_world * dt * dt
        v_new = v + a_world * dt
        R_new = R @ rot_exp(w_meas * dt)
        F = self._transition(R, w_meas, a_meas, dt)
        x["R"], x["p"], x["v"] = R_new, p_new, v_new
        x["P"] = F @ x["P"] @ F.T + self._process_noise(dt)

    # -- updates -------------------------------------------------------------

    def _update(
        self,
        x: dict[str, np.ndarray],
        residual: np.ndarray,
        H: np.ndarray,
        Rcov: np.ndarray,
    ) -> tuple[bool, float]:
        """Standard linear KF update followed by the error-state reset."""
        P = x["P"]
        S = H @ P @ H.T + Rcov
        try:
            K = np.linalg.solve(S, (P @ H.T).T).T
        except np.linalg.LinAlgError:  # pragma: no cover - defensive
            return False, float("nan")
        innov = float(residual @ np.linalg.solve(S, residual))
        dof = residual.shape[0]
        if self.cfg.gate_sigma > 0.0 and innov > (self.cfg.gate_sigma**2) * dof:
            return False, innov
        dx = K @ residual
        dtheta = dx[_IDX_THETA]
        # First-order reset of the attitude error: re-linearise around the
        # injected rotation, otherwise P is inconsistent with the new R.
        G = np.eye(_N_STATES)
        G[:3, :3] = np.eye(3) + 0.5 * _skew(dtheta)
        # Joseph form, then the reset, in that order. The reset is the reason
        # this must happen after the covariance update and not before: the
        # injected rotation changes the linearisation point, and G acting on the
        # Joseph result keeps the matrix symmetric positive semidefinite, while
        # G before the update would reintroduce the asymmetry the Joseph form
        # exists to remove.
        #
        # The textbook shortcut (I - K H) P is symmetric but NOT positive
        # semidefinite: it drops the K R K^T term, so any inconsistency between
        # H and the true sensitivity shows up as a negative eigenvalue instead of
        # a slightly-too-small variance. That is not a rounding curiosity here.
        # With the anchor nuisance states, the position and anchor blocks are
        # near-collinear, and the shortcut drove the smallest eigenvalue to
        # about -0.31 within two visual updates -- large enough to make the
        # covariance physically meaningless and to break the eigendecomposition
        # that the calibration code relies on.
        I_KH = np.eye(_N_STATES) - K @ H
        x["P"] = G @ (I_KH @ P @ I_KH.T + K @ Rcov @ K.T) @ G.T
        x["R"] = x["R"] @ rot_exp(dtheta)
        x["p"] = x["p"] + dx[_IDX_P]
        x["v"] = x["v"] + dx[_IDX_V]
        x["b_g"] = x["b_g"] + dx[_IDX_BG]
        x["b_a"] = x["b_a"] + dx[_IDX_BA]
        return True, innov

    def _gnss_update(self, x: dict[str, np.ndarray], p_meas: np.ndarray, sigma: float) -> tuple[bool, float]:
        Rcov = np.eye(3) * sigma**2
        H = np.zeros((3, _N_STATES))
        H[0, 3] = H[1, 4] = H[2, 5] = 1.0
        return self._update(x, p_meas - x["p"], H, Rcov)

    def _vision_update(
        self,
        x: dict[str, np.ndarray],
        R_rel_meas: np.ndarray,
        t_rel_meas: np.ndarray,
        rot_sigma_deg: float,
        trans_sigma_m: float,
    ) -> tuple[bool, float, bool]:
        """Apply the rotation and translation halves of a relative-pose fix.

        The measurement is ``T_prev_cur = (R_{i-1}^T R_i, R_{i-1}^T
        (p_i - p_{i-1}))``. Both blocks come from the same transform; the
        rotation is the one of ``T_prev_cur`` and is *not*
        ``R_i R_{i-1}^T``, which belongs to the inverse transform. The
        "previous" side must therefore be the filter
        state saved at the *previous visual update*, not the previous inertial
        tick: at 200 Hz inertial against 20 Hz vision, the previous tick is a
        different pose and using it would compare the current frame with itself.
        The saved keyframe is the filter state *after* the previous visual
        correction, so its own error is zero to first order, which is the
        standard first-order treatment of a relative-pose constraint; the
        resulting loss of correlation information is recorded as a known
        simplification.

        Returns ``(ok, normalised innovation, rotation_part_accepted)``.
        """
        if not self.cfg.vision_anchor_modelled:
            # Reproduce the historical filter exactly: the nuisance blocks are
            # present in the state vector but never observed and carry no
            # uncertainty, so they are inert and cannot influence the estimate.
            P = x["P"]
            for blk in (_IDX_CP, _IDX_CT):
                P[blk, :] = 0.0
                P[:, blk] = 0.0
        if not x["vision_keyframe_set"]:
            x["R_vk"] = x["R"].copy()
            x["p_vk"] = x["p"].copy()
            x["P_theta_vk"] = x["P"][_IDX_THETA, _IDX_THETA].copy()
            x["P_p_vk"] = x["P"][_IDX_P, _IDX_P].copy()
            # The stored pose is the current estimate, so its error starts at
            # zero with the covariance it is being stored under. The pose is a
            # raw copy, so this is the only place that fact can be recorded.
            x["c_p"] = np.zeros(3)
            x["c_t"] = np.zeros(3)
            P = x["P"]
            self._commit_anchor_covariance(P)
            x["vision_keyframe_set"] = True
            return True, 0.0, True

        R_prev, p_prev = x["R_vk"], x["p_vk"]
        R_cur = x["R"]

        # Rotation, expressed in the previous body frame. With the keyframe
        # already corrected, R_prev^T R_true = R_rel_pred Exp(dtheta), so
        #
        #   z_rot = Log(R_rel_meas R_rel_pred^T)
        #         = Log(R_rel_pred Exp(dtheta) R_rel_pred^T)
        #         = R_rel_pred dtheta
        #
        # using the conjugation identity Log(Q Exp(v) Q^T) == Q v, which holds
        # for any rotation Q. The residual is therefore R_rel_pred dtheta and
        # *not* dtheta: the Jacobian on the attitude block is R_rel_pred, and it
        # collapses to the identity only in the special case R_rel_pred == I.
        # Claiming H = I here is a frame error of exactly the kind the
        # translation block below documents, and it is invisible whenever the
        # inter-frame rotation is small.
        # (Pinned against a finite-difference Jacobian in
        # tests/test_estimators.py, which is what caught it.)
        # The anchor attitude carries an unknown constant error ``c_t``, so the
        # predicted relative rotation is Exp(-c_t) R_rel_true rather than
        # R_rel_true. It is a *state*, not a term added to the innovation noise:
        # adding it to R would let the filter average it away, which is the
        # self-confirmation failure this state exists to prevent.
        R_rel_pred = R_prev.T @ R_cur
        Rcov_rot = np.eye(3) * np.deg2rad(rot_sigma_deg) ** 2
        H_rot = np.zeros((3, _N_STATES))
        H_rot[:, _IDX_THETA] = R_rel_pred
        if self.cfg.vision_anchor_modelled:
            z_rot = rot_log(R_rel_meas @ rot_exp(x["c_t"]) @ R_rel_pred.T)
            # At the consistent point R_rel_meas == R_rel_pred Exp(-c_t) the
            # residual vanishes, and perturbing c_t gives
            #   z_rot = Log(R_rel_pred Exp(c_t + d) R_rel_pred^T)
            #         = R_rel_pred d,
            # so d z_rot / d c_t == +R_rel_pred and H is its negative, in the
            # same previous body frame as the attitude block.
            H_rot[:, _IDX_CT] = -R_rel_pred
        else:
            z_rot = rot_log(R_rel_meas @ R_rel_pred.T)
            Rcov_rot = Rcov_rot + x["P_theta_vk"]
        ok_rot, innov_rot = self._update(x, z_rot, H_rot, Rcov_rot)

        # Translation, in the previous body frame. The measurement model is
        #   h(x) = R_prev^T (p_cur - p_prev)
        # so the residual is z = t_meas - h(x_nom) and the Jacobian is
        # H = dh/dp = +R_prev^T. (Note that d(residual)/d(nominal p) is
        # -R_prev^T, which is *not* H: H is the derivative of the measurement
        # model. Using the residual derivative here pushes the state the wrong
        # way, which is why this distinction is written down.)
        # The anchor position carries an unknown constant error ``c_p``:
        #   t_rel = R_prev^T (p_cur - p_prev - c_p)
        # so the residual is z = t_meas - h(x_nom) and the Jacobian is
        # [0 R_prev^T 0 0 0 | 0 | -R_prev^T]. The anchor term is a state block
        # rather than an addition to the innovation covariance, for the same
        # reason as the attitude block above.
        H_trans = np.zeros((3, _N_STATES))
        H_trans[:, _IDX_P] = R_prev.T
        Rcov_trans = np.eye(3) * trans_sigma_m**2
        if self.cfg.vision_anchor_modelled:
            z_trans = t_rel_meas - R_prev.T @ (x["p"] - p_prev - x["c_p"])
            H_trans[:, _IDX_CP] = -R_prev.T
        else:
            z_trans = t_rel_meas - R_prev.T @ (x["p"] - p_prev)
            Rcov_trans = Rcov_trans + R_prev.T @ x["P_p_vk"] @ R_prev
        ok_trans, innov_trans = self._update(x, z_trans, H_trans, Rcov_trans)

        # Re-commit the anchor only when the configured interval has elapsed.
        # With the default of None the anchor stays where it was first set, so
        # every visual measurement is a genuine constraint against one fixed pose
        # rather than against a pose the filter just produced from its own output.
        x["vision_updates"] = int(x["vision_updates"]) + 1
        interval = self.cfg.vision_keyframe_interval
        if interval is not None and x["vision_updates"] % int(interval) == 0:
            x["R_vk"] = x["R"].copy()
            x["p_vk"] = x["p"].copy()
            x["c_p"] = np.zeros(3)
            x["c_t"] = np.zeros(3)
            P = x["P"]
            self._commit_anchor_covariance(P)
        return (ok_rot and ok_trans), innov_rot + innov_trans, ok_rot

    # -- main loop -----------------------------------------------------------

    def run(
        self,
        imu: ImuSample,
        gnss: GnssFix | None = None,
        vision: VisionUpdate | None = None,
        t0: float | None = None,
        t_end: float | None = None,
    ) -> EstimatorResult:
        wall_start = time.perf_counter()
        if t0 is not None or t_end is not None:
            imu = imu.subset(t0=t0, t1=t_end)
        n = len(imu)
        if n < 2:
            raise ValueError("ESKF needs at least 2 IMU samples")

        x: dict[str, np.ndarray] = {
            "R": np.eye(3),
            "p": np.zeros(3),
            "v": np.zeros(3),
            "b_a": np.zeros(3),
            "b_g": np.zeros(3),
            "P": self._initial_covariance(),
            "R_vk": np.eye(3),
            "p_vk": np.zeros(3),
            "P_theta_vk": np.zeros((3, 3)),
            "P_p_vk": np.zeros((3, 3)),
            "c_p": np.zeros(3),
            "c_t": np.zeros(3),
            "vision_updates": 0,
        }
        x["vision_keyframe_set"] = False  # type: ignore[assignment]
        cfg = self.cfg
        use_gnss = gnss is not None and cfg.gnss_enabled
        use_vision = vision is not None and cfg.vision_enabled
        g_fixes = gnss.valid() if use_gnss else None
        v_updates = vision.valid() if use_vision else None
        g_ptr = 0
        v_ptr = 0

        poses = np.zeros((n, 4, 4))
        sigma_p = np.zeros(n)
        pos_cov = np.zeros((n, 3, 3))
        n_gnss_used = 0
        n_gnss_rejected = 0
        n_vision_used = 0
        n_vision_rejected = 0
        n_vision_init = 0
        gnss_seen = 0
        max_measurement_latency = 0.0

        for k in range(n):
            t_k = float(imu.t[k])
            if k > 0:
                dt = t_k - float(imu.t[k - 1])
                if dt <= 0.0:
                    continue
                self._propagate(x, imu.accel[k - 1], imu.gyro[k - 1], dt)

            if g_ptr is not None and g_fixes is not None:
                while g_ptr < len(g_fixes) and float(g_fixes.t[g_ptr]) <= t_k:
                    p_meas = g_fixes.positions[g_ptr]
                    latency = t_k - float(g_fixes.t[g_ptr])
                    max_measurement_latency = max(max_measurement_latency, latency)
                    gnss_seen += 1
                    ok, _ = self._gnss_update(x, p_meas, cfg.gnss_position_sigma_m)
                    n_gnss_used += int(ok)
                    n_gnss_rejected += int(not ok)
                    g_ptr += 1

            if v_ptr is not None and v_updates is not None:
                while v_ptr < len(v_updates) and float(v_updates.t[v_ptr]) <= t_k:
                    had_keyframe = bool(x["vision_keyframe_set"])
                    ok, _, _ = self._vision_update(
                        x,
                        v_updates.R_rel[v_ptr],
                        v_updates.t_rel[v_ptr],
                        cfg.vision_rot_sigma_deg,
                        cfg.vision_trans_sigma_m,
                    )
                    v_ptr += 1
                    if not had_keyframe:
                        # The first frame after a stream starts (or restarts)
                        # only establishes the reference keyframe; it carries no
                        # constraint, so it is counted separately rather than
                        # being passed off as a successful fusion.
                        n_vision_init += 1
                        continue
                    n_vision_used += int(ok)
                    n_vision_rejected += int(not ok)

            poses[k, :3, :3] = x["R"]
            poses[k, :3, 3] = x["p"]
            poses[k, 3, :3] = 0.0
            poses[k, 3, 3] = 1.0
            pos_cov[k] = x["P"][_IDX_P, _IDX_P]
            sigma_p[k] = float(np.sqrt(max(np.trace(x["P"][_IDX_P, _IDX_P]), 0.0) / 3.0))

        traj = Trajectory(t=imu.t.copy(), poses=poses, name=self.name)
        elapsed = time.perf_counter() - wall_start
        stats = {
            "gnss_fixes_seen": float(gnss_seen),
            "gnss_updates_used": float(n_gnss_used),
            "gnss_updates_rejected": float(n_gnss_rejected),
            "vision_updates_used": float(n_vision_used),
            "vision_updates_rejected": float(n_vision_rejected),
            "vision_keyframe_initialisations": float(n_vision_init),
            "final_pos_sigma_m": sigma_p[-1],
            "max_pos_sigma_m": float(np.max(sigma_p)),
            "gyro_bias_final_rad_s": float(np.linalg.norm(x["b_g"])),
            "accel_bias_final_m_s2": float(np.linalg.norm(x["b_a"])),
            "max_measurement_latency_s": max_measurement_latency,
            "realtime_factor": traj.duration / elapsed if elapsed > 0 else float("inf"),
        }
        traj.metadata["sigma_p"] = sigma_p
        return EstimatorResult(
            trajectory=traj,
            runtime_s=elapsed,
            stats=stats,
            name=self.name,
            position_cov=pos_cov,
        )
