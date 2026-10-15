"""Read a fetched UrbanNav sequence: the post-processed reference solution and the Xsens IMU.

    navkit urbannav fetch --sequence tunnel1

What this module does with the two files, and what it leaves alone:

* **The reference** is a whitespace-separated text table with two header rows (names, then units) and one row
  per second. Latitude and longitude are written as degrees, minutes and seconds in three tokens each, with the
  sign on the degrees token. They are converted to degrees and then to a local east-north-up frame in metres
  (WGS84, origin at the first row). The quality column is kept as an integer. Its codes are the publisher's, and
  nothing here says what a code means.
* **The IMU** is a ROS bag exported to CSV. Columns are found by name from the header, not by position. Time
  comes from ``field.header.stamp`` (the sensor stamp), not ``%time`` (the logging time). The accelerometer and
  gyroscope values are passed on as recorded: the accelerometer reads about ``+g`` on z at rest, so the sensor
  frame is z-up, as for EuRoC and TUM VI.
* **The GNSS fixes** come from the NMEA ``GGA`` sentences of the u-blox F9P, which carry the receiver's own
  position and fix quality at 1 Hz. The NovAtel and F9P RINEX files hold raw observations only, and turning them
  into positions needs navigation files that the folder does not contain. :func:`outage_intervals` defines the
  GNSS outages from the fix flag alone. See its docstring for the rule.
* **One clock is assumed.** The reference time is Unix seconds and so are the IMU stamps. The two files are placed
  on one clock by subtracting the first IMU stamp from both. Whether the two clocks agree to better than the 1 Hz
  reference spacing is not measured here.
* **Two frames are not related here.** The reference attitude belongs to the NovAtel unit and the IMU to the Xsens.
  The rotation and lever arm between them are not in these files, so no initial attitude is derived.

Nothing is committed (constraint S2). Only numpy is used (constraint S1).
"""

from __future__ import annotations

import calendar
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .io.urbannav_fetch import SOURCES
from .recorded import SequenceError, sha256_of
from .types import ImuSample

DATASET = "UrbanNav"
SLUG = "urbannav"

HEADER_ROWS = 2
REFERENCE_TOKENS = 20
#: The token each quantity starts at in a reference row.
_UTC, _WEEK, _TOW, _LAT, _LON, _HEIGHT, _VEL, _ACC, _RPY, _QUALITY = 0, 1, 2, 3, 6, 9, 10, 13, 16, 19

#: The NMEA file of each sequence, in ``<root>/<seq>/``. It is inside the publisher's folder download.
NMEA_FILES = {"tunnel1": "20210518.tunnel.cht.ublox.f9p.nmea"}

IMU_STAMP = "field.header.stamp"
IMU_GYRO = tuple(f"field.angular_velocity.{a}" for a in "xyz")
IMU_ACCEL = tuple(f"field.linear_acceleration.{a}" for a in "xyz")

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


@dataclass
class Reference:
    """The post-processed reference solution, one row per epoch."""

    utc_s: np.ndarray  # (N,) Unix seconds
    gps_week: np.ndarray  # (N,)
    gps_tow_s: np.ndarray  # (N,)
    lat_deg: np.ndarray  # (N,)
    lon_deg: np.ndarray  # (N,)
    height_m: np.ndarray  # (N,) above the ellipsoid
    vel_body: np.ndarray  # (N, 3) m/s, in the reference unit's body frame
    acc_body: np.ndarray  # (N, 3) m/s^2
    rpy_deg: np.ndarray  # (N, 3) roll, pitch, heading
    quality: np.ndarray  # (N,) int, the publisher's code

    def __len__(self) -> int:
        return int(self.utc_s.shape[0])


@dataclass
class GgaFixes:
    """The position fixes of a receiver, one row per ``GGA`` sentence. Rows without a position hold NaN."""

    utc_s: np.ndarray  # (N,) Unix seconds
    lat_deg: np.ndarray  # (N,)
    lon_deg: np.ndarray  # (N,)
    height_m: np.ndarray  # (N,) ellipsoidal: altitude above mean sea level plus the geoid separation
    quality: np.ndarray  # (N,) int, 0 is no fix
    num_sats: np.ndarray  # (N,) int
    hdop: np.ndarray  # (N,)
    skipped: int = 0  # sentences dropped for a bad checksum or a malformed field

    def __len__(self) -> int:
        return int(self.utc_s.shape[0])


