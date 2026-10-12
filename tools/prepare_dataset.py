#!/usr/bin/env python3
"""Convert the official MaleCNS v1.0 synapse table into FlyPoW v1 records.

This tool deliberately does not download or mirror the dataset. Obtain the
source from HHMI Janelia's public download page, then pass the local Feather
file with --input. The official object identity is checked before conversion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

OFFICIAL_PAGE = "https://male-cns.janelia.org/download/"
OFFICIAL_URL = (
    "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/"
    "flat-connectome/syn-partners-male-cns-v1.0-minconf-0.5.feather"
)
OFFICIAL_SIZE = 6_777_179_098
OFFICIAL_MD5 = "58efcf712f8c4d4de5f2ad51e97def76"
OFFICIAL_CRC32C = "8d394d20"
OFFICIAL_GENERATION = 1_780_494_942_562_468

REQUIRED_COLUMNS = (
    "body_pre",
    "body_post",
    "x_pre",
    "y_pre",
    "z_pre",
    "x_post",
    "y_post",
    "z_post",
)
RECORD_BYTES = 40
CHUNK_RECORDS = 4_096
CHUNK_BYTES = RECORD_BYTES * CHUNK_RECORDS
DATASET_LEAF_DOMAIN = b"FlyPoW/dataset-leaf/v1"
DATASET_NODE_DOMAIN = b"FlyPoW/dataset-node/v1"
PROGRESS_PATH: Path | None = None


def report_progress(stage: str, completed: int, total: int, message: str) -> None:
    if PROGRESS_PATH is None:
        return
    temporary = PROGRESS_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump({"stage": stage, "completed": completed, "total": total,
                   "message": message, "updated_at": int(time.time())}, output)
    os.replace(temporary, PROGRESS_PATH)


def hash_parts(domain: bytes, parts: list[bytes]) -> bytes:
    transcript = hashlib.sha256()
    transcript.update(struct.pack("<I", len(domain)))
    transcript.update(domain)
    transcript.update(struct.pack("<I", len(parts)))
    for part in parts:
        transcript.update(struct.pack("<Q", len(part)))
        transcript.update(part)
    return transcript.digest()


def stream_source_digests(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    read_bytes = 0
    total = path.stat().st_size
    with path.open("rb") as source:
        while block := source.read(16 * 1024 * 1024):
            md5.update(block)
            sha256.update(block)
            read_bytes += len(block)
            report_progress("source_verifying", read_bytes, total, "校验官方源文件 MD5 与 SHA-256")
    return md5.hexdigest(), sha256.hexdigest()


def dataset_merkle_root(path: Path) -> str:
    leaves: list[bytes] = []
    with path.open("rb") as source:
        index = 0
        while chunk := source.read(CHUNK_BYTES):
            leaves.append(
                hash_parts(DATASET_LEAF_DOMAIN, [struct.pack("<Q", index), chunk])
            )
            index += 1
            if index % 512 == 0:
                report_progress("merkle", min(index * CHUNK_BYTES, path.stat().st_size), path.stat().st_size, "计算全量突触 Merkle root")
    if not leaves:
        raise ValueError("canonical dataset is empty")
    while len(leaves) > 1:
        next_level: list[bytes] = []
        for index in range(0, len(leaves), 2):
            left = leaves[index]
            right = leaves[index + 1] if index + 1 < len(leaves) else left
            next_level.append(hash_parts(DATASET_NODE_DOMAIN, [left, right]))
        leaves = next_level
    return leaves[0].hex()


def verify_official_source(path: Path) -> tuple[str, str]:
    actual_size = path.stat().st_size
    if actual_size != OFFICIAL_SIZE:
        raise ValueError(
            f"official source must be {OFFICIAL_SIZE} bytes, got {actual_size}"
        )
    print("[1/4] Scanning all source bytes and checking Janelia object MD5...", flush=True)
    actual_md5, actual_sha256 = stream_source_digests(path)
    if actual_md5 != OFFICIAL_MD5:
        raise ValueError(
            f"official source MD5 mismatch: expected {OFFICIAL_MD5}, got {actual_md5}"
        )
    return actual_md5, actual_sha256


def checked_numpy_column(array, name: str, numpy, upper: int):
    if array.null_count:
        raise ValueError(f"column {name!r} contains {array.null_count} null values")
    values = array.to_numpy(zero_copy_only=False)
    if values.size:
        minimum = int(numpy.min(values))
        maximum = int(numpy.max(values))
        if minimum < 0 or maximum > upper:
            raise ValueError(
                f"column {name!r} range {minimum}..{maximum} is outside 0..{upper}"
            )
    return values


def convert_feather(source_path: Path, partial_path: Path) -> tuple[int, str]:
    try:
        import numpy
        import pyarrow as pa
    except ImportError as error:
        raise RuntimeError(
            "pyarrow and numpy are required; install with: "
            "python -m pip install pyarrow numpy"
        ) from error

    source = pa.memory_map(str(source_path), "r")
    reader = pa.ipc.open_file(source)
    missing = [name for name in REQUIRED_COLUMNS if name not in reader.schema.names]
    if missing:
        raise ValueError(f"source Feather file lacks columns: {', '.join(missing)}")
    column_indices = [reader.schema.get_field_index(name) for name in REQUIRED_COLUMNS]
    for name in REQUIRED_COLUMNS:
        if not pa.types.is_integer(reader.schema.field(name).type):
            raise ValueError(f"column {name!r} must have an integer Arrow type")

    record_dtype = numpy.dtype(
        [
            ("body_pre", "<u8"),
            ("body_post", "<u8"),
            ("x_pre", "<u4"),
            ("y_pre", "<u4"),
            ("z_pre", "<u4"),
            ("x_post", "<u4"),
            ("y_post", "<u4"),
            ("z_post", "<u4"),
        ],
        align=False,
    )
    assert record_dtype.itemsize == RECORD_BYTES

    payload_sha256 = hashlib.sha256()
    record_count = 0
    print("[2/4] Converting every synaptic partner row in official row order...", flush=True)
    with partial_path.open("xb") as output:
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            columns = [batch.column(index) for index in column_indices]
            records = numpy.empty(batch.num_rows, dtype=record_dtype)
            records["body_pre"] = checked_numpy_column(
                columns[0], "body_pre", numpy, (1 << 64) - 1
            )
            records["body_post"] = checked_numpy_column(
                columns[1], "body_post", numpy, (1 << 64) - 1
            )
            for output_name, column, source_name in zip(
                REQUIRED_COLUMNS[2:], columns[2:], REQUIRED_COLUMNS[2:], strict=True
            ):
                records[output_name] = checked_numpy_column(
                    column, source_name, numpy, (1 << 32) - 1
                )
            raw = records.tobytes(order="C")
            output.write(raw)
            payload_sha256.update(raw)
            record_count += batch.num_rows
            report_progress("converting", batch_index + 1, reader.num_record_batches,
                            f"已转换 {record_count:,} 条突触记录")
            if batch_index % 100 == 0 or batch_index + 1 == reader.num_record_batches:
                print(
                    f"  batch {batch_index + 1}/{reader.num_record_batches}: "
                    f"{record_count:,} synapses",
                    flush=True,
                )
        output.flush()
        os.fsync(output.fileno())
    source.close()
    return record_count, payload_sha256.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build FlyPoW canonical synapse records from Janelia MaleCNS v1.0"
    )
    parser.add_argument("--input", required=True, type=Path, help="local official Feather file")
    parser.add_argument("--output", required=True, type=Path, help="new canonical .bin file")
    parser.add_argument("--progress", type=Path, help="optional JSON progress file")
    parser.add_argument(
        "--skip-source-check",
        action="store_true",
        help="allow non-official tiny fixtures; never use this for a network dataset",
    )
    return parser.parse_args()


def main() -> int:
    global PROGRESS_PATH
    args = parse_args()
    PROGRESS_PATH = args.progress
    source_path = args.input.resolve()
    output_path = args.output.resolve()
    manifest_path = output_path.with_suffix(output_path.suffix + ".json")
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")

    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    for path in (output_path, manifest_path, partial_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing path: {path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.skip_source_check:
        print("[1/4] WARNING: official source identity check skipped", flush=True)
        source_md5, source_sha256 = stream_source_digests(source_path)
    else:
        source_md5, source_sha256 = verify_official_source(source_path)

    try:
        record_count, payload_sha256 = convert_feather(source_path, partial_path)
        os.replace(partial_path, output_path)
        print("[3/4] Building the canonical chunk Merkle tree...", flush=True)
        merkle_root = dataset_merkle_root(output_path)
        manifest = {
            "format": "flypow-canonical-synapses-v1",
            "record_bytes": RECORD_BYTES,
            "chunk_records": CHUNK_RECORDS,
            "record_count": record_count,
            "canonical_bytes": output_path.stat().st_size,
            "canonical_sha256": payload_sha256,
            "canonical_merkle_root": merkle_root,
            "official_source_verified": not args.skip_source_check,
            "source": {
                "dataset": "MaleCNS v1.0",
                "download_page": OFFICIAL_PAGE,
                "url": OFFICIAL_URL,
                "bytes": source_path.stat().st_size,
                "md5": source_md5,
                "sha256": source_sha256,
                "expected_official_md5": OFFICIAL_MD5,
                "crc32c": OFFICIAL_CRC32C,
                "generation": OFFICIAL_GENERATION,
                "license": "CC-BY-4.0",
            },
            "attribution": (
                "FlyEM Project Team at HHMI Janelia, Cambridge Connectomics Group, "
                "and Google Research"
            ),
        }
        with manifest_path.open("x", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2, sort_keys=True)
            manifest_file.write("\n")
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
    except Exception:
        if partial_path.exists():
            partial_path.unlink()
        raise

    print("[4/4] Done", flush=True)
    print(f"records:     {record_count:,}")
    print(f"dataset root: {merkle_root}")
    print(f"canonical:   {output_path}")
    print(f"manifest:    {manifest_path}")
    report_progress("prepared", record_count, record_count, "全量突触数据已转换并完成校验")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
