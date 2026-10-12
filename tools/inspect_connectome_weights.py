#!/usr/bin/env python3
"""Stream official weighted connections and measure registry mapping coverage.

No graph/model root is announced here: aggregation, transmitter signs, delay,
and numeric model policy must be frozen before a simulation graph is released.
"""
from __future__ import annotations

import argparse
import heapq
import hashlib
import json
from pathlib import Path
import struct
import tempfile

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc

from prepare_registry import SOURCE_SHA256 as ANNOTATION_SHA256, digest_file

SOURCE_URL = ("https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/"
              "flat-connectome/connectome-weights-male-cns-v1.0-minconf-0.5.feather")
EXPECTED_BYTES = 1_051_241_946
EXPECTED_SHA256 = "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1"


def sorted_values(path: Path):
    """Read a sorted int64 run without loading it all into memory."""
    with path.open("rb") as handle:
        while True:
            block = np.fromfile(handle, dtype="<i8", count=4096)
            if not len(block):
                return
            yield from (int(value) for value in block)


def unique_values(paths: list[Path]):
    previous = None
    for value in heapq.merge(*(sorted_values(path) for path in paths)):
        if value != previous:
            yield value
            previous = value


class DistinctBodies:
    """Exact external sort; no unbounded Python set of fragment IDs."""

    def __init__(self, directory: Path, memory_mib: int):
        if memory_mib < 1:
            raise ValueError("distinct sort memory must be at least 1 MiB")
        self.directory = directory
        # Leave room for concatenation and sorting copies. Arrow batch memory
        # and the frozen registry are separate from this sorting budget.
        self.run_rows = memory_mib * 1024 * 1024 // 24
        self.pending = []
        self.pending_rows = 0
        self.paths = []
        self.sequence = 0

    def new_path(self):
        path = self.directory / f"run-{self.sequence}.bin"
        self.sequence += 1
        return path

    def add(self, values: np.ndarray):
        for start in range(0, len(values), self.run_rows):
            part = np.unique(values[start:start + self.run_rows])
            self.pending.append(part)
            self.pending_rows += len(part)
            if self.pending_rows >= self.run_rows:
                self.flush()

    def flush(self):
        if not self.pending_rows:
            return
        path = self.new_path()
        np.unique(np.concatenate(self.pending)).astype("<i8").tofile(path)
        self.paths.append(path)
        self.pending.clear()
        self.pending_rows = 0

    def values(self):
        self.flush()
        # Limit open files and merge buffers even for very fragmented sources.
        while len(self.paths) > 16:
            merged = []
            for start in range(0, len(self.paths), 16):
                group = self.paths[start:start + 16]
                path = self.new_path()
                buffer = np.empty(65536, dtype="<i8")
                used = 0
                with path.open("wb") as handle:
                    for value in unique_values(group):
                        buffer[used] = value
                        used += 1
                        if used == len(buffer):
                            buffer.tofile(handle)
                            used = 0
                    buffer[:used].tofile(handle)
                merged.append(path)
                for old in group:
                    old.unlink()
            self.paths = merged
        yield from unique_values(self.paths)


def annotation_ids(source: Path, registry: np.ndarray) -> np.ndarray:
    if digest_file(source) != ANNOTATION_SHA256:
        raise ValueError("wrong official annotation SHA-256")
    table = feather.read_table(source, columns=["bodyId", "status"], memory_map=True)
    bodies = np.asarray(table["bodyId"])
    statuses = np.asarray(table["status"])
    if bodies.dtype.kind not in "iu" or np.any(bodies < 0) or np.any(bodies > np.iinfo(np.int64).max):
        raise ValueError("invalid annotation body IDs")
    bodies = bodies.astype(np.int64)
    ordered = np.sort(bodies)
    if np.any(ordered[:-1] == ordered[1:]):
        raise ValueError("duplicate annotation body IDs")
    if not np.array_equal(np.sort(bodies[statuses == "Traced"]), registry):
        raise ValueError("registry does not match the frozen Traced inclusion rule")
    return ordered


def registry_ids(path: Path) -> np.ndarray:
    with path.open("rb") as source:
        if source.read(8) != b"FBRG1\x00\x00\x00":
            raise ValueError("wrong registry format")
        count = struct.unpack("<Q", source.read(8))[0]
        if not count:
            raise ValueError("empty registry")
        ids = np.empty(count, dtype=np.int64)
        for index in range(count):
            header = source.read(11)
            if len(header) != 11:
                raise ValueError("short registry")
            body_id, side, length = struct.unpack("<QBH", header)
            if body_id > np.iinfo(np.int64).max or side > 3:
                raise ValueError("invalid registry entry")
            ids[index] = body_id
            if len(source.read(length)) != length:
                raise ValueError("short type name")
        if source.read(1) or np.any(ids[:-1] >= ids[1:]):
            raise ValueError("registry has trailing bytes or unordered IDs")
        return ids


