"""Scenario schema, parsing and validation.

A scenario describes *what is broken* and *for how long*, not how the estimator
should behave. Times are relative to the start of the replayed sequence, in
seconds, so a scenario is portable between sequences of different length.

The validation is strict and returns every problem it finds rather than the
first one, because a config that silently clamps a 45 s outage to 10 s is worse
than one that refuses to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..io.imu import DEFAULT_NOISE, ImuNoiseModel
from ..sensors.models import GnssConfig, VisionConfig

VALID_SCENARIOS = (
    "normal",
    "gnss_denied",
    "camera_drop",
    "imu_noise",
    "timestamp_offset",
    "image_degradation",
    "sensor_outage",
)


class ConfigError(ValueError):
    """Raised when a configuration or scenario is invalid."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass
class Outage:
    """A time window in which a channel carries no usable data."""

    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    def as_dict(self) -> dict[str, float]:
        return {"start_s": self.start_s, "duration_s": self.duration_s, "end_s": self.end_s}

    def covers(self, t: float) -> bool:
        return self.start_s <= t < self.end_s


@dataclass
class CameraDropConfig:
    """Bursty frame loss, the realistic shape of frame drops under load.

    A uniformly random per-frame drop is easy to write and misleading: real
    frame loss is correlated in time (buffer underruns, exposure stalls,
    transport hiccups) and a long gap between usable frames is what actually
    hurts a relative-pose front end. This generator produces bursts separated
    by a quiet period, with the dropped fraction controlled directly.
    """

    drop_fraction: float = 0.2
    burst_period_s: float = 2.0
    seed: int = 0

    def as_dict(self) -> dict[str, float]:
        return {
            "drop_fraction": self.drop_fraction,
            "burst_period_s": self.burst_period_s,
            "seed": self.seed,
        }


@dataclass
class Scenario:
    """One degradation configuration."""

    name: str
    description: str = ""
    gnss: GnssConfig = field(default_factory=GnssConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    imu_noise: ImuNoiseModel = field(default_factory=lambda: ImuNoiseModel(**DEFAULT_NOISE.as_dict()))
    imu_noise_scale: float = 1.0
    imu_outages: list[Outage] = field(default_factory=list)
    gnss_outages: list[Outage] = field(default_factory=list)
    vision_outages: list[Outage] = field(default_factory=list)
    camera_drop: CameraDropConfig | None = None
    vision_time_offset_s: float = 0.0
    imu_time_offset_s: float = 0.0
    gnss_time_offset_s: float = 0.0
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "gnss": self.gnss.as_dict(),
            "vision": self.vision.as_dict(),
            "imu_noise": self.imu_noise.as_dict(),
            "imu_noise_scale": self.imu_noise_scale,
            "imu_outages": [o.as_dict() for o in self.imu_outages],
            "gnss_outages": [o.as_dict() for o in self.gnss_outages],
            "vision_outages": [o.as_dict() for o in self.vision_outages],
            "vision_time_offset_s": self.vision_time_offset_s,
            "imu_time_offset_s": self.imu_time_offset_s,
            "gnss_time_offset_s": self.gnss_time_offset_s,
            "notes": self.notes,
        }
        d["camera_drop"] = None if self.camera_drop is None else self.camera_drop.as_dict()
        return d

    def total_degraded_time_s(self) -> dict[str, float]:
        """Wall-clock time each channel spends unusable, by simple union.

        A channel that is disabled is unusable for the whole run, so its value
        is ``-1.0`` rather than ``0.0``: zero would read as "this channel was
        never degraded", which is the opposite of what a disabled channel means.
        """
        return {
            "gnss": -1.0 if not self.gnss.enabled else _union_length(self.gnss_outages),
            "vision": -1.0 if not self.vision.enabled else _union_length(self.vision_outages),
            "imu": _union_length(self.imu_outages),
        }


