"""Deterministic degradation injection.

This is the layer that turns a healthy replay into an experiment. It takes the
clean synthetic sensor streams produced by :mod:`navkit.sensors` and applies,
in a fixed order:

1. channel outages (GNSS, vision, IMU),
2. time offsets (vision, GNSS, IMU),
3. camera frame drops,
4. measurement noise (GNSS is already noisy by construction; IMU and vision
   noise are applied here),
5. a manifest of everything applied.

Determinism
-----------
Every stochastic step draws from an explicitly seeded
:class:`numpy.random.Generator` derived from the scenario seed and the channel
name. Two runs of the same scenario produce identical samples. The manifest
includes the seed and a hash of the scenario configuration, so a result file
can be tied back to the exact configuration that produced it.

Order matters and is fixed because it is observable: applying the time offset
before or after dropping frames changes which frames survive, and applying IMU
noise before or after a dropout changes the bias a filter sees on re-entry.
Those are documented consequences of the chosen order, not accidents.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..io.imu import ImuSample
from ..io.imu import apply_imu_noise as add_imu_noise
from ..types import GnssFix, Trajectory, VisionUpdate
from ..types import ImuSample as ImuType
from .config import Outage, Scenario


@dataclass
class InjectedStreams:
    """The degraded sensor streams handed to an estimator."""

    imu: ImuSample
    gnss: GnssFix
    vision: VisionUpdate
    manifest: dict[str, Any] = field(default_factory=dict)


def config_hash(scenario: Scenario, *, estimator: dict[str, Any] | None = None) -> str:
    """Stable short hash of a scenario, for reproducibility records.

    ``estimator`` is folded in when supplied. A benchmark record's hash is a
    provenance label: it is what lets a reader tell that two runs used the same
    setup. Hashing the scenario alone cannot do that, because the estimator is
    configured separately and several of its settings (``vision_fuse``,
    ``vision_anchor_modelled``, ``vision_keyframe_interval``, the anchor
    sigmas) change the filter without touching the scenario at all. Three
    structurally different filters then record one indistinguishable hash.

    Pass the resolved estimator config -- ``{"class": ..., **cfg.as_dict()}`` --
    not the raw override keys, so a record hashes the filter that actually ran.
    """
    payload_dict: dict[str, Any] = {"scenario": scenario.as_dict()}
    if estimator is not None:
        payload_dict["estimator"] = estimator
    payload = json.dumps(payload_dict, sort_keys=True, default=float)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def in_any(t: float, outages: list[Outage]) -> bool:
    return any(o.covers(t) for o in outages)


def mark_outages(t: np.ndarray, outages: list[Outage]) -> np.ndarray:
    """Boolean mask of samples inside any outage window."""
    if not outages or len(t) == 0:
        return np.zeros(len(t), dtype=bool)
    mask = np.zeros(len(t), dtype=bool)
    for o in outages:
        mask |= (t >= o.start_s) & (t < o.end_s)
    return mask


def apply_gnss_outage(gnss: GnssFix, outages: list[Outage], total_enabled: bool) -> GnssFix:
    """Mark fixes unavailable inside the outage windows.

    ``available`` is always populated, even when there is no outage, so that
    downstream code has one shape to handle.
    """
    mask = mark_outages(gnss.t, outages)
    available = np.ones(len(gnss), dtype=bool)
    available &= ~mask
    if not total_enabled:
        available[:] = False
    return GnssFix(
        t=gnss.t.copy(),
        positions=gnss.positions.copy(),
        cov=None if gnss.cov is None else gnss.cov.copy(),
        available=available,
        name=gnss.name,
    )


def apply_camera_drop(vision: VisionUpdate, drop_fraction: float, burst_period_s: float, seed: int) -> VisionUpdate:
    """Drop frames in correlated bursts.

    Within each period of ``burst_period_s`` a single contiguous burst of
    frames is dropped. The burst length is chosen so the overall dropped
    fraction matches ``drop_fraction``; the rounding remainder is carried into
    the last burst so the total is exact.

    A single contiguous burst is a simplification: real drops are neither
    perfectly uniform nor perfectly contiguous. It is used because the
    quantity that matters for a relative-pose front end is the *longest gap*
    between usable frames, and this generator controls that directly.
    """
    n = len(vision)
    dropped = np.zeros(n, dtype=bool)
    if drop_fraction <= 0.0 or n == 0:
        return VisionUpdate(
            t=vision.t.copy(),
            R_rel=vision.R_rel.copy(),
            t_rel=vision.t_rel.copy(),
            rot_cov=vision.rot_cov,
            trans_cov=vision.trans_cov,
            dropped=dropped,
            name=vision.name,
        )

    period_s = float(burst_period_s)
    total_drops = int(round(drop_fraction * n))
    if total_drops <= 0:
        return VisionUpdate(
            t=vision.t.copy(),
            R_rel=vision.R_rel.copy(),
            t_rel=vision.t_rel.copy(),
            rot_cov=vision.rot_cov,
            trans_cov=vision.trans_cov,
            dropped=dropped,
            name=vision.name,
        )

    t = vision.t
    span = float(t[-1] - t[0])
    n_periods = max(1, int(np.floor(span / period_s)) + 1)
    bounds = t[0] + np.arange(n_periods + 1) * period_s
    rng = np.random.default_rng(seed)

    # The first frame has no predecessor and is dropped unconditionally, so it
    # is counted in the budget up front; the rest are dropped in bursts.
    dropped[0] = True
    remaining = total_drops - 1

    for k in range(n_periods):
        if remaining <= 0:
            break
        # int(), not float(): np.arange with float bounds yields a float array,
        # which is not a valid index and raised IndexError for every
        # drop_fraction > 0.
        lo = int(np.searchsorted(t, bounds[k], side="left"))
        hi = int(np.searchsorted(t, bounds[k + 1], side="left"))
        idx = np.arange(lo, hi)
        idx = idx[~dropped[idx]]
        if idx.size == 0:
            continue
        periods_left = n_periods - k
        take = int(np.ceil(remaining / periods_left))
        take = min(take, idx.size, remaining)
        if take <= 0:
            continue
        # One contiguous burst placed at a random offset inside the period.
        start = int(rng.integers(0, idx.size - take + 1))
        dropped[idx[start : start + take]] = True
        remaining -= take

    # The final period is usually truncated by the end of the stream, so the
    # per-period budget can come up short. The docstring promises the total is
    # exact, and the manifest reports a *measured* drop fraction, so top up
    # from the frames that are still usable.
    if remaining > 0:
        spare = np.flatnonzero(~dropped)
        if spare.size:
            dropped[spare[-min(remaining, spare.size) :]] = True

    # Never drop the very first frame twice: it is already unusable.
    dropped[0] = True
    return VisionUpdate(
        t=vision.t.copy(),
        R_rel=vision.R_rel.copy(),
        t_rel=vision.t_rel.copy(),
        rot_cov=vision.rot_cov,
        trans_cov=vision.trans_cov,
        dropped=dropped,
        name=vision.name,
    )


def apply_imu_outage(imu: ImuSample, outages: list[Outage]) -> ImuSample:
    """Remove IMU samples inside outage windows.

    The estimator then receives a genuine gap in its inertial propagation, with
    the state frozen across it. This is the honest representation of a dead
    IMU: the filter cannot know what happened while it was blind, which is the
    point of the scenario.
    """
    mask = mark_outages(imu.t, outages)
    if not mask.any():
        return imu
    keep = ~mask
    if keep.sum() < 2:
        raise ValueError("IMU outage leaves fewer than 2 samples; the filter cannot run")
    return ImuType(
        t=imu.t[keep],
        accel=imu.accel[keep],
        gyro=imu.gyro[keep],
        accel_cov=None if imu.accel_cov is None else imu.accel_cov[keep],
        gyro_cov=None if imu.gyro_cov is None else imu.gyro_cov[keep],
        name=imu.name,
    )


def apply_imu_noise(imu: ImuSample, scenario: Scenario) -> tuple[ImuSample, np.ndarray, np.ndarray]:
    """Add noise and bias according to the scenario's IMU noise model."""
    model = scenario.imu_noise.scaled(scenario.imu_noise_scale)
    if all(v == 0.0 for v in model.as_dict().values()):
        zeros = np.zeros((len(imu), 3))
        return imu, zeros, zeros.copy()
    rng = np.random.default_rng(_derive_seed(scenario, "imu"))
    # The initial bias comes from its own stream, so the white noise and the random walk of every
    # existing scenario are drawn exactly as before. It is zero when the sigma is zero.
    rng0 = np.random.default_rng(_derive_seed(scenario, "imu_bias0"))
    gyro_0 = model.gyro_bias_sigma * rng0.standard_normal(3)
    accel_0 = model.accel_bias_sigma * rng0.standard_normal(3)
    return add_imu_noise(imu, model, rng, bias_gyro_0=gyro_0, bias_accel_0=accel_0)


