"""The Tunnel-1 run, and the aided run of a sequence without an outage, on sequences written here, so that CI
exercises the code that the real data would.

The fixture is generated from code with made-up numbers (S2): a vehicle driving east at constant speed on a made-up
spot of the globe, a reference table at 1 Hz, a 20 Hz IMU, and an NMEA file with one fix per second and a gap in the
middle that is the outage. The second fixture, ``canyon=True``, is the same drive for another sequence name with no
outage, where some fixes carry a valid flag and are tens of metres wrong. A gyroscope bias that starts after the
filter's start-bias window drifts the roll, which is the known answer the oracle tests are checked against. Nothing
here is a row of the real dataset, and no data file is committed. These tests do not skip when the real dataset is
absent.
"""

from __future__ import annotations

import calendar
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from navkit import urbannav_data as ud
from navkit import urbannav_run as ur
from navkit.io import urbannav_fetch as uf
from navkit.types import GRAVITY

SEQ = "tunnel1"
DEEP = "deepurban1"
REF_NAME, IMU_NAME = tuple(uf.SOURCES[SEQ])
NMEA_NAME = ud.NMEA_FILES[SEQ]
CANYON_EVERY, CANYON_PHASE = 7, 3  # every 7th fix, from the 3rd, is a multipath fix
CANYON_ERROR_M = 25.0
CANYON_SIGMA = "4.00"  # what the receiver reports for those fixes; the others report 1.50

DURATION_S = 90
IMU_RATE_HZ = 20
OUTAGE_FIRST, OUTAGE_LAST = 25, 64  # epochs 25 to 64 have no fix, so the outage is [25, 65)
SPEED_M_S = 10.0
LAT0, LON0 = 10.25, 20.5  # a made-up spot
M_PER_DEG = 111_320.0
TILT_BIAS_RAD_S = 0.003  # about the forward axis, from TILT_ONSET_S on: after the start-bias window
TILT_ONSET_S = 24.0  # just before the outage
MIDNIGHT = float(calendar.timegm((2030, 3, 15, 0, 0, 0)))
TOD0 = 36_000.0


def _nmea(body: str) -> str:
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"${body}*{x:02X}"


def _hhmmss(tod: float) -> str:
    return f"{int(tod // 3600):02d}{int(tod % 3600 // 60):02d}{tod % 60:05.2f}"


def _lat_lon(east_m: float, north_m: float = 0.0) -> tuple[float, float]:
    return LAT0 + north_m / M_PER_DEG, LON0 + east_m / (M_PER_DEG * math.cos(math.radians(LAT0)))


def _dms(value: float) -> str:
    total = round(abs(value) * 3600.0 * 1e5)
    deg, rest = divmod(total, 3600 * 10**5)
    minutes, sec = divmod(rest, 60 * 10**5)
    return f"{'-' if value < 0 else ''}{deg} {minutes:02d} {sec / 1e5:08.5f}"


def _ddmm(value: float, digits: int) -> str:
    deg = int(abs(value))
    return f"{deg:0{digits}d}{(abs(value) - deg) * 60.0:08.5f}"


def write_sequence(
    root: Path,
    seq: str = SEQ,
    *,
    gst_sigma: dict[int, str] | None = None,
    tilt_bias: float = TILT_BIAS_RAD_S,
    nmea: bool = True,
    outage: bool = True,
    canyon: bool = False,
) -> Path:
    """Write ``<root>/<seq>/`` in the publisher's layout. ``gst_sigma`` maps an epoch to the text of its sigma.

    ``canyon`` makes every ``CANYON_EVERY``-th fix a multipath fix: valid flag, ``CANYON_ERROR_M`` metres off to the
    east, fewer satellites, a worse HDOP and a larger reported sigma. It does not change the fixes of the other
    epochs, so the stream of a sequence without ``canyon`` is the one the Tunnel-1 tests have always used.
    """
    ref_name, imu_name = tuple(uf.SOURCES[seq])
    nmea_name = ud.NMEA_FILES[seq]
    folder = root / seq
    folder.mkdir(parents=True, exist_ok=True)
    t_unix0 = MIDNIGHT + TOD0

    ref_header = [
        "UTCTime Week GPSTime Latitude Longitude H-Ell VelBdyX VelBdyY VelBdyZ AccBdyX AccBdyY AccBdyZ "
        "Roll Pitch Heading Q",
        "(sec) (weeks) (sec) (+/-D M S) (+/-D M S) (m) (m/s) (m/s) (m/s) (m/s^2) (m/s^2) (m/s^2) (deg) (deg) (deg)",
    ]
    rows = []
    for k in range(DURATION_S + 1):
        lat, lon = _lat_lon(SPEED_M_S * k)
        rows.append(
            f"{t_unix0 + k:.2f} 2000.00000 {TOD0 + k:.2f} {_dms(lat)} {_dms(lon)} 5.000 "
            f"0.000 {SPEED_M_S:.3f} 0.000 0.000 0.000 0.000 0.0 0.0 90.0 2"
        )
    (folder / ref_name).write_bytes(("\r\n".join([*ref_header, *rows]) + "\r\n").encode("ascii"))

    n = DURATION_S * IMU_RATE_HZ + 1
    stamps = (int(t_unix0 * 1e9) + (np.arange(n) * (1e9 / IMU_RATE_HZ)).astype(np.int64)).astype(np.int64)
    lines = [",".join(["%time", ud.IMU_STAMP, *ud.IMU_GYRO, *ud.IMU_ACCEL])]
    g = float(np.linalg.norm(GRAVITY))
    for i, ns in enumerate(stamps):
        gy = tilt_bias if i / IMU_RATE_HZ >= TILT_ONSET_S else 0.0
        lines.append(f"{int(ns) + 300_000},{int(ns)},0.0,{gy!r},0.0,0.0,0.0,{g!r}")
    (folder / imu_name).write_text("\n".join(lines) + "\n", encoding="ascii")

    if nmea:
        rng = np.random.default_rng(1)
        gst = gst_sigma or {}
        out = []
        date = "150330"
        for k in range(DURATION_S):
            tod = TOD0 + k
            stamp = _hhmmss(tod)
            if outage and OUTAGE_FIRST <= k <= OUTAGE_LAST:
                out.append(_nmea(f"GNGGA,{stamp},,,,,0,00,99.99,,,,,,"))
                continue
            e, nn = rng.normal(0.0, 1.0, 2)
            multipath = canyon and k % CANYON_EVERY == CANYON_PHASE
            lat, lon = _lat_lon(SPEED_M_S * k + e + (CANYON_ERROR_M if multipath else 0.0), nn)
            sats, hdop = ("07", "2.50") if multipath else ("12", "0.60")
            if k == 0:
                out.append(_nmea(f"GNRMC,{stamp},A,{_ddmm(lat, 2)},N,{_ddmm(lon, 3)},E,0.0,0.0,{date},,,A"))
            out.append(_nmea(f"GNGGA,{stamp},{_ddmm(lat, 2)},N,{_ddmm(lon, 3)},E,1,{sats},{hdop},5.0,M,-1.0,M,,0000"))
            sigma = gst.get(k, CANYON_SIGMA if multipath else "1.50")
            out.append(_nmea(f"GNGST,{stamp},1.0,2.0,1.0,0.0,{sigma},{sigma},3.00"))
        (folder / nmea_name).write_text("\n".join(out) + "\n", encoding="ascii")
    return root


