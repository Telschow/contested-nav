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


# ----------------------------------------------------------------------- GNSS


def _nmea(body: str) -> str:
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"${body}*{x:02X}"


def _gga(tod: str, quality: int = 2, lat: str = "2218.12774,N", lon: str = "11410.82767,E", sats: int = 12) -> str:
    return _nmea(f"GNGGA,{tod},{lat},{lon},{quality},{sats:02d},0.58,0.4,M,-1.6,M,,0000")


def _no_fix(tod: str) -> str:
    return _nmea(f"GNGGA,{tod},,,,,0,00,99.99,,,,,,")


RMC = _nmea("GNRMC,072028.00,A,2218.12774,N,11410.82767,E,1.247,153.43,180521,,,D,V")


def write_nmea(path: Path, sentences: list[str]) -> Path:
    path.write_text("\r\n".join(sentences) + "\r\n", encoding="ascii")
    return path


def test_gga_fixes_are_read_in_utc_with_the_date_from_rmc(tmp_path):
    p = write_nmea(tmp_path / "f.nmea", [RMC, _gga("072028.00"), _gga("072029.00")])
    fx = ud.read_gga(p)
    assert fx.utc_s.tolist() == [1621322428.0, 1621322429.0]
    assert fx.lat_deg[0] == pytest.approx(22 + 18.12774 / 60)
    assert fx.lon_deg[0] == pytest.approx(114 + 10.82767 / 60)
    assert fx.height_m[0] == pytest.approx(0.4 - 1.6)
    assert fx.quality.tolist() == [2, 2] and fx.num_sats.tolist() == [12, 12]


def test_a_sentence_with_no_position_is_kept_as_nan(tmp_path):
    fx = ud.read_gga(write_nmea(tmp_path / "f.nmea", [RMC, _gga("072028.00"), _no_fix("072029.00")]))
    assert fx.quality.tolist() == [2, 0]
    assert np.isnan(fx.lat_deg[1]) and np.isnan(fx.lon_deg[1]) and np.isnan(fx.height_m[1])


def test_southern_western_hemispheres_are_negative(tmp_path):
    fx = ud.read_gga(write_nmea(tmp_path / "f.nmea", [RMC, _gga("072028.00", lat="3352.12800,S", lon="07040.15800,W")]))
    assert fx.lat_deg[0] == pytest.approx(-(33 + 52.128 / 60))
    assert fx.lon_deg[0] == pytest.approx(-(70 + 40.158 / 60))


def test_bad_checksums_and_malformed_sentences_are_dropped_and_counted(tmp_path):
    bad = _gga("072029.00")[:-2] + "00"
    short = _nmea("GNGGA,072030.00,2218.1,N")
    fx = ud.read_gga(write_nmea(tmp_path / "f.nmea", [RMC, _gga("072028.00"), bad, short, _gga("072031.00")]))
    assert fx.utc_s.tolist() == [1621322428.0, 1621322431.0]
    assert fx.skipped == 2


def test_the_clock_passing_midnight_adds_a_day(tmp_path):
    rmc = _nmea("GNRMC,235958.00,A,2218.12774,N,11410.82767,E,1.2,153.43,180521,,,D,V")
    fx = ud.read_gga(write_nmea(tmp_path / "f.nmea", [rmc, _gga("235959.00"), _gga("000000.00"), _gga("000001.00")]))
    assert np.allclose(np.diff(fx.utc_s), 1.0)


def test_without_a_date_the_fixes_cannot_be_placed_and_a_page_is_rejected(tmp_path):
    with pytest.raises(SequenceError, match="RMC"):
        ud.read_gga(write_nmea(tmp_path / "f.nmea", [_gga("072028.00")]))
    page = tmp_path / "p.nmea"
    page.write_text("<!DOCTYPE html>\n<html>\n", encoding="ascii")
    with pytest.raises(SequenceError):
        ud.read_gga(page)


def _fixes(flags: list[int], times: list[float] | None = None) -> ud.GgaFixes:
    n = len(flags)
    t = np.arange(n, dtype=float) if times is None else np.array(times)
    q = np.array(flags)
    pos = np.where(q > 0, 22.3, np.nan)
    return ud.GgaFixes(t, pos, np.where(q > 0, 114.2, np.nan), np.zeros(n), q, np.full(n, 12), np.full(n, 0.6))


