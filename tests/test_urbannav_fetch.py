"""The UrbanNav fetcher, tested against a local server that stands in for Dropbox.

No test touches the network beyond 127.0.0.1.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from navkit.io import euroc_fetch as ef
from navkit.io import urbannav_fetch as uf

SEQ = "tunnel1"
GT_NAME, IMU_NAME = tuple(uf.SOURCES[SEQ])
GT = b"UTC GPST\nunits\n2021 5 18 1\n"
IMU = b"time,gx,gy,gz\n0.0,0,0,0\n"


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.blobs: dict[str, bytes] = {}
        self.requests: list[str] = []

    def handle_error(self, request: object, client_address: object) -> None:
        pass

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/mirror"

    def serve(self, name: str, blob: bytes) -> None:
        self.blobs[f"/mirror/{SEQ}/{name}"] = blob


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.server.requests.append(self.path)
        blob = self.server.blobs.get(self.path)
        if blob is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


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
    return uf.fetch([SEQ], dest, base_url=server.base_url, attempts=1, **kw)


def _serve_good(server: _Server) -> None:
    server.serve(GT_NAME, GT)
    server.serve(IMU_NAME, IMU)


def test_files_are_written_and_recorded_with_their_hash(server, tmp_path):
    _serve_good(server)
    written = _fetch(server, tmp_path)
    assert (tmp_path / SEQ / GT_NAME).read_bytes() == GT
    assert (tmp_path / SEQ / IMU_NAME).read_bytes() == IMU
    assert {f.path for f in written[SEQ]} == {f"{SEQ}/{GT_NAME}", f"{SEQ}/{IMU_NAME}"}
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert manifest["sequences"][SEQ]["files"][GT_NAME]["sha256"] == hashlib.sha256(GT).hexdigest()
    assert "MIT" in manifest["rights"]
    assert not list((tmp_path / SEQ).glob("*.new"))


def test_a_second_fetch_does_not_download_again(server, tmp_path):
    _serve_good(server)
    _fetch(server, tmp_path)
    count = len(server.requests)
    _fetch(server, tmp_path)
    assert len(server.requests) == count


def test_a_changed_upstream_file_is_reported_and_not_swapped_in(server, tmp_path):
    _serve_good(server)
    _fetch(server, tmp_path)
    server.serve(GT_NAME, GT + b"changed\n")
    with pytest.raises(ef.FetchError, match="changed upstream"):
        _fetch(server, tmp_path, force=True)
    assert (tmp_path / SEQ / GT_NAME).read_bytes() == GT
    assert not list((tmp_path / SEQ).glob("*.new"))


def test_a_web_page_is_rejected_as_data(server, tmp_path):
    server.serve(GT_NAME, b"<!DOCTYPE html><html><body>Dropbox</body></html>")
    server.serve(IMU_NAME, IMU)
    with pytest.raises(ef.FetchError, match="did not return a data file"):
        _fetch(server, tmp_path)
    assert not (tmp_path / SEQ / GT_NAME).exists()
    assert not list((tmp_path / SEQ).glob("*.new"))


def test_an_empty_file_is_rejected(server, tmp_path):
    server.serve(GT_NAME, b"")
    server.serve(IMU_NAME, IMU)
    with pytest.raises(ef.FetchError, match="did not return a data file"):
        _fetch(server, tmp_path)


def test_an_unknown_sequence_is_refused(tmp_path):
    with pytest.raises(ef.FetchError, match="unknown sequence"):
        uf.fetch(["nope"], tmp_path)


def test_the_real_links_ask_for_the_file_and_not_a_preview():
    for files in uf.SOURCES.values():
        for url in files.values():
            assert url.startswith("https://www.dropbox.com/s/")
            assert url.endswith("?dl=1")


def test_main_lists_and_needs_a_sequence(capsys, tmp_path):
    assert uf.main(["--list"]) == 0
    assert "tunnel1" in capsys.readouterr().out
    assert uf.main(["--dest", str(tmp_path)]) == 2


def test_main_fetches_through_a_mirror(server, tmp_path, capsys):
    _serve_good(server)
    code = uf.main(["-s", SEQ, "--dest", str(tmp_path), "--base-url", server.base_url, "--attempts", "1"])
    assert code == 0
    assert "wrote 2 files" in capsys.readouterr().out