def write_tunnel(root: Path, **kwargs: Any) -> Path:
    """The Tunnel-1 fixture: ``write_sequence`` for ``tunnel1``."""
    return write_sequence(root, SEQ, **kwargs)


@pytest.fixture(scope="module")
def tunnel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_tunnel(tmp_path_factory.mktemp("tunnel"))


@pytest.fixture(scope="module")
def built(tunnel: Path) -> Any:
    return ur.build(tunnel)


@pytest.fixture(scope="module")
def results(built: Any) -> dict[str, dict[str, Any]]:
    seq, gnss, spans, info = built
    return {v: ur.run_once(seq, gnss, spans, info, seed=0, variant=v) for v in ur.ALL_VARIANTS}


# ------------------------------------------------------------------------ the reader


def test_the_outage_is_the_gap_and_no_fix_is_offered_inside_it(built):
    _, gnss, spans, _ = built
    assert len(spans) == 1
    a, b = spans[0]
    assert (a, b) == pytest.approx((float(OUTAGE_FIRST), float(OUTAGE_LAST + 1)))
    assert not np.any((gnss.t >= a) & (gnss.t < b))
    assert len(gnss) == DURATION_S - (OUTAGE_LAST - OUTAGE_FIRST + 1)
    assert gnss.cov is not None and np.all(gnss.cov[:, 2] == ur.GNSS_VERTICAL_SIGMA_M**2)


def test_the_reader_reports_exactly_the_epochs_that_are_not_valid(built):
    _, _, _, info = built
    assert info["epochs_not_valid"] == OUTAGE_LAST - OUTAGE_FIRST + 1
    assert info["fixes_variance_unusable"] == 0
    assert info["fixes_variance_below_floor"] == 0


def test_the_filter_is_offered_only_the_valid_fixes_and_the_run_says_so(results, built):
    _, gnss, _, info = built
    for v, r in results.items():
        assert r["fixes_total"] == len(gnss), v
        assert r["epochs_not_valid"] == info["epochs_not_valid"], v
        assert r["fixes_variance_unusable"] == 0 and r["fixes_variance_below_floor"] == 0, v


# ----------------------------------------------------------------------- the variants


def test_every_variant_runs_and_gives_the_documented_quantities(results):
    assert set(results) == set(ur.ALL_VARIANTS)
    rows = ur.rows_for(SEQ, list(results.values()))
    assert {r["quantity"] for r in rows} == {k for k, _, _ in ur.QUANTITIES}
    assert {r["variant"] for r in rows} == set(ur.ALL_VARIANTS)
    assert len(rows) == len(ur.ALL_VARIANTS) * len(ur.QUANTITIES)
    assert all(set(r) == set(ur.CSV_COLUMNS) for r in rows)
    assert {r["sequence"] for r in rows} == {SEQ}


def test_the_oracle_variants_are_labelled_as_diagnostics_in_the_output(results):
    rows = ur.rows_for(SEQ, list(results.values()))
    block = ur.oracle_markdown(rows)
    for v in ur.ORACLE_VARIANTS:
        assert ur.ORACLE_LABELS[v] in block
        assert ur.ORACLE_LABELS[v].startswith("ORACLE DIAGNOSTIC")
        assert "not a filter" in ur.DECLARED[f"variant: {v}"][1]
    assert block.count("ORACLE DIAGNOSTIC") == len(ur.ORACLE_VARIANTS)
    assert "ORACLE" not in ur.oracle_markdown([r for r in rows if r["variant"] == "declared"])