def _union_length(outages: list[Outage]) -> float:
    if not outages:
        return 0.0
    spans = sorted((o.start_s, o.end_s) for o in outages)
    total = 0.0
    cur_s, cur_e = spans[0]
    for s, e in spans[1:]:
        if s > cur_e:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + (cur_e - cur_s)


def outage_from_dict(d: dict[str, Any], where: str, problems: list[str]) -> Outage | None:
    start = d.get("start_s", d.get("start"))
    dur = d.get("duration_s", d.get("duration"))
    if start is None or dur is None:
        problems.append(f"{where}: outage needs 'start_s' and 'duration_s'")
        return None
    try:
        start = float(start)
        dur = float(dur)
    except (TypeError, ValueError):
        problems.append(f"{where}: outage start/duration must be numbers")
        return None
    if start < 0.0:
        problems.append(f"{where}: start_s must be >= 0, got {start}")
    if dur <= 0.0:
        problems.append(f"{where}: duration_s must be > 0, got {dur}")
        return None
    return Outage(start_s=start, duration_s=dur)


def _outage_list(value: Any, where: str, problems: list[str]) -> list[Outage]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        problems.append(f"{where}: expected a list of outages")
        return []
    out: list[Outage] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            problems.append(f"{where}[{i}]: expected a mapping")
            continue
        o = outage_from_dict(item, f"{where}[{i}]", problems)
        if o is not None:
            out.append(o)
    return out


def scenario_from_dict(d: dict[str, Any], problems: list[str] | None = None) -> Scenario:
    """Build a :class:`Scenario` from a plain mapping, collecting problems."""
    problems = [] if problems is None else problems
    if not isinstance(d, dict):
        problems.append("scenario must be a mapping")
        return Scenario(name="invalid")

    name = str(d.get("name", "unnamed"))
    if not name.strip():
        problems.append("scenario.name must be a non-empty string")

    g_raw = d.get("gnss") or {}
    g = GnssConfig(
        enabled=bool(g_raw.get("enabled", True)),
        rate_hz=float(g_raw.get("rate_hz", 5.0)),
        sigma_m=float(g_raw.get("sigma_m", 0.8)),
        multipath_sigma_m=float(g_raw.get("multipath_sigma_m", 0.0)),
        multipath_tau_s=float(g_raw.get("multipath_tau_s", 30.0)),
        seed=int(g_raw.get("seed", 0)),
    )
    v_raw = d.get("vision") or {}
    v = VisionConfig(
        enabled=bool(v_raw.get("enabled", True)),
        rate_hz=float(v_raw.get("rate_hz", 20.0)),
        rot_sigma_deg=float(v_raw.get("rot_sigma_deg", 0.35)),
        trans_sigma_m=float(v_raw.get("trans_sigma_m", 0.05)),
        noise_multiplier=float(v_raw.get("noise_multiplier", 1.0)),
        seed=int(v_raw.get("seed", 0)),
    )
    noise_raw = dict(d.get("imu_noise") or {})
    unknown = set(noise_raw) - set(DEFAULT_NOISE.as_dict())
    if unknown:
        problems.append(f"scenario.imu_noise: unknown keys {sorted(unknown)}")
    known = {k: float(noise_raw.get(k, getattr(DEFAULT_NOISE, k))) for k in DEFAULT_NOISE.as_dict()}
    imu_noise = ImuNoiseModel(**known)

    cd_raw = d.get("camera_drop")
    camera_drop = None
    if cd_raw:
        camera_drop = CameraDropConfig(
            drop_fraction=float(cd_raw.get("drop_fraction", 0.2)),
            burst_period_s=float(cd_raw.get("burst_period_s", 2.0)),
            seed=int(cd_raw.get("seed", 0)),
        )

    scen = Scenario(
        name=name,
        description=str(d.get("description", "")),
        gnss=g,
        vision=v,
        imu_noise=imu_noise,
        imu_noise_scale=float(d.get("imu_noise_scale", 1.0)),
        imu_outages=_outage_list(d.get("imu_outages"), "scenario.imu_outages", problems),
        gnss_outages=_outage_list(d.get("gnss_outages"), "scenario.gnss_outages", problems),
        vision_outages=_outage_list(d.get("vision_outages"), "scenario.vision_outages", problems),
        camera_drop=camera_drop,
        vision_time_offset_s=float(d.get("vision_time_offset_s", 0.0)),
        imu_time_offset_s=float(d.get("imu_time_offset_s", 0.0)),
        gnss_time_offset_s=float(d.get("gnss_time_offset_s", 0.0)),
        notes=str(d.get("notes", "")),
    )
    _validate_scenario(scen, problems)
    return scen


