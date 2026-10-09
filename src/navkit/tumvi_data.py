"""Read a fetched TUM VI room sequence as the same sequence object the EuRoC path uses.

    navkit tumvi fetch --sequence room1
    navkit euroc run --dataset tumvi --sequence room1 --outage 60:20 --markdown

What differs from EuRoC, and what this module does about it:

* **The ground truth has no velocity and no bias columns.** ``mocap0/data.csv`` is a pose stream at
  about 120 Hz in the IMU frame. Velocity at the start comes from a local straight-line fit to the
  positions over a short window, which averages the motion-capture noise that a plain difference would
  amplify. The biases are unknown, so the sequence is marked ``bias_known=False`` and the run estimates
  them from the quietest stretch at the start (:func:`navkit.euroc_eval.static_bias_estimate`).
* **The noise figures are in ``imu_config.yaml``.** The file carries two sets. The active one is
  inflated by its authors "to account for unmodelled effects": white noise multiplied by 2 and bias random
  walk by 10 over the figures from their Allan plots. The raw figures are kept in the file's comments.
  Both are read, as ``file`` and ``allan``, so a run can ask for either.
* **The world frame is the motion-capture frame.** Whether it is z-up is checked, not assumed: the
  result record carries a gravity check against the ground-truth attitude, as for EuRoC.

The ground truth is time-aligned to the IMU by the dataset authors. Nothing here re-estimates that.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import yaml

from .euroc_eval import EurocSequence, SequenceError, _sha256
from .io.imu import DEFAULT_NOISE, ImuNoiseModel, read_euroc_imu
from .io.trajectory import read_trajectory
from .io.tumvi_fetch import IMU_CSV, NOISE_YAML, SEQUENCES, TRUTH_CSV
from .types import ImuSample, Trajectory

DATASET = "TUM VI"
SLUG = "tumvi"
VELOCITY_HALF_WINDOW_S = 0.1

_TERMS = (
    "gyroscope_noise_density",
    "gyroscope_random_walk",
    "accelerometer_noise_density",
    "accelerometer_random_walk",
)


def _model(values: dict[str, float]) -> ImuNoiseModel:
    return ImuNoiseModel(
        gyro_noise_density=values["gyroscope_noise_density"],
        accel_noise_density=values["accelerometer_noise_density"],
        gyro_bias_rw=values["gyroscope_random_walk"],
        accel_bias_rw=values["accelerometer_random_walk"],
    )


def read_noise(path: Path) -> tuple[ImuNoiseModel | None, ImuNoiseModel | None]:
    """The active (inflated) figures and the raw ones from the comments, either of which may be ``None``.

    The raw figures are the commented lines under "Values from allan plots". They are read by pattern, so
    a file that does not follow that shape yields ``None`` for them and the active figures are still used.
    """
    if not path.is_file():
        return None, None
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        raw = None
    active: ImuNoiseModel | None = None
    if isinstance(raw, dict) and all(isinstance(raw.get(k), (int, float)) and raw[k] > 0 for k in _TERMS):
        active = _model({k: float(raw[k]) for k in _TERMS})
    commented: dict[str, float] = {}
    for line in text.splitlines():
        match = re.match(r"\s*#\s*(" + "|".join(_TERMS) + r")\s*:\s*([0-9.eE+-]+)", line)
        if match and match.group(1) not in commented:
            commented[match.group(1)] = float(match.group(2))
    allan = _model(commented) if len(commented) == len(_TERMS) else None
    return active, allan


def smoothed_velocity(t: np.ndarray, p: np.ndarray, half_window_s: float = VELOCITY_HALF_WINDOW_S) -> np.ndarray:
    """Velocity from a straight-line least-squares fit to the positions within +-``half_window_s``.

    Differencing noisy positions at 120 Hz amplifies the noise by about that rate; the local fit averages
    it. Near the ends the window shrinks to the samples that exist. Exact for a constant velocity.
    """
    t = np.asarray(t, float)
    p = np.asarray(p, float).reshape(len(t), -1)
    out = np.zeros_like(p)
    lo = np.searchsorted(t, t - half_window_s, side="left")
    hi = np.searchsorted(t, t + half_window_s, side="right")
    for i in range(len(t)):
        a, b = int(lo[i]), int(hi[i])
        if b - a < 2:
            continue
        tt = t[a:b] - t[a:b].mean()
        denom = float(tt @ tt)
        if denom > 0.0:
            out[i] = (tt[:, None] * (p[a:b] - p[a:b].mean(axis=0))).sum(axis=0) / denom
    return out


def load_sequence(root: str | Path, name: str) -> EurocSequence:
    """Read ``<root>/<name>/...`` as written by ``navkit tumvi fetch``."""
    if name not in SEQUENCES:
        raise SequenceError(f"unknown TUM VI sequence {name!r}; known: {', '.join(SEQUENCES)}")
    base = Path(root) / name
    imu_path, truth_path = base / IMU_CSV, base / TRUTH_CSV
    for path in (imu_path, truth_path):
        if not path.is_file():
            raise SequenceError(f"{path} not found. Fetch it with: navkit tumvi fetch --sequence {name}")

    imu = read_euroc_imu(str(imu_path), name=f"{name}-imu")
    origin = float(imu.t[0])
    imu = ImuSample(t=imu.t - origin, accel=imu.accel, gyro=imu.gyro, name=imu.name)
    raw_truth = read_trajectory(str(truth_path), fmt="euroc", name=f"{name}-truth")
    truth = Trajectory(t=raw_truth.t - origin, poses=raw_truth.poses, name=f"{name}-truth")
    if truth.t[-1] <= imu.t[0] or truth.t[0] >= imu.t[-1]:
        raise SequenceError(f"{name}: the IMU and ground-truth time spans do not overlap")
    quat_norm = np.linalg.norm(truth.quaternions, axis=1)
    if not np.all(np.abs(quat_norm - 1.0) < 1e-3):
        raise SequenceError(f"{truth_path}: quaternions are not unit length; wrong column layout?")

    velocity = smoothed_velocity(truth.t, truth.positions)
    active, allan = read_noise(base / NOISE_YAML)
    notes = ["ground truth has no velocity or bias columns: velocity is a local line fit, biases are unknown"]
    if active is None:
        active, source = DEFAULT_NOISE, "project default (DEFAULT_NOISE), not the sensor's own"
        notes.append("imu_config.yaml missing or incomplete; the project default noise is used")
    else:
        source = "imu_config.yaml (inflated by its authors: white noise x2, bias random walk x10)"
    hashes = {rel: _sha256(base / rel) for rel in (IMU_CSV, TRUTH_CSV) if (base / rel).is_file()}
    return EurocSequence(
        name=name,
        imu=imu,
        truth=truth,
        velocity=velocity,
        gyro_bias=np.zeros((len(truth.t), 3)),
        accel_bias=np.zeros((len(truth.t), 3)),
        noise=active,
        noise_source=source,
        sha256=hashes,
        notes=notes,
        dataset=DATASET,
        slug=SLUG,
        bias_known=False,
        noise_variants={"allan": allan} if allan is not None else {},
    )


def write_fixture(
    root: str | Path,
    name: str = "room1",
    *,
    duration_s: float = 40.0,
    rest_s: float = 3.0,
    imu_rate_hz: float = 200.0,
    mocap_rate_hz: float = 120.0,
    seed: int = 0,
    accel_bias: tuple[float, float, float] = (0.04, -0.03, 0.06),
    gyro_bias: tuple[float, float, float] = (0.003, -0.002, 0.004),
) -> Path:
    """Write a synthetic sequence in the layout ``navkit tumvi fetch`` produces.

    The rig rests for ``rest_s`` seconds and then follows the synthetic motion. The IMU is a physical z-up
    one with the given biases, so a test knows the answer the static bias estimate should find. The
    ground truth is pose only at ``mocap_rate_hz``, like the real ``mocap0``. The noise file has the shape
    of the real one: inflated active figures, with the raw figures in the comments. It says nothing about
    the filter on real data.
    """
    from .euroc_eval import GRAVITY_Z_UP
    from .geometry.rigid import matrix_to_quat
    from .synthetic import SyntheticConfig, analytic_kinematics, analytic_pose

    base = Path(root) / name
    syn = SyntheticConfig(duration_s=duration_s)
    rng = np.random.default_rng(seed)
    n = int(round((duration_s + rest_s) * imu_rate_hz)) + 1
    t = np.arange(n) / imu_rate_hz
    ts = np.maximum(t - rest_s, 0.0)  # motion time: held at the start pose during the rest
    pose = analytic_pose(syn, ts)
    a_world, omega = analytic_kinematics(syn, ts)
    moving = (t >= rest_s)[:, None]
    a_world = np.where(moving, a_world, 0.0)
    omega = np.where(moving, omega, 0.0)
    noise = ImuNoiseModel(1.6e-4, 2.8e-3, 2.2e-5, 8.6e-4)
    accel = (
        np.einsum("nji,nj->ni", pose[:, :3, :3], a_world - GRAVITY_Z_UP)
        + np.asarray(accel_bias)
        + rng.standard_normal((n, 3)) * noise.accel_noise_density * np.sqrt(imu_rate_hz)
    )
    gyro = omega + np.asarray(gyro_bias) + rng.standard_normal((n, 3)) * noise.gyro_noise_density * np.sqrt(imu_rate_hz)
    origin_ns = 1520530308181901469
    ns = origin_ns + np.round(t * 1e9).astype(np.int64)
    (base / "mav0" / "imu0").mkdir(parents=True, exist_ok=True)
    (base / "mav0" / "mocap0").mkdir(parents=True, exist_ok=True)
    with (base / IMU_CSV).open("w", encoding="utf-8") as fh:
        fh.write(
            "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
            "a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]\n"
        )
        for k in range(n):
            fh.write(f"{ns[k]}," + ",".join(f"{x:.10f}" for x in (*gyro[k], *accel[k])) + "\n")
    m = int(round((duration_s + rest_s) * mocap_rate_hz)) + 1
    tm = np.arange(m) / mocap_rate_hz + 0.0072  # the mocap clock is not on the IMU's grid
    pm = analytic_pose(syn, np.maximum(tm - rest_s, 0.0))
    nsm = origin_ns + np.round(tm * 1e9).astype(np.int64)
    with (base / TRUTH_CSV).open("w", encoding="utf-8") as fh:
        fh.write(
            "#timestamp [ns], p_RS_R_x [m], p_RS_R_y [m], p_RS_R_z [m], q_RS_w [], q_RS_x [], q_RS_y [], q_RS_z []\n"
        )
        for k in range(m):
            q = matrix_to_quat(pm[k, :3, :3])
            fh.write(f"{nsm[k]}," + ",".join(f"{x:.10f}" for x in (*pm[k, :3, 3], *q)) + "\n")
    (base / NOISE_YAML).write_text(
        "rostopic: /imu0\nupdate_rate: 200.0  # Hz\n\n# Values from allan plots\n"
        f"#accelerometer_noise_density: {noise.accel_noise_density / 2:g}     # m/s^1.5\n"
        f"#accelerometer_random_walk:   {noise.accel_bias_rw / 10:g}   # m/s^2.5\n"
        f"#gyroscope_noise_density:     {noise.gyro_noise_density / 2:g}   # rad/s^0.5\n"
        f"#gyroscope_random_walk:       {noise.gyro_bias_rw / 10:g}  # rad/s^1.5\n\n"
        "# Inflated values (to account for unmodelled effects)\n"
        f"accelerometer_noise_density: {noise.accel_noise_density:g}     # m/s^1.5\n"
        f"accelerometer_random_walk:   {noise.accel_bias_rw:g}    # m/s^2.5\n"
        f"gyroscope_noise_density:     {noise.gyro_noise_density:g}    # rad/s^0.5\n"
        f"gyroscope_random_walk:       {noise.gyro_bias_rw:g}   # rad/s^1.5\n",
        encoding="utf-8",
    )
    return base
