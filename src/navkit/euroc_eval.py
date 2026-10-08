"""Run the filter on a recorded EuRoC sequence and score it with the calibration harness.

    navkit euroc fetch --sequence MH_01_easy           # once; see navkit.io.euroc_fetch
    navkit euroc run --sequence MH_01_easy --outage 60:20 --markdown
    navkit euroc selftest                              # no download; checks the pipeline

What is real and what is not. The IMU stream is the recorded one. The reference is the
dataset's ground-truth estimate. EuRoC has no GNSS, so the position fixes are **simulated from
that ground truth** with the same noise model the synthetic benchmark uses, and an outage is
cut out of them the same way. The result is therefore a test of the filter against real
inertial data and a known reference, not a test of GNSS-denied navigation in the field. The
record says so in ``data_class`` and ``caveats``. Visual fusion stays off (constraint S3).

Choices that change the numbers, all recorded in the result:

* **Frame and gravity.** The filter runs in the dataset's world frame, which is z-up, so
  gravity is ``(0, 0, -9.80665)``. The synthetic benchmark uses the opposite sign
  convention, because its synthetic accelerometer is built that way; passing the default
  gravity to a real z-up IMU doubles the vertical acceleration and the position error grows by
  orders of magnitude. :func:`gravity_check` reports how well the quietest second of the
  recording agrees with the ground-truth attitude.
* **Start state.** Pose and velocity at the first sample come from the ground truth, then are
  perturbed by a seeded draw from the filter's declared initial 1-sigma, so the filter is not
  handed an exact start it then claims to be uncertain about (``--exact-init`` switches that
  off). Biases start at the ground-truth estimate (``--init-bias truth``) or at zero.
* **Noise model.** Read from ``imu0/sensor.yaml`` when it carries the four noise terms.
  Otherwise the project default is used and the result says so (``noise_source``).
* **GNSS.** Antenna at the IMU origin, 5 Hz, 0.8 m 1-sigma white noise, like the benchmark.

The ground truth is itself an estimate (motion capture or a laser tracker, fused), and the
dataset's own notes say its synchronisation with the sensors is limited. Nothing here is
field performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from . import __version__
from .benchmark import MEASUREMENT, _jsonable
from .degrade.config import Outage
from .degrade.inject import apply_gnss_outage
from .estimators.eskf import ErrorStateKalmanFilter, EskfConfig, InitialState
from .eval.calibration import normalized_error_squared, summarise
from .eval.metrics import ate_bundle, outage_summary, relative_pose_error
from .geometry.rigid import matrix_to_quat, quat_to_matrix, rot_exp
from .io.euroc_fetch import IMU_CSV, IMU_SENSOR, SEQUENCES, TRUTH_CSV
from .io.euroc_fetch import main as fetch_main
from .io.imu import DEFAULT_NOISE, ImuNoiseModel, read_euroc_imu
from .io.trajectory import _read_rows
from .sensors.models import GnssConfig, gnss_fixes
from .synthetic import SyntheticConfig, analytic_kinematics, analytic_pose
from .types import GRAVITY, ImuSample, Trajectory, interpolate_trajectory

#: Gravity vector of a z-up world, in the sign convention of ``ErrorStateKalmanFilter``
#: (``a_world = R @ specific_force + g``).
GRAVITY_Z_UP = -GRAVITY

DEFAULT_ROOT = "data/raw/euroc"

DATA_CLASS = "real_imu_simulated_gnss"

CAVEATS = (
    "GNSS fixes are simulated from the ground-truth trajectory, antenna at the IMU origin.",
    "Initial pose and velocity come from the ground truth.",
    "The ground truth is an estimate; its time synchronisation with the sensors is limited.",
    "Visual fusion is disabled (constraint S3).",
    "Not field performance.",
)

_TERMS = (
    "gyroscope_noise_density",
    "gyroscope_random_walk",
    "accelerometer_noise_density",
    "accelerometer_random_walk",
)

# Looser than the accelerometer bias of the sensor and tighter than a mounting error: a recording
# whose quietest second does not reproduce gravity to this much has a frame or attitude problem.
_GRAVITY_ANGLE_WARN_DEG = 5.0
_GRAVITY_NORM_WARN_M_S2 = 0.5


class SequenceError(ValueError):
    """The files of a sequence are missing or do not look like EuRoC data."""


# ------------------------------------------------------------------------ loading


@dataclass
class EurocSequence:
    """One sequence in memory. Time is in seconds from the first IMU sample."""

    name: str
    imu: ImuSample
    truth: Trajectory
    velocity: np.ndarray  # (N, 3) world frame, on truth.t
    gyro_bias: np.ndarray  # (N, 3), on truth.t
    accel_bias: np.ndarray  # (N, 3), on truth.t
    noise: ImuNoiseModel
    noise_source: str
    sha256: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_noise(sensor_yaml: Path) -> tuple[ImuNoiseModel, str]:
    """The IMU noise model from ``sensor.yaml``, or the project default and a statement of that."""
    fallback = (DEFAULT_NOISE, "project default (DEFAULT_NOISE), not the sensor's own")
    if not sensor_yaml.is_file():
        return fallback
    try:
        raw = yaml.safe_load(sensor_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return fallback
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), (int, float)) and raw[k] > 0 for k in _TERMS):
        return fallback
    model = ImuNoiseModel(
        gyro_noise_density=float(raw["gyroscope_noise_density"]),
        accel_noise_density=float(raw["accelerometer_noise_density"]),
        gyro_bias_rw=float(raw["gyroscope_random_walk"]),
        accel_bias_rw=float(raw["accelerometer_random_walk"]),
    )
    return model, "imu0/sensor.yaml"


def _read_truth(path: Path) -> tuple[np.ndarray, ...]:
    a, _ = _read_rows(str(path))
    if a.shape[1] < 11:
        raise SequenceError(f"{path}: expected t, p, q, v (11 or more columns), got {a.shape[1]}")
    if abs(a[0, 0]) < 1e12:
        raise SequenceError(f"{path}: timestamps are not in nanoseconds; this is not an EuRoC ground-truth file")
    t = a[:, 0] / 1e9
    t, keep = np.unique(t, return_index=True)
    a = a[keep]
    q = a[:, 4:8]
    norms = np.linalg.norm(q, axis=1)
    if not np.all(np.abs(norms - 1.0) < 1e-3):
        raise SequenceError(f"{path}: quaternion columns 4 to 7 are not unit length; wrong column layout?")
    return t, a[:, 1:4], q, a[:, 8:11], a[:, 11:14], a[:, 14:17]


def load_sequence(root: str | Path, name: str) -> EurocSequence:
    """Read ``<root>/<name>/mav0/...`` as written by ``navkit euroc fetch``."""
    base = Path(root) / name
    imu_path, truth_path = base / IMU_CSV, base / TRUTH_CSV
    for path in (imu_path, truth_path):
        if not path.is_file():
            raise SequenceError(f"{path} not found. Fetch it with: navkit euroc fetch --sequence {name}")

    imu = read_euroc_imu(str(imu_path), name=f"{name}-imu")
    origin = float(imu.t[0])
    imu = ImuSample(t=imu.t - origin, accel=imu.accel, gyro=imu.gyro, name=imu.name)

    t, p, q, v, bg, ba = _read_truth(truth_path)
    t = t - origin
    poses = np.zeros((len(t), 4, 4))
    poses[:, 3, 3] = 1.0
    poses[:, :3, 3] = p
    for k in range(len(t)):
        poses[k, :3, :3] = quat_to_matrix(q[k])
    notes: list[str] = []
    if bg.shape[1] < 3 or np.isnan(bg).any() or np.isnan(ba).any():
        bg, ba = np.zeros((len(t), 3)), np.zeros((len(t), 3))
        notes.append("ground-truth file carries no bias columns; biases taken as zero")
    truth = Trajectory(t=t, poses=poses, name=f"{name}-truth")
    if truth.t[-1] <= imu.t[0] or truth.t[0] >= imu.t[-1]:
        raise SequenceError(f"{name}: the IMU and ground-truth time spans do not overlap")

    noise, source = read_noise(base / IMU_SENSOR)
    hashes = {rel: _sha256(base / rel) for rel in (IMU_CSV, TRUTH_CSV)}
    return EurocSequence(
        name=name,
        imu=imu,
        truth=truth,
        velocity=v,
        gyro_bias=bg,
        accel_bias=ba,
        noise=noise,
        noise_source=source,
        sha256=hashes,
        notes=notes,
    )


# ----------------------------------------------------------------------- running


@dataclass
class RunOptions:
    """Everything that changes a result besides the data."""

    gnss_rate_hz: float = 5.0
    gnss_sigma_m: float = 0.8
    outages: tuple[tuple[float, float], ...] = ()  # (start, duration) in seconds after the window start
    seed: int = 0
    noise_scale: float = 1.0
    init_bias: str = "truth"  # "truth" or "zero"
    bias_sigma: float | None = None  # None keeps the filter's declared default
    exact_init: bool = False
    process_noise: str = "legacy"  # EskfConfig.process_noise_form
    skip_s: float = 0.0
    duration_s: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gnss_rate_hz": self.gnss_rate_hz,
            "gnss_sigma_m": self.gnss_sigma_m,
            "outages": [list(o) for o in self.outages],
            "seed": self.seed,
            "noise_scale": self.noise_scale,
            "init_bias": self.init_bias,
            "bias_sigma": self.bias_sigma,
            "exact_init": self.exact_init,
            "process_noise": self.process_noise,
            "skip_s": self.skip_s,
            "duration_s": self.duration_s,
        }


def gravity_check(
    imu: ImuSample,
    truth: Trajectory,
    accel_bias: np.ndarray,
    window_s: float = 1.0,
    search_s: float = 30.0,
) -> dict[str, Any]:
    """Does the quietest second reproduce gravity once the ground-truth attitude rotates it into the world?

    The mean specific force in the world frame of a vehicle at rest is ``-g``, which for a z-up
    world is ``(0, 0, +9.8)``. A large angle to +z or a wrong norm points at the frame, the
    quaternion order or the pose convention, and those make every later number meaningless.

    A recording does not have to start at rest (MH_01_easy is being moved in its first second), and a
    moving vehicle reads more or less than ``g``. So the check uses the window of ``window_s`` seconds,
    within the first ``search_s``, in which the accelerometer norm varies least, and reports where
    it was. Even that window may not be at rest, so this is a warning and not a gate.
    """
    t = imu.t
    stop = np.searchsorted(t, t[0] + search_s)
    starts = np.arange(0, max(stop, 1), max(1, int(round(0.25 * imu.rate_hz()))))
    width = max(2, int(round(window_s * imu.rate_hz())))
    norms = np.linalg.norm(imu.accel - accel_bias, axis=1)
    best, best_score = 0, np.inf
    for i in starts:
        if i + width > len(t):
            break
        score = float(np.std(norms[i : i + width]))
        if score < best_score:
            best, best_score = int(i), score
    sel = slice(best, min(best + width, len(t)))
    ref = interpolate_trajectory(truth, t[sel])
    f_world = np.einsum("nij,nj->ni", ref.rotations, imu.accel[sel] - accel_bias).mean(axis=0)
    norm = float(np.linalg.norm(f_world))
    angle = float(np.degrees(np.arccos(np.clip(f_world[2] / max(norm, 1e-12), -1.0, 1.0))))
    expected = float(np.linalg.norm(GRAVITY))
    warn = angle > _GRAVITY_ANGLE_WARN_DEG or abs(norm - expected) > _GRAVITY_NORM_WARN_M_S2
    return {
        "window_start_s": float(t[best] - t[0]),
        "window_accel_norm_std_m_s2": best_score,
        "mean_world_specific_force_m_s2": f_world.tolist(),
        "norm_m_s2": norm,
        "expected_norm_m_s2": expected,
        "angle_to_vertical_deg": angle,
        "warning": bool(warn),
    }


def _initial_state(seq: EurocSequence, opts: RunOptions, cfg: EskfConfig, t0: float) -> InitialState:
    ref = interpolate_trajectory(seq.truth, np.array([t0]))
    R0, p0 = ref.rotations[0], ref.positions[0]
    v0 = np.array([np.interp(t0, seq.truth.t, seq.velocity[:, k]) for k in range(3)])
    if opts.init_bias == "truth":
        b_g = np.array([np.interp(t0, seq.truth.t, seq.gyro_bias[:, k]) for k in range(3)])
        b_a = np.array([np.interp(t0, seq.truth.t, seq.accel_bias[:, k]) for k in range(3)])
    elif opts.init_bias == "zero":
        b_g, b_a = np.zeros(3), np.zeros(3)
    else:
        raise ValueError(f"init_bias must be 'truth' or 'zero', got {opts.init_bias!r}")
    if not opts.exact_init:
        # A stream of its own, so changing the GNSS seed does not move the start and vice versa.
        rng = np.random.default_rng(np.random.SeedSequence([opts.seed, 1]))
        p0 = p0 + rng.standard_normal(3) * cfg.initial_pos_sigma_m
        v0 = v0 + rng.standard_normal(3) * cfg.initial_vel_sigma_m_s
        R0 = R0 @ rot_exp(rng.standard_normal(3) * np.deg2rad(cfg.initial_rot_sigma_deg))
    return InitialState(R=R0, p=p0, v=v0, b_a=b_a, b_g=b_g)


def run_sequence(seq: EurocSequence, opts: RunOptions | None = None) -> dict[str, Any]:
    """Run the ESKF on one sequence and return a result record shaped like the benchmark's."""
    opts = opts or RunOptions()
    if opts.init_bias == "zero" and not (opts.bias_sigma and opts.bias_sigma > 0):
        # With a bias prior of zero the filter takes the zero start as exact and never estimates the
        # bias, so a real offset turns into a large, confident position error. Refuse instead.
        raise SequenceError("--init-bias zero needs a declared --bias-sigma greater than 0")
    t_start = max(float(seq.imu.t[0]), float(seq.truth.t[0])) + opts.skip_s
    t_end = min(float(seq.imu.t[-1]), float(seq.truth.t[-1]))
    if opts.duration_s is not None:
        t_end = min(t_end, t_start + opts.duration_s)
    if t_end - t_start < 1.0:
        raise SequenceError(f"{seq.name}: the evaluation window is {t_end - t_start:.2f} s, too short to run")

    imu = seq.imu.subset(t_start, t_end)
    reference = seq.truth.subset(t_start, t_end)
    window = [(t_start + s, d) for s, d in opts.outages]
    for start, dur in window:
        if dur <= 0 or start >= t_end:
            raise SequenceError(
                f"outage starting at {start - t_start:.1f} s lies outside the {t_end - t_start:.1f} s window"
            )

    gnss = gnss_fixes(reference, GnssConfig(rate_hz=opts.gnss_rate_hz, sigma_m=opts.gnss_sigma_m, seed=opts.seed))
    gnss = apply_gnss_outage(gnss, [Outage(start_s=s, duration_s=d) for s, d in window], True)

    cfg_kwargs: dict[str, Any] = {}
    if opts.bias_sigma is not None:
        cfg_kwargs["initial_bias_sigma"] = opts.bias_sigma
    cfg = EskfConfig(
        imu_noise=seq.noise.scaled(opts.noise_scale),
        gnss_position_sigma_m=opts.gnss_sigma_m,
        vision_enabled=False,
        gravity=GRAVITY_Z_UP,
        process_noise_form=opts.process_noise,
        **cfg_kwargs,
    )
    initial = _initial_state(seq, opts, cfg, float(imu.t[0]))
    result = ErrorStateKalmanFilter(cfg).run(imu, gnss=gnss, initial=initial)
    est = result.trajectory

    ate = ate_bundle(est, reference)
    headline_ate = ate["none"]
    ref_on_est = interpolate_trajectory(reference, est.t)

    record: dict[str, Any] = {
        "name": f"euroc_{seq.name}",
        "description": f"EuRoC {seq.name}: recorded IMU, ground-truth-derived GNSS",
        "claim_type": MEASUREMENT,
        "data_class": DATA_CLASS,
        "caveats": list(CAVEATS),
        "navkit_version": __version__,
        "sequence": seq.name,
        "inputs": {"sha256": seq.sha256, "noise_source": seq.noise_source, "notes": seq.notes},
        "options": opts.as_dict(),
        "window_s": {"start": t_start - float(seq.imu.t[0]), "end": t_end - float(seq.imu.t[0])},
        "imu_samples": len(imu),
        "estimator": {"class": "ErrorStateKalmanFilter", **cfg.as_dict()},
        "gravity_check": gravity_check(imu, reference, initial.b_a),
        "runtime_s": result.runtime_s,
        "stats": dict(result.stats),
        "ate": {k: v.as_dict() for k, v in ate.items()},
        "headline": {
            "alignment": headline_ate.alignment,
            "ate_rmse_m": headline_ate.position_m.rmse,
            "ate_median_m": headline_ate.position_m.median,
            "ate_p95_m": headline_ate.position_percentiles_m.get("p95"),
            "rotation_rmse_deg": headline_ate.rotation_deg.rmse,
        },
    }

    if result.position_cov is not None:
        series = normalized_error_squared(est.positions, ref_on_est.positions, result.position_cov)
        cal = summarise(
            estimator="eskf",
            scenario=record["name"],
            series=series,
            notes=("recorded IMU with ground-truth-derived GNSS; not field performance",),
        )
        claimed = np.sqrt(np.trace(result.position_cov, axis1=1, axis2=2) / 3.0)
        record["calibration"] = cal.as_dict()
        head = record["headline"]
        head["nees_mean"] = series.mean_squared()
        head["nees_expected"] = float(series.dof)
        head["claimed_sigma_p_m"] = float(np.median(claimed))
        head["claimed_sigma_p95_m"] = float(np.percentile(claimed, 95))
        head["coverage"] = {f"{p.sigma_per_axis:g}sigma": p.observed for p in cal.coverage.points}
        head["calibration_verdict"] = cal.verdict
        head["bulk_verdict"] = cal.bulk_verdict
        head["tail_verdict"] = cal.tail_verdict
        head["calibrated"] = bool(cal.calibrated)
        record["error_time_series"] = {
            "t": (est.t - float(seq.imu.t[0])).tolist(),
            "position_error_m": headline_ate.per_pose_position_m.tolist(),
            "claimed_sigma_p_m": claimed.tolist(),
        }
        if window:
            baseline = float(np.median(headline_ate.per_pose_position_m[: max(1, len(est) // 10)]))
            record["outages"] = outage_summary(
                est.t, headline_ate.per_pose_position_m, [(s, s + d) for s, d in window], baseline_error_m=baseline
            )

    rpe = relative_pose_error(est, reference, delta=1.0, mode="time")
    record["rpe_1s"] = rpe.as_dict()
    return _jsonable(record)  # type: ignore[no-any-return]


# ------------------------------------------------------------------------ fixture


def write_fixture(
    root: str | Path,
    name: str = "FIXTURE_z_up",
    *,
    duration_s: float = 40.0,
    rate_hz: float = 200.0,
    seed: int = 0,
    accel_bias: tuple[float, float, float] = (0.03, -0.02, 0.05),
    gyro_bias: tuple[float, float, float] = (0.002, -0.001, 0.003),
) -> Path:
    """Write a synthetic sequence in the exact EuRoC file layout, with a physical z-up IMU.

    The accelerometer reads ``R^T (a - g)`` with ``g = (0, 0, -9.80665)``, so it reads +g
    upward at rest, as a real one does. Timestamps are nanoseconds from a large offset, like the
    recordings'. The point is to exercise every step of the real path (loading, units, frames,
    gravity, start state, scoring) before the real data is on disk. It says nothing about
    the filter's performance on real data.
    """
    base = Path(root) / name
    syn = SyntheticConfig(duration_s=duration_s)
    n = int(round(duration_s * rate_hz)) + 1
    t = np.arange(n) / rate_hz
    pose = analytic_pose(syn, t)
    a_world, omega = analytic_kinematics(syn, t)
    rng = np.random.default_rng(seed)
    noise = DEFAULT_NOISE
    accel = (
        np.einsum("nji,nj->ni", pose[:, :3, :3], a_world - GRAVITY_Z_UP)
        + np.asarray(accel_bias)
        + rng.standard_normal((n, 3)) * noise.accel_noise_density * np.sqrt(rate_hz)
    )
    gyro = omega + np.asarray(gyro_bias) + rng.standard_normal((n, 3)) * noise.gyro_noise_density * np.sqrt(rate_hz)
    vel = np.gradient(pose[:, :3, 3], t, axis=0)

    ns = 1403636579763555584 + np.round(t * 1e9).astype(np.int64)
    (base / "mav0" / "imu0").mkdir(parents=True, exist_ok=True)
    (base / "mav0" / "state_groundtruth_estimate0").mkdir(parents=True, exist_ok=True)
    with (base / IMU_CSV).open("w", encoding="utf-8") as fh:
        fh.write(
            "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
            "a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]\n"
        )
        for k in range(n):
            fh.write(f"{ns[k]}," + ",".join(f"{x:.9f}" for x in (*gyro[k], *accel[k])) + "\n")
    with (base / TRUTH_CSV).open("w", encoding="utf-8") as fh:
        fh.write(
            "#timestamp,p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
            "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
            "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]\n"
        )
        for k in range(n):
            q = matrix_to_quat(pose[k, :3, :3])
            row = (*pose[k, :3, 3], *q, *vel[k], *gyro_bias, *accel_bias)
            fh.write(f"{ns[k]}," + ",".join(f"{x:.9f}" for x in row) + "\n")
    (base / IMU_SENSOR).write_text(
        yaml.safe_dump(
            {
                "sensor_type": "imu",
                "rate_hz": rate_hz,
                "gyroscope_noise_density": noise.gyro_noise_density,
                "gyroscope_random_walk": noise.gyro_bias_rw,
                "accelerometer_noise_density": noise.accel_noise_density,
                "accelerometer_random_walk": noise.accel_bias_rw,
            }
        ),
        encoding="utf-8",
    )
    return base


# --------------------------------------------------------------------------- CLI


def _parse_outage(text: str) -> tuple[float, float]:
    start, sep, dur = text.partition(":")
    try:
        if not sep:
            raise ValueError
        return float(start), float(dur)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"outage must be START:DURATION in seconds, got {text!r}") from exc


def as_markdown(records: list[dict[str, Any]]) -> str:
    """A small table. The numbers come from the records; none are typed here."""
    lines = [
        "| Sequence | Outage s | ATE RMSE m | Mean NEES (expected) | 2σ coverage | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        h = r["headline"]
        outage = ", ".join(f"{s:g}+{d:g}" for s, d in r["options"]["outages"]) or "none"
        cov = h.get("coverage", {}).get("2sigma")
        lines.append(
            f"| {r['sequence']} | {outage} | {h['ate_rmse_m']:.3f} | "
            f"{h.get('nees_mean', float('nan')):.2f} ({h.get('nees_expected', float('nan')):g}) | "
            f"{'n/a' if cov is None else f'{100 * cov:.1f}%'} | {h.get('calibration_verdict', 'n/a')} |"
        )
    return "\n".join(lines)


def _run_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit euroc run",
        description="Run the ESKF on a fetched EuRoC sequence with GNSS simulated from its ground truth.",
    )
    p.add_argument(
        "--sequence", "-s", action="append", default=[], metavar="NAME", help=f"one of {', '.join(SEQUENCES)}"
    )
    p.add_argument(
        "--root", default=DEFAULT_ROOT, help="where `navkit euroc fetch` wrote the files (default: %(default)s)"
    )
    p.add_argument("--outage", action="append", default=[], type=_parse_outage, metavar="START:DURATION")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--gnss-rate", type=float, default=5.0, help="Hz (default: %(default)s)")
    p.add_argument("--gnss-sigma", type=float, default=0.8, help="metres, 1-sigma per axis (default: %(default)s)")
    p.add_argument("--noise-scale", type=float, default=1.0, help="multiplier on the filter's IMU noise model")
    p.add_argument("--init-bias", choices=("truth", "zero"), default="truth")
    p.add_argument(
        "--bias-sigma", type=float, default=None, help="declared initial bias 1-sigma (filter default if unset)"
    )
    p.add_argument(
        "--exact-init", action="store_true", help="start exactly at the ground truth, with no seeded perturbation"
    )
    p.add_argument("--process-noise", choices=("legacy", "textbook"), default="legacy", help="IMU white-noise form")
    p.add_argument("--skip", type=float, default=0.0, help="seconds to skip at the start of the recording")
    p.add_argument("--duration", type=float, default=None, help="seconds to evaluate (default: to the end)")
    p.add_argument(
        "--out", default=None, help="result JSON (default: results/euroc_<sequence>.json); one sequence only"
    )
    p.add_argument("--markdown", action="store_true", help="print a table instead of the headline lines")
    return p


def _run(argv: list[str]) -> int:
    args = _run_parser().parse_args(argv)
    if not args.sequence:
        print("give at least one --sequence NAME", file=sys.stderr)
        return 2
    if args.out and len(args.sequence) > 1:
        print("--out takes one sequence; omit it to write results/euroc_<sequence>.json for each", file=sys.stderr)
        return 2
    opts = RunOptions(
        gnss_rate_hz=args.gnss_rate,
        gnss_sigma_m=args.gnss_sigma,
        outages=tuple(args.outage),
        seed=args.seed,
        noise_scale=args.noise_scale,
        init_bias=args.init_bias,
        bias_sigma=args.bias_sigma,
        exact_init=args.exact_init,
        process_noise=args.process_noise,
        skip_s=args.skip,
        duration_s=args.duration,
    )
    records: list[dict[str, Any]] = []
    for name in args.sequence:
        try:
            record = run_sequence(load_sequence(args.root, name), opts)
        except (SequenceError, FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        out = Path(args.out) if args.out else Path("results") / f"euroc_{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        gc = record["gravity_check"]
        if gc["warning"]:
            print(
                f"warning: {name}: the quietest second does not reproduce gravity once rotated by the ground-truth "
                f"attitude (angle to vertical {gc['angle_to_vertical_deg']:.1f} deg, "
                f"norm {gc['norm_m_s2']:.2f} m/s^2). "
                "Check the frame and quaternion order before trusting this result.",
                file=sys.stderr,
            )
        records.append(record)
        print(f"wrote {out}", file=sys.stderr)
    if args.markdown:
        print(as_markdown(records))
    else:
        for r in records:
            h = r["headline"]
            print(
                f"{r['sequence']}: ATE RMSE {h['ate_rmse_m']:.3f} m, mean NEES {h.get('nees_mean', float('nan')):.2f}"
            )
    return 0


def _selftest(argv: list[str]) -> int:
    """Write a synthetic sequence in the EuRoC layout and run the whole pipeline on it."""
    parser = argparse.ArgumentParser(prog="navkit euroc selftest", description=_selftest.__doc__)
    parser.add_argument("--keep", metavar="DIR", help="write the fixture here and keep it")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(args.keep or tmp)
        write_fixture(root)
        record = run_sequence(load_sequence(root, "FIXTURE_z_up"), RunOptions(outages=((15.0, 10.0),)))
        print(as_markdown([record]))
        gc = record["gravity_check"]
        print(f"gravity check: angle to vertical {gc['angle_to_vertical_deg']:.2f} deg, warning={gc['warning']}")
        print("This is a synthetic sequence in the EuRoC layout. It checks the pipeline, not the filter on real data.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Route ``navkit euroc fetch|run|selftest``."""
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {"fetch": fetch_main, "run": _run, "selftest": _selftest}
    if not args or args[0] in ("-h", "--help") or args[0] not in commands:
        usage = "usage: navkit euroc {fetch,run,selftest} [options]"
        kinds = (
            "  fetch     download the IMU and ground-truth files of a sequence (needs network)",
            "  run       run the filter on a fetched sequence, GNSS simulated from its ground truth",
            "  selftest  run the whole pipeline on a synthetic sequence in the EuRoC layout",
        )
        print("\n".join((usage, *kinds)), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 2
    return commands[args[0]](args[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
