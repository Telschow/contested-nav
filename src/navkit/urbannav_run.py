"""Run the filter on an UrbanNav sequence with the receiver's own GNSS fixes and its real outage.

    navkit urbannav run --sequence tunnel1 --csv docs/data/urbannav_run.csv --page docs/urbannav.md
    navkit urbannav run --sequence deepurban1 --csv docs/data/urbannav_run.csv --page docs/urbannav.md

This is the test that ADR-0013 and ADR-0016 left open: a recorded IMU and recorded GNSS, with the outage the tunnel
causes and not one cut into simulated fixes. The decision behind it is ADR-0026.

Every setting is declared in :data:`DECLARED` and is not changed after a run. It was written before the first run of
the filter on this data, from sources that do not depend on how the filter does:

* The IMU noise densities are the larger of the two published figures for the Xsens MTi-10, because two datasheets
  disagree. The bias random walks are the repository's defaults, since the datasheets give none.
* The GNSS noise is the receiver's own error estimate (its ``GST`` sentences), not a fit to the reference.
* The vertical noise is declared very large, because the receiver's height has a bias that changes between the two
  sides of the outage (see the UrbanNav page). The height is therefore almost unused.
* The start pose and velocity come from the reference, as in the other recorded-data runs, and the start biases are
  estimated from the quietest stretch of the first seconds.

A sequence in which the receiver reports no outage by the rule of :func:`urbannav_data.outage_intervals` gets the
**aided run**: the declared and per-fix variants over the whole sequence, with the same settings. The oracle variants
act only inside an outage, so they are not applicable there, and the output says so. The outage rule is not changed to
find one (issue #95). Imposed outages are a separate experiment.

Not corrected: the antenna offset from the IMU (about 0.9 m, measured by hand to 0.1 m) and the 0.14 m offset between
the IMU and the reference point. No clock offset is applied: the offset search found none within its step, which a
1 Hz reference cannot resolve finely.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import math
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np

from . import urbannav_data as ud
from .estimators.eskf import ErrorStateKalmanFilter, EskfConfig
from .euroc_eval import RunOptions, run_sequence
from .eval.calibration import effective_samples, wilson_interval
from .fdir.gating import chi2_threshold
from .io.imu import DEFAULT_NOISE, ImuNoiseModel
from .recorded import EurocSequence, SequenceError
from .types import GRAVITY, GnssFix, Trajectory, interpolate_trajectory, rot_log_batch

SEQUENCE = "tunnel1"
DEG = math.pi / 180.0
UG = 1.0e-6 * float(np.linalg.norm(GRAVITY))

#: The two published MTi-10 noise densities that disagree: gyro in deg/s/sqrt(Hz), accelerometer in ug/sqrt(Hz).
GYRO_DENSITY_SOURCES_DEG = (0.03, 0.01)
ACCEL_DENSITY_SOURCES_UG = (60.0, 80.0)

DECLARED: dict[str, tuple[str, str]] = {
    "gyro_noise_density": (
        f"{max(GYRO_DENSITY_SOURCES_DEG) * DEG:.4g}",
        "rad/s/sqrt(Hz): the larger of 0.03 and 0.01 deg/s/sqrt(Hz)",
    ),
    "accel_noise_density": (
        f"{max(ACCEL_DENSITY_SOURCES_UG) * UG:.4g}",
        "m/s^2/sqrt(Hz): the larger of 60 and 80 ug/sqrt(Hz)",
    ),
    "gyro_bias_rw": (f"{DEFAULT_NOISE.gyro_bias_rw:.4g}", "rad/s/sqrt(Hz): the repository default"),
    "accel_bias_rw": (f"{DEFAULT_NOISE.accel_bias_rw:.4g}", "m/s^2/sqrt(Hz): the repository default"),
    "gnss_horizontal_sigma": (
        "receiver",
        "per axis: the root mean square of the receiver's own latitude and longitude sigma over valid fixes",
    ),
    "gnss_vertical_sigma": ("100", "m: declared large because the height is biased"),
    "start_pose": (
        "reference",
        "pose and velocity from the reference at the first IMU sample, perturbed by the filter's start sigmas",
    ),
    "start_bias": ("static", "estimated from the quietest stretch of the first seconds"),
    "clock_offset_applied": ("0", "s"),
    "antenna_offset": ("not corrected", "about 0.9 m"),
    "seeds": ("0 1 2 3 4", "perturb the start state only; the data is one recording"),
    "variant: declared": ("scalar sigma", "the settings above, fixed before the first run"),
    "variant: per_fix": (
        "receiver sigma per fix",
        "added AFTER the first run, because one scalar over-weights the fixes at the tunnel mouth. Not blind",
    ),
    "variant: oracle_tilt": (
        "reference roll and pitch in the outage",
        "ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the roll and pitch are set to the "
        "reference's at every IMU step and the yaw is the filter's own. Otherwise the declared settings",
    ),
    "variant: oracle_yaw": (
        "reference yaw in the outage",
        "ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the yaw is set to the reference's "
        "at every IMU step and the roll and pitch are the filter's own. Otherwise the declared settings",
    ),
    "variant: oracle_attitude": (
        "reference attitude in the outage",
        "ORACLE DIAGNOSTIC, not a filter: it uses the reference. Inside the outage the whole attitude is set to the "
        "reference's at every IMU step. Otherwise the declared settings",
    ),
}
VARIANTS = ("declared", "per_fix")
#: Diagnostics that separate where the outage error comes from. They use the reference, so they are not filters.
ORACLE_VARIANTS = ("oracle_tilt", "oracle_yaw", "oracle_attitude")
ALL_VARIANTS = VARIANTS + ORACLE_VARIANTS
#: Said wherever the oracle variants would be, for a sequence in which the receiver reports no outage.
ORACLE_NOT_APPLICABLE = (
    "Not applicable: the receiver reports no outage on this sequence by the outage rule, and an oracle diagnostic "
    "acts only inside an outage. The oracle variants are not run."
)
ORACLE_LABELS = {
    "declared": "declared filter",
    "oracle_tilt": "ORACLE DIAGNOSTIC: reference roll and pitch in the outage",
    "oracle_yaw": "ORACLE DIAGNOSTIC: reference yaw in the outage",
    "oracle_attitude": "ORACLE DIAGNOSTIC: reference attitude in the outage",
}
#: The smallest per-fix sigma the filter believes (``EskfConfig.gnss_per_fix_min_sigma_m``); the run reports how many
#: fixes are below it.
FLOOR_SIGMA_M = EskfConfig(imu_noise=DEFAULT_NOISE).gnss_per_fix_min_sigma_m
SEEDS = (0, 1, 2, 3, 4)
GNSS_VERTICAL_SIGMA_M = 100.0
#: Valid fixes whose horizontal difference from the reference exceeds this are 'wrong though marked valid'.
WRONG_FIX_M = 10.0
GATE_ALPHA = 0.001  # the FDIR default, ADR-0005


def variants_for(spans: list[tuple[float, float]]) -> tuple[str, ...]:
    """The variants to run: all of them with an outage, the declared and per-fix variants without one."""
    return ALL_VARIANTS if spans else VARIANTS


def imu_noise() -> ImuNoiseModel:
    return ImuNoiseModel(
        gyro_noise_density=max(GYRO_DENSITY_SOURCES_DEG) * DEG,
        accel_noise_density=max(ACCEL_DENSITY_SOURCES_UG) * UG,
        gyro_bias_rw=DEFAULT_NOISE.gyro_bias_rw,
        accel_bias_rw=DEFAULT_NOISE.accel_bias_rw,
    )


def receiver_sigma_m(root: str | Path, seq: str, fixes: ud.GgaFixes) -> float:
    """Per-axis horizontal sigma: the RMS of the receiver's own latitude and longitude sigmas at its valid fixes."""
    gst = ud.read_gst(Path(root) / seq / ud.NMEA_FILES[seq])
    valid = fixes.utc_s[(fixes.quality > 0) & np.isfinite(fixes.lat_deg)]
    idx = np.searchsorted(gst.utc_s, valid)
    ok = (idx < len(gst)) & (gst.utc_s[np.minimum(idx, len(gst) - 1)] == valid)
    i = idx[ok]
    variance = 0.5 * (gst.sigma_lat[i] ** 2 + gst.sigma_lon[i] ** 2)
    variance = variance[np.isfinite(variance)]  # a NaN or infinite sigma is dropped by `build`, so it is not averaged
    if variance.size < 10:
        raise SequenceError(f"{seq}: fewer than 10 valid fixes have a matching, finite GST sentence")
    return float(np.sqrt(np.mean(variance)))