def mapped_indices(ids: np.ndarray, bodies: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if not len(ids):
        return np.zeros(len(bodies), dtype=np.int64), np.zeros(len(bodies), dtype=bool)
    positions = np.searchsorted(ids, bodies)
    valid = positions < len(ids)
    valid &= ids[np.minimum(positions, len(ids) - 1)] == bodies
    return positions, valid


def inspect(source: Path, registry: Path, annotation: Path | None = None,
            memory_mib: int = 64, temporary_directory: Path | None = None) -> dict:
    if source.stat().st_size != EXPECTED_BYTES:
        raise ValueError("wrong official weight object size")
    source_hash = digest_file(source)
    if source_hash != EXPECTED_SHA256:
        raise ValueError("wrong official weight SHA-256")
    ids = registry_ids(registry)
    annotated = annotation_ids(annotation, ids) if annotation else None
    connected = np.zeros(len(ids), dtype=bool)
    counts = {"source_rows": 0, "both_mapped_rows": 0, "pre_only_rows": 0,
              "post_only_rows": 0, "neither_mapped_rows": 0, "both_mapped_weight_sum": 0}
    with tempfile.TemporaryDirectory(prefix="flypow-coverage-", dir=temporary_directory) as temp, pa.memory_map(str(source)) as handle:
        distinct = DistinctBodies(Path(temp), memory_mib)
        reader = ipc.open_file(handle)
        if reader.schema.names != ["body_pre", "body_post", "weight"]:
            raise ValueError("unexpected official weights schema")
        for batch_number in range(reader.num_record_batches):
            batch = reader.get_batch(batch_number)
            pre = np.asarray(batch.column(0))
            post = np.asarray(batch.column(1))
            weight = np.asarray(batch.column(2))
            for bodies in [pre, post]:
                if bodies.dtype.kind not in "iu" or np.any(bodies < 0) or np.any(bodies > np.iinfo(np.int64).max):
                    raise ValueError("invalid official endpoint ID")
            pre, post = pre.astype(np.int64, copy=False), post.astype(np.int64, copy=False)
            if np.any(weight <= 0):
                raise ValueError("nonpositive official connection weight")
            a_index, a = mapped_indices(ids, pre)
            b_index, b = mapped_indices(ids, post)
            connected[a_index[a]] = True
            connected[b_index[b]] = True
            distinct.add(pre[~a])
            distinct.add(post[~b])
            both = a & b
            counts["source_rows"] += len(pre)
            counts["both_mapped_rows"] += int(np.count_nonzero(both))
            counts["pre_only_rows"] += int(np.count_nonzero(a & ~b))
            counts["post_only_rows"] += int(np.count_nonzero(~a & b))
            counts["neither_mapped_rows"] += int(np.count_nonzero(~a & ~b))
            counts["both_mapped_weight_sum"] += int(np.sum(weight[both], dtype=np.int64))
            if (batch_number + 1) % 256 == 0:
                print(f"checked batches: {batch_number + 1}/{reader.num_record_batches}", flush=True)
        counts["record_batches"] = reader.num_record_batches
        total = annotated_count = 0
        block = []

        def count_block():
            if annotated is None:
                return 0
            _, known = mapped_indices(annotated, np.asarray(block, dtype=np.int64))
            return int(np.count_nonzero(known))

        print("counting distinct unmapped endpoints (external sort)", flush=True)
        for body in distinct.values():
            total += 1
            block.append(body)
            if len(block) == 65536:
                annotated_count += count_block()
                block.clear()
        annotated_count += count_block()
        counts.update({
            "unmapped_unique_body_ids": total,
            "unmapped_annotated_body_ids": annotated_count if annotation else None,
            "unmapped_without_annotation_body_ids": total - annotated_count if annotation else None,
            "registry_neurons_with_connections": int(np.count_nonzero(connected)),
            "registry_neurons_without_connections": len(ids) - int(np.count_nonzero(connected)),
            "unmapped_definition": "Distinct union of body_pre/body_post IDs absent from the frozen registry; fragments are not counted as biological neurons",
            "annotation_source_sha256": ANNOTATION_SHA256 if annotation else None,
            "distinct_sort_memory_mib": memory_mib,
        })
    counts.update({"state": "COVERAGE_ONLY", "source_url": SOURCE_URL,
                   "source_bytes": source.stat().st_size, "source_sha256": source_hash,
                   "registry_root_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                   "registry_neuron_count": len(ids)})
    if sum(counts[key] for key in ["both_mapped_rows", "pre_only_rows", "post_only_rows", "neither_mapped_rows"]) != counts["source_rows"]:
        raise AssertionError("mapping categories do not balance")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--annotation", type=Path, help="Frozen official annotations; separate excluded IDs from missing annotations")
    parser.add_argument("--memory-mib", type=int, default=64, help="External sorting budget; excludes Arrow batch and registry memory")
    parser.add_argument("--temporary-directory", type=Path, help="Existing scratch directory for disposable sort runs")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; will not replace it")
    report = inspect(args.source, args.registry, args.annotation, args.memory_mib, args.temporary_directory)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