def _validate_scenario(s: Scenario, problems: list[str]) -> None:
    if s.name != "normal" and s.name not in VALID_SCENARIOS and s.name.startswith("__"):
        problems.append(f"scenario.name {s.name!r} looks like an internal name; use a custom name")
    if s.gnss.rate_hz <= 0.0:
        problems.append(f"scenario.gnss.rate_hz must be > 0, got {s.gnss.rate_hz}")
    if s.gnss.sigma_m <= 0.0:
        problems.append(f"scenario.gnss.sigma_m must be > 0, got {s.gnss.sigma_m}")
    if s.gnss.multipath_tau_s <= 0.0:
        problems.append(f"scenario.gnss.multipath_tau_s must be > 0, got {s.gnss.multipath_tau_s}")
    if s.vision.rate_hz <= 0.0:
        problems.append(f"scenario.vision.rate_hz must be > 0, got {s.vision.rate_hz}")
    if s.vision.rot_sigma_deg <= 0.0:
        problems.append(f"scenario.vision.rot_sigma_deg must be > 0, got {s.vision.rot_sigma_deg}")
    if s.vision.trans_sigma_m <= 0.0:
        problems.append(f"scenario.vision.trans_sigma_m must be > 0, got {s.vision.trans_sigma_m}")
    if s.vision.noise_multiplier < 0.0:
        problems.append(
            f"scenario.vision.noise_multiplier must be >= 0, got {s.vision.noise_multiplier}"
        )
    if s.imu_noise_scale < 0.0:
        problems.append(f"scenario.imu_noise_scale must be >= 0, got {s.imu_noise_scale}")
    for key, value in s.imu_noise.as_dict().items():
        if value < 0.0:
            problems.append(f"scenario.imu_noise.{key} must be >= 0, got {value}")
    if s.camera_drop is not None:
        if not 0.0 <= s.camera_drop.drop_fraction < 1.0:
            problems.append(
                "scenario.camera_drop.drop_fraction must be in [0, 1), got "
                f"{s.camera_drop.drop_fraction}"
            )
        if s.camera_drop.burst_period_s <= 0.0:
            problems.append("scenario.camera_drop.burst_period_s must be > 0")
    # Offsets larger than a few sensor periods stop being a "clock offset
    # between two channels" and become a re-indexing of the data, which would
    # mask every other effect in the scenario. Beyond that, reject.
    vision_period = 1.0 / max(s.vision.rate_hz, 1e-9)
    if abs(s.vision_time_offset_s) > 5.0 * vision_period:
        problems.append(
            f"scenario.vision_time_offset_s={s.vision_time_offset_s} exceeds five camera "
            f"periods ({5.0 * vision_period:.4f}s); that is a data re-indexing, not a clock offset"
        )
    if abs(s.imu_time_offset_s) > 0.5:
        problems.append(
            f"scenario.imu_time_offset_s={s.imu_time_offset_s} is implausibly large for an "
            "IMU clock offset"
        )
    if not s.gnss.enabled and s.gnss_outages:
        problems.append("scenario.gnss is disabled but gnss_outages were given; the outages are dead config")
    if not s.vision.enabled and (s.vision_outages or s.camera_drop):
        problems.append("scenario.vision is disabled but vision degradations were given")
    if s.gnss.enabled and not s.gnss_outages and s.gnss.sigma_m <= 0.0:
        problems.append("scenario.gnss.sigma_m must be > 0 when GNSS is enabled")