@dataclass
class UrbanNavSequence:
    """One sequence in memory. Time is in seconds from the first IMU sample."""

    name: str
    imu: ImuSample
    epoch_unix_s: float  # the Unix time of t = 0
    reference: Reference
    truth_t: np.ndarray  # (N,) reference epochs on the IMU clock
    truth_enu: np.ndarray  # (N, 3) metres, origin at the first reference row
    origin_llh: tuple[float, float, float]
    sha256: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    dataset: str = DATASET
    slug: str = SLUG


# ------------------------------------------------------------------ reference


def dms_to_deg(degrees: str, minutes: str, seconds: str) -> float:
    """``22 18 07.7`` to degrees. The sign is the sign of the first token, so ``-0 30 00`` is negative."""
    d, m, s = float(degrees), float(minutes), float(seconds)
    if not (0.0 <= m < 60.0 and 0.0 <= s < 60.0):
        raise SequenceError(f"minutes and seconds out of range in {degrees!r} {minutes!r} {seconds!r}")
    sign = -1.0 if degrees.strip().startswith("-") else 1.0
    return sign * (abs(d) + m / 60.0 + s / 3600.0)


def read_reference(path: str | Path) -> Reference:
    """Parse the reference table. Anything that does not look like it raises :class:`SequenceError`."""
    try:
        lines = Path(path).read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SequenceError(f"{path}: cannot read as an ASCII text table ({exc})") from exc
    if len(lines) <= HEADER_ROWS or not lines[0].split() or lines[0].split()[0] != "UTCTime":
        raise SequenceError(f"{path}: expected a header row starting with 'UTCTime' and data rows below it")
    rows: list[list[float]] = []
    quality: list[int] = []
    for number, line in enumerate(lines[HEADER_ROWS:], start=HEADER_ROWS + 1):
        if not line.strip():
            continue
        tok = line.split()
        if len(tok) != REFERENCE_TOKENS:
            raise SequenceError(f"{path}:{number}: {len(tok)} values, expected {REFERENCE_TOKENS}")
        try:
            lat = dms_to_deg(*tok[_LAT : _LAT + 3])
            lon = dms_to_deg(*tok[_LON : _LON + 3])
            rest = [float(x) for x in (*tok[_UTC : _TOW + 1], tok[_HEIGHT], *tok[_VEL:_QUALITY])]
            q = int(tok[_QUALITY])
        except ValueError as exc:
            raise SequenceError(f"{path}:{number}: a value is not a number ({exc})") from exc
        values = [lat, lon, *rest]
        if not all(math.isfinite(v) for v in values):
            raise SequenceError(f"{path}:{number}: a value is not finite")
        rows.append(values)
        quality.append(q)
    a = np.array(rows)
    # a columns: lat, lon, utc, week, tow, height, vel(3), acc(3), rpy(3)
    if a.shape[0] > 1 and not np.all(np.diff(a[:, 2]) > 0):
        raise SequenceError(f"{path}: reference times are not strictly increasing")
    return Reference(
        utc_s=a[:, 2],
        gps_week=a[:, 3],
        gps_tow_s=a[:, 4],
        lat_deg=a[:, 0],
        lon_deg=a[:, 1],
        height_m=a[:, 5],
        vel_body=a[:, 6:9],
        acc_body=a[:, 9:12],
        rpy_deg=a[:, 12:15],
        quality=np.array(quality, dtype=int),
    )


def llh_to_ecef(lat_deg: np.ndarray, lon_deg: np.ndarray, height_m: np.ndarray) -> np.ndarray:
    """WGS84 geodetic to Earth-centred Earth-fixed, metres, shape (N, 3)."""
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * np.sin(lat) ** 2)
    return np.column_stack(
        [
            (n + height_m) * np.cos(lat) * np.cos(lon),
            (n + height_m) * np.cos(lat) * np.sin(lon),
            (n * (1.0 - WGS84_E2) + height_m) * np.sin(lat),
        ]
    )


