"""The Tunnel-1 run on a sequence written here, so that CI exercises the code that the real data would.

The fixture is generated from code with made-up numbers (S2): a vehicle driving east at constant speed on a made-up
spot of the globe, a reference table at 1 Hz, a 20 Hz IMU, and an NMEA file with one fix per second and a gap in the
middle that is the outage. A gyroscope bias that starts after the filter's start-bias window drifts the roll, which is
the known answer the oracle tests are checked against. Nothing here is a row of the real dataset, and no data file is
committed. These tests do not skip when the real dataset is absent.
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
REF_NAME, IMU_NAME = tuple(uf.SOURCES[SEQ])
NMEA_NAME = ud.NMEA_FILES[SEQ]

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


def write_tunnel(
    root: Path,
    *,
    gst_sigma: dict[int, str] | None = None,
    tilt_bias: float = TILT_BIAS_RAD_S,
    nmea: bool = True,
    outage: bool = True,
) -> Path:
    """Write ``<root>/tunnel1/`` in the publisher's layout. ``gst_sigma`` maps an epoch to the text of its sigma."""
    folder = root / SEQ
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
    (folder / REF_NAME).write_bytes(("\r\n".join([*ref_header, *rows]) + "\r\n").encode("ascii"))

    n = DURATION_S * IMU_RATE_HZ + 1
    stamps = (int(t_unix0 * 1e9) + (np.arange(n) * (1e9 / IMU_RATE_HZ)).astype(np.int64)).astype(np.int64)
    lines = [",".join(["%time", ud.IMU_STAMP, *ud.IMU_GYRO, *ud.IMU_ACCEL])]
    g = float(np.linalg.norm(GRAVITY))
    for i, ns in enumerate(stamps):
        gy = tilt_bias if i / IMU_RATE_HZ >= TILT_ONSET_S else 0.0
        lines.append(f"{int(ns) + 300_000},{int(ns)},0.0,{gy!r},0.0,0.0,0.0,{g!r}")
    (folder / IMU_NAME).write_text("\n".join(lines) + "\n", encoding="ascii")

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
            lat, lon = _lat_lon(SPEED_M_S * k + e, nn)
            if k == 0:
                out.append(_nmea(f"GNRMC,{stamp},A,{_ddmm(lat, 2)},N,{_ddmm(lon, 3)},E,0.0,0.0,{date},,,A"))
            out.append(_nmea(f"GNGGA,{stamp},{_ddmm(lat, 2)},N,{_ddmm(lon, 3)},E,1,12,0.60,5.0,M,-1.0,M,,0000"))
            sigma = gst.get(k, "1.50")
            out.append(_nmea(f"GNGST,{stamp},1.0,2.0,1.0,0.0,{sigma},{sigma},3.00"))
        (folder / NMEA_NAME).write_text("\n".join(out) + "\n", encoding="ascii")
    return root


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