def test_a_known_tilt_drift_grows_the_roll_error_and_the_outage_error(results):
    declared = results["declared"]
    assert abs(declared["att_roll_err_at_end_deg"]) > 5.0 * abs(declared["att_roll_err_at_start_deg"])
    assert declared["hor_err_at_end_m"] > 5.0 * declared["hor_err_at_start_m"]
    assert declared["hor_err_at_end_m"] > 3.0 * declared["hor_claimed_at_end_m"]


def test_an_oracle_given_the_true_tilt_ends_the_outage_nearer_the_reference(results):
    base = results["declared"]["hor_err_at_end_m"]
    assert results["oracle_tilt"]["hor_err_at_end_m"] < 0.5 * base
    assert results["oracle_attitude"]["hor_err_at_end_m"] < 0.5 * base
    # the true yaw changes nothing here, because the injected drift is in the tilt
    assert results["oracle_yaw"]["hor_err_at_end_m"] == pytest.approx(base, rel=0.1)


def test_an_oracle_is_the_declared_filter_before_the_outage(results):
    for v in ur.ORACLE_VARIANTS:
        for key in ("hor_err_median_before_m", "hor_nees_before", "hor_err_at_start_m"):
            assert results[v][key] == pytest.approx(results["declared"][key], rel=1e-9), (v, key)


def test_the_tilt_oracle_removes_the_roll_error_inside_the_outage(results):
    assert abs(results["oracle_tilt"]["att_roll_err_at_end_deg"]) < 0.1 * abs(
        results["declared"]["att_roll_err_at_end_deg"]
    )


def test_the_first_return_nis_is_reported_and_over_the_gate_when_the_error_is_large(results):
    level = ur.chi2_threshold(3, ur.GATE_ALPHA)
    r = results["declared"]
    assert r["fixes_after_outage"] > 0
    assert r["nis_first_return"] > level
    assert r["fixes_after_outage_over_gate"] >= 1


# ------------------------------------------------------------- an unusable variance


@pytest.mark.parametrize("text", ["nan", "inf"])
def test_a_fix_with_an_unusable_variance_is_dropped_before_the_filter_and_counted(tmp_path, text):
    root = write_tunnel(tmp_path, gst_sigma={7: text})
    seq, gnss, spans, info = ur.build(root)
    assert info["fixes_variance_unusable"] == 1
    assert len(gnss) == DURATION_S - (OUTAGE_LAST - OUTAGE_FIRST + 1) - 1
    assert 7.0 not in set(np.round(gnss.t, 3))
    assert np.isfinite(info["sigma_h"]) and info["sigma_h"] == pytest.approx(1.5, rel=1e-6)
    assert np.all(ur.usable_variance_mask(gnss.cov))
    for variant in ("declared", "per_fix"):
        r = ur.run_once(seq, gnss, spans, info, seed=0, variant=variant)  # no ValueError reaches the caller
        assert r["fixes_variance_unusable"] == 1
        assert r["fixes_total"] == len(gnss)


def test_a_sigma_below_the_floor_is_counted_and_kept(tmp_path):
    root = write_tunnel(tmp_path, gst_sigma={7: "0.005", 8: "0.0"})
    seq, gnss, spans, info = ur.build(root)
    assert info["fixes_variance_below_floor"] == 2
    assert info["fixes_variance_unusable"] == 0
    r = ur.run_once(seq, gnss, spans, info, seed=0, variant="per_fix")  # the filter floors them, it does not raise
    assert r["fixes_variance_below_floor"] == 2


