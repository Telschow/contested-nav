"""Tests for the EuRoC/TUM-VI ASCII IMU loader.

``read_euroc_imu`` had no test at all, and it was broken in two independent
ways: ``_NUM`` was a plain string being called with ``.fullmatch()``, which
raised ``AttributeError`` on every invocation, and the nanosecond-detection
heuristic inspected only the first sample, so a recording that starts near zero
was read as seconds.

Both defects are the kind that a coverage number hides rather than reveals. The
loader is the entry point for every real-dataset experiment described in the
docs, so an import-time crash meant the documented "run this on EuRoC" path had
never been executed, and the unit heuristic would have quietly turned a 20 s
recording into a 20-billion-second one. These tests pin both.
"""

from __future__ import annotations

import numpy as np
import pytest

from navkit.io.imu import ImuSample, read_euroc_imu

HEADER = "#timestamp [ns], w_RS_S_x, w_RS_S_y, w_RS_S_z, a_RS_S_x, a_RS_S_y, a_RS_S_z"


def _write(tmp_path, lines, name="data.csv"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_reads_a_well_formed_nanosecond_file(tmp_path):
    path = _write(
        tmp_path,
        [
            HEADER,
            "1000000000, 0.1, 0.2, 0.3, 0.0, 0.0, 9.81",
            "2000000000, 0.1, 0.2, 0.3, 0.0, 0.1, 9.82",
            "3000000000, 0.1, 0.2, 0.3, 0.0, 0.0, 9.83",
        ],
    )
    imu = read_euroc_imu(path)

    assert isinstance(imu, ImuSample)
    assert imu.t.shape == (3,)
    assert imu.gyro.shape == (3, 3)
    assert imu.accel.shape == (3, 3)
    # Columns are gyro first, then accelerometer, per the EuRoC header.
    assert np.allclose(imu.gyro[:, 0], [0.1, 0.1, 0.1])
    assert np.allclose(imu.accel[:, 2], [9.81, 9.82, 9.83])


def test_nanosecond_timestamps_are_converted_to_seconds(tmp_path):
    """A 1 ns gap must become 1e-9 s, not 1.0 s."""
    path = _write(
        tmp_path,
        [
            HEADER,
            "15000000000000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "15000000001000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
        ],
    )
    imu = read_euroc_imu(path)
    # 1e6 ns == 1e-3 s. Asserting the wrong unit here would let a missing
    # conversion pass whenever it happened to be off by a power of 1000.
    assert np.allclose(np.diff(imu.t), [1e-3])


def test_a_nanosecond_stream_starting_near_zero_is_still_detected(tmp_path):
    """Regression: the decision must not depend on the first sample.

    A recording that begins at t=0 and is long enough to cross 1e12 nanoseconds
    (about 17 minutes at 1e12 ns = 1000 s, so a stream crossing 1e13 is unambiguous) was previously read as seconds, because the old check
    only looked at element 0. Real EuRoC logs start from the host clock rather
    than zero, but a relative-timestamp export is a natural thing to hand this
    loader, and the failure is silent.
    """
    path = _write(
        tmp_path,
        [
            HEADER,
            "0, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "500000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "15000000000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
        ],
    )
    imu = read_euroc_imu(path)
    # 1.5e13 ns == 15000 s. Read as seconds it would be 1.5e13.
    assert np.allclose(imu.t, [0.0, 0.5, 15000.0])


def test_a_relative_second_stream_is_left_alone(tmp_path):
    """Seconds must not be rescaled the other way."""
    path = _write(
        tmp_path,
        [
            HEADER,
            "0.000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "0.005, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "0.010, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
        ],
    )
    imu = read_euroc_imu(path)
    assert np.allclose(imu.t, [0.0, 0.005, 0.010])


def test_comma_and_whitespace_separated_files_agree(tmp_path):
    """EuRoC ships both; the parser must not care which."""
    values = ["0.1", "0.2", "0.3", "0.0", "0.0", "9.81"]
    commas = _write(tmp_path, [HEADER, "1000000000, " + ", ".join(values)], "a.csv")
    spaces = _write(tmp_path, [HEADER, "1000000000 " + " ".join(values)], "b.csv")
    assert np.allclose(read_euroc_imu(commas).accel, read_euroc_imu(spaces).accel)


def test_a_bare_column_header_is_skipped(tmp_path):
    """Some exports omit the leading ``#``."""
    path = _write(
        tmp_path,
        [
            "timestamp [ns], w_RS_S_x, w_RS_S_y, w_RS_S_z, a_RS_S_x, a_RS_S_y, a_RS_S_z",
            "1000000000, 0.1, 0.2, 0.3, 0.0, 0.0, 9.81",
        ],
    )
    imu = read_euroc_imu(path)
    assert imu.t.shape == (1,)


def test_rows_are_returned_in_time_order(tmp_path):
    path = _write(
        tmp_path,
        [
            HEADER,
            "3000000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "1000000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
            "2000000000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81",
        ],
    )
    imu = read_euroc_imu(path)
    assert np.all(np.diff(imu.t) > 0), "unsorted input must be sorted, not trusted"


def test_a_trailing_temperature_column_is_ignored(tmp_path):
    """EuRoC appends temperature; the loader takes the first seven fields."""
    path = _write(
        tmp_path,
        [HEADER, "1000000000, 0.1, 0.2, 0.3, 0.0, 0.0, 9.81, 36.5"],
    )
    imu = read_euroc_imu(path)
    assert imu.accel.shape == (1, 3)


def test_a_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_euroc_imu(str(tmp_path / "absent.csv"))


def test_a_file_with_no_data_rows_raises_value_error(tmp_path):
    """A header-only file is a data problem, and must not look like an empty stream.

    Returning a zero-length ImuSample here would let an empty recording reach
    the filter, where it would fail later with a much less obvious message.
    """
    path = _write(tmp_path, [HEADER, "# only comments", ""])
    with pytest.raises(ValueError, match="no IMU rows"):
        read_euroc_imu(path)
