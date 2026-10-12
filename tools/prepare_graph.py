#!/usr/bin/env python3
"""Build a deterministic directed CSR graph from official MaleCNS v1.0 weights.

Only connections whose two endpoints are in the draft NeuronRegistry are kept.
Weights are anatomical contact counts, not signed physiological conductances.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

from inspect_connectome_weights import EXPECTED_BYTES, mapped_indices, registry_ids

MAGIC = b"FBGR1\x00\x00\x00"
EXPECTED_WEIGHTS_SHA256 = "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, registry: Path, coverage: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("output exists; refusing to overwrite")
    if source.stat().st_size != EXPECTED_BYTES or sha256_file(source) != EXPECTED_WEIGHTS_SHA256:
        raise ValueError("official weight object version/hash mismatch")
    ids = registry_ids(registry)
    report = json.loads(coverage.read_text())
    registry_root = sha256_file(registry)
    if report["source_sha256"] != EXPECTED_WEIGHTS_SHA256 or report["registry_root_sha256"] != registry_root:
        raise ValueError("coverage report and inputs disagree")
    edge_count = report["both_mapped_rows"]
    edges = np.empty(edge_count, dtype=[("pre", "<u4"), ("post", "<u4"), ("weight", "<u4")])
    cursor = 0
    with pa.memory_map(str(source)) as handle:
        reader = ipc.open_file(handle)
        for batch_number in range(reader.num_record_batches):
            batch = reader.get_batch(batch_number)
            pre = np.asarray(batch.column(0))
            post = np.asarray(batch.column(1))
            weights = np.asarray(batch.column(2))
            a_index, a = mapped_indices(ids, pre)
            b_index, b = mapped_indices(ids, post)
            selected = a & b
            size = int(np.count_nonzero(selected))
            if size:
                chosen = weights[selected]
                if np.any(chosen <= 0) or np.any(chosen > np.iinfo(np.uint32).max):
                    raise ValueError("weight cannot be encoded as positive u32")
                edges["pre"][cursor:cursor + size] = a_index[selected]
                edges["post"][cursor:cursor + size] = b_index[selected]
                edges["weight"][cursor:cursor + size] = chosen
                cursor += size
            if (batch_number + 1) % 256 == 0:
                print(f"mapped batches: {batch_number + 1}/{reader.num_record_batches}", flush=True)
    if cursor != edge_count:
        raise ValueError("mapping count changed since coverage scan")
    print("sorting all included edges by source and target", flush=True)
    order = np.lexsort((edges["post"], edges["pre"]))
    edges[:] = edges[order]
    del order
    duplicates = (edges["pre"][1:] == edges["pre"][:-1]) & (edges["post"][1:] == edges["post"][:-1])
    if np.any(duplicates):
        raise ValueError("official weight object contains duplicate directed pair; aggregation policy needs review")
    del duplicates
    counts = np.bincount(edges["pre"], minlength=len(ids))
    offsets = np.empty(len(ids) + 1, dtype="<u8")
    offsets[0] = 0
    np.cumsum(counts, out=offsets[1:])
    if int(offsets[-1]) != edge_count or int(np.sum(edges["weight"], dtype=np.uint64)) != report["both_mapped_weight_sum"]:
        raise AssertionError("graph totals differ from coverage report")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + ".assembling")
    if stage.exists():
        raise ValueError("staged output exists; inspect before retry")
    digest = hashlib.sha256()
    with stage.open("wb") as handle:
        def write(payload: bytes):
            handle.write(payload)
            digest.update(payload)
        write(MAGIC)
        write(struct.pack("<IQ", len(ids), edge_count))
        write(bytes.fromhex(registry_root))
        write(ids.astype("<u8", copy=False).tobytes())
        write(offsets.tobytes())
        for start in range(0, edge_count, 1_000_000):
            subset = edges[start:start + 1_000_000]
            output_edges = np.empty(len(subset), dtype=[("post", "<u4"), ("weight", "<u4")])
            output_edges["post"] = subset["post"]
            output_edges["weight"] = subset["weight"]
            write(output_edges.tobytes())
    expected_length = 52 + 8 * len(ids) + 8 * (len(ids) + 1) + 8 * edge_count
    if stage.stat().st_size != expected_length:
        raise AssertionError("graph length mismatch")
    stage.replace(output)
    result = {"state": "ANATOMICAL_GRAPH_ONLY", "graph_file": output.name,
              "graph_root_sha256": digest.hexdigest(), "source_sha256": EXPECTED_WEIGHTS_SHA256,
              "registry_root_sha256": registry_root, "neuron_count": len(ids),
              "directed_connection_count": edge_count,
              "included_synaptic_weight_sum": report["both_mapped_weight_sum"],
              "excluded_connection_rows": report["source_rows"] - edge_count,
              "model_root": None, "task_manifest_root": None}
    output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.registry, args.coverage, args.output), indent=2))
