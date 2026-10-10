"""Measurement sources derived from a reference trajectory.

The framework replays a recorded trajectory and synthesises the measurements a
downstream estimator would receive. Two generators:

``gnss_fixes``
    Samples the reference position at a configured rate and adds position
    noise. Optionally adds a slowly varying common-mode bias, which is a
    stand-in for multipath or a biased correction stream. It is explicitly a
    *surrogate*: real multipath depends on satellite geometry and the
    environment in ways this cannot represent, and the flag
    ``multipath_is_surrogate`` records that.

``visual_updates``
    Produces the relative-pose stream a visual front end would emit,
    ``T_cur_prev``, from consecutive reference poses, plus noise. The
    convention matches the output of a standard two-frame relative pose
    estimator.

Both generators are seeded. Given the same seed and the same reference
trajectory they produce bit-identical output, which is what makes a scenario
comparison a controlled experiment rather than a anecdote.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry.rigid import rot_exp, rot_log
from ..io.imu import make_time_grid, resample
from ..types import GnssFix, Trajectory, VisionUpdate, interpolate_trajectory


@dataclass
class GnssConfig:
    """GNSS measurement model, in metres and hertz."""

    enabled: bool = True
    rate_hz: float = 5.0
    sigma_m: float = 0.8
    # Slow common-mode position bias, modelled as a first-order Gauss-Markov
    # process with correlation time `multipath_tau_s`. Zero disables it.
    multipath_sigma_m: float = 0.0
    multipath_tau_s: float = 30.0
    seed: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "rate_hz": self.rate_hz,
            "sigma_m": self.sigma_m,
            "multipath_sigma_m": self.multipath_sigma_m,
            "multipath_tau_s": self.multipath_tau_s,
            "seed": self.seed,
        }


@dataclass
class VisionConfig:
    """Visual front end surrogate, in degrees, metres and hertz."""

    enabled: bool = True
    rate_hz: float = 20.0
    rot_sigma_deg: float = 0.35
    trans_sigma_m: float = 0.05
    # Multiplies rot_sigma_deg / trans_sigma_m. Image degradation is applied by
    # inflating these; see docs/limitations.md for why this is a surrogate and
    # not a rendering-based model.
    noise_multiplier: float = 1.0
    seed: int = 0
    # After frames are dropped, make each delivered measurement relative to the last *delivered* frame, as a
    # front end tracking against its last keyframe would report. Off by default: the generator otherwise
    # measures against the immediately preceding grid frame even when that frame was dropped, so a filter
    # that compares with its last received frame is handed a measurement of a different transform.
    rereference: bool = False
    # Opt-in departures from an ideal front end, for stress tests. All off by default. The surrogate otherwise
    # draws independent, Gaussian, unbiased errors, which a real front end does not.
    #
    # ``noise_corr_s``: correlation time of the per-measurement errors. The marginal spread is unchanged; the
    # errors become correlated from frame to frame (an AR(1) filter), as they are when consecutive frames share
    # features. ``outlier_fraction``: the share of frames whose error is multiplied by ``outlier_scale``, as
    # with a wrong feature match. ``scale_sigma``: a fractional error on the translation scale that drifts
    # slowly (a Gauss-Markov process with correlation time ``scale_tau_s``), as monocular scale does.
    noise_corr_s: float = 0.0
    outlier_fraction: float = 0.0
    outlier_scale: float = 20.0
    scale_sigma: float = 0.0
    scale_tau_s: float = 30.0

    def stress(self) -> bool:
        return self.noise_corr_s > 0.0 or self.outlier_fraction > 0.0 or self.scale_sigma > 0.0

    def as_dict(self) -> dict[str, object]:
        base: dict[str, object] = {
            "enabled": self.enabled,
            "rate_hz": self.rate_hz,
            "rot_sigma_deg": self.rot_sigma_deg,
            "trans_sigma_m": self.trans_sigma_m,
            "noise_multiplier": self.noise_multiplier,
            "seed": self.seed,
            "rereference": self.rereference,
        }
        if self.stress():
            # Only when used, so the serialised scenario (and its hash) of every existing result is unchanged.
            base.update(
                {
                    "noise_corr_s": self.noise_corr_s,
                    "outlier_fraction": self.outlier_fraction,
                    "outlier_scale": self.outlier_scale,
                    "scale_sigma": self.scale_sigma,
                    "scale_tau_s": self.scale_tau_s,
                }
            )
        return base


#: The keys of ``VisionConfig`` that ``as_dict`` leaves out unless one of them is used.
VISION_STRESS_KEYS = ("noise_corr_s", "outlier_fraction", "outlier_scale", "scale_sigma", "scale_tau_s")


def gauss_markov(n: int, dt: float, sigma: float, tau: float, rng: np.random.Generator) -> np.ndarray:
    """First-order Gauss-Markov sequence with stationary std ``sigma``.

    ``tau`` is the correlation time. ``sigma == 0`` gives an all-zero sequence.
    """
    if sigma == 0.0 or n == 0:
        return np.zeros(n)
    if tau <= 0.0:
        raise ValueError(f"multipath_tau_s must be positive, got {tau}")
    a = float(np.exp(-dt / tau))
    s = float(sigma * np.sqrt(max(1.0 - a * a, 0.0)))
    out = np.empty(n)
    out[0] = rng.standard_normal() * sigma
    noise = rng.standard_normal(n - 1) * s
    for i in range(1, n):
        out[i] = a * out[i - 1] + noise[i - 1]
    return out


def gnss_fixes(reference: Trajectory, cfg: GnssConfig) -> GnssFix:
    """Synthesise a GNSS position-fix stream from a reference trajectory."""
    t0, t1 = float(reference.t[0]), float(reference.t[-1])
    if not cfg.enabled or cfg.rate_hz <= 0.0:
        # Still emit the grid, fully marked unavailable, so that downstream
        # logging of "no GNSS at all" is uniform with the outage case.
        t = np.array([t0, t1]) if t1 > t0 else np.array([t0])
        return GnssFix(
            t=t,
            positions=np.zeros((len(t), 3)),
            cov=np.zeros((len(t), 3)),
            available=np.zeros(len(t), dtype=bool),
            name="gnss_disabled",
        )

    t = make_time_grid(t0, t1, cfg.rate_hz)
    pos = resample(reference.t, reference.positions, t)
    dt = float(np.mean(np.diff(t))) if len(t) > 1 else 1.0
    rng = np.random.default_rng(cfg.seed)

    common = np.empty((len(t), 3))
    for k in range(3):
        common[:, k] = gauss_markov(len(t), dt, cfg.multipath_sigma_m, cfg.multipath_tau_s, rng)
    white = rng.standard_normal((len(t), 3)) * cfg.sigma_m
    measured = pos + common + white
    return GnssFix(
        t=t,
        positions=measured,
        cov=np.tile(np.full(3, cfg.sigma_m**2), (len(t), 1)),
        available=np.ones(len(t), dtype=bool),
        name="gnss",
    )


def visual_updates(reference: Trajectory, cfg: VisionConfig) -> VisionUpdate:
    """Synthesise a stream of relative-pose measurements between frames.

    For consecutive sampled poses this emits, for each current frame ``i``, the
    two blocks of the single transform ``T_prev_cur = T_{i-1}^{-1} T_i``:

    * ``R_rel[i] = R_{i-1}^T R_i`` -- current-frame axes in the previous frame;
    * ``t_rel[i] = R_{i-1}^T (p_i - p_{i-1})`` -- current origin in the previous
      frame.

    ``R_rel`` is the rotation of ``T_prev_cur`` and must not be confused with
    ``R_i R_{i-1}^T``, which is the rotation of the *inverse* transform
    ``T_i^{-1} T_{i-1}``. Mixing the two makes the rotation and translation
    blocks mutually inconsistent, and the resulting measurement stream does not
    telescope: chaining it does not reproduce the trajectory. This is what a
    two-frame relative pose front end outputs. The camera-to-IMU extrinsic is
    assumed identity; a real system must transform both parts into the IMU frame
    before fusing them, and this assumption is one of the recorded limitations.

    Poses are resampled with SLERP on rotation, not by linear interpolation of
    matrix entries, so the resampled rotations stay orthonormal.
    """
    t0, t1 = float(reference.t[0]), float(reference.t[-1])
    if not cfg.enabled or cfg.rate_hz <= 0.0 or len(reference) < 2:
        t = np.array([t0, t1]) if t1 > t0 else np.array([t0])
        n = len(t)
        return VisionUpdate(
            t=t,
            R_rel=np.tile(np.eye(3), (n, 1, 1)),
            t_rel=np.zeros((n, 3)),
            dropped=np.ones(n, dtype=bool),
            name="vision_disabled",
        )

    t = make_time_grid(t0, t1, cfg.rate_hz)
    sampled = interpolate_trajectory(reference, t)
    rng = np.random.default_rng(cfg.seed)

    n = len(t)
    R_rel = np.tile(np.eye(3), (n, 1, 1))
    t_rel = np.zeros((n, 3))
    rot_sigma = np.deg2rad(cfg.rot_sigma_deg) * cfg.noise_multiplier
    trans_sigma = cfg.trans_sigma_m * cfg.noise_multiplier
    poses = sampled.poses
    # The draws are made first, in the order the original loop made them, so a scenario without stress
    # reproduces its numbers exactly; the stress options then act on these arrays.
    rot_noise = np.zeros((n, 3))
    trans_noise = np.zeros((n, 3))
    for i in range(1, n):
        rot_noise[i] = rng.standard_normal(3) * rot_sigma
        # Noise on the baseline is applied along a random direction, which is a
        # crude but honest stand-in for depth ambiguity in monocular matching.
        direction = rng.standard_normal(3)
        nrm = float(np.linalg.norm(direction))
        direction = direction / nrm if nrm > 1e-9 else np.array([1.0, 0.0, 0.0])
        trans_noise[i] = direction * (rng.standard_normal() * trans_sigma)
    scale = np.zeros(n)
    if cfg.stress():
        rot_noise, trans_noise, scale = _stress(rot_noise, trans_noise, cfg)
    for i in range(1, n):
        R_prev, R_cur = poses[i - 1][:3, :3], poses[i][:3, :3]
        p_prev, p_cur = poses[i - 1][:3, 3], poses[i][:3, 3]
        R_rel_true = R_prev.T @ R_cur
        t_rel_true = R_prev.T @ (p_cur - p_prev)
        R_rel[i] = R_rel_true @ rot_exp(rot_noise[i])
        t_rel[i] = (
            t_rel_true * (1.0 + scale[i]) + trans_noise[i] if cfg.scale_sigma > 0.0 else t_rel_true + trans_noise[i]
        )
    # The first entry has no predecessor and is marked as not usable.
    dropped = np.zeros(n, dtype=bool)
    dropped[0] = True
    return VisionUpdate(
        t=t,
        R_rel=R_rel,
        t_rel=t_rel,
        rot_cov=np.tile(np.full(3, rot_sigma**2), (n, 1)),
        trans_cov=np.tile(np.full(3, trans_sigma**2), (n, 1)),
        dropped=dropped,
        name="vision",
    )


def _ar1(x: np.ndarray, a: float) -> np.ndarray:
    """First-order autoregressive filter along axis 0 that keeps each column's marginal variance."""
    out = np.empty_like(x)
    out[0] = x[0]
    gain = float(np.sqrt(max(1.0 - a * a, 0.0)))
    for k in range(1, len(x)):
        out[k] = a * out[k - 1] + gain * x[k]
    return out