def test_one_run_of_denied_epochs_is_one_outage_that_ends_at_the_next_valid_epoch():
    assert ud.outage_intervals(_fixes([2, 2, 0, 0, 0, 2, 2])) == [(2.0, 5.0)]


def test_an_outage_covers_its_start_and_not_its_end():
    start, end = ud.outage_intervals(_fixes([2, 0, 0, 2]))[0]
    t = np.arange(4.0)
    assert [(start <= x < end) for x in t] == [False, True, True, False]


def test_a_run_that_reaches_the_end_of_the_file_ends_one_spacing_later():
    assert ud.outage_intervals(_fixes([2, 2, 0, 0])) == [(2.0, 4.0)]


def test_a_position_with_quality_zero_and_a_missing_position_with_quality_two_are_both_denied():
    fx = _fixes([2, 2, 2, 2])
    fx.quality[1] = 0
    fx.lat_deg[2] = np.nan
    assert ud.outage_intervals(fx) == [(1.0, 3.0)]


def test_time_with_no_epoch_is_denied():
    fx = _fixes([2, 2, 2, 2], times=[0.0, 1.0, 2.0, 7.0])
    assert ud.outage_intervals(fx) == [(3.0, 7.0)]


def test_a_gap_next_to_a_denied_run_merges_into_one_outage():
    fx = _fixes([2, 0, 2, 2], times=[0.0, 1.0, 2.0, 6.0])
    assert ud.outage_intervals(fx) == [(1.0, 2.0), (3.0, 6.0)]
    fx = _fixes([2, 0, 0, 2], times=[0.0, 1.0, 2.0, 6.0])
    assert ud.outage_intervals(fx) == [(1.0, 6.0)]


def test_two_separate_runs_are_two_outages_and_a_clean_stream_has_none():
    assert ud.outage_intervals(_fixes([2, 0, 2, 0, 2])) == [(1.0, 2.0), (3.0, 4.0)]
    assert ud.outage_intervals(_fixes([2, 2, 2, 2])) == []


def test_the_rule_reads_only_the_fix_flag():
    flags = [2, 2, 0, 0, 2, 2]
    a = _fixes(flags)
    b = _fixes(flags)
    b.num_sats[:] = 3
    b.hdop[:] = 50.0
    assert ud.outage_intervals(a) == ud.outage_intervals(b)


def test_a_missing_nmea_file_says_where_it_goes(tmp_path):
    with pytest.raises(SequenceError, match="copy it here"):
        ud.load_gga(tmp_path, SEQ)
    with pytest.raises(SequenceError, match="no NMEA file"):
        ud.load_gga(tmp_path, "nope")


@pytest.fixture(scope="module")
def real_fixes():
    if not (FETCHED / SEQ / ud.NMEA_FILES[SEQ]).is_file():
        pytest.skip("the tunnel1 NMEA file is not in data/raw/urbannav/tunnel1/ (from the publisher's folder download)")
    return ud.load_gga(FETCHED, SEQ)


def test_the_real_receiver_epochs_sit_on_the_reference_seconds(real_fixes, real):
    assert real_fixes.skipped == 0
    assert np.all(np.isin(real_fixes.utc_s, real.reference.utc_s))


def test_the_real_tunnel_is_one_outage_of_minutes_and_not_at_the_edges(real_fixes, real):
    spans = ud.outage_intervals(real_fixes)
    assert len(spans) == 1
    start, end = spans[0]
    assert 60.0 < end - start < 300.0
    assert real.reference.utc_s[0] + 60.0 < start and end < real.reference.utc_s[-1] - 30.0


# ------------------------------------------------------------ GST and attitude


def _gst(tod: str, lat: float = 1.2, lon: float = 1.3, alt: float = 3.0) -> str:
    return _nmea(f"GNGST,{tod},59,3.0,2.8,130,{lat},{lon},{alt}")


def test_gst_error_estimates_are_read_with_the_date_from_rmc(tmp_path):
    p = write_nmea(tmp_path / "f.nmea", [RMC, _gst("072028.00"), _gst("072029.00", 16.5, 17.0, 40.0)])
    g = ud.read_gst(p)
    assert g.utc_s.tolist() == [1621322428.0, 1621322429.0]
    assert g.sigma_lat.tolist() == [1.2, 16.5] and g.sigma_lon.tolist() == [1.3, 17.0]
    assert g.sigma_alt.tolist() == [3.0, 40.0]