def usable_variance_mask(cov: np.ndarray) -> np.ndarray:
    """True for a fix whose three variances are finite and not negative: the filter raises on any other."""
    c = np.asarray(cov, dtype=float)
    return np.asarray(np.all(np.isfinite(c) & (c >= 0.0), axis=1))


def variance_report(cov: np.ndarray, floor_sigma_m: float = FLOOR_SIGMA_M) -> dict[str, int]:
    """Fixes the filter would refuse (``unusable``) and usable ones it would raise to the floor (``below_floor``)."""
    c = np.asarray(cov, dtype=float)
    ok = usable_variance_mask(c)
    below = ok & np.any(c < floor_sigma_m**2, axis=1)
    return {"unusable": int((~ok).sum()), "below_floor": int(below.sum())}


def epochs_not_valid(fixes: ud.GgaFixes) -> int:
    """GGA epochs the reader does not hand to the filter: quality 0 or no position."""
    return int(np.sum((fixes.quality <= 0) | ~np.isfinite(fixes.lat_deg)))


@contextlib.contextmanager
def oracle_attitude(seq: EurocSequence, span: tuple[float, float], mode: str) -> Iterator[None]:
    """ORACLE DIAGNOSTIC, not a filter: replace part of the attitude with the reference's inside one outage.

    After every IMU step whose time lies in ``[span[0], span[1])`` the filter's attitude is rebuilt from roll, pitch
    and heading (the dataset's convention): ``oracle_tilt`` takes the reference's roll and pitch and keeps the filter's
    heading, ``oracle_yaw`` takes the reference's heading and keeps the filter's roll and pitch, ``oracle_attitude``
    takes all three. The covariance is not touched. The filter's code is not changed: the method is wrapped for the
    length of the ``with`` block and restored on exit, also on an error. The step times are the sum of the steps taken,
    from the first IMU sample, which is how the run steps through the IMU, so the result is deterministic.
    """
    if mode not in ORACLE_VARIANTS:
        raise ValueError(f"oracle mode must be one of {', '.join(ORACLE_VARIANTS)}, got {mode!r}")
    t0 = float(seq.imu.t[0])
    start, stop = span[0] - t0, span[1] - t0
    timeline = seq.imu.t - t0
    ref_roll, ref_pitch, ref_heading = ud.rotation_to_rpy(interpolate_trajectory(seq.truth, seq.imu.t).rotations)
    original = ErrorStateKalmanFilter._propagate
    clock = {"t": 0.0}

    def wrapped(self: ErrorStateKalmanFilter, x: Any, accel: np.ndarray, gyro: np.ndarray, dt: float) -> None:
        original(self, x, accel, gyro, dt)
        clock["t"] += dt
        t = clock["t"]
        if not start <= t < stop:
            return
        k = min(int(np.searchsorted(timeline, t)), len(timeline) - 1)
        roll, pitch, heading = (float(v) for v in ud.rotation_to_rpy(x["R"]))
        if mode in ("oracle_tilt", "oracle_attitude"):
            roll, pitch = float(ref_roll[k]), float(ref_pitch[k])
        if mode in ("oracle_yaw", "oracle_attitude"):
            heading = float(ref_heading[k])
        x["R"] = ud.rpy_to_rotation(np.array([roll]), np.array([pitch]), np.array([heading]))[0]

    ErrorStateKalmanFilter._propagate = wrapped  # type: ignore[method-assign]
    try:
        yield
    finally:
        ErrorStateKalmanFilter._propagate = original  # type: ignore[method-assign]


