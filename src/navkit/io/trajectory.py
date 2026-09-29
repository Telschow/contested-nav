"""Trajectory file readers.

Formats supported, all of which appear in the public datasets this project
targets. The quaternion order differs between them and getting it wrong
silently mirrors the trajectory, so every reader states its order explicitly
and the conversion is unit tested.

``tum``      whitespace separated ``t tx ty tz qx qy qz qw``; timestamp in
             seconds or nanoseconds. TUM RGB-D ``groundtruth.txt`` and the
             ``*_poses.txt`` files published with the TUM VI benchmark.
``euroc``    comma separated with a ``#`` comment header; timestamp in
             nanoseconds; quaternion in ``w x y z`` order. EuRoC
             ``mav0/mocap0/data.csv`` and the TUM VI ``exported/euroc``
             sequences.
``csv_xyz_qw`` comma separated ``t,x,y,z,qx,qy,qz,qw`` with an optional
              header. Used by the TUM VI ``*_groundtruth_plotly.csv`` files.
``euroc_txt``   a real-valued header plus whitespace data with
              ``(nanoseconds, x, y, z, qw, qx, qy, qz)`` ordering, the raw
              EuRoC layout before it is written out as CSV.

The delimiter is sniffed rather than assumed: real dataset exports mix
commas and spaces in nominally similar files.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable

import numpy as np

from ..geometry.rigid import quat_to_matrix
from ..types import Trajectory

_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_NS_THRESHOLD = 1e12  # anything above this is nanoseconds, not seconds

# Every trajectory is stored internally as (w, x, y, z). Most public exports
# put the scalar part last instead, so the two reorderings live here as named
# helpers rather than as bare ``[3, 0, 1, 2]`` slices at each call site: a
# mislabelled reorder produces a perfectly orthonormal rotation matrix of the
# wrong orientation, which no shape or orthonormality check will catch.
_TO_WXYZ = (3, 0, 1, 2)
_TO_XYZW = (1, 2, 3, 0)


def xyzw_to_wxyz(q: np.ndarray) -> np.ndarray:
    """Reorder a scalar-last ``(x, y, z, w)`` quaternion to internal ``(w, x, y, z)``."""
    return np.asarray(q)[..., list(_TO_WXYZ)]


def wxyz_to_xyzw(q: np.ndarray) -> np.ndarray:
    """Reorder an internal ``(w, x, y, z)`` quaternion to scalar-last ``(x, y, z, w)``."""
    return np.asarray(q)[..., list(_TO_XYZW)]


class TrajectoryParseError(ValueError):
    """Raised when a trajectory file cannot be interpreted."""


def _read_rows(path: str) -> tuple[np.ndarray, list[str]]:
    """Read numeric rows from a text file, tolerating headers and comments."""
    if not os.path.isfile(path):
        raise TrajectoryParseError(f"no such file: {path}")
    rows: list[list[float]] = []
    header: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                body = line.lstrip("#").strip()
                if body:
                    header.extend(t.strip() for t in re.split(r"[\s,]+", body) if t.strip())
                continue
            # A non-numeric first field that is not '#' is a CSV header row.
            tokens = re.split(r"[,\s]+", line)
            if not _NUM.fullmatch(tokens[0]):
                if not rows:
                    header.extend(t.strip() for t in tokens if t.strip())
                    continue
                raise TrajectoryParseError(f"{path}:{lineno}: unexpected non-numeric field {tokens[0]!r}")
            try:
                rows.append([float(t) for t in tokens])
            except ValueError as exc:  # pragma: no cover - defensive
                raise TrajectoryParseError(f"{path}:{lineno}: {exc}") from exc
    if not rows:
        raise TrajectoryParseError(f"{path}: no numeric rows found")
    # Rows may be ragged (a header line with a trailing empty field, or a file
    # whose last column is optional). Pad to the widest row so readers can
    # probe for optional trailing columns such as EuRoC velocity and bias.
    width = max(len(r) for r in rows)
    for r in rows:
        r.extend([np.nan] * (width - len(r)))
    return np.asarray(rows, dtype=float), header


def _fix_timestamp_unit(t: np.ndarray, header: list[str] | None = None) -> np.ndarray:
    """Convert nanosecond timestamps to seconds.

    Real exports mix units across files of the same sequence, so this is
    decided per file rather than from a config flag. The header wins when it
    names the unit, because it is the only unambiguous signal available;
    otherwise the magnitude of the first timestamp is used, which is the
    fallback for the many TUM-style files that carry no unit at all.
    """
    if header and any(re.search(r"\b(ns|nanosecond)", h, re.IGNORECASE) for h in header):
        return t / 1e9
    if abs(t[0]) > _NS_THRESHOLD:
        return t / 1e9
    return t


def _build(
    t: np.ndarray,
    xyz: np.ndarray,
    quat: np.ndarray,
    name: str,
    source: str,
    header: list[str] | None = None,
) -> Trajectory:
    t = _fix_timestamp_unit(t, header)
    order = np.argsort(t, kind="stable")
    t, xyz, quat = t[order], xyz[order], quat[order]
    # Drop exact duplicate timestamps; keep the first occurrence.
    keep = np.concatenate([[True], np.diff(t) > 0.0])
    t, xyz, quat = t[keep], xyz[keep], quat[keep]
    poses = np.empty((len(t), 4, 4))
    for i in range(len(t)):
        poses[i, :3, :3] = quat_to_matrix(quat[i])
        poses[i, :3, 3] = xyz[i]
        poses[i, 3, :3] = 0.0
        poses[i, 3, 3] = 1.0
    return Trajectory(t=t, poses=poses, name=name, metadata={"source": source, "format": "t"})


def _read_tum(path: str, name: str | None = None) -> Trajectory:
    """``t tx ty tz qx qy qz qw``, scalar-last quaternion on disk."""
    a, hdr = _read_rows(path)
    if a.shape[1] < 8:
        raise TrajectoryParseError(f"{path}: expected 8 columns, got {a.shape[1]}")
    return _build(a[:, 0], a[:, 1:4], xyzw_to_wxyz(a[:, 4:8]), name or os.path.basename(path), path, hdr)


def _read_euroc(path: str, name: str | None = None) -> Trajectory:
    """``#timestamp [ns], p_x, p_y, p_z, q_w, q_x, q_y, q_z, [v, b]``."""
    a, hdr = _read_rows(path)
    if a.shape[1] < 8:
        raise TrajectoryParseError(f"{path}: expected >=8 columns, got {a.shape[1]}")
    traj = _build(a[:, 0], a[:, 1:4], a[:, 4:8], name or os.path.basename(path), path, hdr)
    meta = dict(traj.metadata)
    # EuRoC mocap layout: t p(1:4) q(4:8) v(8:11) b_g(11:15) b_a(15:18). The
    # velocity slice is 8:11, not the trailing columns, which are gyro and
    # accelerometer bias.
    if a.shape[1] >= 11:  # world-frame linear velocity is present
        meta["velocity"] = a[:, 8:11]
    traj.metadata = meta
    traj.name = name or os.path.basename(path)
    return traj


