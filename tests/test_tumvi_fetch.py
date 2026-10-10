"""The TUM VI fetcher, tested against a local server that stands in for the publisher.

No test touches the network beyond 127.0.0.1. The archives are built here with the layout the
fetcher expects, so a change in the real layout shows up as a ``LayoutError`` with a member list.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from navkit.io import euroc_fetch as ef
from navkit.io import tumvi_fetch as tf

SEQ = "room1"
TOP = f"dataset-{SEQ}_512_16"
IMU = b"#timestamp [ns],w\n1,0,0,0,0,0,9.8\n2,0,0,0,0,0,9.8\n"
MOCAP = b"#timestamp [ns], p\n1,0,0,0,1,0,0,0\n2,0,0,0,1,0,0,0\n"
YAML = b"accelerometer_noise_density: 0.0028\n"


def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def good_archive(extra: dict[str, bytes] | None = None) -> bytes:
    members = {
        f"{TOP}/mav0/imu0/data.csv": IMU,
        f"{TOP}/mav0/mocap0/data.csv": MOCAP,
        f"{TOP}/dso/imu_config.yaml": YAML,
        f"{TOP}/mav0/cam0/data/1.png": b"\x89PNG" + bytes(5000),
    }
    return _tar({**members, **(extra or {})})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.blobs: dict[str, bytes] = {}
        self.requests: list[tuple[str, str | None]] = []

    def handle_error(self, request: object, client_address: object) -> None:
        pass

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/tumvi"

    def serve(self, seq: str, blob: bytes, md5: str | None = None) -> None:
        name = tf.archive_name(seq)
        self.blobs[f"/tumvi/{name}"] = blob
        self.blobs[f"/tumvi/{name}.md5"] = f"{md5 or hashlib.md5(blob).hexdigest()}  {name}\n".encode()


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        rng = self.headers.get("Range")
        self.server.requests.append((self.path, rng))
        blob = self.server.blobs.get(self.path)
        if blob is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start, status = 0, 200
        if rng:
            start, status = int(rng.removeprefix("bytes=").partition("-")[0]), 206
        body = blob[start:]
        self.send_response(status)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{len(blob) - 1}/{len(blob)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "127.0.0.1,localhost")
    srv = _Server()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _fetch(server: _Server, dest: Path, **kw):
    return tf.fetch([SEQ], dest, base_url=server.base_url, **kw)


def test_the_wanted_files_are_extracted_and_the_images_are_not(server, tmp_path):
    server.serve(SEQ, good_archive())
    written = _fetch(server, tmp_path)
    assert (tmp_path / SEQ / tf.IMU_CSV).read_bytes() == IMU
    assert (tmp_path / SEQ / tf.TRUTH_CSV).read_bytes() == MOCAP
    assert (tmp_path / SEQ / tf.NOISE_YAML).read_bytes() == YAML
    assert {f.path for f in written[SEQ]} == {f"{SEQ}/{rel}" for rel in (tf.IMU_CSV, tf.TRUTH_CSV, tf.NOISE_YAML)}
    assert not list(tmp_path.rglob("*.png"))


def test_the_archive_is_deleted_unless_asked_to_keep_it(server, tmp_path):
    server.serve(SEQ, good_archive())
    _fetch(server, tmp_path)
    assert not (tmp_path / ".downloads" / tf.archive_name(SEQ)).exists()
    _fetch(server, tmp_path, keep_archive=True)
    assert (tmp_path / ".downloads" / tf.archive_name(SEQ)).exists()


def test_the_manifest_records_md5_sha256_rights_and_the_citation(server, tmp_path):
    blob = good_archive()
    server.serve(SEQ, blob)
    _fetch(server, tmp_path)
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert manifest["dataset"] == "TUM VI" and "CC BY 4.0" in manifest["rights"]
    assert "Schubert" in manifest["cite"]
    entry = manifest["sequences"][SEQ]
    assert entry["archive_md5"] == hashlib.md5(blob).hexdigest()
    files = {f["path"]: f for f in entry["files"]}
    assert files[f"{SEQ}/{tf.IMU_CSV}"]["sha256"] == hashlib.sha256(IMU).hexdigest()


def test_a_checksum_mismatch_stops_before_anything_is_extracted(server, tmp_path):
    server.serve(SEQ, good_archive(), md5="0" * 32)
    with pytest.raises(ef.FetchError, match="MD5"):
        _fetch(server, tmp_path)
    assert not (tmp_path / SEQ).exists()


def test_a_layout_without_the_required_files_lists_what_it_does_have(server, tmp_path):
    server.serve(SEQ, _tar({f"{TOP}/somewhere/else.txt": b"x", f"{TOP}/mav0/cam0/data/1.png": b"p"}))
    with pytest.raises(ef.LayoutError, match=r"else\.txt"):
        _fetch(server, tmp_path)
    assert not (tmp_path / SEQ).exists()


def test_member_names_never_choose_where_a_file_is_written(server, tmp_path):
    blob = good_archive({"../../evil.txt": b"x", f"{TOP}/../../evil2.txt": b"x"})
    server.serve(SEQ, blob)
    dest = tmp_path / "out"
    _fetch(server, dest)
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "evil2.txt").exists()
    names = {p.name for p in dest.rglob("*") if p.is_file()}
    assert names <= {"data.csv", "imu_config.yaml", "MANIFEST.json"}


def test_a_partial_download_is_resumed_with_a_range_request(server, tmp_path):
    blob = good_archive()
    server.serve(SEQ, blob)
    folder = tmp_path / ".downloads"
    folder.mkdir()
    (folder / (tf.archive_name(SEQ) + ".part")).write_bytes(blob[:1000])
    _fetch(server, tmp_path, keep_archive=True)
    assert (folder / tf.archive_name(SEQ)).read_bytes() == blob
    assert (f"/tumvi/{tf.archive_name(SEQ)}", "bytes=1000-") in server.requests


def test_an_existing_archive_is_not_downloaded_again(server, tmp_path):
    blob = good_archive()
    server.serve(SEQ, blob)
    folder = tmp_path / ".downloads"
    folder.mkdir()
    (folder / tf.archive_name(SEQ)).write_bytes(blob)
    _fetch(server, tmp_path)
    assert all(path.endswith(".md5") for path, _ in server.requests)


def test_parse_md5_accepts_a_checksum_line_and_rejects_anything_else():
    assert tf.parse_md5("51D2B8D93EE4ADA47EC0B2D10115DCF8  file.tar\n") == "51d2b8d93ee4ada47ec0b2d10115dcf8"
    with pytest.raises(ef.FetchError):
        tf.parse_md5("<html>Not Found</html>")


def test_unknown_sequence_is_rejected_before_any_request(server, tmp_path):
    with pytest.raises(ef.FetchError, match="unknown sequence"):
        tf.fetch(["room9"], tmp_path, base_url=server.base_url)
    assert server.requests == []


def test_list_prints_every_room_the_rights_and_the_citation(capsys):
    assert tf.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert all(s in out for s in tf.SEQUENCES) and "CC BY 4.0" in out and "Schubert" in out


def test_no_sequence_is_a_usage_error():
    assert tf.main([]) == 2


def test_the_command_is_routed_from_navkit(capsys):
    from navkit.cli import main as cli_main

    assert cli_main(["tumvi"]) == 2
    assert "fetch" in capsys.readouterr().err
    assert cli_main(["tumvi", "fetch", "--list"]) == 0