def inject(
    scenario: Scenario,
    imu: ImuSample,
    gnss: GnssFix,
    vision: VisionUpdate,
    reference: Trajectory | None = None,
) -> InjectedStreams:
    """Apply a scenario to clean sensor streams and return the degraded set."""
    # 1. Outages.
    gnss_out = apply_gnss_outage(gnss, scenario.gnss_outages, scenario.gnss.enabled)
    vision_dropped = None if vision.dropped is None else vision.dropped.copy()
    vision_outages = mark_outages(vision.t, scenario.vision_outages)
    if vision_dropped is not None:
        vision_dropped = vision_dropped | vision_outages
    vision = VisionUpdate(
        t=vision.t.copy(),
        R_rel=vision.R_rel,
        t_rel=vision.t_rel,
        rot_cov=vision.rot_cov,
        trans_cov=vision.trans_cov,
        dropped=vision_dropped,
        name=vision.name,
    )
    imu = apply_imu_outage(imu, scenario.imu_outages)
    if scenario.imu_time_offset_s != 0.0:
        imu = imu.time_offset(scenario.imu_time_offset_s)

    # 2. Time offsets for the remaining channels.
    vision = vision.time_offset(scenario.vision_time_offset_s)
    gnss_off = GnssFix(
        t=gnss_out.t + scenario.gnss_time_offset_s,
        positions=gnss_out.positions.copy(),
        cov=gnss_out.cov,
        available=None if gnss_out.available is None else gnss_out.available.copy(),
        name=gnss_out.name,
    )

    # 3. Camera frame drops.
    if scenario.camera_drop is not None:
        vision = apply_camera_drop(
            vision,
            scenario.camera_drop.drop_fraction,
            scenario.camera_drop.burst_period_s,
            scenario.camera_drop.seed,
        )

    # 4. Noise. apply_imu_noise() owns the model scaling, the derived seed and
    # the all-zero fast path, so it is called here rather than being
    # reimplemented: the inline version passed (imu, model, rng) to a function
    # whose signature is (imu, scenario), which raised TypeError for every
    # scenario with non-zero noise -- including the default Scenario.
    imu, gyro_bias, accel_bias = apply_imu_noise(imu, scenario)

    if scenario.vision.noise_multiplier != 1.0:
        # Regenerate the vision stream with the inflated noise rather than
        # scaling the existing realisation: scaling would leave the two
        # channels correlated in a way no real sensor is.
        from ..sensors.models import VisionConfig, visual_updates

        assert reference is not None, "vision noise scaling needs the reference trajectory"
        cfg = VisionConfig(
            enabled=scenario.vision.enabled,
            rate_hz=scenario.vision.rate_hz,
            rot_sigma_deg=scenario.vision.rot_sigma_deg,
            trans_sigma_m=scenario.vision.trans_sigma_m,
            noise_multiplier=scenario.vision.noise_multiplier,
            seed=scenario.vision.seed,
        )
        vision = visual_updates(reference, cfg)
        if scenario.camera_drop is not None:
            vision = apply_camera_drop(
                vision,
                scenario.camera_drop.drop_fraction,
                scenario.camera_drop.burst_period_s,
                scenario.camera_drop.seed,
            )
        if scenario.vision_time_offset_s != 0.0:
            vision = vision.time_offset(scenario.vision_time_offset_s)
        if scenario.vision_outages:
            d = vision.dropped.copy() if vision.dropped is not None else np.zeros(len(vision), bool)
            vision = VisionUpdate(
                t=vision.t,
                R_rel=vision.R_rel,
                t_rel=vision.t_rel,
                rot_cov=vision.rot_cov,
                trans_cov=vision.trans_cov,
                dropped=d | mark_outages(vision.t, scenario.vision_outages),
                name=vision.name,
            )

    manifest = build_manifest(scenario, imu, gnss_off, vision, gyro_bias, accel_bias)
    return InjectedStreams(imu=imu, gnss=gnss_off, vision=vision, manifest=manifest)