def _stress(
    rot_noise: np.ndarray, trans_noise: np.ndarray, cfg: VisionConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply correlation, outliers and a drifting scale error to the independent draws.

    All of it comes from a stream of its own, so switching an option on does not move the original draws.
    """
    n = len(rot_noise)
    rng = np.random.default_rng(cfg.seed + 104729)
    dt = 1.0 / cfg.rate_hz
    if cfg.noise_corr_s > 0.0:
        a = float(np.exp(-dt / cfg.noise_corr_s))
        rot_noise, trans_noise = _ar1(rot_noise, a), _ar1(trans_noise, a)
    if cfg.outlier_fraction > 0.0:
        hit = rng.random(n) < cfg.outlier_fraction
        hit[0] = False
        rot_noise = np.where(hit[:, None], rot_noise * cfg.outlier_scale, rot_noise)
        trans_noise = np.where(hit[:, None], trans_noise * cfg.outlier_scale, trans_noise)
    scale = np.zeros(n)
    if cfg.scale_sigma > 0.0:
        a = float(np.exp(-dt / max(cfg.scale_tau_s, 1e-9)))
        scale = _ar1(rng.standard_normal((n, 1)), a)[:, 0] * cfg.scale_sigma
    return rot_noise, trans_noise, scale


def angular_rate_between(a: Trajectory, b: Trajectory) -> np.ndarray:
    """Body-frame angular rate between two trajectories on a common grid.

    Exposed for diagnostics: it is the cleanest way to check that a
    timestamp-offset scenario actually shifted the signal by the intended
    amount. Rotation is resampled with SLERP.
    """
    t = b.t
    Ra = interpolate_trajectory(a, t).rotations
    dt = np.diff(t).reshape(-1, 1)
    R_rel = np.einsum("nji,njk->nik", Ra[:-1], Ra[1:])
    w = np.array([rot_log(R) for R in R_rel]) / dt
    out = np.empty((len(t), 3))
    out[:-1] = w
    out[-1] = w[-1]
    return out


def rereference_visual_updates(
    vision: VisionUpdate, reference: Trajectory, cfg: VisionConfig, time_offset_s: float = 0.0
) -> VisionUpdate:
    """Make each delivered measurement relative to the last delivered frame.

    :func:`visual_updates` measures frame ``i`` against frame ``i - 1`` of the sampling grid. When frames
    are dropped, the next delivered measurement is still against the dropped one, so a filter that compares
    with the last frame it received is handed a measurement of a different transform. A front end that
    tracks against its last keyframe would report the transform from that keyframe. This re-derives such a
    measurement from the reference trajectory with a fresh draw of the same per-measurement noise, so its
    error does not grow with the gap. A measurement whose predecessor was delivered is left untouched.
    """
    n = len(vision)
    dropped = np.zeros(n, dtype=bool) if vision.dropped is None else vision.dropped.copy()
    if n < 2 or not dropped.any():
        return vision
    t_grid = vision.t - float(time_offset_s)
    poses = interpolate_trajectory(reference, t_grid).poses
    rng = np.random.default_rng(cfg.seed + 7919)  # a stream of its own: the original draws are not disturbed
    rot_sigma = np.deg2rad(cfg.rot_sigma_deg) * cfg.noise_multiplier
    trans_sigma = cfg.trans_sigma_m * cfg.noise_multiplier
    R_rel, t_rel = vision.R_rel.copy(), vision.t_rel.copy()
    previous: int | None = None
    for i in range(n):
        if dropped[i]:
            continue
        if previous is not None and previous != i - 1:
            R_j, R_i = poses[previous][:3, :3], poses[i][:3, :3]
            p_j, p_i = poses[previous][:3, 3], poses[i][:3, 3]
            R_rel[i] = (R_j.T @ R_i) @ rot_exp(rng.standard_normal(3) * rot_sigma)
            direction = rng.standard_normal(3)
            norm = float(np.linalg.norm(direction))
            direction = direction / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
            t_rel[i] = R_j.T @ (p_i - p_j) + direction * (rng.standard_normal() * trans_sigma)
        previous = i
    return VisionUpdate(
        t=vision.t.copy(),
        R_rel=R_rel,
        t_rel=t_rel,
        rot_cov=vision.rot_cov,
        trans_cov=vision.trans_cov,
        dropped=dropped,
        name=vision.name,
    )
