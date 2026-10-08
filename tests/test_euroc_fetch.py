"""The EuRoC fetcher, tested against a local server that stands in for the Research Collection.

No test touches the network beyond 127.0.0.1. The archives are built here with the layouts the
fetcher claims to handle, so a change in the real archive layout shows up as a ``LayoutError``
with a member list and not as a quiet wrong file. What these tests cannot establish is that the
real archives look like one of the layouts; that is only known after a real fetch.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from navkit.io import euroc_fetch as ef

IMU_TEXT = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
    "a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]\n"
    + "".join(f"{1403636579763555584 + 5_000_000 * k},0.1,0.2,0.3,0.0,0.0,9.8\n" for k in range(50))
).encode()
TRUTH_TEXT = (
    "#timestamp,p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
    "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
    "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]\n"
    + "".join(f"{1403636579763555584 + 5_000_000 * k},1,2,3,1,0,0,0,0,0,0,0,0,0,0,0,0\n" for k in range(50))
).encode()
SENSOR_TEXT = b"sensor_type: imu\nrate_hz: 200\n"

SEQ = "MH_01_easy"
GROUP = "machine_hall"


def _members(prefix: str) -> dict[str, bytes]:
    return {
        f"{prefix}mav0/imu0/data.csv": IMU_TEXT,
        f"{prefix}mav0/imu0/sensor.yaml": SENSOR_TEXT,
        f"{prefix}mav0/state_groundtruth_estimate0/data.csv": TRUTH_TEXT,
    }


def _zip_bytes(members: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name), data, compress_type=method)
    return buf.getvalue()


def _images(prefix: str) -> dict[str, bytes]:
    """Incompressible stand-ins for the camera frames, the bulk of a real archive."""
    return {f"{prefix}mav0/cam0/data/{k}.png": os.urandom(1 << 20) for k in range(8)}


def flat_archive() -> bytes:
    return _zip_bytes({**_members(f"{SEQ}/"), **_images(f"{SEQ}/")}, zipfile.ZIP_STORED)


def nested_archive(inner_method: int, outer_method: int | None = None) -> bytes:
    """One ``<sequence>.zip`` inside the archive. By default the outer member is stored only when the
    inner archive is, which is the case where the inner one cannot be read in place."""
    inner = _zip_bytes({**_members(""), **_images("")}, inner_method)
    if outer_method is None:
        outer_method = zipfile.ZIP_STORED if inner_method == zipfile.ZIP_STORED else zipfile.ZIP_DEFLATED
    return _zip_bytes({f"machine_hall/{SEQ}/{SEQ}.zip": inner}, outer_method)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.blobs: dict[str, bytes] = {}
        self.honour_range = True
        self.throttle = 0
        self.retry_after: str | None = None
        self.sent = 0
        self.requests: list[str | None] = []

    def handle_error(self, request: object, client_address: object) -> None:
        pass  # a client that stops reading a full-body reply (the no-range test) is not a failure

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def serve(self, group: str, blob: bytes) -> None:
        self.blobs[f"/bitstreams/{ef.BITSTREAMS[group]}/download"] = blob


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        srv = self.server
        rng = self.headers.get("Range")
        srv.requests.append(rng)
        if srv.throttle > 0:
            srv.throttle -= 1
            self.send_response(429)
            if srv.retry_after is not None:
                self.send_header("Retry-After", srv.retry_after)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        blob = srv.blobs.get(self.path)
        if blob is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start, stop, status = 0, len(blob) - 1, 200
        if rng and srv.honour_range:
            first, _, last = rng.removeprefix("bytes=").partition("-")
            start = int(first)
            stop = min(int(last), len(blob) - 1) if last else len(blob) - 1
            status = 206
        body = blob[start : stop + 1]
        self.send_response(status)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{stop}/{len(blob)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        srv.sent += len(body)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "127.0.0.1,localhost")
    srv = _Server()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def no_sleep() -> list[float]:
    """The waits the fetcher asked for. Pass ``sleep=no_sleep.append`` so the test does not wait."""
    return []


def _fetch(server: _Server, dest: Path, **kw):
    return ef.fetch([SEQ], dest, base_url=server.base_url, **kw)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------- layouts


def test_flat_layout_fetches_only_the_wanted_files(server, tmp_path):
    blob = flat_archive()
    server.serve(GROUP, blob)
    written = _fetch(server, tmp_path)
    assert (tmp_path / SEQ / ef.IMU_CSV).read_bytes() == IMU_TEXT
    assert (tmp_path / SEQ / ef.TRUTH_CSV).read_bytes() == TRUTH_TEXT
    assert (tmp_path / SEQ / ef.IMU_SENSOR).read_bytes() == SENSOR_TEXT
    assert {f.path for f in written[SEQ]} == {f"{SEQ}/{rel}" for rel in ef.WANTED}
    # The point of the byte-range reader: the eight megabytes of frames are not transferred.
    assert server.sent < len(blob) / 2
    assert not (tmp_path / SEQ / "mav0" / "cam0").exists()


def test_nested_stored_zip_is_read_in_place(server, tmp_path):
    blob = nested_archive(zipfile.ZIP_STORED)
    server.serve(GROUP, blob)
    _fetch(server, tmp_path)
    assert (tmp_path / SEQ / ef.IMU_CSV).read_bytes() == IMU_TEXT
    assert (tmp_path / SEQ / ef.TRUTH_CSV).read_bytes() == TRUTH_TEXT
    assert server.sent < len(blob) / 2


def test_a_stored_nested_zip_is_read_in_place_even_when_it_is_compressed_inside(server, tmp_path):
    # The likely real shape: an outer archive of already-compressed ZIPs, stored as they are.
    blob = nested_archive(zipfile.ZIP_DEFLATED, outer_method=zipfile.ZIP_STORED)
    server.serve(GROUP, blob)
    _fetch(server, tmp_path)
    assert (tmp_path / SEQ / ef.IMU_CSV).read_bytes() == IMU_TEXT
    assert (tmp_path / SEQ / ef.TRUTH_CSV).read_bytes() == TRUTH_TEXT
    assert server.sent < len(blob) / 2
    assert not (tmp_path / ".work").exists()


def test_nested_compressed_zip_is_copied_then_cleaned_up(server, tmp_path):
    server.serve(GROUP, nested_archive(zipfile.ZIP_DEFLATED))
    _fetch(server, tmp_path)
    assert (tmp_path / SEQ / ef.TRUTH_CSV).read_bytes() == TRUTH_TEXT
    assert not list((tmp_path / ".work").glob("*.zip"))


def test_nested_compressed_zip_over_the_limit_is_refused(server, tmp_path):
    server.serve(GROUP, nested_archive(zipfile.ZIP_DEFLATED))
    with pytest.raises(ef.FetchError, match="downloaded whole"):
        _fetch(server, tmp_path, max_nested_bytes=1024)


def test_unknown_layout_lists_what_the_archive_contains(server, tmp_path):
    server.serve(GROUP, _zip_bytes({"somewhere/else.txt": b"x"}))
    with pytest.raises(ef.LayoutError, match=r"somewhere/else\.txt"):
        _fetch(server, tmp_path)


def test_a_missing_required_file_is_a_layout_error_not_a_partial_write(server, tmp_path):
    members = _members(f"{SEQ}/")
    del members[f"{SEQ}/{ef.TRUTH_CSV}"]
    server.serve(GROUP, _zip_bytes(members))
    with pytest.raises(ef.LayoutError):
        _fetch(server, tmp_path)
    assert not (tmp_path / SEQ).exists()


def test_macosx_resource_forks_are_ignored(server, tmp_path):
    members = {**_members(f"{SEQ}/"), f"__MACOSX/{SEQ}/mav0/imu0/data.csv": b"junk"}
    server.serve(GROUP, _zip_bytes(members))
    _fetch(server, tmp_path)
    assert (tmp_path / SEQ / ef.IMU_CSV).read_bytes() == IMU_TEXT


def test_member_names_never_choose_where_a_file_is_written(server, tmp_path):
    members = {**_members(f"{SEQ}/"), "../../evil.txt": b"x", f"{SEQ}/../../evil2.txt": b"x"}
    server.serve(GROUP, _zip_bytes(members))
    dest = tmp_path / "out"
    _fetch(server, dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "evil2.txt").exists()
    assert {p.name for p in dest.rglob("*") if p.is_file()} <= {"data.csv", "sensor.yaml", "MANIFEST.json"}


# ---------------------------------------------------------------- integrity


def test_manifest_records_sha256_and_terms(server, tmp_path):
    server.serve(GROUP, flat_archive())
    _fetch(server, tmp_path)
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert manifest["doi"] == ef.DOI
    assert manifest["rights"] == ef.RIGHTS
    files = {f["path"]: f for f in manifest["sequences"][SEQ]["files"]}
    assert files[f"{SEQ}/{ef.IMU_CSV}"]["sha256"] == _sha(IMU_TEXT)
    assert files[f"{SEQ}/{ef.TRUTH_CSV}"]["bytes"] == len(TRUTH_TEXT)


def test_a_second_fetch_keeps_the_first_sequences_in_the_manifest(server, tmp_path):
    other = "MH_02_easy"
    server.serve(GROUP, _zip_bytes({**_members(f"{SEQ}/"), **_members(f"{other}/")}))
    ef.fetch([SEQ], tmp_path, base_url=server.base_url)
    ef.fetch([other], tmp_path, base_url=server.base_url)
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert set(manifest["sequences"]) == {SEQ, other}


def test_a_corrupted_transfer_fails_the_crc_and_leaves_no_file(server, tmp_path):
    blob = bytearray(_zip_bytes(_members(f"{SEQ}/"), zipfile.ZIP_STORED))
    at = blob.index(b"\n1403636579763555584") + 5  # inside the stored IMU body
    blob[at] ^= 0xFF
    server.serve(GROUP, bytes(blob))
    with pytest.raises(zipfile.BadZipFile):
        _fetch(server, tmp_path)
    assert not (tmp_path / SEQ / ef.IMU_CSV).exists()
    assert not list(tmp_path.rglob("*.part"))


# -------------------------------------------------------- server behaviour


def test_a_rate_limited_server_is_retried_with_its_retry_after(server, tmp_path, no_sleep):
    server.serve(GROUP, flat_archive())
    server.throttle = 2
    server.retry_after = "7"
    _fetch(server, tmp_path, sleep=no_sleep.append)
    assert no_sleep[:2] == [7.0, 7.0]
    assert (tmp_path / SEQ / ef.IMU_CSV).exists()


def test_backoff_doubles_without_retry_after_and_is_capped(server, tmp_path, no_sleep):
    server.serve(GROUP, flat_archive())
    server.throttle = 3
    _fetch(server, tmp_path, sleep=no_sleep.append)
    assert no_sleep[:3] == [2.0, 4.0, 8.0]
    assert ef._RETRY_AFTER_CAP_S == 300.0
    server.throttle = 1
    server.retry_after = "99999"
    ef.open_url(server.base_url + f"/bitstreams/{ef.BITSTREAMS[GROUP]}/download", sleep=no_sleep.append)
    assert no_sleep[-1] == 300.0


def test_giving_up_names_the_429_and_what_to_do(server, tmp_path, no_sleep):
    server.serve(GROUP, flat_archive())
    server.throttle = 99
    with pytest.raises(ef.FetchError, match=r"429.*rate limiting"):
        _fetch(server, tmp_path, attempts=3, sleep=no_sleep.append)
    assert len(no_sleep) == 2


def test_a_missing_archive_is_a_clear_error(server, tmp_path):
    with pytest.raises(ef.FetchError, match="404"):
        _fetch(server, tmp_path)


def test_a_server_that_ignores_range_is_reported_not_downloaded(server, tmp_path):
    server.serve(GROUP, flat_archive())
    server.honour_range = False
    with pytest.raises(ef.RangeNotSupported, match="--full-download"):
        _fetch(server, tmp_path)
    assert main_exit(server, tmp_path, []) == 3


def main_exit(server: _Server, dest: Path, extra: list[str]) -> int:
    return ef.main(["--sequence", SEQ, "--dest", str(dest), "--base-url", server.base_url, "--attempts", "1", *extra])


def test_full_download_works_when_ranges_do_not(server, tmp_path):
    server.serve(GROUP, flat_archive())
    server.honour_range = False
    assert main_exit(server, tmp_path, ["--full-download"]) == 0
    assert (tmp_path / SEQ / ef.IMU_CSV).read_bytes() == IMU_TEXT


def test_full_download_resumes_a_partial_file(server, tmp_path):
    blob = flat_archive()
    server.serve(GROUP, blob)
    target = tmp_path / "a.zip"
    target.with_suffix(".zip.part").write_bytes(blob[:1000])
    ef.download_whole(server.base_url + f"/bitstreams/{ef.BITSTREAMS[GROUP]}/download", target)
    assert target.read_bytes() == blob
    assert server.requests[-1] == "bytes=1000-"


def test_range_file_reads_match_the_source_across_block_boundaries(server):
    blob = os.urandom(10_000)
    server.serve(GROUP, blob)
    rf = ef.RangeFile(server.base_url + f"/bitstreams/{ef.BITSTREAMS[GROUP]}/download", block=1024)
    assert rf.size == len(blob)
    rf.seek(1000)
    assert rf.read(100) == blob[1000:1100]
    rf.seek(-50, 2)
    assert rf.read(1000) == blob[-50:]
    rf.seek(0)
    assert rf.read() == blob
    assert rf.read(10) == b""


# --------------------------------------------------------------------- CLI


def test_unknown_sequence_is_rejected_before_any_request(server, tmp_path):
    with pytest.raises(ef.FetchError, match="unknown sequence"):
        ef.fetch(["MH_99"], tmp_path, base_url=server.base_url)
    assert server.requests == []


def test_list_prints_every_sequence_and_the_terms(capsys):
    assert ef.main(["--list"]) == 0
    out = capsys.readouterr().out
    for seq in ef.SEQUENCES:
        assert seq in out
    assert "Non-Commercial" in out


def test_no_sequence_is_a_usage_error(capsys):
    assert ef.main([]) == 2


def test_every_sequence_maps_to_a_known_archive():
    assert set(ef.SEQUENCES.values()) <= set(ef.BITSTREAMS)
    assert len(ef.SEQUENCES) == 11