def llh_to_enu(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    height_m: np.ndarray,
    origin: tuple[float, float, float] | None = None,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Local east-north-up in metres about ``origin`` (default: the first point). Returns the origin used."""
    lat0, lon0, h0 = origin if origin is not None else (float(lat_deg[0]), float(lon_deg[0]), float(height_m[0]))
    delta = llh_to_ecef(lat_deg, lon_deg, height_m) - llh_to_ecef(np.array([lat0]), np.array([lon0]), np.array([h0]))
    la, lo = math.radians(lat0), math.radians(lon0)
    rot = np.array(
        [
            [-math.sin(lo), math.cos(lo), 0.0],
            [-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)],
            [math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)],
        ]
    )
    return delta @ rot.T, (lat0, lon0, h0)


# ------------------------------------------------------------------------ IMU


def read_imu(path: str | Path, name: str = "xsens") -> tuple[ImuSample, float]:
    """The IMU as an :class:`ImuSample` with time from the first sample, and the Unix time of that sample."""
    try:
        with Path(path).open(newline="", encoding="ascii") as fh:
            header = next(csv.reader(fh), [])
    except (OSError, UnicodeDecodeError) as exc:
        raise SequenceError(f"{path}: cannot read the CSV header ({exc})") from exc
    wanted = (IMU_STAMP, *IMU_GYRO, *IMU_ACCEL)
    missing = [c for c in wanted if c not in header]
    if missing:
        raise SequenceError(f"{path}: the CSV has no column {missing[0]!r}; first columns are {header[:6]}")
    cols = [header.index(c) for c in wanted]
    try:
        # The stamps are integer nanoseconds near 1.6e18, past what a float64 holds exactly, so read them as integers.
        stamp_ns = np.loadtxt(path, delimiter=",", skiprows=1, usecols=cols[0], dtype=np.int64, ndmin=1)
        data = np.loadtxt(path, delimiter=",", skiprows=1, usecols=cols[1:], dtype=np.float64, ndmin=2)
    except ValueError as exc:
        raise SequenceError(f"{path}: a value is not a number ({exc})") from exc
    if stamp_ns.shape[0] < 2 or not np.all(np.isfinite(data)):
        raise SequenceError(f"{path}: too few rows, or a value is not finite")
    if np.any(np.diff(stamp_ns) < 0):
        raise SequenceError(f"{path}: IMU stamps go backwards")
    t = (stamp_ns - stamp_ns[0]) * 1e-9
    imu = ImuSample(t=t, accel=data[:, 3:6], gyro=data[:, 0:3], name=name)
    return imu, float(stamp_ns[0]) * 1e-9


# ------------------------------------------------------------------- sequence


def load_sequence(root: str | Path, seq: str) -> UrbanNavSequence:
    """Read ``<root>/<seq>/`` as fetched by ``navkit urbannav fetch``."""
    if seq not in SOURCES:
        raise SequenceError(f"unknown sequence {seq!r}; known: {', '.join(SOURCES)}")
    ref_name, imu_name = tuple(SOURCES[seq])
    ref_path, imu_path = Path(root) / seq / ref_name, Path(root) / seq / imu_name
    for p in (ref_path, imu_path):
        if not p.is_file():
            raise SequenceError(f"{p} is missing; run `navkit urbannav fetch --sequence {seq}`")
    reference = read_reference(ref_path)
    imu, epoch = read_imu(imu_path)
    enu, origin = llh_to_enu(reference.lat_deg, reference.lon_deg, reference.height_m)
    truth_t = reference.utc_s - epoch
    notes = [
        "The reference clock (Unix seconds) and the IMU stamps are taken to be one clock. The offset is not measured.",
        "The reference attitude is the NovAtel unit's. The Xsens frame is not related to it here.",
    ]
    outside = int(np.sum((truth_t < 0.0) | (truth_t > imu.t[-1])))
    if outside:
        notes.append(f"{outside} of {len(reference)} reference epochs fall outside the IMU time span.")
    return UrbanNavSequence(
        name=seq,
        imu=imu,
        epoch_unix_s=epoch,
        reference=reference,
        truth_t=truth_t,
        truth_enu=enu,
        origin_llh=origin,
        sha256={ref_name: sha256_of(ref_path), imu_name: sha256_of(imu_path)},
        notes=notes,
    )


# ----------------------------------------------------------------------- GNSS


def _checksum_ok(line: str) -> bool:
    body, star, tail = line[1:].partition("*")
    if not star or len(tail) < 2:
        return False
    x = 0
    for ch in body:
        x ^= ord(ch)
    try:
        return x == int(tail[:2], 16)
    except ValueError:
        return False


def _ddmm(value: str, hemisphere: str, degree_digits: int, positive: str) -> float:
    deg, minutes = int(value[:degree_digits]), float(value[degree_digits:])
    if not 0.0 <= minutes < 60.0:
        raise ValueError("minutes out of range")
    return (deg + minutes / 60.0) * (1.0 if hemisphere == positive else -1.0)


def read_gga(path: str | Path) -> GgaFixes:
    """The ``GGA`` fixes of an NMEA file, with the date taken from its first ``RMC`` sentence.

    A sentence with a bad checksum or a malformed field is dropped and counted in ``skipped``. A sentence with no
    position (an empty field, as a receiver writes with no fix) is kept with NaN so that the outage is visible.
    """
    try:
        lines = Path(path).read_text(encoding="ascii", errors="replace").splitlines()
    except OSError as exc:
        raise SequenceError(f"{path}: cannot read ({exc})") from exc
    midnight: float | None = None
    for raw in lines:
        line = raw.strip()
        if line[3:6] == "RMC" and _checksum_ok(line):
            f = line[1 : line.index("*")].split(",")
            if len(f) > 9 and len(f[9]) == 6 and f[9].isdigit():
                day, month, year = int(f[9][0:2]), int(f[9][2:4]), 2000 + int(f[9][4:6])
                midnight = float(calendar.timegm((year, month, day, 0, 0, 0)))
                break
    if midnight is None:
        raise SequenceError(f"{path}: no valid RMC sentence with a date, so the fixes cannot be placed in UTC")
    out: list[tuple[float, float, float, float, int, int, float]] = []
    skipped, day_offset, previous = 0, 0.0, -1.0
    for raw in lines:
        line = raw.strip()
        if line[3:6] != "GGA":
            continue
        if not _checksum_ok(line):
            skipped += 1
            continue
        f = line[1 : line.index("*")].split(",")
        try:
            tod = int(f[1][0:2]) * 3600 + int(f[1][2:4]) * 60 + float(f[1][4:])
            quality, sats = int(f[6] or 0), int(f[7] or 0)
            hdop = float(f[8]) if f[8] else math.nan
            if f[2] and f[4]:
                lat, lon = _ddmm(f[2], f[3], 2, "N"), _ddmm(f[4], f[5], 3, "E")
                height = float(f[9]) + float(f[11] or 0.0)
            else:
                lat = lon = height = math.nan
        except (ValueError, IndexError):
            skipped += 1
            continue
        if tod < previous:
            day_offset += 86400.0  # the clock passed midnight
        previous = tod
        out.append((midnight + day_offset + tod, lat, lon, height, quality, sats, hdop))
    if not out:
        raise SequenceError(f"{path}: no valid GGA sentence")
    a = np.array(out)
    return GgaFixes(
        utc_s=a[:, 0],
        lat_deg=a[:, 1],
        lon_deg=a[:, 2],
        height_m=a[:, 3],
        quality=a[:, 4].astype(int),
        num_sats=a[:, 5].astype(int),
        hdop=a[:, 6],
        skipped=skipped,
    )


GAP_FACTOR = 1.5


def outage_intervals(fixes: GgaFixes) -> list[tuple[float, float]]:
    """GNSS outages as ``(start, end)`` in Unix seconds, with the repository's meaning ``start <= t < end``.

    The rule, fixed before any filter was run on this data and not changed since:

    * An epoch is **denied** when its fix quality is 0 or it carries no position.
    * Time with **no epoch at all** is denied: a gap longer than 1.5 times the median epoch spacing, from the
      expected next epoch to the next epoch that exists.
    * An outage is a maximal denied stretch. It starts at its first denied epoch and ends at the first valid epoch
      after it (or one spacing after the last epoch, when the stretch reaches the end of the file).

    The rule reads only the receiver's own flag. It does not look at the reference, at the satellite count, at the
    dilution of precision, or at how wrong a fix that is marked valid turns out to be. Fixes marked valid can be
    badly wrong, as in the seconds before a receiver gives up, and the filter's gate is what has to catch them.
    """
    t = fixes.utc_s
    if t.shape[0] < 2:
        return []
    step = float(np.median(np.diff(t)))
    denied = (fixes.quality == 0) | ~np.isfinite(fixes.lat_deg) | ~np.isfinite(fixes.lon_deg)
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for i in range(t.shape[0]):
        if denied[i] and start is None:
            start = float(t[i])
        elif not denied[i] and start is not None:
            spans.append((start, float(t[i])))
            start = None
    if start is not None:
        spans.append((start, float(t[-1]) + step))
    for i in range(t.shape[0] - 1):
        if t[i + 1] - t[i] > GAP_FACTOR * step:
            spans.append((float(t[i]) + step, float(t[i + 1])))
    spans.sort()
    merged: list[tuple[float, float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def load_gga(root: str | Path, seq: str) -> GgaFixes:
    """Read the NMEA file of ``seq`` from ``<root>/<seq>/``."""
    if seq not in NMEA_FILES:
        raise SequenceError(f"no NMEA file is known for sequence {seq!r}; known: {', '.join(NMEA_FILES)}")
    path = Path(root) / seq / NMEA_FILES[seq]
    if not path.is_file():
        raise SequenceError(
            f"{path} is missing. It is inside the publisher's folder download (the GNSS RINEX link); copy it here."
        )
    return read_gga(path)
