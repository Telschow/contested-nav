"""IMU readers and the ground-truth-derived inertial signal.

Two ways to obtain inertial data:

``read_euroc_imu``
    Parse a real ``mav0/imu0/data.csv``:
    ``#timestamp [ns], w_x, w_y, w_z, a_x, a_y, a_z`` in the body/IMU frame.

``synthesize_imu``
    Derive a *consistent* gyro and specific force from a ground-truth pose
    stream. This exists because the TUM VI ground truth that is published
    alongside the benchmark results is a pose stream, while an error-state
    filter needs angular rate and specific force.

    The synthesised signal is exact in the kinematic sense -- integrating it
    reproduces the source trajectory up to integration error -- but it is not
    an IMU measurement. It carries none of the real hardware effects:
    bias, scale factor error, temperature dependence, digitisation, or the
    effect of the finite bandwidth of the accelerometer. Treating it as a
    measurement without adding a noise model would be dishonest, so the
    degradation layer always applies a noise model to it, and
    ``docs/limitations.md`` records it as the single largest caveat of the
    session-1 results.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import numpy as np

from ..types import (
    GRAVITY,
    ImuSample,
    Trajectory,
    finite_difference,
    rot_log_batch,
)

_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


@dataclass
class ImuNoiseModel:
    """Continuous-time noise, stated in the units the filter consumes.

    ``gyro_noise_density`` / ``accel_noise_density`` are rad/s/sqrt(Hz) and
    m/s^2/sqrt(Hz), integrated over the step with sqrt(dt). ``*_bias_*`` are
    random walks in rad/s/sqrt(Hz) and m/s^2/sqrt(Hz), applied as an
    integrated random walk on the bias state.
    """

    gyro_noise_density: float = 0.0
    accel_noise_density: float = 0.0
    gyro_bias_rw: float = 0.0
    accel_bias_rw: float = 0.0
    gyro_bias_sigma: float = 0.0
    accel_bias_sigma: float = 0.0

    def scaled(self, factor: float) -> "ImuNoiseModel":
        """Multiply every noise term by ``factor`` (1.0 = unchanged)."""
        return ImuNoiseModel(
            gyro_noise_density=self.gyro_noise_density * factor,
            accel_noise_density=self.accel_noise_density * factor,
            gyro_bias_rw=self.gyro_bias_rw * factor,
            accel_bias_rw=self.accel_bias_rw * factor,
            gyro_bias_sigma=self.gyro_bias_sigma * factor,
            accel_bias_sigma=self.accel_bias_sigma * factor,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "gyro_noise_density": self.gyro_noise_density,
            "accel_noise_density": self.accel_noise_density,
            "gyro_bias_rw": self.gyro_bias_rw,
            "accel_bias_rw": self.accel_bias_rw,
            "gyro_bias_sigma": self.gyro_bias_sigma,
            "accel_bias_sigma": self.accel_bias_sigma,
        }


# Representative consumer IMU values, used as defaults. Order-of-magnitude
# figures for an industrial MEMS unit; they are configurable and the point of
# quoting them is that the experiment is stated in physical units.
DEFAULT_NOISE = ImuNoiseModel(
    gyro_noise_density=2.0e-4,
    accel_noise_density=2.0e-3,
    gyro_bias_rw=2.0e-6,
    accel_bias_rw=1.0e-4,
    gyro_bias_sigma=1.0e-5,
    accel_bias_sigma=2.0e-3,
)


def read_euroc_imu(path: str, name: str = "imu") -> ImuSample:
    """Read an EuRoC/TUM-VI ``data.csv`` IMU stream.

    Columns: ``timestamp [ns], w_RS_S_x, w_RS_S_y, w_RS_S_z, a_RS_S_x,
    a_RS_S_y, a_RS_S_z`` (optional trailing temperature column is ignored).
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    rows: list[list[float]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tok = re.split(r"[,\s]+", line)
            if not _NUM.fullmatch(tok[0]):
                continue  # header
            rows.append([float(x) for x in tok[:7]])
    if not rows:
        raise ValueError(f"{path}: no IMU rows found")
    a = np.asarray(rows, dtype=float)
    t = a[:, 0] / 1e9 if abs(a[0, 0]) > 1e12 else a[:, 0]
    order = np.argsort(t, kind="stable")
    return ImuSample(t=t[order], accel=a[order, 4:7], gyro=a[order, 1:4], name=name)


def resample(t_src: np.ndarray, x_src: np.ndarray, t_dst: np.ndarray) -> np.ndarray:
    """Linear interpolation of an ``(N, C)`` signal onto ``t_dst``."""
    t_src = np.asarray(t_src, float).reshape(-1)
    x_src = np.asarray(x_src, float).reshape(len(t_src), -1)
    t_dst = np.asarray(t_dst, float).reshape(-1)
    if t_src.shape[0] < 2:
        raise ValueError("need at least 2 source samples to resample")
    tq = np.clip(t_dst, t_src[0], t_src[-1])
    out = np.empty((len(tq), x_src.shape[1]))
    for c in range(x_src.shape[1]):
        out[:, c] = np.interp(tq, t_src, x_src[:, c])
    return out


def make_time_grid(t0: float, t1: float, rate_hz: float) -> np.ndarray:
    """Uniform time grid on ``[t0, t1]`` including both endpoints."""
    if rate_hz <= 0:
        raise ValueError(f"rate_hz must be positive, got {rate_hz}")
    n = int(np.floor((t1 - t0) * rate_hz)) + 1
    if n < 2:
        raise ValueError(f"time span {t1 - t0:.4f}s is too short for {rate_hz}Hz")
    return t0 + np.arange(n) / rate_hz


def synthesize_imu(
    traj: Trajectory,
    rate_hz: float = 200.0,
    name: str = "imu_from_gt",
) -> ImuSample:
    """Derive a consistent (noise-free) gyro and specific force from a pose stream.

    Derivation, with ``R = R_wb`` and ``p`` the world position:

    * ``omega_b`` from ``R[k+1] R_k^T = Exp(omega_b dt)``, so
      ``omega_b = Log(R[k+1] R_k^T) / dt``.
    * ``a_w = d2p/dt2`` from a second central difference.
    * specific force ``f_b = R^T (a_w - g_w)``, which gives ``f_b = (0, 0, -g)``
      for a body at rest in a world-Z-up frame.

    Differentiate first, resample second
    -------------------------------------
    When the trajectory rate differs from ``rate_hz``, the derivatives are
    computed on the *native* pose stream and the resulting smooth signals are
    then interpolated onto the requested grid. The order matters: resampling the
    positions first and differentiating afterwards turns position into a
    piecewise-linear function whose second derivative is a train of impulses, and
    the "specific force" that comes out is noise with the right units. Angular
    rate has the same problem for a different reason -- interpolating rotation
    matrices entry-wise does not preserve orthonormality.

    The first and last step use one-sided differences, which is where the
    derivative is least trustworthy; the caller should discard a short margin
    at both ends if it needs an honest result.
    """
    if rate_hz <= 0.0:
        raise ValueError(f"rate_hz must be positive, got {rate_hz}")
    if len(traj) < 4:
        raise ValueError("need at least 4 poses to differentiate twice")

    t_src = traj.t
    R_src = traj.rotations
    dt = np.diff(t_src).reshape(-1, 1)
    # R_k^T R_{k+1}: the increment expressed in the body frame of the *earlier*
    # pose, which is the frame the gyroscope measures in. (R_{k+1} R_k^T is the
    # same rotation in the world frame, and a different signal.)
    R_rel = np.einsum("nji,njk->nik", R_src[:-1], R_src[1:])
    omega = rot_log_batch(R_rel) / dt
    omega_src = np.empty((len(traj), 3))
    omega_src[1:-1] = 0.5 * (omega[:-1] + omega[1:])
    omega_src[0] = omega[0]
    omega_src[-1] = omega[-1]

    a_world_src = finite_difference(t_src, traj.positions, second=True)
    accel_src = np.einsum("nji,nj->ni", R_src, a_world_src - GRAVITY[None, :])

    if abs(traj.rate_hz() - rate_hz) > 1e-6:
        span = traj.duration
        n = int(np.floor(span * rate_hz)) + 1
        t = t_src[0] + np.arange(n) / rate_hz
        gyro = resample(t_src, omega_src, t)
        accel = resample(t_src, accel_src, t)
    else:
        t = t_src.copy()
        gyro = omega_src
        accel = accel_src

    return ImuSample(t=t, accel=accel, gyro=gyro, name=name)


def apply_imu_noise(
    imu: ImuSample,
    model: ImuNoiseModel,
    rng: np.random.Generator,
    bias_gyro_0: np.ndarray | None = None,
    bias_accel_0: np.ndarray | None = None,
) -> tuple[ImuSample, np.ndarray, np.ndarray]:
    """Add white noise, a constant bias and a bias random walk to an IMU stream.

    Returns the corrupted samples together with the *realised* bias history so
    that the estimator can be checked against the bias that was actually
    applied. Realised bias is ground truth about the scenario, not something a
    real system would have; it is used only for post-hoc analysis.
    """
    t = imu.t
    n = len(imu)
    if n < 2:
        raise ValueError("need at least 2 IMU samples to apply a noise model")
    dt = np.diff(t)
    dt = np.concatenate([dt[:1], dt])  # step ending at each sample
    sqrt_dt = np.sqrt(np.maximum(dt, 1e-9))
    gyro_bias = np.zeros((n, 3))
    accel_bias = np.zeros((n, 3))
    if n > 1:
        gyro_bias[1:] = np.cumsum(model.gyro_bias_rw * sqrt_dt[1:, None] * rng.standard_normal((n - 1, 3)), axis=0)
        accel_bias[1:] = np.cumsum(model.accel_bias_rw * sqrt_dt[1:, None] * rng.standard_normal((n - 1, 3)), axis=0)
    gb0 = np.zeros(3) if bias_gyro_0 is None else np.asarray(bias_gyro_0, float)
    ab0 = np.zeros(3) if bias_accel_0 is None else np.asarray(bias_accel_0, float)
    gyro_bias += gb0
    accel_bias += ab0

    gyro = imu.gyro + gyro_bias + model.gyro_noise_density / sqrt_dt[:, None] * rng.standard_normal((n, 3))
    accel = imu.accel + accel_bias + model.accel_noise_density / sqrt_dt[:, None] * rng.standard_normal((n, 3))

    var = dt.mean()
    out = ImuSample(
        t=t.copy(),
        accel=accel,
        gyro=gyro,
        accel_cov=np.tile(model.accel_noise_density**2 / max(var, 1e-12), (n, 3)),
        gyro_cov=np.tile(model.gyro_noise_density**2 / max(var, 1e-12), (n, 3)),
        name=imu.name,
    )
    return out, gyro_bias, accel_bias


def imu_residual(imu: ImuSample, truth: ImuSample) -> dict[str, float]:
    """Summary statistics of the difference between two IMU streams.

    Used to confirm that an injection did what the scenario says it did, which
    keeps the "degradation was applied" claim a measurement rather than an
    assumption. ``gyro_bias`` is reported as the mean angular rate, whose
    magnitude is the bias for a stationary-at-start bias; a rotating body makes
    that term meaningless, which is why the scenario can also report the full
    per-axis mean.
    """
    n = min(len(imu), len(truth))
    d_gyro = imu.gyro[:n] - truth.gyro[:n]
    d_acc = imu.accel[:n] - truth.accel[:n]
    g_mag = np.linalg.norm(truth.accel[:n], axis=1)
    return {
        "gyro_bias_mean_rad_s": float(np.linalg.norm(d_gyro.mean(axis=0))),
        "gyro_bias_xyz_rad_s": d_gyro.mean(axis=0).tolist(),
        "gyro_noise_std_rad_s": float(d_gyro.std()),
        "accel_noise_std_m_s2": float(d_acc.std()),
        "accel_norm_mean_m_s2": float(g_mag.mean()),
        "accel_norm_std_m_s2": float(g_mag.std()),
        "samples": int(n),
    }
