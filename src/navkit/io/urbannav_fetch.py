"""Fetch the UrbanNav files this project reads: the reference solution and the IMU of a sequence.

The dataset is not vendored (constraint S2). The authors state that the dataset files and the repository are
MIT licensed (``IPNL-POLYU/UrbanNavDataset``, LICENSE in the root) and ask for a citation: Hsu et al. (2023),
NAVIGATION. Everything is written under ``data/raw/``, which git ignores.

    navkit urbannav fetch --list
    navkit urbannav fetch --sequence tunnel1

Two things differ from ``navkit tumvi fetch``:

* The publisher gives no checksum and no file size. The first fetch records a SHA-256 per file in
  ``MANIFEST.json``. Later fetches compare against it, so a file that changed upstream is reported
  and not silently replaced. That detects change. It does not prove the first copy was intact.
* The files are on Dropbox. A wrong or expired link answers with an HTML page, which is rejected here
  instead of being written as data.

The ROS bags (tens of GB) and the GNSS RINEX folders are not fetched. A bag needs a ROS reader, which
constraint S1 does not allow, and the RINEX files sit in a Dropbox folder whose file names the README does
not list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .euroc_fetch import Extracted, FetchError, _log, download_whole

DATASET = "UrbanNav"
RECORD_URL = "https://github.com/IPNL-POLYU/UrbanNavDataset"
RIGHTS = "MIT License (dataset files, code and documentation), as stated by the authors"
CITATION = "Hsu et al. (2023), NAVIGATION. UrbanNav: an open-sourced multisensory dataset for urban positioning."

#: sequence -> file name -> download URL. ``dl=1`` asks Dropbox for the file and not a preview page.
SOURCES: dict[str, dict[str, str]] = {
    "tunnel1": {
        "UrbanNav_tunnel_GT_raw.txt": "https://www.dropbox.com/s/fqsviiei3r5tu6r/UrbanNav_tunnel_GT_raw.txt?dl=1",
        "xsense_imu_tunnel_1.csv": "https://www.dropbox.com/s/1aql7o1w4sf7j6o/xsense_imu_tunnel_1.csv?dl=1",
    },
    "deepurban1": {
        "UrbanNav_whampoa_raw.txt": "https://www.dropbox.com/s/ej2mkue2w3r36s2/UrbanNav_whampoa_raw.txt?dl=1",
        "xsense_imu_deep_urban1.csv": "https://www.dropbox.com/s/pet3up4vka61jop/xsense_imu_deep_urban1.csv?dl=1",
    },
}
SEQUENCES: tuple[str, ...] = tuple(SOURCES)
DEFAULT_DEST = "data/raw/urbannav"


def file_url(seq: str, name: str, base_url: str | None = None) -> str:
    if base_url is not None:
        return f"{base_url.rstrip('/')}/{seq}/{name}"
    return SOURCES[seq][name]


def looks_like_html(path: Path) -> bool:
    """True if the file starts like a web page, which is what a dead share link returns."""
    with path.open("rb") as fh:
        head = fh.read(512).lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<?xml"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(dest: Path) -> dict[str, Any]:
    path = dest / "MANIFEST.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(dest: Path, seq: str, files: list[tuple[str, str, Extracted]]) -> Path:
    """Record each file's source URL and SHA-256, merging earlier fetches."""
    path = dest / "MANIFEST.json"
    manifest = read_manifest(dest)
    manifest.update(
        {
            "dataset": DATASET,
            "record": RECORD_URL,
            "rights": RIGHTS,
            "cite": CITATION,
            "note": (
                "Third-party data. Not committed to this repository. The publisher gives no checksum, so the "
                "SHA-256 values are those of the first copy fetched."
            ),
        }
    )
    entry = manifest.setdefault("sequences", {}).setdefault(seq, {"files": {}})
    for name, url, ex in files:
        entry["files"][name] = {
            "url": url,
            "sha256": ex.sha256,
            "bytes": ex.bytes,
            "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    dest.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest, prefix="MANIFEST.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_name, path)
    return path


def fetch(
    sequences: list[str],
    dest: Path,
    *,
    base_url: str | None = None,
    force: bool = False,
    attempts: int = 6,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[Extracted]]:
    """Download the wanted files of each sequence, check them and record them. Returns what is on disk."""
    unknown = [s for s in sequences if s not in SOURCES]
    if unknown:
        raise FetchError(f"unknown sequence {unknown[0]!r}; known: {', '.join(SEQUENCES)}")
    written: dict[str, list[Extracted]] = {}
    for seq in sequences:
        known = read_manifest(dest).get("sequences", {}).get(seq, {}).get("files", {})
        rows: list[tuple[str, str, Extracted]] = []
        for name in SOURCES[seq]:
            url = file_url(seq, name, base_url)
            target = dest / seq / name
            if target.exists() and not force:
                _log(f"{seq}/{name}: already on disk, not downloading (use --force to fetch again)")
                new = target
            else:
                new = target.with_name(target.name + ".new")
                new.unlink(missing_ok=True)
                download_whole(url, new, attempts=attempts, sleep=sleep)
                if new.stat().st_size == 0 or looks_like_html(new):
                    new.unlink(missing_ok=True)
                    raise FetchError(
                        f"{seq}/{name}: {url} did not return a data file (empty, or a web page). "
                        "The share link may have changed or expired."
                    )
            digest = file_sha256(new)
            before = known.get(name, {}).get("sha256")
            if before is not None and before != digest:
                if new != target:
                    new.unlink(missing_ok=True)
                raise FetchError(
                    f"{seq}/{name}: the SHA-256 is {digest}, the manifest recorded {before}. The file changed "
                    "upstream or on disk. Nothing was replaced. Delete the manifest entry to accept the new copy."
                )
            if new != target:
                os.replace(new, target)
            size = target.stat().st_size
            _log(f"  {seq}/{name}  {size:,} bytes")
            rows.append((name, url, Extracted(path=f"{seq}/{name}", sha256=digest, bytes=size)))
        write_manifest(dest, seq, rows)
        written[seq] = [ex for _, _, ex in rows]
    return written


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navkit urbannav fetch",
        description=(
            f"Download the reference solution and IMU of UrbanNav sequences. Rights: {RIGHTS}. Cite: {CITATION}"
        ),
    )
    p.add_argument(
        "--sequence", "-s", action="append", default=[], metavar="NAME", help=f"one of {', '.join(SEQUENCES)}"
    )
    p.add_argument("--dest", default=DEFAULT_DEST, help="output directory (default: %(default)s, git-ignored)")
    p.add_argument("--force", action="store_true", help="download again even if the file is on disk")
    p.add_argument("--list", action="store_true", help="list the sequences and file URLs, then exit")
    p.add_argument("--base-url", default=None, help="server root for a mirror or test; files are <root>/<seq>/<name>")
    p.add_argument("--attempts", type=int, default=6, help="tries per request on 429/5xx (default: %(default)s)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        for seq, files in SOURCES.items():
            for name in files:
                print(f"{seq:<12}{name:<32}{file_url(seq, name, args.base_url)}")
        print(f"\nrecord: {RECORD_URL}\nrights: {RIGHTS}\ncite: {CITATION}")
        return 0
    if not args.sequence:
        print("give at least one --sequence NAME (see --list)", file=sys.stderr)
        return 2
    try:
        written = fetch(
            args.sequence, Path(args.dest), base_url=args.base_url, force=args.force, attempts=args.attempts
        )
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    count = sum(len(v) for v in written.values())
    print(f"wrote {count} files under {args.dest}; manifest: {Path(args.dest) / 'MANIFEST.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
