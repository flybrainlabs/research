#!/usr/bin/env python3
"""Resume an official HTTPS object by checked byte ranges into local files.

This is a local preparation fallback when the official endpoint lacks browser
CORS permission. The project server does not proxy or redistribute the data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

CHUNK = 8 * 1024 * 1024


def fetch_part(url: str, parts: Path, index: int, size: int, total: int) -> int:
    start = index * CHUNK
    end = min(start + CHUNK, total) - 1
    path = parts / f"{index:05d}.part"
    if path.exists() and path.stat().st_size == end - start + 1:
        return index
    for attempt in range(4):
        with tempfile.TemporaryDirectory(dir=parts) as temp:
            payload = Path(temp) / "payload"
            headers = Path(temp) / "headers"
            result = subprocess.run(
                ["curl", "--http1.1", "-fLsS", "--max-time", "90", "--range",
                 f"{start}-{end}", "--dump-header", str(headers), "--output", str(payload), url],
                capture_output=True, text=True, check=False,
            )
            header_text = headers.read_text() if headers.exists() else ""
            content_range = re.search(rf"(?im)^content-range:\s*bytes {start}-{end}/{total}\s*$", header_text)
            if result.returncode == 0 and content_range and payload.stat().st_size == end - start + 1:
                payload.replace(path)
                return index
    raise RuntimeError(f"range {start}-{end} failed or response was not the requested range")


def fetch(url: str, output: Path, total: int, workers: int = 4) -> str:
    if output.exists():
        raise ValueError(f"refusing to replace existing file: {output}")
    parts = output.with_name(output.name + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    count = (total + CHUNK - 1) // CHUNK
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_part, url, parts, i, CHUNK, total) for i in range(count)]
        for number, future in enumerate(as_completed(futures), 1):
            future.result()
            if number % 16 == 0 or number == count:
                print(f"verified ranges: {number}/{count}", flush=True)
    digest = hashlib.sha256()
    staged = output.with_name(output.name + ".assembling")
    if staged.exists():
        staged.unlink()
    with staged.open("wb") as target:
        for index in range(count):
            with (parts / f"{index:05d}.part").open("rb") as part:
                while block := part.read(CHUNK):
                    target.write(block)
                    digest.update(block)
    if staged.stat().st_size != total:
        raise RuntimeError("assembled length differs from official metadata")
    staged.replace(output)
    print(f"SHA-256: {digest.hexdigest()}")
    return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bytes", required=True, type=int)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not args.url.startswith("https://storage.googleapis.com/flyem-male-cns/v1.0/"):
        parser.error("only official frozen MaleCNS v1.0 objects are allowed")
    if args.bytes <= 0 or not 1 <= args.workers <= 8:
        parser.error("invalid size or worker count")
    fetch(args.url, args.output, args.bytes, args.workers)