# ----------------------------------------------------------------------------- main


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_main_writes_the_documented_csv_and_it_is_deterministic(tunnel, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    assert ur.main(["--root", str(tunnel), "--csv", str(first)]) == 0
    err = capsys.readouterr().err
    assert "epochs not passed on" in err and "dropped for an unusable variance" in err
    assert ur.main(["--root", str(tunnel), "--csv", str(second)]) == 0
    assert _sha(first) == _sha(second)
    rows = ur.rows_from_csv(first)
    assert first.read_text(encoding="utf-8").splitlines()[0] == ",".join(ur.CSV_COLUMNS)
    assert len(rows) == len(ur.ALL_VARIANTS) * len(ur.QUANTITIES)
    assert {r["variant"] for r in rows} == set(ur.ALL_VARIANTS)
    assert all(r["unit"] in {"", "m", "deg", "count", "flag"} for r in rows)


def test_main_fills_the_page_blocks_from_a_saved_csv_and_runs_nothing(tunnel, tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    csv_path, page = tmp_path / "run.csv", tmp_path / "page.md"
    assert ur.main(["--root", str(tunnel), "--csv", str(csv_path)]) == 0
    page.write_text(
        "\n".join(f"<!-- {name}:start -->\n<!-- {name}:end -->" for name in {**ur.BLOCKS, **ur.CODE_BLOCKS}) + "\n",
        encoding="utf-8",
    )
    assert ur.main(["--from-csv", str(csv_path), "--page", str(page)]) == 0
    text = page.read_text(encoding="utf-8")
    rows = ur.rows_from_csv(csv_path)
    for fn in {**ur.BLOCKS, **ur.CODE_BLOCKS}.values():
        assert fn(rows) in text
    assert "ORACLE DIAGNOSTIC" in text


def test_main_prints_the_tables_when_given_no_output(tunnel, monkeypatch, capsys):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    assert ur.main(["--root", str(tunnel)]) == 0
    out = capsys.readouterr().out
    assert "declared" in out and "ORACLE DIAGNOSTIC" in out


def test_a_page_without_the_block_lines_is_refused_with_a_message(tmp_path, monkeypatch, capsys):
    page = tmp_path / "page.md"
    page.write_text("no blocks here\n", encoding="utf-8")
    csv_path = tmp_path / "x.csv"
    ur.write_csv(csv_path, [])
    assert ur.main(["--from-csv", str(csv_path), "--page", str(page)]) == 1
    assert "needs the lines" in capsys.readouterr().err


def test_a_missing_dataset_path_gives_the_documented_message_and_not_a_traceback(tmp_path, capsys):
    assert ur.main(["--root", str(tmp_path / "nowhere")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "is missing" in err and "navkit urbannav fetch" in err
    assert "Traceback" not in err


def test_a_missing_nmea_file_gives_the_documented_message(tmp_path, capsys):
    root = write_tunnel(tmp_path, nmea=False)
    assert ur.main(["--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and NMEA_NAME in err and "missing" in err


def test_too_few_finite_receiver_sigmas_is_refused_with_a_message(tmp_path):
    root = write_tunnel(tmp_path, gst_sigma=dict.fromkeys(range(DURATION_S), "nan"))
    with pytest.raises(ur.SequenceError, match="fewer than 10 valid fixes"):
        ur.build(root)


def test_an_oracle_needs_an_outage_and_the_declared_filter_runs_without_one(tmp_path):
    root = write_tunnel(tmp_path, outage=False)
    seq, gnss, spans, info = ur.build(root)
    assert spans == [] and info["epochs_not_valid"] == 0
    with pytest.raises(ur.SequenceError, match="needs an outage"):
        ur.run_once(seq, gnss, spans, info, seed=0, variant="oracle_tilt")
    r = ur.run_once(seq, gnss, spans, info, seed=0, variant="declared")
    assert r["fixes_total"] == DURATION_S
    assert "hor_err_at_end_m" not in r  # the outage quantities exist only when there is an outage


# ================================================== a sequence without an outage: the aided run


@pytest.fixture(scope="module")
def canyon(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Every fix valid, some of them tens of metres wrong, no outage: the shape of an urban-canyon sequence."""
    return write_sequence(tmp_path_factory.mktemp("canyon"), DEEP, canyon=True, outage=False, tilt_bias=0.0)


@pytest.fixture(scope="module")
def canyon_built(canyon: Path) -> Any:
    return ur.build(canyon, DEEP)


@pytest.fixture(scope="module")
def aided(canyon_built: Any) -> dict[str, dict[str, Any]]:
    seq, gnss, spans, info = canyon_built
    return {v: ur.run_once(seq, gnss, spans, info, seed=0, variant=v) for v in ur.variants_for(spans)}


def _csv_lines(path: Path, sequence: str) -> list[bytes]:
    return [x for x in path.read_bytes().splitlines(keepends=True) if x.startswith(f"{sequence},".encode())]


def test_the_deep_urban_receiver_file_has_a_name_and_the_loader_uses_it(canyon):
    assert ud.NMEA_FILES[DEEP] == "UrbanNav-HK-Deep-Urban-1.ublox.f9p.nmea"
    assert (canyon / DEEP / ud.NMEA_FILES[DEEP]).is_file()
    fixes = ud.load_gga(canyon, DEEP)
    assert len(fixes) == DURATION_S and fixes.skipped == 0
    seq = ud.load_sequence(canyon, DEEP)
    assert seq.name == DEEP
    # the notes are about the units, not about one sequence
    assert all("tunnel" not in n.lower() and "deep" not in n.lower() for n in seq.notes)


def test_a_canyon_has_valid_degraded_fixes_and_no_outage(canyon, canyon_built):
    _, gnss, spans, info = canyon_built
    fixes = ud.load_gga(canyon, DEEP)
    assert ud.outage_intervals(fixes) == [] and spans == []
    assert np.all(fixes.quality == 1) and np.any(fixes.num_sats < 12) and np.any(fixes.hdop > 2.0)
    assert len(gnss) == DURATION_S and info["epochs_not_valid"] == 0
    assert ur.variants_for(spans) == ur.VARIANTS
    assert ur.variants_for([(1.0, 2.0)]) == ur.ALL_VARIANTS
    wrong = info["fix_difference_m"] > ur.WRONG_FIX_M
    assert 0 < int(wrong.sum()) < len(gnss)


def test_the_aided_run_gives_the_documented_quantities_and_only_those(aided):
    assert set(aided) == set(ur.VARIANTS)
    rows = ur.rows_for(DEEP, list(aided.values()))
    assert {r["quantity"] for r in rows} == {k for k, _, _ in ur.AIDED_QUANTITIES}
    assert len(rows) == len(ur.VARIANTS) * len(ur.AIDED_QUANTITIES)
    assert {r["sequence"] for r in rows} == {DEEP} and {r["variant"] for r in rows} == set(ur.VARIANTS)
    assert all(set(r) == set(ur.CSV_COLUMNS) for r in rows)
    for r in aided.values():
        for outage_only in ("hor_err_at_end_m", "nis_first_return", "accel_only_hor_err_at_end_m"):
            assert outage_only not in r


def test_the_aided_quantities_are_consistent_with_each_other(aided, canyon_built):
    _, gnss, _, info = canyon_built
    for v, r in aided.items():
        assert r["fixes_total"] == len(gnss), v
        assert r["fixes_used"] + r["gnss_updates_rejected"] == r["fixes_total"], v
        assert r["fix_rejection_rate"] == pytest.approx(r["gnss_updates_rejected"] / r["fixes_total"]), v
        assert 0.0 <= r["hor_coverage_2sigma"] <= 1.0 and 0.0 <= r["hor_inside_95"] <= 1.0
        assert math.isfinite(r["hor_nees_mean"]) and r["hor_nees_mean"] > 0.0
        assert math.isfinite(r["att_nees_mean"]) and r["att_nees_mean"] > 0.0
        assert r["fix_err_p50_m"] <= r["fix_err_p95_m"] <= r["fix_err_p99_m"], v
        assert r["fix_err_p99_m"] <= float(info["fix_difference_m"].max()) + 1e-9
        assert r["wrong_fixes_over_gate"] <= r["wrong_fixes"] <= r["fixes_total"]
        assert r["gnss_channel_faulted"] in (0, 1) and r["gnss_reaccepted"] >= 0


def test_the_fix_statistics_are_those_of_the_fixes_and_not_of_the_filter(aided, canyon_built):
    _, _, _, info = canyon_built
    d, s = info["fix_difference_m"], info["fix_sigma_h_m"]
    for r in aided.values():
        assert r["fix_nees_mean"] == pytest.approx(float(np.mean((d / s) ** 2)))
        assert r["fix_err_p95_m"] == pytest.approx(float(np.percentile(d, 95)))
    # the same fixes under both variants, so the same fix statistics
    a, b = aided["declared"], aided["per_fix"]
    assert a["fix_nees_mean"] == b["fix_nees_mean"] and a["fix_err_p50_m"] == b["fix_err_p50_m"]
    # the multipath fixes are far from the reference against what the receiver reports for them
    assert float(np.max(d / s)) > 3.0


def _trajectory(positions: np.ndarray, rotations: np.ndarray) -> Any:
    from navkit.types import Trajectory

    poses = np.tile(np.eye(4), (len(positions), 1, 1))
    poses[:, :3, :3], poses[:, :3, 3] = rotations, positions
    return Trajectory(t=np.arange(len(positions), dtype=float), poses=poses)


def _rot_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


@pytest.mark.parametrize(
    ("error_sigmas", "att_error_rad", "coverage", "att_nees"),
    [(0.0, 0.0, 1.0, 0.0), (1.9, 0.1, 1.0, 4.0), (2.1, 0.2, 0.0, 16.0)],
)
def test_the_aided_summary_against_known_answers(error_sigmas, att_error_rad, coverage, att_nees):
    n, sigma = 50, 2.0
    ref = _trajectory(np.zeros((n, 3)), np.tile(np.eye(3), (n, 1, 1)))
    est = _trajectory(
        np.tile([error_sigmas * sigma, -error_sigmas * sigma, 0.0], (n, 1)), np.tile(_rot_z(att_error_rad), (n, 1, 1))
    )
    detail = {
        "est": est,
        "reference": ref,
        "position_cov": np.tile(np.diag([sigma**2] * 3), (n, 1, 1)),
        "rotation_cov": np.tile(np.eye(3) * 0.05**2, (n, 1, 1)),
    }
    d = np.array([1.0, 2.0, 3.0, 4.0])
    out = ur.aided_summary(detail, {"gnss_updates_used": 3, "gnss_updates_rejected": 1}, 4, d, np.full(4, 2.0))
    assert out["hor_coverage_2sigma"] == coverage
    assert out["att_nees_mean"] == pytest.approx(att_nees, rel=1e-9)
    assert (out["fixes_used"], out["fix_rejection_rate"]) == (3, 0.25)
    assert out["fix_nees_mean"] == pytest.approx(np.mean((d / 2.0) ** 2))
    assert out["fix_err_p50_m"] == pytest.approx(2.5) and out["aided"] == 1


def _known_detail(n: int = 50) -> dict[str, Any]:
    ref = _trajectory(np.zeros((n, 3)), np.tile(np.eye(3), (n, 1, 1)))
    return {
        "est": ref,
        "reference": ref,
        "position_cov": np.tile(np.diag([4.0] * 3), (n, 1, 1)),
        "rotation_cov": np.tile(np.eye(3) * 0.05**2, (n, 1, 1)),
    }


def test_the_rejection_rate_has_wilson_intervals_on_the_raw_and_the_effective_count():
    from navkit.eval.calibration import wilson_interval

    level = ur.chi2_threshold(3, ur.GATE_ALPHA)
    rng = np.random.default_rng(5)
    nis = rng.uniform(0.0, 0.9 * level, 400)  # independent, and none over the level
    nis[[100, 101, 102, 103]] = 2.0 * level  # four in a row over it
    out = ur.aided_summary(
        _known_detail(),
        {"gnss_updates_used": 396, "gnss_updates_rejected": 4},
        400,
        np.ones(4),
        np.ones(4),
        nis=nis,
        gate_level=level,
    )
    assert out["fix_gate_alpha"] == ur.GATE_ALPHA
    assert out["fix_rejections_expected"] == pytest.approx(400 * ur.GATE_ALPHA)
    lo, hi = wilson_interval(4, 400)
    assert (out["fix_rejection_wilson_lo"], out["fix_rejection_wilson_hi"]) == (lo, hi)
    # four rejections in a row are one cluster, not four: the effective count is smaller and the interval wider
    assert out["fix_rejection_ess_defined"] == 1 and 1.0 <= out["fix_rejection_ess"] < 400.0
    eff_k = 4 * out["fix_rejection_ess"] / 400
    elo, ehi = wilson_interval(eff_k, out["fix_rejection_ess"])
    assert (out["fix_rejection_eff_wilson_lo"], out["fix_rejection_eff_wilson_hi"]) == (elo, ehi)
    assert ehi - elo > hi - lo


def test_with_no_rejection_the_effective_interval_is_the_raw_one_and_says_so():
    from navkit.eval.calibration import wilson_interval

    level = ur.chi2_threshold(3, ur.GATE_ALPHA)
    nis = np.linspace(0.1, 0.5 * level, 300)
    out = ur.aided_summary(
        _known_detail(),
        {"gnss_updates_used": 300, "gnss_updates_rejected": 0},
        300,
        np.ones(4),
        np.ones(4),
        nis=nis,
        gate_level=level,
    )
    assert out["fix_rejection_ess_defined"] == 0 and out["fix_rejection_ess"] == 300.0
    assert (out["fix_rejection_wilson_lo"], out["fix_rejection_wilson_hi"]) == wilson_interval(0, 300)
    assert (out["fix_rejection_eff_wilson_lo"], out["fix_rejection_eff_wilson_hi"]) == wilson_interval(0, 300)


def test_the_nees_means_carry_their_effective_sample_sizes():
    from navkit.eval.calibration import effective_samples

    n = 400
    rng = np.random.default_rng(2)
    slow = np.cumsum(rng.normal(size=n)) ** 2 + 1.0  # strongly autocorrelated
    out = ur.aided_summary(
        _known_detail(n), {"gnss_updates_used": 4, "gnss_updates_rejected": 0}, 4, np.ones(4), np.ones(4), nees_h=slow
    )
    n_eff, truncated = effective_samples(slow)
    assert out["hor_nees_ess"] == pytest.approx(n_eff) and out["hor_nees_ess_truncated"] == int(truncated)
    assert 1.0 <= out["hor_nees_ess"] < n
    # the attitude series here is constant (zero error), which has no estimate: it is NaN and not a made-up number
    assert math.isnan(out["att_nees_ess"]) and out["att_nees_ess_truncated"] == 0


def test_the_aided_run_reports_the_intervals_and_sample_sizes_it_documents(aided):
    for v, r in aided.items():
        assert 0.0 <= r["fix_rejection_wilson_lo"] <= r["fix_rejection_rate"] <= r["fix_rejection_wilson_hi"] <= 1.0, v
        assert r["fix_rejection_eff_wilson_lo"] <= r["fix_rejection_rate"] <= r["fix_rejection_eff_wilson_hi"], v
        assert 1.0 <= r["fix_rejection_ess"] <= r["fixes_total"], v
        assert r["fix_rejections_expected"] == pytest.approx(r["fixes_total"] * ur.GATE_ALPHA), v
        assert r["hor_nees_ess"] >= 1.0 and r["att_nees_ess"] >= 1.0, v


def test_the_aided_summary_counts_fixes_over_three_sigma_and_compares_the_sigmas():
    n = 60
    d = np.array([1.0, 5.9, 6.1, 20.0])  # receiver sigma 2: two of these are over 3 sigma
    nis = np.array([0.5, 1.5, 2.5, 0.1])
    out = ur.aided_summary(
        _known_detail(n),
        {"gnss_updates_used": 4, "gnss_updates_rejected": 0},
        4,
        d,
        np.full(4, 2.0),
        nis=nis,
        gate_level=16.0,
    )
    assert out["fixes_over_3sigma"] == 2
    assert out["receiver_sigma_median_m"] == 2.0 and out["claimed_sigma_median_m"] == pytest.approx(2.0)  # sqrt(4)
    assert out["nis_mean"] == pytest.approx(1.15) and out["fix_gate_level"] == 16.0


def test_the_nees_thirds_are_the_means_of_the_first_middle_and_last_part():
    n = 90
    rng = np.random.default_rng(7)
    ref = _trajectory(np.zeros((n, 3)), np.tile(np.eye(3), (n, 1, 1)))
    ramp = np.repeat([0.0, 1.0, 2.0], n // 3)  # error of 0, 1 and 2 sigma in each axis, by third
    est = _trajectory(np.column_stack([ramp * 2.0, ramp * 2.0, np.zeros(n)]), np.tile(np.eye(3), (n, 1, 1)))
    detail = {**_known_detail(n), "est": est, "reference": ref}
    nees = np.repeat([0.0, 2.0, 8.0], n // 3) + 0.0 * rng.normal(size=n)
    out = ur.aided_summary(
        detail, {"gnss_updates_used": 4, "gnss_updates_rejected": 0}, 4, np.ones(4), np.ones(4), nees_h=nees
    )
    assert [out[f"hor_nees_third{k}"] for k in (1, 2, 3)] == [0.0, 2.0, 8.0]
    assert [out[f"att_nees_third{k}"] for k in (1, 2, 3)] == [0.0, 0.0, 0.0]


def test_the_coverage_expectation_is_the_gaussian_two_sigma_share():
    assert abs(ur.COVERAGE_2SIGMA_GAUSSIAN - 0.9545) < 5e-5


def test_the_filter_exposes_its_attitude_covariance_next_to_the_position_one(canyon_built):
    seq, gnss, _, info = canyon_built
    detail: dict[str, Any] = {}
    opts = ur.RunOptions(
        gnss_sigma_m=info["sigma_h"], gnss_vertical_sigma_m=ur.GNSS_VERTICAL_SIGMA_M, seed=0, init_bias="static"
    )
    ur.run_sequence(seq, opts, gnss_override=gnss, detail_out=detail)
    rot = detail["rotation_cov"]
    assert rot.shape == detail["position_cov"].shape == (len(detail["est"]), 3, 3)
    assert np.all(np.linalg.eigvalsh(0.5 * (rot + rot.transpose(0, 2, 1))) > 0.0)


# ----------------------------------------------------------- the oracle variants are not applicable


def test_the_oracle_variants_are_not_applicable_without_an_outage_and_the_output_says_so(aided):
    rows = ur.rows_for(DEEP, list(aided.values()))
    block = ur.oracle_markdown(rows, DEEP)
    assert block == ur.ORACLE_NOT_APPLICABLE and "Not applicable" in block
    assert "ORACLE DIAGNOSTIC" not in block
    assert not {r["variant"] for r in rows} & set(ur.ORACLE_VARIANTS)
    assert ur.CODE_BLOCKS["urbannav-deep-urban-oracle"](rows) == ur.ORACLE_NOT_APPLICABLE


def test_asking_for_an_oracle_directly_without_an_outage_is_still_refused(canyon_built):
    seq, gnss, spans, info = canyon_built
    with pytest.raises(ur.SequenceError, match="needs an outage"):
        ur.run_once(seq, gnss, spans, info, seed=0, variant="oracle_tilt")


def test_main_runs_the_aided_variants_only_and_says_the_oracles_are_not_applicable(
    canyon, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    out_csv = tmp_path / "run.csv"
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--csv", str(out_csv)]) == 0
    err = capsys.readouterr().err
    assert "0 outage(s)" in err and "aided run" in err and "Not applicable" in err
    assert "oracle_tilt" not in err and "declared seed 0 done" in err and "per_fix seed 0 done" in err
    rows = ur.rows_from_csv(out_csv)
    assert {r["variant"] for r in rows} == set(ur.VARIANTS)
    assert len(rows) == len(ur.VARIANTS) * len(ur.AIDED_QUANTITIES)
    assert ur.main(["--root", str(canyon), "--sequence", DEEP]) == 0
    out = capsys.readouterr().out
    assert "declared" in out and "Not applicable" in out
    assert "Pooled 2-sigma per-axis coverage" in out


def test_main_is_deterministic_for_the_aided_run(canyon, tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--csv", str(first)]) == 0
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--csv", str(second)]) == 0
    assert _sha(first) == _sha(second)


# ----------------------------------------------------------------- writing one sequence at a time


def _stub_rows(sequence: str, n: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "sequence": sequence,
            "variant": "declared",
            "seed": s,
            "quantity": "hor_rmse_m",
            "value": f"{s}.5",
            "unit": "m",
        }
        for s in range(n)
    ]


def test_writing_another_sequence_leaves_the_tunnel_rows_byte_identical(tunnel, tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    path = tmp_path / "run.csv"
    assert ur.main(["--root", str(tunnel), "--csv", str(path)]) == 0
    before, tunnel_lines = path.read_bytes(), _csv_lines(path, SEQ)
    assert tunnel_lines
    ur.write_csv(path, _stub_rows(DEEP))
    assert path.read_bytes().startswith(before)  # nothing before the new rows moved or changed
    assert _csv_lines(path, SEQ) == tunnel_lines
    assert hashlib.sha256(b"".join(_csv_lines(path, SEQ))).digest() == hashlib.sha256(b"".join(tunnel_lines)).digest()
    assert len(_csv_lines(path, DEEP)) == 3


def test_writing_a_sequence_again_replaces_its_rows_and_keeps_its_place(tmp_path):
    path = tmp_path / "run.csv"
    ur.write_csv(path, _stub_rows(SEQ, 2))
    ur.write_csv(path, _stub_rows(DEEP, 2))
    ur.write_csv(path, _stub_rows(SEQ, 4))  # the first sequence again, with more rows
    assert [r["sequence"] for r in ur.rows_from_csv(path)] == [SEQ] * 4 + [DEEP] * 2
    ur.write_csv(path, _stub_rows(DEEP, 1))
    assert [r["sequence"] for r in ur.rows_from_csv(path)] == [SEQ] * 4 + [DEEP]


def test_the_committed_csv_is_a_prefix_of_what_a_second_sequence_adds_to_it(tmp_path):
    committed = Path(__file__).resolve().parent.parent / "docs" / "data" / "urbannav_run.csv"
    copy = tmp_path / "copy.csv"
    copy.write_bytes(committed.read_bytes())
    ur.write_csv(copy, _stub_rows("stubseq"))  # a sequence the file does not hold: added at the end
    assert copy.read_bytes().startswith(committed.read_bytes())
    # writing back the rows the file already holds gives the same bytes: the writer is the one that wrote them
    again = tmp_path / "again.csv"
    again.write_bytes(committed.read_bytes())
    ur.write_csv(again, ur.rows_from_csv(committed))
    assert again.read_bytes() == committed.read_bytes()


def test_rewriting_deep_urban_1_leaves_the_tunnel_1_lines_byte_identical(tmp_path):
    committed = Path(__file__).resolve().parent.parent / "docs" / "data" / "urbannav_run.csv"
    copy = tmp_path / "copy.csv"
    copy.write_bytes(committed.read_bytes())
    tunnel = _csv_lines(committed, SEQ)
    assert tunnel and _csv_lines(committed, DEEP)
    ur.write_csv(copy, _stub_rows(DEEP))
    assert _csv_lines(copy, SEQ) == tunnel
    assert _csv_lines(copy, DEEP) != _csv_lines(committed, DEEP)


def test_a_csv_with_another_header_is_refused_and_not_overwritten(tmp_path):
    path = tmp_path / "run.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        ur.write_csv(path, _stub_rows(DEEP))
    assert path.read_text(encoding="utf-8") == "a,b,c\n1,2,3\n"


def test_main_reports_a_csv_with_another_header_and_does_not_traceback(canyon, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    path = tmp_path / "run.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--csv", str(path)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "Traceback" not in err


# --------------------------------------------------------------- the blocks never mix sequences


def _both(results, aided) -> list[dict[str, Any]]:
    return ur.rows_for(SEQ, list(results.values())) + ur.rows_for(DEEP, list(aided.values()))


def test_a_block_shows_the_rows_of_its_own_sequence_only(results, aided):
    tunnel_only = ur.rows_for(SEQ, list(results.values()))
    deep_only = ur.rows_for(DEEP, list(aided.values()))
    both = _both(results, aided)
    for v in ur.VARIANTS:
        assert ur.run_markdown(both, v, SEQ) == ur.run_markdown(tunnel_only, v, SEQ)
        assert ur.run_markdown(both, v, DEEP) == ur.run_markdown(deep_only, v, DEEP)
        assert ur.run_markdown(both, v, SEQ) != ur.run_markdown(both, v, DEEP)
    assert ur.oracle_markdown(both, SEQ) == ur.oracle_markdown(tunnel_only, SEQ)
    assert "ORACLE DIAGNOSTIC" in ur.oracle_markdown(both, SEQ)
    assert ur.oracle_markdown(both, DEEP) == ur.ORACLE_NOT_APPLICABLE


def test_the_tunnel_blocks_are_unchanged_by_rows_of_another_sequence(results, aided):
    tunnel_only = ur.rows_for(SEQ, list(results.values()))
    both = _both(results, aided)
    for name, fn in {**ur.BLOCKS, **ur.CODE_BLOCKS}.items():
        if "deep-urban" not in name:
            assert fn(both) == fn(tunnel_only), name


def test_a_table_uses_the_quantities_of_its_kind(results, aided):
    both = _both(results, aided)
    tunnel_table, deep_table = ur.run_markdown(both, "declared", SEQ), ur.run_markdown(both, "declared", DEEP)
    assert "Peak horizontal error in the outage" in tunnel_table and "Peak horizontal error" not in deep_table
    assert "Attitude mean NEES" in deep_table and "Attitude mean NEES" not in tunnel_table
    assert "Pooled 2-sigma per-axis coverage" in deep_table


def test_a_sequence_with_no_rows_says_it_has_not_been_run(results):
    rows = ur.rows_for(SEQ, list(results.values()))
    for block in (ur.run_markdown(rows, "declared", DEEP), ur.oracle_markdown(rows, DEEP)):
        assert "has not been run" in block and "Deep-Urban-1" in block
    assert ur.run_markdown([], "declared", SEQ).startswith("No rows for Tunnel-1")


def test_the_page_is_filled_from_the_merged_csv_and_a_run_of_one_sequence_keeps_the_other_blocks(
    tunnel, canyon, tmp_path, monkeypatch
):
    monkeypatch.setattr(ur, "SEEDS", (0,))
    csv_path, page = tmp_path / "run.csv", tmp_path / "page.md"
    page.write_text(
        "\n".join(f"<!-- {name}:start -->\n<!-- {name}:end -->" for name in {**ur.BLOCKS, **ur.CODE_BLOCKS}) + "\n",
        encoding="utf-8",
    )
    assert ur.main(["--root", str(tunnel), "--csv", str(csv_path), "--page", str(page)]) == 0
    after_tunnel = page.read_text(encoding="utf-8")
    assert "No rows for Deep-Urban-1" in after_tunnel and "ORACLE DIAGNOSTIC" in after_tunnel
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--csv", str(csv_path), "--page", str(page)]) == 0
    text = page.read_text(encoding="utf-8")
    rows = ur.rows_from_csv(csv_path)
    assert {r["sequence"] for r in rows} == {SEQ, DEEP}
    for fn in {**ur.BLOCKS, **ur.CODE_BLOCKS}.values():
        assert fn(rows) in text
    assert "ORACLE DIAGNOSTIC" in text  # the Tunnel-1 oracle block is still there
    assert "Not applicable" in text and "Attitude mean NEES" in text
    assert "No rows for Deep-Urban-1" not in text


def test_a_page_needs_a_csv_to_be_filled_from(canyon, tmp_path, capsys):
    page = tmp_path / "page.md"
    page.write_text("x\n", encoding="utf-8")
    assert ur.main(["--root", str(canyon), "--sequence", DEEP, "--page", str(page)]) == 2
    assert "--page needs --csv or --from-csv" in capsys.readouterr().err