def _derive_seed(scenario: Scenario, channel: str) -> int:
    h = hashlib.sha256(f"{scenario.name}:{channel}:{scenario.gnss.seed}:{scenario.vision.seed}".encode())
    return int.from_bytes(h.digest()[:4], "little")


def build_manifest(
    scenario: Scenario,
    imu: ImuSample,
    gnss: GnssFix,
    vision: VisionUpdate,
    gyro_bias: np.ndarray,
    accel_bias: np.ndarray,
) -> dict[str, Any]:
    """A record of what was injected, with measured rather than claimed counts."""
    valid_v = vision.valid()
    dropped = int(vision.dropped.sum()) if vision.dropped is not None else 0
    longest_gap = 0.0
    if len(valid_v) > 1:
        longest_gap = float(np.max(np.diff(valid_v.t)))
    return {
        "scenario": scenario.name,
        "config_hash": config_hash(scenario),
        "gnss": {
            "enabled": scenario.gnss.enabled,
            "configured_rate_hz": scenario.gnss.rate_hz,
            "emitted_fixes": int(len(gnss)),
            "usable_fixes": int(len(gnss.valid())),
            "unavailable_fixes": int(len(gnss) - len(gnss.valid())),
            "position_sigma_m": scenario.gnss.sigma_m,
            "multipath_sigma_m": scenario.gnss.multipath_sigma_m,
            "outages": [o.as_dict() for o in scenario.gnss_outages],
            "unavailable_intervals_s": [list(iv) for iv in gnss.outage_intervals()],
        },
        "vision": {
            "enabled": scenario.vision.enabled,
            "configured_rate_hz": scenario.vision.rate_hz,
            "emitted_frames": int(len(vision)),
            "usable_frames": int(len(valid_v)),
            "dropped_frames": dropped,
            "drop_fraction_measured": dropped / len(vision) if len(vision) else 0.0,
            "longest_gap_s": longest_gap,
            "effective_rate_hz": 1.0 / float(np.mean(np.diff(valid_v.t))) if len(valid_v) > 1 else 0.0,
            "noise_multiplier": scenario.vision.noise_multiplier,
            "time_offset_s": scenario.vision_time_offset_s,
            "outages": [o.as_dict() for o in scenario.vision_outages],
        },
        "imu": {
            "rate_hz": imu.rate_hz(),
            "samples": int(len(imu)),
            "time_offset_s": scenario.imu_time_offset_s,
            "outages": [o.as_dict() for o in scenario.imu_outages],
            "noise_scale": scenario.imu_noise_scale,
            "applied_bias_gyro_rad_s": gyro_bias[0].tolist() if len(gyro_bias) else [0.0, 0.0, 0.0],
            "applied_bias_accel_m_s2": accel_bias[0].tolist() if len(accel_bias) else [0.0, 0.0, 0.0],
        },
    }