def test_gst_sentences_with_a_bad_checksum_or_an_empty_field_are_skipped(tmp_path):
    bad = _gst("072029.00")[:-2] + "00"
    empty = _nmea("GNGST,072030.00,,,,,,,")
    g = ud.read_gst(write_nmea(tmp_path / "f.nmea", [RMC, _gst("072028.00"), bad, empty]))
    assert len(g) == 1
    with pytest.raises(SequenceError, match="no valid GST"):
        ud.read_gst(write_nmea(tmp_path / "g.nmea", [RMC, _gga("072028.00")]))


def test_the_attitude_convention_points_the_forward_axis_where_the_heading_says():
    one = lambda v: np.array([v], dtype=float)  # noqa: E731
    fwd = np.array([0.0, 1.0, 0.0])  # body y is forward
    east = ud.rpy_to_rotation(one(0), one(0), one(90))[0] @ fwd
    assert east == pytest.approx([1.0, 0.0, 0.0], abs=1e-12)  # heading is clockwise from north
    assert ud.rpy_to_rotation(one(0), one(0), one(0))[0] @ fwd == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)
    up = ud.rpy_to_rotation(one(0), one(30), one(0))[0] @ fwd
    assert up[2] == pytest.approx(0.5, abs=1e-12) and up[1] > 0  # positive pitch is nose up
    right = np.array([1.0, 0.0, 0.0])
    down = ud.rpy_to_rotation(one(30), one(0), one(0))[0] @ right
    assert down[2] == pytest.approx(-0.5, abs=1e-12)  # positive roll is the right side down


def test_the_attitude_matrices_are_rotations():
    rng = np.random.default_rng(0)
    r = ud.rpy_to_rotation(rng.uniform(-30, 30, 50), rng.uniform(-30, 30, 50), rng.uniform(0, 360, 50))
    assert np.allclose(r @ np.transpose(r, (0, 2, 1)), np.eye(3), atol=1e-12)
    assert np.allclose(np.linalg.det(r), 1.0)


def test_the_real_reference_velocity_rotated_with_this_convention_matches_the_positions(real):
    r = ud.rpy_to_rotation(real.reference.rpy_deg[:, 0], real.reference.rpy_deg[:, 1], real.reference.rpy_deg[:, 2])
    v = np.einsum("nij,nj->ni", r, real.reference.vel_body)[1:-1]
    e, t = real.truth_enu, real.truth_t
    fd = (e[2:] - e[:-2]) / (t[2:] - t[:-2])[:, None]
    moving = np.linalg.norm(fd[:, :2], axis=1) > 3.0
    assert np.median(np.linalg.norm((v - fd)[moving], axis=1)) < 0.2


def test_the_real_static_accelerometer_reading_rotated_with_this_convention_points_up(real):
    r = ud.rpy_to_rotation(real.reference.rpy_deg[:, 0], real.reference.rpy_deg[:, 1], real.reference.rpy_deg[:, 2])
    f = real.imu.accel[real.imu.t < 3.0].mean(axis=0)
    k = int(np.argmin(np.abs(real.truth_t - 1.5)))
    up = r[k] @ f
    assert up[2] > 9.3 and abs(up[0]) < 0.6 and abs(up[1]) < 0.6


def test_rotation_to_rpy_inverts_rpy_to_rotation():
    rng = np.random.default_rng(3)
    roll, pitch, heading = rng.uniform(-60, 60, 200), rng.uniform(-80, 80, 200), rng.uniform(-180, 180, 200)
    r, p, h = ud.rotation_to_rpy(ud.rpy_to_rotation(roll, pitch, heading))
    assert r == pytest.approx(roll, abs=1e-9)
    assert p == pytest.approx(pitch, abs=1e-9)
    assert (h - heading + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-9)


def test_rotation_to_rpy_gives_the_same_angles_for_a_single_matrix_and_for_a_stack():
    r = ud.rpy_to_rotation(np.array([10.0]), np.array([-5.0]), np.array([200.0]))
    single = ud.rotation_to_rpy(r[0])
    stack = ud.rotation_to_rpy(r)
    assert single[0] == pytest.approx(stack[0][0]) and single[2] == pytest.approx(stack[2][0])