def build(
    root: str | Path, seq_name: str = SEQUENCE
) -> tuple[EurocSequence, GnssFix, list[tuple[float, float]], dict[str, Any]]:
    """The sequence in the filter's types, the receiver's valid fixes, the outages and some facts about them."""
    base = ud.load_sequence(root, seq_name)
    fixes = ud.load_gga(root, seq_name)
    ref = base.reference
    rot = ud.rpy_to_rotation(ref.rpy_deg[:, 0], ref.rpy_deg[:, 1], ref.rpy_deg[:, 2])
    poses = np.tile(np.eye(4), (len(ref), 1, 1))
    poses[:, :3, :3] = rot
    poses[:, :3, 3] = base.truth_enu
    truth = Trajectory(t=base.truth_t, poses=poses, name=f"urbannav_{seq_name}_reference")
    velocity = np.einsum("nij,nj->ni", rot, ref.vel_body)
    zeros = np.zeros((len(ref), 3))
    seq = EurocSequence(
        name=seq_name,
        imu=base.imu,
        truth=truth,
        velocity=velocity,
        gyro_bias=zeros,
        accel_bias=zeros,
        noise=imu_noise(),
        noise_source="declared: larger published MTi-10 densities, repository bias random walks",
        sha256=base.sha256,
        notes=base.notes,
        dataset=ud.DATASET,
        slug=ud.SLUG,
        bias_known=False,
    )
    valid = (fixes.quality > 0) & np.isfinite(fixes.lat_deg)
    enu, _ = ud.llh_to_enu(fixes.lat_deg[valid], fixes.lon_deg[valid], fixes.height_m[valid], origin=base.origin_llh)
    sigma_h = receiver_sigma_m(root, seq_name, fixes)
    gst = ud.read_gst(Path(root) / seq_name / ud.NMEA_FILES[seq_name])
    idx = np.searchsorted(gst.utc_s, fixes.utc_s[valid])
    found = (idx < len(gst)) & (gst.utc_s[np.minimum(idx, len(gst) - 1)] == fixes.utc_s[valid])
    own = np.full((int(valid.sum()), 3), np.nan)
    own[found, 0] = gst.sigma_lat[idx[found]] ** 2
    own[found, 1] = gst.sigma_lon[idx[found]] ** 2
    own[:, 2] = GNSS_VERTICAL_SIGMA_M**2
    own[~found, :2] = sigma_h**2  # a fix with no GST sentence takes the scalar
    # The filter raises on a negative, NaN or infinite variance, so such a fix is dropped here and counted.
    report = variance_report(own)
    keep = usable_variance_mask(own)
    enu, own = enu[keep], own[keep]
    gnss = GnssFix(t=(fixes.utc_s[valid] - base.epoch_unix_s)[keep], positions=enu, cov=own, name="f9p")
    spans = [(a - base.epoch_unix_s, b - base.epoch_unix_s) for a, b in ud.outage_intervals(fixes)]
    horiz = np.linalg.norm(
        enu[:, :2] - np.column_stack([np.interp(gnss.t, base.truth_t, base.truth_enu[:, k]) for k in range(2)]), axis=1
    )
    info = {
        "sigma_h": sigma_h,
        "fix_difference_m": horiz,
        "fix_sigma_h_m": np.sqrt(0.5 * (own[:, 0] + own[:, 1])),
        "fix_t": gnss.t,
        "epochs_not_valid": epochs_not_valid(fixes),
        "fixes_variance_unusable": report["unusable"],
        "fixes_variance_below_floor": report["below_floor"],
    }
    return seq, gnss, spans, info


