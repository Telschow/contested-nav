"""Fetch the EuRoC MAV files this project uses from the ETH Research Collection.

The dataset is not vendored (constraint S2). This module downloads only what the evaluation
reads, the IMU stream and the ground-truth estimate of one sequence, and leaves the images
alone, because the images are almost all of the bytes.

The record offers four large ZIP archives (machine hall, Vicon room 1, Vicon room 2,
calibration), not one file per sequence. A ZIP keeps its index at the end of the file, so a
reader that can ask a server for a byte range can read the index and then fetch only the
members it wants. :class:`RangeFile` does that over plain ``urllib``, and ``zipfile`` does the
rest. If the server does not honour byte ranges, ``--full-download`` fetches the whole archive
to disk first.

Layout of the archive is not guaranteed. Two shapes are handled: the sequence folder holds
``mav0/...`` directly, or the archive holds one ``<sequence>.zip`` per sequence. A nested ZIP
that is stored (not compressed) is read in place by byte range. A compressed nested ZIP is
copied to disk first.

Terms. The record's rights statement is "In Copyright - Non-Commercial Use Permitted"
(http://rightsstatements.org/page/InC-NC/1.0/). It is not an open licence. Do not commit the
files, and do not republish them. Results computed from them (an error figure, a coverage
figure) are the intended output. Everything is written under ``data/raw/``, which git ignores.

    navkit euroc fetch --list
    navkit euroc fetch --sequence MH_01_easy --sequence V1_01_easy
    navkit euroc fetch --sequence MH_01_easy --full-download

What this file knows from the record page: the DOI, the four archive identifiers and the
rights statement. What it does not know until a real fetch has run: the internal layout of
the archives, and the checksums. The first fetch writes ``MANIFEST.json`` with the SHA-256 of
every file it extracted; later runs record that hash next to their results.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

DOI = "10.3929/ethz-b-000690084"
RECORD_URL = "https://www.research-collection.ethz.ch/handle/20.500.11850/690084"
BASE_URL = "https://www.research-collection.ethz.ch"
RIGHTS = "In Copyright - Non-Commercial Use Permitted"
RIGHTS_URL = "http://rightsstatements.org/page/InC-NC/1.0/"
USER_AGENT = "navkit-euroc-fetch (+https://github.com/Telschow/contested-nav)"

#: Bitstream identifier of each archive on the record page.
BITSTREAMS: dict[str, str] = {
    "machine_hall": "7b2419c1-62b5-4714-b7f8-485e5fe3e5fe",
    "vicon_room1": "02ecda9a-298f-498b-970c-b7c44334d880",
    "vicon_room2": "ea12bc01-3677-4b4c-853d-87c7870b8c44",
}

#: The sequences of the dataset and the archive each one lives in.
SEQUENCES: dict[str, str] = {
    "MH_01_easy": "machine_hall",
    "MH_02_easy": "machine_hall",
    "MH_03_medium": "machine_hall",
    "MH_04_difficult": "machine_hall",
    "MH_05_difficult": "machine_hall",
    "V1_01_easy": "vicon_room1",
    "V1_02_medium": "vicon_room1",
    "V1_03_difficult": "vicon_room1",
    "V2_01_easy": "vicon_room2",
    "V2_02_medium": "vicon_room2",
    "V2_03_difficult": "vicon_room2",
}

#: Files read by the evaluation, relative to the sequence folder. The first two are required.
IMU_CSV = "mav0/imu0/data.csv"
TRUTH_CSV = "mav0/state_groundtruth_estimate0/data.csv"
IMU_SENSOR = "mav0/imu0/sensor.yaml"
REQUIRED = (IMU_CSV, TRUTH_CSV)
WANTED = (IMU_CSV, TRUTH_CSV, IMU_SENSOR)

DEFAULT_DEST = "data/raw/euroc"
_BLOCK = 1 << 20
_BLOCKS_KEPT = 8
_RETRY_AFTER_CAP_S = 300.0
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")


class FetchError(RuntimeError):
    """The download cannot continue. The message says what to do about it."""


class RangeNotSupported(FetchError):
    """The server answered a byte-range request with the whole body."""


class LayoutError(FetchError):
    """The archive does not contain the sequence in a shape this module understands."""


def archive_url(group: str, base_url: str = BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/bitstreams/{BITSTREAMS[group]}/download"


# --------------------------------------------------------------------------- HTTP


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def open_url(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    attempts: int = 6,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Open ``url`` and return the response, backing off on 429 and 5xx.

    The Research Collection answers 429 when its request rate is too high, and says so in the
    body. A ``Retry-After`` header is honoured when present (capped at five minutes).
    Otherwise the wait doubles from two seconds. After ``attempts`` tries the error says what
    the user can do, which is wait and try again, or fetch on another network.
    """
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    delay = 2.0
    last = ""
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers=request_headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise FetchError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
            wait = _retry_after(exc.headers.get("Retry-After"))
            last = f"HTTP {exc.code}"
            exc.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            wait = None
            last = f"{type(exc).__name__}: {exc}"
        if attempt == attempts:
            break
        pause = min(wait if wait is not None else delay, _RETRY_AFTER_CAP_S)
        _log(f"{last}; retrying in {pause:.0f} s (attempt {attempt} of {attempts})")
        sleep(pause)
        delay *= 2.0
    raise FetchError(
        f"{url}: gave up after {attempts} attempts ({last}). HTTP 429 means the server is rate limiting this "
        "address and 5xx that it had a problem. Wait some minutes and run the same command again, or fetch from "
        "another network."
    )


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ file objects