def _read_plotly(path: str, name: str | None = None) -> Trajectory:
    """``t,x,y,z,qx,qy,qz,qw`` CSV, optional ``t,x,...`` header row."""
    a, hdr = _read_rows(path)
    if a.shape[1] < 8:
        raise TrajectoryParseError(f"{path}: expected 8 columns, got {a.shape[1]}")
    return _build(a[:, 0], a[:, 1:4], xyzw_to_wxyz(a[:, 4:8]), name or os.path.basename(path), path, hdr)


def _read_euroc_txt(path: str, name: str | None = None) -> Trajectory:
    """EuRoC ``state_groundtruth_estimate0/data.csv`` body: ``ns x y z qw qx qy qz``."""
    a, hdr = _read_rows(path)
    if a.shape[1] < 8:
        raise TrajectoryParseError(f"{path}: expected 8 columns, got {a.shape[1]}")
    return _build(a[:, 0], a[:, 1:4], a[:, 4:8], name or os.path.basename(path), path, hdr)


READERS: dict[str, Callable[[str, str | None], Trajectory]] = {
    "tum": _read_tum,
    "euroc": _read_euroc,
    "csv_xyz_qw": _read_plotly,
    "euroc_txt": _read_euroc_txt,
}


def read_trajectory(path: str, fmt: str = "auto", name: str | None = None) -> Trajectory:
    """Read a trajectory file.

    ``fmt="auto"`` inspects the header (when present) and falls back to the
    ``tum`` whitespace reader, which is the most permissive of the four.
    """
    if fmt == "auto":
        fmt = detect_format(path)
    if fmt not in READERS:
        raise TrajectoryParseError(f"unknown trajectory format {fmt!r}")
    return READERS[fmt](path, name)


def detect_format(path: str) -> str:
    """Guess the file format from its header and separators."""
    header: list[str] = []
    first_data = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                header.extend(t.strip() for t in re.split(r"[\s,]+", line.lstrip("#")) if t.strip())
                continue
            first_data = line
            break
    joined = " ".join(header).lower()
    if "q_rs_w" in joined or "q_w" in joined:
        # 'q_w [ ]' is the EuRoC mocap header; 'qw' is the raw estimate layout.
        return "euroc" if "," in first_data else "euroc_txt"
    if first_data and "," in first_data:
        return "csv_xyz_qw"
    if first_data and _NUM.fullmatch(re.split(r"[,\s]+", first_data)[0]):
        return "tum"
    raise TrajectoryParseError(f"{path}: could not determine trajectory format")


def write_tum(path: str, traj: Trajectory, digits: int = 12) -> None:
    """Write a trajectory in TUM ``t tx ty tz qx qy qz qw`` order, seconds."""
    q = wxyz_to_xyzw(traj.quaternions)
    p = traj.positions
    fmt = f"%.{digits}e"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# timestamp tx ty tz qx qy qz qw\n")
        for i in range(len(traj)):
            fh.write(
                " ".join(
                    [
                        fmt % traj.t[i],
                        *(fmt % v for v in p[i]),
                        *(fmt % v for v in q[i]),
                    ]
                )
                + "\n"
            )


def write_euroc(path: str, traj: Trajectory, nanoseconds: bool = True) -> None:
    """Write a trajectory as an EuRoC ``data.csv`` mocap-style file."""
    q = traj.quaternions
    p = traj.positions
    t = traj.t * 1e9 if nanoseconds else traj.t
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "#timestamp [ns], p_RS_R_x [m], p_RS_R_y [m], p_RS_R_z [m], q_RS_w [], q_RS_x [], q_RS_y [], q_RS_z []\n"
        )
        for i in range(len(traj)):
            fh.write(
                f"{t[i]:.9f}, {p[i, 0]:.9e}, {p[i, 1]:.9e}, {p[i, 2]:.9e}, "
                f"{q[i, 0]:.9e}, {q[i, 1]:.9e}, {q[i, 2]:.9e}, {q[i, 3]:.9e}\n"
            )


def iter_loaders() -> Iterable[str]:
    return tuple(READERS)