def _nis(innovations: list[tuple[float, np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    t = np.array([i[0] for i in innovations])
    nis = np.array([float(r @ np.linalg.solve(s, r)) for _, r, s in innovations])
    return t, nis


def accel_only_error_m(seq: EurocSequence, span: tuple[float, float]) -> float:
    """Horizontal error at the end of an outage from integrating the accelerometer alone with the reference attitude.

    No gyroscope and no filter: the reference attitude is interpolated to every IMU sample and the start velocity and
    position are the reference's. What is left is the accelerometer's own error, so this is the drift the filter could
    not do better than if its attitude were as good as the reference's.
    """
    a, b = span
    m = (seq.imu.t >= a) & (seq.imu.t <= b)
    t, f = seq.imu.t[m], seq.imu.accel[m]
    rot = np.stack(
        [np.stack([np.interp(t, seq.truth.t, seq.truth.rotations[:, i, j]) for j in range(3)], -1) for i in range(3)], 1
    )
    u, _, vt = np.linalg.svd(rot)
    acc = np.einsum("nij,nj->ni", u @ vt, f) + np.array([0.0, 0.0, -float(np.linalg.norm(GRAVITY))])
    v0 = np.array([np.interp(a, seq.truth.t, seq.velocity[:, k]) for k in range(3)])
    p0 = np.array([np.interp(a, seq.truth.t, seq.truth.positions[:, k]) for k in range(3)])
    dt = np.diff(t, prepend=t[0])
    pos = p0 + np.cumsum((v0 + np.cumsum(acc * dt[:, None], axis=0)) * dt[:, None], axis=0)
    ref_end = np.array([np.interp(t[-1], seq.truth.t, seq.truth.positions[:, k]) for k in range(2)])
    return float(np.linalg.norm(pos[-1, :2] - ref_end))


#: The 95% chi-square level for 2 degrees of freedom, for the share of epochs inside the horizontal 95% ellipse.
CHI2_95_DOF2 = 5.991464547107979
#: The share of a Gaussian inside plus or minus two sigma: the value the per-axis coverage is read against.
COVERAGE_2SIGMA_GAUSSIAN = math.erf(2.0 / math.sqrt(2.0))
#: Percentiles of the fixes' horizontal difference from the reference that the aided run reports.
FIX_PERCENTILES = (50, 95, 99)


def rejection_intervals(rejected: int, offered: int, nis: np.ndarray, gate_level: float) -> dict[str, Any]:
    """The Wilson intervals of the rejection rate, on the raw count and on the effective count (ADR-0029).

    The raw interval takes the ``offered`` fixes as independent. The effective one replaces their number by the
    effective sample size of the 0/1 series "the fix's NIS is over the gate's level" and the count by
    ``rejected * ess / offered``, which is how ``fdir_false_alarm`` pools a rate. A series with no fix over the level
    (or all of them over it) is constant and has no autocorrelation: it counts as ``offered`` independent samples,
    the generous reading, so the effective interval is then the raw one, and ``fix_rejection_ess_defined`` is 0.
    """
    ess, _ = effective_samples((np.asarray(nis, dtype=float) > gate_level).astype(float))
    defined = math.isfinite(ess)
    if not defined:
        ess = float(offered)
    lo, hi = wilson_interval(rejected, offered)
    eff_lo, eff_hi = wilson_interval(rejected * ess / offered if offered else 0.0, ess)
    return {
        "fix_gate_alpha": GATE_ALPHA,
        "fix_rejections_expected": offered * GATE_ALPHA,
        "fix_rejection_wilson_lo": lo,
        "fix_rejection_wilson_hi": hi,
        "fix_rejection_ess": ess,
        "fix_rejection_ess_defined": int(defined),
        "fix_rejection_eff_wilson_lo": eff_lo,
        "fix_rejection_eff_wilson_hi": eff_hi,
    }


def aided_summary(
    detail: dict[str, Any],
    stats: dict[str, Any],
    offered: int,
    fix_difference_m: np.ndarray,
    fix_sigma_h_m: np.ndarray,
    nis: np.ndarray | None = None,
    gate_level: float | None = None,
    nees_h: np.ndarray | None = None,
) -> dict[str, Any]:
    """The quantities of the aided run, over the whole recording. Aggregates only.

    * ``att_nees_mean``: the attitude error, ``log(R_est^T R_ref)``, against the filter's attitude covariance block
      (3 degrees of freedom). The filter perturbs its attitude on the right, so this is the matching error.
    * ``hor_coverage_2sigma``: the share of (epoch, axis) pairs, east and north pooled, whose error is within two of the
      filter's own sigmas. The vertical axis is left out, because its sigma is declared very large on purpose.
    * ``fix_*``: the receiver's fixes themselves against the reference, without the filter: percentiles of the
      horizontal difference, and the mean of (horizontal difference / receiver sigma) squared, which is 2 when the
      receiver's sigma is right and the errors are Gaussian.
    * ``fix_rejection_*``, with ``nis`` and ``gate_level``: the Wilson intervals of :func:`rejection_intervals`.
    * ``fixes_over_3sigma``, ``receiver_sigma_median_m``, ``claimed_sigma_median_m``: the fixes more than three of the
      receiver's own per-axis sigmas from the reference, the receiver's median per-axis sigma, and the median per-axis
      sigma the filter claims for its position. ``nis_mean`` and ``fix_gate_level`` come with ``nis``.
    * ``*_nees_third1..3``: the mean of each NEES series over the first, middle and last third of the run.
    * ``*_nees_ess``, with ``nees_h`` for the horizontal one: the effective sample size of each NEES series, and
      whether it reached the largest window (then it is an upper bound, ADR-0029). The means are over every IMU step,
      so they are far from independent samples, and the effective size is what says how many there are.
    """
    est, ref, cov = detail["est"], detail["reference"], detail["position_cov"]
    err = est.positions - ref.positions
    sigma = np.sqrt(np.stack([cov[:, 0, 0], cov[:, 1, 1]], axis=1))
    out: dict[str, Any] = {
        "aided": 1,
        "hor_coverage_2sigma": float(np.mean(np.abs(err[:, :2]) <= 2.0 * sigma)),
        "fixes_used": int(stats.get("gnss_updates_used", 0)),
        "fix_rejection_rate": float(stats.get("gnss_updates_rejected", 0)) / offered if offered else math.nan,
        "fix_nees_mean": float(np.mean((fix_difference_m / fix_sigma_h_m) ** 2)),
    }
    out["fixes_over_3sigma"] = int(np.sum(fix_difference_m > 3.0 * fix_sigma_h_m))
    out["receiver_sigma_median_m"] = float(np.median(fix_sigma_h_m))
    out["claimed_sigma_median_m"] = float(np.median(np.sqrt(0.5 * (cov[:, 0, 0] + cov[:, 1, 1]))))
    if nis is not None and gate_level is not None:
        out["nis_mean"] = float(np.mean(nis))
        out["fix_gate_level"] = float(gate_level)
        out.update(rejection_intervals(int(stats.get("gnss_updates_rejected", 0)), offered, nis, gate_level))
    if nees_h is not None:
        out["hor_nees_ess"], truncated = effective_samples(nees_h)
        out["hor_nees_ess_truncated"] = int(truncated)
        for k, part in enumerate(np.array_split(nees_h, 3), start=1):
            out[f"hor_nees_third{k}"] = float(np.mean(part))
    rot_cov = detail.get("rotation_cov")
    if rot_cov is not None:
        dtheta = rot_log_batch(np.einsum("nji,njk->nik", est.rotations, ref.rotations))
        nees_att = np.einsum("ni,ni->n", dtheta, np.linalg.solve(rot_cov, dtheta[..., None])[..., 0])
        out["att_nees_mean"] = float(np.mean(nees_att))
        out["att_nees_ess"], truncated = effective_samples(nees_att)
        out["att_nees_ess_truncated"] = int(truncated)
        for k, part in enumerate(np.array_split(nees_att, 3), start=1):
            out[f"att_nees_third{k}"] = float(np.mean(part))
    for q in FIX_PERCENTILES:
        out[f"fix_err_p{q}_m"] = float(np.percentile(fix_difference_m, q))
    return out


def run_once(
    seq: EurocSequence,
    gnss: GnssFix,
    spans: list[tuple[float, float]],
    info: dict[str, Any],
    seed: int,
    variant: str = "declared",
) -> dict[str, Any]:
    t0 = float(seq.imu.t[0])
    opts = RunOptions(
        gnss_sigma_m=info["sigma_h"],
        gnss_vertical_sigma_m=GNSS_VERTICAL_SIGMA_M,
        outages=tuple((a - t0, b - a) for a, b in spans),
        seed=seed,
        init_bias="static",
        gnss_per_fix_covariance=variant == "per_fix",
    )
    inn: list[tuple[float, np.ndarray, np.ndarray]] = []
    detail: dict[str, Any] = {}
    if variant in ORACLE_VARIANTS:
        if not spans:
            raise SequenceError("an oracle diagnostic needs an outage to act in")
        guard: contextlib.AbstractContextManager[None] = oracle_attitude(seq, spans[0], variant)
    else:
        guard = contextlib.nullcontext()
    with guard:
        record = run_sequence(seq, opts, innovations_out=inn, gnss_override=gnss, detail_out=detail)
    t_i, nis = _nis(inn)
    level = chi2_threshold(3, GATE_ALPHA)
    wrong = np.interp(t_i, info["fix_t"], info["fix_difference_m"]) > WRONG_FIX_M
    est, ref, cov = detail["est"], detail["reference"], detail["position_cov"]
    t = est.t - t0
    err = est.positions - ref.positions
    eh, ev = np.linalg.norm(err[:, :2], axis=1), np.abs(err[:, 2])
    ph = cov[:, :2, :2]
    nees_h = np.einsum("ni,ni->n", err[:, :2], np.linalg.solve(ph, err[:, :2][..., None])[..., 0])
    claimed_h = np.sqrt(np.trace(ph, axis1=1, axis2=2) / 2.0)
    att = (
        np.linalg.norm(rot_log_batch(np.einsum("nji,njk->nik", est.rotations, ref.rotations)), axis=1) * 180.0 / math.pi
    )
    out: dict[str, Any] = {
        "seed": seed,
        "variant": variant,
        "hor_rmse_m": float(np.sqrt(np.mean(eh**2))),
        "hor_nees_mean": float(np.mean(nees_h)),
        "hor_inside_95": float(np.mean(nees_h <= CHI2_95_DOF2)),
        "ver_rmse_m": float(np.sqrt(np.mean(ev**2))),
        "ate_rmse_m": record["headline"]["ate_rmse_m"],
        "fixes_total": int(nis.size),
        "fixes_over_gate": int((nis > level).sum()),
        "wrong_fixes": int(wrong.sum()),
        "wrong_fixes_over_gate": int((nis[wrong] > level).sum()),
        "gnss_updates_rejected": int(record["stats"].get("gnss_updates_rejected", 0)),
        "gnss_channel_faulted": int(record["stats"].get("fdir_gnss_faulted", 0)),
        "gnss_reaccepted": int(record["stats"].get("fdir_gnss_reaccepted", 0)),
        "start_bias_at_rest": int(bool(record["inputs"]["static_bias"]["quiet"])),
        "epochs_not_valid": int(info["epochs_not_valid"]),
        "fixes_variance_unusable": int(info["fixes_variance_unusable"]),
        "fixes_variance_below_floor": int(info["fixes_variance_below_floor"]),
    }
    if spans:
        a, b = spans[0][0] - t0, spans[0][1] - t0
        i_a = max(int(np.searchsorted(t, a)) - 1, 0)
        i_b = min(int(np.searchsorted(t, b)), len(t) - 1)
        inside = (t >= a) & (t < b)
        out["hor_err_median_before_m"] = float(np.median(eh[t < a]))
        out["hor_nees_before"] = float(np.mean(nees_h[t < a]))
        out["hor_err_at_start_m"] = float(eh[i_a])
        out["hor_claimed_at_start_m"] = float(claimed_h[i_a])
        out["hor_err_peak_in_outage_m"] = float(eh[inside].max())
        out["hor_err_at_end_m"] = float(eh[i_b])
        out["hor_claimed_at_end_m"] = float(claimed_h[i_b])
        out["hor_nees_outage"] = float(np.mean(nees_h[inside]))
        out["ver_err_at_end_m"] = float(ev[i_b])
        out["att_err_at_start_deg"] = float(att[i_a])
        out["att_err_at_end_deg"] = float(att[i_b])
        out["accel_only_hor_err_at_end_m"] = accel_only_error_m(seq, spans[0])
        e_roll, e_pitch, e_head = ud.rotation_to_rpy(est.rotations)
        r_roll, r_pitch, r_head = ud.rotation_to_rpy(ref.rotations)
        d_roll, d_pitch = e_roll - r_roll, e_pitch - r_pitch
        d_yaw = (e_head - r_head + 180.0) % 360.0 - 180.0
        for when, idx in (("start", i_a), ("end", i_b)):
            out[f"att_roll_err_at_{when}_deg"] = float(d_roll[idx])
            out[f"att_pitch_err_at_{when}_deg"] = float(d_pitch[idx])
            out[f"att_yaw_err_at_{when}_deg"] = float(d_yaw[idx])
        returned = (t_i - t0) >= b
        out["fixes_after_outage"] = int(returned.sum())
        out["fixes_after_outage_over_gate"] = int((nis[returned] > level).sum())
        if returned.any():
            out["nis_first_return"] = float(nis[returned][0])
        after = t >= b + 10.0
        if after.any():
            out["hor_err_median_after_m"] = float(np.median(eh[after]))
    else:
        out.update(
            aided_summary(
                detail,
                record["stats"],
                int(nis.size),
                info["fix_difference_m"],
                info["fix_sigma_h_m"],
                nis=nis,
                gate_level=level,
                nees_h=nees_h,
            )
        )
    return out


QUANTITIES = (
    ("hor_rmse_m", "Horizontal position RMSE over the recording", "m"),
    ("hor_nees_mean", "Horizontal mean NEES (2 degrees of freedom, expected 2)", ""),
    ("hor_inside_95", "Share of epochs inside the horizontal 95% ellipse (expected 0.95)", ""),
    ("ver_rmse_m", "Vertical RMSE (the height is almost unused by design)", "m"),
    ("hor_err_median_before_m", "Horizontal error, median before the outage", "m"),
    ("hor_nees_before", "Horizontal mean NEES before the outage", ""),
    ("hor_err_at_start_m", "Horizontal error when the outage starts", "m"),
    ("hor_claimed_at_start_m", "Claimed horizontal sigma when the outage starts", "m"),
    ("att_err_at_start_deg", "Attitude error when the outage starts", "deg"),
    ("hor_err_peak_in_outage_m", "Peak horizontal error in the outage", "m"),
    ("hor_err_at_end_m", "Horizontal error when the outage ends", "m"),
    ("hor_claimed_at_end_m", "Claimed horizontal sigma when the outage ends", "m"),
    ("att_err_at_end_deg", "Attitude error when the outage ends", "deg"),
    (
        "accel_only_hor_err_at_end_m",
        "For comparison: horizontal error from the accelerometer alone with the reference attitude",
        "m",
    ),
    ("ver_err_at_end_m", "Vertical error when the outage ends", "m"),
    ("hor_nees_outage", "Horizontal mean NEES inside the outage", ""),
    ("hor_err_median_after_m", "Horizontal error, median from 10 s after the outage", "m"),
    ("att_roll_err_at_start_deg", "Roll error when the outage starts (estimate minus reference)", "deg"),
    ("att_pitch_err_at_start_deg", "Pitch error when the outage starts (estimate minus reference)", "deg"),
    ("att_yaw_err_at_start_deg", "Yaw error when the outage starts (estimate minus reference)", "deg"),
    ("att_roll_err_at_end_deg", "Roll error when the outage ends (estimate minus reference)", "deg"),
    ("att_pitch_err_at_end_deg", "Pitch error when the outage ends (estimate minus reference)", "deg"),
    ("att_yaw_err_at_end_deg", "Yaw error when the outage ends (estimate minus reference)", "deg"),
    ("nis_first_return", "NIS of the first fix after the outage (3 degrees of freedom)", ""),
    ("fixes_after_outage", "Fixes offered after the outage", "count"),
    ("fixes_after_outage_over_gate", "Of those, over the 0.1% chi-square level", "count"),
    ("epochs_not_valid", "Receiver epochs the reader did not pass on (no fix or no position)", "count"),
    ("fixes_variance_unusable", "Fixes dropped because a reported variance was negative, NaN or infinite", "count"),
    ("fixes_variance_below_floor", "Fixes with a reported sigma below the filter's floor", "count"),
    ("start_bias_at_rest", "The start-bias stretch was judged at rest (1 yes, 0 no)", "flag"),
    ("fixes_total", "Valid fixes offered to the filter", "count"),
    ("gnss_updates_rejected", "Fixes the filter rejected", "count"),
    ("gnss_channel_faulted", "GNSS channel declared faulty by the end", "count"),
    ("gnss_reaccepted", "Times a faulty channel was taken back", "count"),
    ("fixes_over_gate", "Fixes whose NIS is over the 0.1% chi-square level", "count"),
    ("wrong_fixes", "Valid fixes over 10 m from the reference", "count"),
    ("wrong_fixes_over_gate", "Of those, over the 0.1% chi-square level", "count"),
)
#: What the aided run (a sequence without an outage) reports, over the whole recording. Several keys are those of
#: :data:`QUANTITIES`, with the same meaning.
AIDED_QUANTITIES = (
    ("fixes_total", "Valid fixes offered to the filter", "count"),
    ("fixes_used", "Fixes the filter used", "count"),
    ("gnss_updates_rejected", "Fixes the filter rejected", "count"),
    ("fix_rejection_rate", "Share of the offered fixes the gate rejected", ""),
    ("fix_gate_alpha", "The gate's alpha (the FDIR default)", ""),
    ("fix_gate_level", "The gate's level on the NIS (3 degrees of freedom)", ""),
    ("nis_mean", "Mean NIS of the offered fixes", ""),
    (
        "fix_rejections_expected",
        "Rejections expected at that alpha if every fix were consistent (offered x alpha)",
        "count",
    ),
    ("fix_rejection_wilson_lo", "Wilson 95% interval of the rejection rate on the raw count, lower end", ""),
    ("fix_rejection_wilson_hi", "Wilson 95% interval of the rejection rate on the raw count, upper end", ""),
    (
        "fix_rejection_ess",
        "Effective number of fixes behind the rate (effective sample size of the over-the-level series)",
        "count",
    ),
    (
        "fix_rejection_ess_defined",
        "That size could be estimated (1 yes, 0 no: the series is constant, so it counts every fix)",
        "flag",
    ),
    ("fix_rejection_eff_wilson_lo", "Wilson 95% interval on the effective count, lower end", ""),
    ("fix_rejection_eff_wilson_hi", "Wilson 95% interval on the effective count, upper end", ""),
    ("gnss_channel_faulted", "GNSS channel declared faulty by the end", "count"),
    ("gnss_reaccepted", "Times a faulty channel was taken back", "count"),
    ("hor_nees_mean", "Horizontal mean NEES over the whole run (2 degrees of freedom, expected 2)", ""),
    ("hor_nees_third1", "Horizontal mean NEES, first third of the run", ""),
    ("hor_nees_third2", "Horizontal mean NEES, middle third of the run", ""),
    ("hor_nees_third3", "Horizontal mean NEES, last third of the run", ""),
    ("hor_nees_ess", "Effective sample size of the horizontal NEES series (it has one value per IMU step)", "count"),
    ("hor_nees_ess_truncated", "That size is an upper bound (1 yes, 0 no)", "flag"),
    ("att_nees_mean", "Attitude mean NEES over the whole run (3 degrees of freedom, expected 3)", ""),
    ("att_nees_third1", "Attitude mean NEES, first third of the run", ""),
    ("att_nees_third2", "Attitude mean NEES, middle third of the run", ""),
    ("att_nees_third3", "Attitude mean NEES, last third of the run", ""),
    ("att_nees_ess", "Effective sample size of the attitude NEES series", "count"),
    ("att_nees_ess_truncated", "That size is an upper bound (1 yes, 0 no)", "flag"),
    (
        "hor_coverage_2sigma",
        f"Pooled 2-sigma per-axis coverage, east and north (a Gaussian gives {COVERAGE_2SIGMA_GAUSSIAN:.4f})",
        "",
    ),
    ("hor_inside_95", "Share of epochs inside the horizontal 95% ellipse (expected 0.95)", ""),
    ("hor_rmse_m", "Horizontal position RMSE over the recording", "m"),
    ("ver_rmse_m", "Vertical RMSE (the height is almost unused by design)", "m"),
    ("ate_rmse_m", "Absolute trajectory error, RMSE, no alignment", "m"),
    ("fix_err_p50_m", "Fix horizontal difference from the reference, median", "m"),
    ("fix_err_p95_m", "Fix horizontal difference, 95th percentile", "m"),
    ("fix_err_p99_m", "Fix horizontal difference, 99th percentile", "m"),
    ("fixes_over_3sigma", "Fixes more than 3 of the receiver's own per-axis sigmas from the reference", "count"),
    ("receiver_sigma_median_m", "Receiver's own reported per-axis sigma, median", "m"),
    ("claimed_sigma_median_m", "Per-axis position sigma the filter claims, median over the run", "m"),
    (
        "fix_nees_mean",
        "Fixes alone: mean of (horizontal difference / receiver sigma) squared (expected 2)",
        "",
    ),
    ("fixes_over_gate", "Fixes whose NIS is over the 0.1% chi-square level", "count"),
    ("wrong_fixes", "Valid fixes over 10 m from the reference", "count"),
    ("wrong_fixes_over_gate", "Of those, over the 0.1% chi-square level", "count"),
    ("epochs_not_valid", "Receiver epochs the reader did not pass on (no fix or no position)", "count"),
    ("fixes_variance_unusable", "Fixes dropped because a reported variance was negative, NaN or infinite", "count"),
    ("fixes_variance_below_floor", "Fixes with a reported sigma below the filter's floor", "count"),
    ("start_bias_at_rest", "The start-bias stretch was judged at rest (1 yes, 0 no)", "flag"),
)
#: Keys only the aided run has. A sequence with rows for any of them is an aided sequence.
AIDED_ONLY_KEYS = frozenset(k for k, _, _ in AIDED_QUANTITIES) - frozenset(k for k, _, _ in QUANTITIES)
#: Rows of the aided run that are in the CSV and not in the page tables: the absolute trajectory error is a
#: three-dimensional number that the unused height dominates, so the page quotes the horizontal RMSE.
NOT_ON_PAGE = frozenset({"ate_rmse_m"})
CSV_COLUMNS = ("sequence", "variant", "seed", "quantity", "value", "unit")


def rows_for(seq_name: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in results:
        for key, _label, unit in AIDED_QUANTITIES if r.get("aided") else QUANTITIES:
            if r.get(key) is not None:
                v = r[key]
                rows.append(
                    {
                        "sequence": seq_name,
                        "variant": r["variant"],
                        "seed": r["seed"],
                        "quantity": key,
                        "value": v if isinstance(v, int) else f"{v:.4g}",
                        "unit": unit,
                    }
                )
    return rows


# ---------------------------------------------------------------------- output

#: Sequence names are those of ``navkit urbannav fetch``. The first is the one the older blocks of the page show.
SEQUENCE_TITLES = {"tunnel1": "Tunnel-1", "deepurban1": "Deep-Urban-1"}


def declared_markdown(_rows: list[dict[str, Any]] | None = None) -> str:
    lines = ["| Setting | Value | Meaning |", "|---|---|---|"]
    lines += [f"| {k} | {v} | {m} |" for k, (v, m) in DECLARED.items()]
    return "\n".join(lines)


def rows_of(rows: list[dict[str, Any]], sequence: str) -> list[dict[str, Any]]:
    """The rows of one sequence. A block never shows another sequence's rows."""
    return [r for r in rows if r["sequence"] == sequence]


def not_run_markdown(sequence: str) -> str:
    return (
        f"No rows for {SEQUENCE_TITLES.get(sequence, sequence)} are in the committed CSV, so it has not been run "
        "for this page. The table appears here when the CSV has its rows."
    )


def is_aided(rows: list[dict[str, Any]]) -> bool:
    """True when the rows hold quantities that only the aided run (a sequence without an outage) reports."""
    return any(r["quantity"] in AIDED_ONLY_KEYS for r in rows)


def run_markdown(rows: list[dict[str, Any]], variant: str = "declared", sequence: str = SEQUENCE) -> str:
    rows = [r for r in rows_of(rows, sequence) if r["variant"] == variant]
    if not rows:
        return not_run_markdown(sequence)
    quantities = AIDED_QUANTITIES if is_aided(rows) else QUANTITIES
    seeds = sorted({int(r["seed"]) for r in rows})
    by = {(int(r["seed"]), r["quantity"]): r["value"] for r in rows}
    head = "| Quantity | " + " | ".join(f"seed {s}" for s in seeds) + " | Unit |"
    lines = [head, "|---|" + "---:|" * len(seeds) + "---|"]
    for key, label, unit in quantities:
        if key in NOT_ON_PAGE and quantities is AIDED_QUANTITIES:
            continue
        if any((s, key) in by for s in seeds):
            lines.append(f"| {label} | " + " | ".join(str(by.get((s, key), "")) for s in seeds) + f" | {unit} |")
    return "\n".join(lines)


def _block(variant: str, sequence: str = SEQUENCE) -> Callable[[list[dict[str, Any]]], str]:
    def render(rows: list[dict[str, Any]]) -> str:
        return run_markdown(rows, variant, sequence)

    return render


ORACLE_QUANTITIES = ("hor_err_at_end_m", "gnss_updates_rejected")


def oracle_markdown(rows: list[dict[str, Any]], sequence: str = SEQUENCE) -> str:
    """The declared filter next to the oracle diagnostics, per seed. Every oracle row is labelled as one.

    A sequence that was run without an outage has no oracle rows, and the block says so. A sequence with no rows at all
    has not been run.
    """
    rows = rows_of(rows, sequence)
    if not rows:
        return not_run_markdown(sequence)
    if is_aided(rows) or not any(r["variant"] in ORACLE_VARIANTS for r in rows):
        return ORACLE_NOT_APPLICABLE
    seeds = sorted({int(r["seed"]) for r in rows})
    by = {(r["variant"], int(r["seed"]), r["quantity"]): r["value"] for r in rows}
    meta = {k: (label, unit) for k, label, unit in QUANTITIES}
    head = "| Variant | Quantity | " + " | ".join(f"seed {s}" for s in seeds) + " | Unit |"
    lines = [head, "|---|---|" + "---:|" * len(seeds) + "---|"]
    for variant in ("declared", *ORACLE_VARIANTS):
        for n, key in enumerate(ORACLE_QUANTITIES):
            if not any((variant, s, key) in by for s in seeds):
                continue
            label, unit = meta[key]
            cells = " | ".join(str(by.get((variant, s, key), "")) for s in seeds)
            lines.append(f"| {ORACLE_LABELS[variant] if n == 0 else ''} | {label} | {cells} | {unit} |")
    return "\n".join(lines)


def _oracle_block(sequence: str) -> Callable[[list[dict[str, Any]]], str]:
    def render(rows: list[dict[str, Any]]) -> str:
        return oracle_markdown(rows, sequence)

    return render


DEEP_URBAN = "deepurban1"
BLOCKS: dict[str, Callable[[list[dict[str, Any]]], str]] = {
    f"urbannav-run-{v.replace('_', '-')}": _block(v) for v in VARIANTS
}
#: The Deep-Urban-1 section of the page: the same variants, filtered to that sequence.
BLOCKS.update({f"urbannav-deep-urban-run-{v.replace('_', '-')}": _block(v, DEEP_URBAN) for v in VARIANTS})
CODE_BLOCKS: dict[str, Callable[[list[dict[str, Any]]], str]] = {
    "urbannav-declared": declared_markdown,
    "urbannav-run-oracle": oracle_markdown,
    "urbannav-deep-urban-oracle": _oracle_block(DEEP_URBAN),
}


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write ``rows`` to ``path``, replacing the rows of those sequences and keeping the rows of any other."""
    ud.write_merged_csv(path, CSV_COLUMNS, rows)


def rows_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_block(path: str | Path, name: str, block: str) -> None:
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text or text.index(start) > text.index(end):
        raise ValueError(f"{page} needs the lines {start} and {end}, in that order")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    page.write_text(f"{head}{start}\n\n{block}\n\n{end}{tail}", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="navkit urbannav run", description="Run the filter on UrbanNav with real fixes.")
    p.add_argument("--root", default="data/raw/urbannav")
    p.add_argument("--sequence", "-s", default=SEQUENCE)
    p.add_argument(
        "--csv", default=None, help="write one row per seed and quantity; other sequences' rows in the file are kept"
    )
    p.add_argument("--from-csv", default=None, help="rebuild the tables from a saved CSV; runs nothing")
    p.add_argument(
        "--page",
        default=None,
        help="fill the urbannav-run, urbannav-deep-urban and urbannav-declared blocks of this page from the CSV "
        "(needs --csv or --from-csv, so that every sequence is filled from one file)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.page and not (args.csv or args.from_csv):
        print(
            "error: --page needs --csv or --from-csv, so that every block is filled from the same file", file=sys.stderr
        )
        return 2
    try:
        if args.from_csv:
            rows = rows_from_csv(args.from_csv)
        else:
            seq, gnss, spans, info = build(args.root, args.sequence)
            print(
                f"{len(gnss)} fixes passed on, {info['epochs_not_valid']} epochs not passed on (no fix or no "
                f"position), {info['fixes_variance_unusable']} dropped for an unusable variance, "
                f"{info['fixes_variance_below_floor']} below the filter's floor, {len(spans)} outage(s), "
                f"declared horizontal sigma {info['sigma_h']:.3f} m",
                file=sys.stderr,
            )
            if not spans:
                print(f"{args.sequence}: no outage, so this is the aided run. {ORACLE_NOT_APPLICABLE}", file=sys.stderr)
            results = []
            for variant in variants_for(spans):
                for seed in SEEDS:
                    results.append(run_once(seq, gnss, spans, info, seed, variant))
                    print(f"{variant} seed {seed} done", file=sys.stderr)
            rows = rows_for(args.sequence, results)
    except SequenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.csv:
        try:
            write_csv(args.csv, rows)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.page:
        all_rows = rows_from_csv(args.csv or args.from_csv)
        try:
            for name, fn in {**BLOCKS, **CODE_BLOCKS}.items():
                write_block(args.page, name, fn(all_rows))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if not (args.csv or args.page):
        print(
            declared_markdown()
            + "".join(f"\n\n{v}\n\n{run_markdown(rows, v, args.sequence)}" for v in VARIANTS)
            + f"\n\n{oracle_markdown(rows, args.sequence)}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