class RangeFile(io.RawIOBase):
    """A read-only, seekable file over an HTTP resource, one byte-range request per block.

    The size comes from the ``Content-Range`` of a one-byte request. A server that ignores
    ``Range`` and answers 200 raises :class:`RangeNotSupported`, so the caller can fall back to a
    full download instead of silently pulling twelve gigabytes through a tunnel.
    """

    def __init__(
        self,
        url: str,
        *,
        block: int = _BLOCK,
        attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self.url = url
        self._block = block
        self._attempts = attempts
        self._sleep = sleep
        self._pos = 0
        self._cache: dict[int, bytes] = {}
        self.requests = 0
        self.bytes_received = 0
        self.size = self._probe()

    def _get(self, start: int, stop: int) -> tuple[Any, bytes]:
        """Fetch bytes ``[start, stop]`` inclusive. Returns the response and its body."""
        response = open_url(
            self.url,
            {"Range": f"bytes={start}-{stop}"},
            attempts=self._attempts,
            sleep=self._sleep,
        )
        with response:
            if response.status != 206:
                raise RangeNotSupported(
                    f"{self.url}: the server answered HTTP {response.status} to a byte-range request. "
                    "Run again with --full-download."
                )
            body: bytes = response.read()
        self.requests += 1
        self.bytes_received += len(body)
        return response, body

    def _probe(self) -> int:
        response, _ = self._get(0, 0)
        match = re.fullmatch(r"bytes \d+-\d+/(\d+)", response.headers.get("Content-Range", ""))
        if match is None:
            raise FetchError(f"{self.url}: no usable Content-Range in the reply, cannot size the archive")
        return int(match.group(1))

    def _block_at(self, index: int) -> bytes:
        cached = self._cache.get(index)
        if cached is not None:
            return cached
        start = index * self._block
        stop = min(start + self._block, self.size) - 1
        _, body = self._get(start, stop)
        if len(body) != stop - start + 1:
            raise FetchError(f"{self.url}: short read at {start} (got {len(body)} of {stop - start + 1} bytes)")
        if len(self._cache) >= _BLOCKS_KEPT:
            self._cache.pop(next(iter(self._cache)))
        self._cache[index] = body
        return body

    # -- io.RawIOBase ------------------------------------------------------

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}.get(whence)
        if base is None:
            raise ValueError(f"bad whence {whence}")
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        want = min(len(view), max(0, self.size - self._pos))
        done = 0
        while done < want:
            index, inner = divmod(self._pos, self._block)
            chunk = self._block_at(index)[inner : inner + (want - done)]
            view[done : done + len(chunk)] = chunk
            done += len(chunk)
            self._pos += len(chunk)
        return done


class SliceFile(io.RawIOBase):
    """A window ``[offset, offset + length)`` onto another seekable file."""

    def __init__(self, base: IO[bytes], offset: int, length: int) -> None:
        super().__init__()
        self._base = base
        self._offset = offset
        self._length = length
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._length}.get(whence)
        if base is None:
            raise ValueError(f"bad whence {whence}")
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        want = min(len(view), max(0, self._length - self._pos))
        if want == 0:
            return 0
        self._base.seek(self._offset + self._pos)
        data = self._base.read(want)
        view[: len(data)] = data
        self._pos += len(data)
        return len(data)


def stored_data_offset(fobj: IO[bytes], info: zipfile.ZipInfo) -> int:
    """Absolute offset of a member's data, read from its local header.

    The local header repeats the name and extra-field lengths, and they can differ from the
    central directory's copy, so the offset cannot be computed from ``ZipInfo`` alone.
    """
    fobj.seek(info.header_offset)
    raw = fobj.read(_LOCAL_HEADER.size)
    if len(raw) != _LOCAL_HEADER.size:
        raise FetchError(f"truncated local header for {info.filename}")
    fields = _LOCAL_HEADER.unpack(raw)
    if fields[0] != b"PK\x03\x04":
        raise FetchError(f"bad local header signature for {info.filename}")
    name_len, extra_len = fields[-2], fields[-1]
    return info.header_offset + _LOCAL_HEADER.size + name_len + extra_len


