"""The UrbanNav reader, on files written here in the publisher's layout, and on the fetched files when present.

The synthetic files copy the layout of the real ones: CRLF line ends, two header rows, latitude and longitude as
three tokens each with the sign on the degrees, and an IMU CSV with the 41 columns of the ROS export. The real-file
test runs only when ``navkit urbannav fetch --sequence tunnel1`` has been run.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from navkit import urbannav_data as ud
from navkit.io import urbannav_fetch as uf
from navkit.recorded import SequenceError

ROOT = Path(__file__).resolve().parent.parent
FETCHED = ROOT / "data" / "raw" / "urbannav"
SEQ = "tunnel1"
REF_NAME, IMU_NAME = tuple(uf.SOURCES[SEQ])

REF_HEADER = [
    "      UTCTime       Week   GPSTime         Latitude        Longitude        H-Ell VelBdyX VelBdyY VelBdyZ "
    "AccBdyX AccBdyY AccBdyZ           Roll          Pitch        Heading Q",
    "        (sec)    (weeks)     (sec)       (+/-D M S)       (+/-D M S)          (m)   (m/s)   (m/s)   (m/s) "
    "(m/s^2) (m/s^2) (m/s^2)          (deg)          (deg)          (deg)  ",
]


def _dms(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    d = int(v)
    m = int((v - d) * 60.0)
    s = (v - d - m / 60.0) * 3600.0
    return f"{sign}{d} {m:02d} {s:08.5f}"


def _ref_row(utc: float, lat: float, lon: float, h: float, vel: float = 0.0, q: int = 2) -> str:
    return (
        f"{utc:.2f} 2158.00000 {utc - 1621123182.0:.2f}   {_dms(lat)}  {_dms(lon)}  {h:.3f} "
        f"{vel:.3f} 0.000 0.000 0.100 0.200 0.300 1.0 2.0 -173.8 {q}"
    )


def write_reference(path: Path, rows: list[str], header: list[str] | None = None) -> Path:
    path.write_bytes(("\r\n".join([*(REF_HEADER if header is None else header), *rows]) + "\r\n").encode("ascii"))
    return path


def imu_header() -> list[str]:
    cov = lambda base: [f"{base}_covariance{i}" for i in range(9)]  # noqa: E731
    return [
        "%time",
        "field.header.seq",
        "field.header.stamp",
        "field.header.frame_id",
        *[f"field.orientation.{a}" for a in "xyzw"],
        *cov("field.orientation"),
        *[f"field.angular_velocity.{a}" for a in "xyz"],
        *cov("field.angular_velocity"),
        *[f"field.linear_acceleration.{a}" for a in "xyz"],
        *cov("field.linear_acceleration"),
    ]


def write_imu(path: Path, stamps_ns: list[int], header: list[str] | None = None) -> Path:
    head = imu_header() if header is None else header
    lines = [",".join(head)]
    for i, ns in enumerate(stamps_ns):
        row = ["0"] * len(imu_header())
        row[0], row[1], row[2], row[3] = str(ns + 300_000), str(i), str(ns), "/imu"
        row[17:20] = ["0.1", "0.2", "0.3"]  # angular velocity
        row[29:32] = ["1.5", "2.5", "9.8"]  # linear acceleration
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


# ------------------------------------------------------------------ reference


def test_degrees_minutes_seconds_with_the_sign_on_the_degrees():
    assert ud.dms_to_deg("22", "18", "07.71148") == pytest.approx(22 + 18 / 60 + 7.71148 / 3600)
    assert ud.dms_to_deg("-22", "18", "07.71148") == pytest.approx(-(22 + 18 / 60 + 7.71148 / 3600))
    assert ud.dms_to_deg("+114", "10", "49.68095") == pytest.approx(114 + 10 / 60 + 49.68095 / 3600)


def test_a_negative_angle_below_one_degree_keeps_its_sign():
    assert ud.dms_to_deg("-0", "30", "00") == pytest.approx(-0.5)


@pytest.mark.parametrize(("m", "s"), [("60", "00"), ("-1", "00"), ("10", "60"), ("10", "-3")])
def test_minutes_and_seconds_out_of_range_are_rejected(m, s):
    with pytest.raises(SequenceError, match="out of range"):
        ud.dms_to_deg("22", m, s)


def test_the_reference_is_read_with_crlf_and_two_header_rows(tmp_path):
    rows = [
        _ref_row(1621322428.0 + i, 22.302142 + i * 1e-5, 114.180467, 3.7 - i * 0.01, vel=1.0 + i, q=1 + i)
        for i in range(4)
    ]
    ref = ud.read_reference(write_reference(tmp_path / REF_NAME, rows))
    assert len(ref) == 4
    assert np.array_equal(ref.utc_s, 1621322428.0 + np.arange(4))
    assert ref.lat_deg[0] == pytest.approx(22.302142, abs=1e-8)
    assert ref.lon_deg[0] == pytest.approx(114.180467, abs=1e-8)
    assert ref.height_m[3] == pytest.approx(3.67)
    assert ref.vel_body[:, 0].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert ref.acc_body[0].tolist() == [0.1, 0.2, 0.3]
    assert ref.rpy_deg[0].tolist() == [1.0, 2.0, -173.8]
    assert ref.quality.tolist() == [1, 2, 3, 4]
    assert ref.gps_tow_s[0] == pytest.approx(1621322428.0 - 1621123182.0)


def test_southern_and_western_positions_are_negative(tmp_path):
    ref = ud.read_reference(write_reference(tmp_path / REF_NAME, [_ref_row(1.0, -33.8688, -70.6693, 5.0)]))
    assert ref.lat_deg[0] == pytest.approx(-33.8688, abs=1e-8)
    assert ref.lon_deg[0] == pytest.approx(-70.6693, abs=1e-8)


def test_a_row_with_the_wrong_number_of_values_is_rejected_with_its_line_number(tmp_path):
    rows = [_ref_row(1.0, 22.3, 114.2, 3.0), _ref_row(2.0, 22.3, 114.2, 3.0) + " 9"]
    with pytest.raises(SequenceError, match=r":4: 21 values, expected 20"):
        ud.read_reference(write_reference(tmp_path / REF_NAME, rows))


def test_times_that_do_not_increase_are_rejected(tmp_path):
    rows = [_ref_row(2.0, 22.3, 114.2, 3.0), _ref_row(2.0, 22.3, 114.2, 3.0)]
    with pytest.raises(SequenceError, match="strictly increasing"):
        ud.read_reference(write_reference(tmp_path / REF_NAME, rows))


def test_a_file_that_is_not_the_table_is_rejected(tmp_path):
    with pytest.raises(SequenceError, match="UTCTime"):
        ud.read_reference(
            write_reference(tmp_path / REF_NAME, [_ref_row(1.0, 22.3, 114.2, 3.0)], header=["<html>", "x"])
        )
    page = tmp_path / "page.txt"
    page.write_bytes(b"<!DOCTYPE html>\r\n<html>\r\n")
    with pytest.raises(SequenceError):
        ud.read_reference(page)


def test_a_value_that_is_not_a_number_is_rejected(tmp_path):
    bad = _ref_row(1.0, 22.3, 114.2, 3.0).replace("0.100", "abc", 1)
    with pytest.raises(SequenceError, match="not a number"):
        ud.read_reference(write_reference(tmp_path / REF_NAME, [bad]))


# ------------------------------------------------------------------------ ENU


def test_the_origin_row_is_zero_and_height_is_up():
    enu, origin = ud.llh_to_enu(np.array([22.3, 22.3]), np.array([114.2, 114.2]), np.array([3.0, 13.0]))
    assert origin == (22.3, 114.2, 3.0)
    assert np.allclose(enu[0], 0.0, atol=1e-6)
    assert np.allclose(enu[1], [0.0, 0.0, 10.0], atol=1e-6)


def test_north_and_east_steps_match_the_ellipsoid_radii():
    lat0, lon0 = 22.302142, 114.180467
    d = 0.001
    enu, _ = ud.llh_to_enu(np.array([lat0, lat0 + d, lat0]), np.array([lon0, lon0, lon0 + d]), np.zeros(3))
    phi = math.radians(lat0)
    w = 1.0 - ud.WGS84_E2 * math.sin(phi) ** 2
    meridian = ud.WGS84_A * (1.0 - ud.WGS84_E2) / w**1.5
    prime = ud.WGS84_A / math.sqrt(w)
    assert enu[1, 1] == pytest.approx(meridian * math.radians(d), abs=2e-3)
    assert abs(enu[1, 0]) < 2e-3
    assert enu[2, 0] == pytest.approx(prime * math.cos(phi) * math.radians(d), abs=2e-3)
    assert abs(enu[2, 1]) < 2e-3


# ------------------------------------------------------------------------ IMU


def test_the_imu_columns_are_found_by_name_and_time_is_the_sensor_stamp(tmp_path):
    ns0 = 1_621_322_428_511_884_927
    imu, epoch = ud.read_imu(write_imu(tmp_path / IMU_NAME, [ns0 + i * 2_500_000 for i in range(5)]))
    assert len(imu) == 5
    assert imu.gyro[0].tolist() == [0.1, 0.2, 0.3]
    assert imu.accel[0].tolist() == [1.5, 2.5, 9.8]
    assert imu.t[0] == 0.0
    assert np.allclose(np.diff(imu.t), 0.0025, atol=1e-9)
    assert epoch == pytest.approx(1621322428.511885, abs=1e-6)


def test_the_logging_time_is_not_used(tmp_path):
    ns0 = 1_000_000_000_000
    imu, _ = ud.read_imu(write_imu(tmp_path / IMU_NAME, [ns0, ns0 + 5_000_000]))
    assert imu.t[1] == pytest.approx(0.005)


def test_a_missing_column_is_named(tmp_path):
    head = [c for c in imu_header() if c != "field.angular_velocity.y"]
    path = tmp_path / IMU_NAME
    path.write_text(",".join(head) + "\n" + ",".join(["0"] * len(head)) + "\n", encoding="ascii")
    with pytest.raises(SequenceError, match=r"no column 'field.angular_velocity.y'"):
        ud.read_imu(path)


def test_stamps_that_go_backwards_are_rejected(tmp_path):
    with pytest.raises(SequenceError, match="backwards"):
        ud.read_imu(write_imu(tmp_path / IMU_NAME, [1_000_000_000, 3_000_000_000, 2_000_000_000]))


def test_a_web_page_is_not_an_imu_file(tmp_path):
    page = tmp_path / IMU_NAME
    page.write_text("<!DOCTYPE html>\n<html>\n", encoding="ascii")
    with pytest.raises(SequenceError):
        ud.read_imu(page)


# ------------------------------------------------------------------- sequence


def _synthetic_sequence(root: Path) -> None:
    folder = root / SEQ
    folder.mkdir(parents=True)
    ns0 = 1_621_322_428_500_000_000
    write_imu(folder / IMU_NAME, [ns0 + i * 2_500_000 for i in range(1600)])  # 4 s at 400 Hz
    rows = [_ref_row(1621322428.0 + i, 22.302142 + i * 1e-5, 114.180467, 3.0) for i in range(6)]
    write_reference(folder / REF_NAME, rows)


def test_reference_and_imu_share_one_clock(tmp_path):
    _synthetic_sequence(tmp_path)
    seq = ud.load_sequence(tmp_path, SEQ)
    assert seq.truth_t[0] == pytest.approx(-0.5, abs=1e-6)
    assert seq.truth_t[1] == pytest.approx(0.5, abs=1e-6)
    assert seq.truth_enu.shape == (6, 3)
    assert np.allclose(seq.truth_enu[0], 0.0, atol=1e-6)
    assert seq.truth_enu[5, 1] == pytest.approx(5 * 1e-5 * 110_700.0, rel=0.01)
    assert any("outside the IMU time span" in n for n in seq.notes)
    assert set(seq.sha256) == {REF_NAME, IMU_NAME}
    assert any("one clock" in n for n in seq.notes)


def test_missing_files_say_how_to_fetch(tmp_path):
    with pytest.raises(SequenceError, match="navkit urbannav fetch --sequence tunnel1"):
        ud.load_sequence(tmp_path, SEQ)
    with pytest.raises(SequenceError, match="unknown sequence"):
        ud.load_sequence(tmp_path, "nope")


def test_the_fetcher_and_the_reader_agree_on_which_file_is_which():
    for seq, files in uf.SOURCES.items():
        ref_name, imu_name = tuple(files)
        assert ref_name.endswith(".txt"), seq
        assert imu_name.endswith(".csv") and "imu" in imu_name, seq


# ------------------------------------------------------------- the real files


@pytest.fixture(scope="module")
def real():
    if not (FETCHED / SEQ / REF_NAME).is_file() or not (FETCHED / SEQ / IMU_NAME).is_file():
        pytest.skip("tunnel1 is not fetched (navkit urbannav fetch --sequence tunnel1)")
    return ud.load_sequence(FETCHED, SEQ)


def test_the_fetched_reference_is_one_row_per_second_with_no_gaps(real):
    assert len(real.reference) > 100
    assert np.allclose(np.diff(real.reference.utc_s), 1.0)
    assert set(np.unique(real.reference.quality)) <= set(range(1, 7))


def test_the_fetched_imu_runs_at_about_400_hz_and_reads_gravity_on_z(real):
    rate = 1.0 / np.median(np.diff(real.imu.t))
    assert 350.0 < rate < 450.0
    first = real.imu.accel[real.imu.t < 1.0].mean(axis=0)
    assert 9.0 < first[2] < 10.5
    assert abs(first[0]) < 1.0 and abs(first[1]) < 1.0


def test_the_converted_positions_move_at_the_speed_the_reference_reports(real):
    e, t = real.truth_enu, real.truth_t
    v_enu = np.linalg.norm((e[2:] - e[:-2]) / (t[2:] - t[:-2])[:, None], axis=1)
    v_body = np.linalg.norm(real.reference.vel_body[1:-1], axis=1)
    assert np.median(np.abs(v_enu - v_body)) < 0.1
