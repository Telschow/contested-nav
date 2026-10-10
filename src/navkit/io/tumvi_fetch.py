"""Fetch the TUM VI room sequences this project uses, and keep only the files the evaluation reads.

The dataset is not vendored (constraint S2). Its data is published under CC BY 4.0, which asks for
attribution. Cite: D. Schubert, T. Goll, N. Demmel, V. Usenko, J. Stueckler and D. Cremers, "The TUM VI
Benchmark for Evaluating Visual-Inertial Odometry", IROS 2018 (arXiv:1804.06120). Everything is written
under ``data/raw/``, which git ignores.

Each room sequence is one TAR of 1.4 to 1.8 GB, almost all of it camera images. A TAR has no index at the
end, so unlike the EuRoC ZIPs it cannot be read selectively by byte range without one request per image.
This module downloads the whole archive (resuming a partial file), checks it against the MD5 file the
publisher provides, copies out the three small files it needs, and deletes the archive unless asked to
keep it.

    navkit tumvi fetch --list
    navkit tumvi fetch --sequence room1 --sequence room2
    navkit tumvi fetch --sequence room1 --keep-archive

What it keeps, per sequence: ``mav0/imu0/data.csv`` (the IMU at 200 Hz), ``mav0/mocap0/data.csv`` (the
motion-capture pose in the IMU frame, time-aligned to the IMU by the dataset authors) and
``imu_config.yaml`` (their IMU noise figures). The ground truth has no velocity or bias columns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .euroc_fetch import Extracted, FetchError, LayoutError, _log, download_whole, open_url

DATASET = "TUM VI"
BASE_URL = "https://vision.in.tum.de/tumvi/exported/euroc/512_16"
RECORD_URL = "https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset"
RIGHTS = "Creative Commons Attribution 4.0 (CC BY 4.0)"
RIGHTS_URL = "https://creativecommons.org/licenses/by/4.0/"
CITATION = (
    "D. Schubert, T. Goll, N. Demmel, V. Usenko, J. Stueckler, D. Cremers. The TUM VI Benchmark for Evaluating "
    "Visual-Inertial Odometry. IROS 2018. arXiv:1804.06120"
)

#: The room sequences, which have motion-capture ground truth for the whole trajectory.
SEQUENCES: tuple[str, ...] = tuple(f"room{n}" for n in range(1, 7))

IMU_CSV = "mav0/imu0/data.csv"
TRUTH_CSV = "mav0/mocap0/data.csv"
NOISE_YAML = "imu_config.yaml"
#: Where each wanted file sits inside the archive, below the single top-level folder.
_IN_ARCHIVE = {IMU_CSV: IMU_CSV, TRUTH_CSV: TRUTH_CSV, NOISE_YAML: "dso/imu_config.yaml"}
REQUIRED = (IMU_CSV, TRUTH_CSV)

DEFAULT_DEST = "data/raw/tumvi"
DEFAULT_ARCHIVES = "data/raw/tumvi/.downloads"


def archive_name(seq: str) -> str:
    return f"dataset-{seq}_512_16.tar"


def archive_url(seq: str, base_url: str = BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/{archive_name(seq)}"


def parse_md5(text: str) -> str:
    """The hash from a ``md5sum``-style file: ``<32 hex>  <name>``."""
    match = re.match(r"\s*([0-9a-fA-F]{32})\b", text)
    if match is None:
        raise FetchError(f"the MD5 file does not start with a 32 digit hash: {text[:60]!r}")
    return match.group(1).lower()


def file_md5(path: Path) -> str:
    digest = hashlib.md5()  # the publisher's checksum is MD5; used for integrity only
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(name: str) -> bool:
    return not name.startswith("/") and ".." not in Path(name).parts


def extract_files(archive: Path, seq: str, dest: Path) -> list[Extracted]:
    """Copy the wanted files out of the archive, hashing as they are written.

    Member names choose nothing about where a file goes: the target is built from the fixed list above.
    """
    prefix = f"dataset-{seq}_512_16/"
    out: list[Extracted] = []
    with tarfile.open(archive) as tar:
        names = {m.name: m for m in tar.getmembers() if m.isfile() and _safe(m.name)}
        missing = [rel for rel in REQUIRED if prefix + _IN_ARCHIVE[rel] not in names]
        if missing:
            sample = sorted(n for n in names if not n.endswith(".png"))[:12]
            raise LayoutError(
                f"{seq}: the archive has no {missing[0]!r} under {prefix!r}. Members that are not images: {sample}. "
                "The layout differs from the one this module expects; please report it with this list."
            )
        for rel, inner in _IN_ARCHIVE.items():
            member = names.get(prefix + inner)
            if member is None:
                continue
            target = dest / seq / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".part")
            try:
                src = tar.extractfile(member)
                if src is None:
                    raise LayoutError(f"{seq}: {member.name} cannot be read")
                with os.fdopen(fd, "wb") as fh, src:
                    while chunk := src.read(1 << 20):
                        fh.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                os.replace(tmp_name, target)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
            _log(f"  {seq}/{rel}  {size:,} bytes")
            out.append(Extracted(path=f"{seq}/{rel}", sha256=digest.hexdigest(), bytes=size))
    return out


def write_manifest(dest: Path, seq: str, url: str, md5: str, files: list[Extracted]) -> Path:
    """Record where each file came from, the archive's MD5 and each file's SHA-256, merging earlier fetches."""
    path = dest / "MANIFEST.json"
    manifest: dict[str, Any] = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest.update(
        {
            "dataset": DATASET,
            "record": RECORD_URL,
            "rights": RIGHTS,
            "rights_url": RIGHTS_URL,
            "cite": CITATION,
            "note": "Third-party data under CC BY 4.0: attribute it. Not committed to this repository.",
        }
    )
    manifest.setdefault("sequences", {})[seq] = {
        "url": url,
        "archive_md5": md5,
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
    archive_dir: Path | None = None,
    base_url: str = BASE_URL,
    keep_archive: bool = False,
    attempts: int = 6,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[Extracted]]:
    """Download, verify and extract the given sequences. Returns what was written."""
    unknown = [s for s in sequences if s not in SEQUENCES]
    if unknown:
        raise FetchError(f"unknown sequence {unknown[0]!r}; known: {', '.join(SEQUENCES)}")
    folder = archive_dir if archive_dir is not None else dest / ".downloads"
    written: dict[str, list[Extracted]] = {}
    for seq in sequences:
        url = archive_url(seq, base_url)
        archive = folder / archive_name(seq)
        with open_url(url + ".md5", attempts=attempts, sleep=sleep) as response:
            expected = parse_md5(response.read().decode("utf-8", "replace"))
        if not archive.exists():
            _log(f"{seq}: downloading {url}")
            download_whole(url, archive, attempts=attempts, sleep=sleep)
        _log(f"{seq}: checking the MD5 of {archive}")
        actual = file_md5(archive)
        if actual != expected:
            raise FetchError(
                f"{seq}: the archive's MD5 is {actual}, the publisher's file says {expected}. "
                f"The download is incomplete or corrupted; delete {archive} and run the command again."
            )
        files = extract_files(archive, seq, dest)
        write_manifest(dest, seq, url, expected, files)
        written[seq] = files
        if not keep_archive:
            archive.unlink(missing_ok=True)
    return written


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit tumvi fetch",
        description=(
            "Download TUM VI room sequences and keep the IMU, ground-truth and noise files. "
            f"Rights: {RIGHTS}. Cite: {CITATION}"
        ),
    )
    p.add_argument(
        "--sequence", "-s", action="append", default=[], metavar="NAME", help=f"one of {', '.join(SEQUENCES)}"
    )
    p.add_argument("--dest", default=DEFAULT_DEST, help="output directory (default: %(default)s, git-ignored)")
    p.add_argument("--archive-dir", default=None, help="where the TARs are downloaded (default: <dest>/.downloads)")
    p.add_argument("--keep-archive", action="store_true", help="keep each TAR after extracting (1.4 to 1.8 GB each)")
    p.add_argument("--list", action="store_true", help="list the sequences and archive URLs, then exit")
    p.add_argument("--base-url", default=BASE_URL, help="server root for a mirror or test (default: %(default)s)")
    p.add_argument("--attempts", type=int, default=6, help="tries per request on 429/5xx (default: %(default)s)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        for seq in SEQUENCES:
            print(f"{seq:<8}{archive_url(seq, args.base_url)}")
        print(f"\nrecord: {RECORD_URL}\nrights: {RIGHTS} ({RIGHTS_URL})\ncite: {CITATION}")
        return 0
    if not args.sequence:
        print("give at least one --sequence NAME (see --list)", file=sys.stderr)
        return 2
    try:
        written = fetch(
            args.sequence,
            Path(args.dest),
            archive_dir=Path(args.archive_dir) if args.archive_dir else None,
            base_url=args.base_url,
            keep_archive=args.keep_archive,
            attempts=args.attempts,
        )
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except tarfile.TarError as exc:
        print(f"error: the archive could not be read as a TAR: {exc}", file=sys.stderr)
        return 1
    count = sum(len(v) for v in written.values())
    print(f"wrote {count} files under {args.dest}; manifest: {Path(args.dest) / 'MANIFEST.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