# ------------------------------------------------------------------- extraction


@dataclass
class Extracted:
    """One file written to disk."""

    path: str  # relative to the destination root, posix separators
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


def _norm(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/")


def _pick(members: dict[str, zipfile.ZipInfo], suffix: str) -> zipfile.ZipInfo | None:
    """The one member whose path is ``suffix`` or ends with ``/suffix``, ignoring ``__MACOSX``."""
    want = suffix.lower()
    hits = [
        info
        for name, info in members.items()
        if not name.startswith("__MACOSX/") and (name.lower() == want or name.lower().endswith("/" + want))
    ]
    if len(hits) > 1:
        raise LayoutError(f"{len(hits)} members match {suffix!r}: {[h.filename for h in hits[:4]]}")
    return hits[0] if hits else None


def _index(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    return {_norm(i.filename): i for i in zf.infolist() if not i.is_dir()}


def _copy_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> Extracted:
    """Stream one member to ``target`` through a temporary file, hashing as it goes.

    ``zipfile`` checks the CRC when the member is read to the end, so a corrupted transfer
    raises ``BadZipFile`` instead of leaving a quietly wrong file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, zf.open(info) as src:
            while chunk := src.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return Extracted(path="", sha256=digest.hexdigest(), bytes=size)


def _extract_files(
    zf: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    prefix: str,
    seq: str,
    dest: Path,
) -> list[Extracted] | None:
    """Extract the wanted files if all required ones are found under ``prefix``; else None."""
    found = {rel: _pick(members, f"{prefix}{rel}") for rel in WANTED}
    if any(found[rel] is None for rel in REQUIRED):
        return None
    out: list[Extracted] = []
    for rel, info in found.items():
        if info is None:
            continue
        target = dest / seq / rel
        item = _copy_member(zf, info, target)
        item.path = f"{seq}/{rel}"
        _log(f"  {item.path}  {item.bytes:,} bytes")
        out.append(item)
    return out


def extract_sequence(
    zf: zipfile.ZipFile,
    fobj: IO[bytes],
    seq: str,
    dest: Path,
    *,
    work_dir: Path,
    max_nested_bytes: int = 4 << 30,
) -> list[Extracted]:
    """Extract one sequence's IMU and ground-truth files from an open archive.

    ``fobj`` is the file object ``zf`` reads from, needed to locate a stored nested ZIP.
    """
    members = _index(zf)
    flat = _extract_files(zf, members, f"{seq}/", seq, dest)
    if flat is not None:
        return flat

    nested = [info for name, info in members.items() if name.lower().split("/")[-1] == f"{seq.lower()}.zip"]
    if len(nested) != 1:
        sample = sorted(members)[:12]
        raise LayoutError(
            f"{seq}: found neither '{seq}/{IMU_CSV}' nor a single '{seq}.zip' in the archive "
            f"({len(members)} members; first ones: {sample}). The archive layout differs from the one this "
            "module expects. Please report it, with this list."
        )
    info = nested[0]
    if info.compress_type == zipfile.ZIP_STORED:
        offset = stored_data_offset(fobj, info)
        _log(f"{seq}: nested ZIP is stored, reading it in place ({info.file_size:,} bytes, not downloaded)")
        window = SliceFile(fobj, offset, info.file_size)
        with zipfile.ZipFile(window) as inner:
            result = _extract_files(inner, _index(inner), "", seq, dest)
    else:
        if info.file_size > max_nested_bytes:
            raise FetchError(
                f"{seq}: the nested ZIP is compressed and {info.file_size:,} bytes, which would have to be "
                "downloaded whole. Raise --max-nested-gb or use --full-download."
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        local = work_dir / f"{seq}.zip"
        _log(f"{seq}: nested ZIP is compressed, copying it to {local} first ({info.file_size:,} bytes)")
        _copy_member(zf, info, local)
        try:
            with zipfile.ZipFile(local) as inner:
                result = _extract_files(inner, _index(inner), "", seq, dest)
        finally:
            local.unlink(missing_ok=True)
    if result is None:
        raise LayoutError(f"{seq}: the nested ZIP does not contain '{IMU_CSV}' and '{TRUTH_CSV}'")
    return result


# ---------------------------------------------------------------------- driver


def download_whole(
    url: str,
    target: Path,
    *,
    attempts: int = 6,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Download ``url`` to ``target``, resuming a partial file with a ``Range`` request."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    response = open_url(url, headers, attempts=attempts, sleep=sleep)
    with response:
        if have and response.status != 206:
            have = 0  # the server restarted the body; start the file over
        total = response.headers.get("Content-Length")
        _log(f"downloading {url} ({int(total):,} bytes remaining)" if total else f"downloading {url}")
        with part.open("ab" if have else "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
    os.replace(part, target)


def _manifest_path(dest: Path) -> Path:
    return dest / "MANIFEST.json"


def write_manifest(dest: Path, seq: str, group: str, url: str, files: list[Extracted]) -> Path:
    """Record where each file came from and its SHA-256, merging with earlier fetches."""
    path = _manifest_path(dest)
    manifest: dict[str, Any] = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest.update(
        {
            "dataset": "EuRoC MAV",
            "doi": DOI,
            "record": RECORD_URL,
            "rights": RIGHTS,
            "rights_url": RIGHTS_URL,
            "note": "Third-party data. Do not commit or republish it.",
        }
    )
    sequences = manifest.setdefault("sequences", {})
    sequences[seq] = {
        "archive": group,
        "url": url,
        "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": [f.as_dict() for f in files],
    }
    dest.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def fetch(
    sequences: list[str],
    dest: Path,
    *,
    base_url: str = BASE_URL,
    full_download: bool = False,
    attempts: int = 6,
    max_nested_bytes: int = 4 << 30,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[Extracted]]:
    """Fetch the given sequences into ``dest`` and write the manifest. Returns what was written."""
    unknown = [s for s in sequences if s not in SEQUENCES]
    if unknown:
        raise FetchError(f"unknown sequence {unknown[0]!r}; known: {', '.join(SEQUENCES)}")
    by_group: dict[str, list[str]] = {}
    for seq in sequences:
        by_group.setdefault(SEQUENCES[seq], []).append(seq)

    written: dict[str, list[Extracted]] = {}
    for group, seqs in by_group.items():
        url = archive_url(group, base_url)
        work_dir = dest / ".work"
        if full_download:
            archive = dest / ".downloads" / f"{group}.zip"
            if not archive.exists():
                download_whole(url, archive, attempts=attempts, sleep=sleep)
            _log(f"{group}: reading {archive}")
            fobj: IO[bytes] = archive.open("rb")
        else:
            _log(f"{group}: reading the archive index by byte range from {url}")
            fobj = cast(IO[bytes], RangeFile(url, attempts=attempts, sleep=sleep))
        try:
            with zipfile.ZipFile(fobj) as zf:
                for seq in seqs:
                    _log(f"{seq}:")
                    files = extract_sequence(zf, fobj, seq, dest, work_dir=work_dir, max_nested_bytes=max_nested_bytes)
                    write_manifest(dest, seq, group, url, files)
                    written[seq] = files
        finally:
            if isinstance(fobj, RangeFile):
                _log(f"{group}: {fobj.requests} requests, {fobj.bytes_received:,} bytes received")
            fobj.close()
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="navkit euroc fetch",
        description=(
            "Download the IMU and ground-truth files of EuRoC sequences. "
            f"Rights: {RIGHTS}. Do not commit or republish the files."
        ),
    )
    parser.add_argument("--sequence", "-s", action="append", default=[], metavar="NAME", help="sequence to fetch")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="output directory (default: %(default)s, git-ignored)")
    parser.add_argument("--list", action="store_true", help="list the known sequences and archive URLs, then exit")
    parser.add_argument("--full-download", action="store_true", help="download each whole archive first (several GB)")
    parser.add_argument(
        "--base-url", default=BASE_URL, help="server root, for a mirror or a test (default: %(default)s)"
    )
    parser.add_argument(
        "--attempts", type=int, default=6, help="tries per request on 429 or 5xx (default: %(default)s)"
    )
    parser.add_argument(
        "--max-nested-gb", type=float, default=4.0, help="largest compressed nested ZIP to copy (default: %(default)s)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        for seq, group in SEQUENCES.items():
            print(f"{seq:<16}{group:<14}{archive_url(group, args.base_url)}")
        print(f"\nrecord: {RECORD_URL}\nrights: {RIGHTS} ({RIGHTS_URL})")
        return 0
    if not args.sequence:
        print("give at least one --sequence NAME (see --list)", file=sys.stderr)
        return 2
    try:
        written = fetch(
            args.sequence,
            Path(args.dest),
            base_url=args.base_url,
            full_download=args.full_download,
            attempts=args.attempts,
            max_nested_bytes=int(args.max_nested_gb * (1 << 30)),
        )
    except RangeNotSupported as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except zipfile.BadZipFile as exc:
        print(f"error: the archive or a member failed its integrity check: {exc}", file=sys.stderr)
        return 1
    count = sum(len(v) for v in written.values())
    print(f"wrote {count} files under {args.dest}; manifest: {_manifest_path(Path(args.dest))}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
